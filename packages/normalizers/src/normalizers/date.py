"""DateNormalizer — Source.txt Phase 9 (§43-§45).

Canonical output is ISO 8601 (`YYYY-MM-DD` for dates; ISO datetime with
an explicit UTC offset for datetimes). Conservative by construction:
`ciso8601` is a fast, strict "is this already ISO?" path; anything else
that LOOKS like a bare numeric `D/M/Y`-or-`M/D/Y` date (both leading
groups <= 12, so genuinely either order is plausible) is refused —
`AMBIGUOUS`, never a guess — unless the caller's `NormalizationContext`
supplies a locale/country that lets us derive an explicit day/month
order. This is §43's own example made literal: `"03/04/2024"` does NOT
silently resolve without context.

Non-Gregorian calendars (Jalali, Hijri, ...): `dateparser`'s calendar-
conversion behavior could not be reliably verified against this
environment's installed version during M4 (see the M4 verification pack)
— rather than ship unverified conversion logic, non-ISO, non-Gregorian-
looking input is parsed best-effort via `dateparser`; what it cannot read
falls to the partial-date path or to `INVALID`, with the original string
preserved. (An earlier version of this note promised `NEEDS_REVIEW`; no
normalizer emits it — its one producer is an adjudicated value, ADR-018.)
"""

from __future__ import annotations

import re
from functools import cache, lru_cache
from itertools import permutations
from typing import TYPE_CHECKING

import blake3
import ciso8601
import pyarrow as pa
from dateparser.date import DateDataParser
from dateparser.languages.loader import default_loader
from edtf import natlang as edtf_natlang
from edtf import parser as edtf_parser
from normcore.context import NormalizationContext
from normcore.enums import (
    FieldSemanticType,
    MissingKind,
    NormalizationStatus,
    QualityFlag,
    Reversibility,
)
from normcore.models import NormalizedValue
from normcore.pii import character_class_mask, content_hash
from normcore.rules import ComponentVersionInfo, ExplanationText, ValidationOutcome
from normcore.trace import TraceStep

from normalizers import text_ops

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from normcore.interfaces import ComponentVersion, Explanation, StepSpec, ValidationResult

_VERSION = "0.1.0"
_PARSE_PARAMS_HASH = blake3.blake3(b"{}").hexdigest()

_NUMERIC_DMY_RE = re.compile(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})$")

# --- partial precision & repair -------------------------------------------
#
# Two rules, both general, neither tied to any particular source database:
#
# 1. PRECISION IS PRESERVED, NEVER INVENTED. A value that only states a
#    year normalizes to `1966`, one that states year+month to `1998-01`,
#    and only a fully specified value to `1998-01-15`. The old behaviour
#    (always emit YYYY-MM-DD) had no way to express "year only" and so
#    refused such a value outright rather than fabricate a January 1st
#    that is not in the source.
#
# 2. AFFIXES GLUED TO A DIGIT RUN ARE JUNK. Real sources ship sentinel
#    letters welded onto the number (`d1989-12-11`, `1990\u5e74`, `zzz1966zzz`).
#    A letter run is only stripped when it directly abuts a digit with no
#    separator, which is exactly what distinguishes a sentinel from a real
#    textual component: `March 1990` has a space, so `March` survives.
#
# Both only ever run AFTER the strict paths above have already failed, so
# no value that normalizes today can change meaning.
# dateparser fills components it did NOT read from today's date, so a value
# it only half-understood comes back with a year that never appeared in the
# input (`1990\u5e74` parses as year 36, silently). Whenever the input does
# contain a four-digit run, the year we emit must be one of them.
_FOUR_DIGIT_RE = re.compile(r"\d{4}")

# How much of a date an ISO-ish value actually states. `ciso8601` happily
# turns `1990-03` into 1990-03-01, inventing a day the source never gave.
_ISO_PRECISION_RE = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?(?=[T\s]|$)")


# A DATETIME-typed field keeps its time of day. The old code called
# `.date()` on every path, so a column declared DATETIME silently lost its
# time — the mirror image of inventing precision, and contradicted by this
# module's own docstring. A DATE-typed field still truncates, because that
# is what the field was declared to be.
_HAS_TIME_RE = re.compile(r"\d[T ]\d{1,2}:\d{2}")


def _wants_time(ctx: NormalizationContext, value: str) -> bool:
    return ctx.semantic_type is FieldSemanticType.DATETIME and bool(_HAS_TIME_RE.search(value))


def _year_is_supported(year: int, text: str) -> bool:
    four_digit_runs = _FOUR_DIGIT_RE.findall(text)
    return not four_digit_runs or f"{year:04d}" in four_digit_runs


_GLUED_PREFIX_RE = re.compile(r"^[^\W\d_]+(?=\d)")
_GLUED_SUFFIX_RE = re.compile(r"(?<=\d)[^\W\d_]+$")

# Leading ISO-ish skeleton: YYYY, YYYY-MM or YYYY-MM-DD, all numeric.
_SKELETON_RE = re.compile(r"^(\d{4})(?:[-/.](\d{1,2})(?:[-/.](\d{1,2}))?)?")
# What may follow that skeleton and still count as "the rest is unknown"
# rather than "the rest is content we failed to read": placeholder glyphs
# and separators only. `1982-XX-XX` qualifies, `1982-01-15 09:00` does not.
_UNKNOWN_TAIL_RE = re.compile(r"^[-/.\s*?#xXnN_]*$")

_TIME_OF_DAY_RE = re.compile(r"\d{1,2}:\d{2}(?::\d{2}(?:[.,]\d+)?)?")
_DIGITS_RE = re.compile(r"\d+")
_PRECISIONS = ("day", "month", "year")


_MONTH_KEYS = (
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
)  # fmt: skip


@cache
def _month_names(locale: str, month: int) -> frozenset[str]:
    """`month`'s names in dateparser's data for `locale`, e.g. de 3: märz."""
    names = default_loader.get_locale(locale).info.get(_MONTH_KEYS[month - 1], [])
    return frozenset(n.casefold().rstrip(".") for n in names)


def _names_month(text: str, month: int, locale: str | None) -> bool:
    names = _month_names(locale, month) if locale else frozenset()
    return any(m.group().casefold() in names for m in _LETTER_RUN_RE.finditer(text))


def _stated_precision(text: str, parsed: datetime, claimed: str, locale: str | None) -> str | None:
    """The finest precision, at most `claimed`, whose components `text`
    states: the year and the day each as a number of their own, the month
    as a number or as its name in the detected `locale`. Parsers reuse one
    number twice (`03/2024` -> 2024-03-03) or fill gaps from today's date;
    neither is stated. None when a number in the text is no component at
    all (`13/2024`). An all-zero number may be the year (`12/31/00`); one no
    component claims is a placeholder (`00/2024`). Any word used to count
    as the month: `15 Z 2024` (`Z` a time zone to dateparser) came back with
    today's month."""
    date_part = _TIME_OF_DAY_RE.sub(" ", text)
    found = _DIGITS_RE.findall(date_part)
    numbers = [n for n in found if n.strip("0")]
    zeros = [n for n in found if not n.strip("0")]
    if any(len(n) > 4 for n in numbers):
        # ponytail: compact digits (`03032024`) are not split into components,
        # the parser is trusted; split by length if one is found inventing.
        return claimed
    has_word = _names_month(date_part, parsed.month, locale)

    def year(n: str) -> bool:
        return int(n) == parsed.year or (len(n) == 2 and int(n) == parsed.year % 100)

    def month(n: str) -> bool:
        return int(n) == parsed.month

    def day(n: str) -> bool:
        return int(n) == parsed.day

    for precision in _PRECISIONS[_PRECISIONS.index(claimed) :]:
        needed = {"day": [year, month, day], "month": [year, month], "year": [year]}[precision]
        options = [needed, [p for p in needed if p is not month]] if has_word else [needed]
        for parts in options:
            for claimed_zeros in range(len(zeros) + 1):
                groups = numbers + zeros[:claimed_zeros]
                if len(parts) == len(groups) and any(
                    all(p(n) for p, n in zip(parts, order, strict=True))
                    for order in permutations(groups)
                ):
                    return precision
    return None


_PARTIAL_PARSER_SETTINGS: dict[str, object] = {
    "STRICT_PARSING": False,
    # Without this a bare month name ("March") silently resolves against
    # today's date and invents a year that is nowhere in the input.
    "REQUIRE_PARTS": ["year"],
    "RETURN_AS_TIMEZONE_AWARE": False,
}


@lru_cache(maxsize=4)
def _partial_parser(date_order: str | None) -> DateDataParser:
    """DateDataParser (not dateparser.parse) because it is the only entry
    point that reports `period` — 'year' / 'month' / 'day' — which IS the
    precision the source stated. Cached: constructing one compiles a large
    locale table, and there are at most three distinct orders."""
    settings = dict(_PARTIAL_PARSER_SETTINGS)
    if date_order is not None:
        settings["DATE_ORDER"] = date_order
    return DateDataParser(settings=settings)


def _repair_candidates(cleaned: str) -> list[tuple[str, list[str]]]:
    """`(candidate, repairs_applied)` in decreasing fidelity. The first
    entry is always the untouched input, so a value that needs no repair
    is never reported as repaired."""
    candidates: list[tuple[str, list[str]]] = [(cleaned, [])]
    stripped = _GLUED_SUFFIX_RE.sub("", _GLUED_PREFIX_RE.sub("", cleaned))
    if stripped and stripped != cleaned:
        candidates.append((stripped, ["stripped non-numeric affix glued to the digits"]))
    for candidate, repairs in list(candidates):
        truncated = _drop_unknown_components(candidate)
        if truncated is not None:
            candidates.append((truncated, [*repairs, "dropped unknown date components"]))
    return candidates


def _drop_unknown_components(value: str) -> str | None:
    """`1982-XX-XX` -> `1982`, `1998-01-XX` -> `1998-01`. None when the
    value is not an ISO skeleton followed by placeholders only."""
    match = _SKELETON_RE.match(value)
    if match is None:
        return None
    if not _UNKNOWN_TAIL_RE.match(value[match.end() :]):
        return None
    kept = [g for g in match.groups() if g is not None]
    truncated = "-".join(kept)
    return truncated if truncated != value else None


_LETTER_RUN_RE = re.compile(r"[^\W\d_]+")


@cache
def _skip_words(locale: str) -> frozenset[str]:
    """The words dateparser's data for `locale` says carry no date meaning."""
    return frozenset(w.casefold() for w in default_loader.get_locale(locale).info.get("skip", []))


def _letter_beside_a_digit_unread(text: str, locale: str | None) -> bool:
    """True when a letter beside a digit is the shape of a damaged digit
    that the parser did not read as a digit.

    With no language given, dateparser tries every locale and keeps the
    first that parses, so a stray letter in a damaged numeric date is some
    language's word and vanishes: `1O/15/2024` became 2024-01-15 (Polish
    skip word `o`), `l2:34:56` became 02:34:56 (Estonian `L`, Saturday). Two
    shapes are refused:
    - letters that all read as digits under Unicode TR39 (`O`, `I`, `l`),
      glued to a digit;
    - a value whose only words are filler in the detected language, one of
      them glued to a digit: it gave the parser no language of its own.
    Ordinals (`15th March`) and prepositions (`on 15 March`) still parse:
    `th` is not a look-alike and `March` is not filler; `on` touches no digit.
    """
    runs = list(_LETTER_RUN_RE.finditer(text))
    glued = [
        m
        for m in runs
        if (m.start() > 0 and text[m.start() - 1].isdigit())
        or (m.end() < len(text) and text[m.end()].isdigit())
    ]
    if not glued:
        return False
    if any(text_ops.is_digit_lookalike(m.group()) for m in glued):
        return True
    skip = _skip_words(locale) if locale else frozenset()
    return all(m.group().casefold() in skip for m in runs)


def _unread_letter(original: str, ctx: NormalizationContext) -> NormalizedValue:
    return NormalizedValue(
        original=original,
        display=original,
        structured={"assumption": None},
        validation_status="AMBIGUOUS",
        normalization_status=NormalizationStatus.AMBIGUOUS,
        confidence=0.0,
        errors=["a letter beside the digits was not read: a damaged digit, not guessed"],
        trace=[_parse_trace_step(original, changed=False)],
        lossiness=Reversibility.LOSSLESS,
        profile_version="",
        env_id="",
        semantic_type=ctx.semantic_type,
        context_hash=ctx.context_hash,
    )


def _parse_partial(candidate: str, date_order: str | None) -> tuple[str, str] | None:
    """`(iso_text, precision)` at the precision the input actually states,
    or None."""
    try:
        data = _partial_parser(date_order).get_date_data(candidate)
    except (ValueError, TypeError, OverflowError, RecursionError):
        return None
    parsed, period = data.date_obj, data.period
    if (
        parsed is None
        or _letter_beside_a_digit_unread(candidate, data.locale)
        or period not in ("year", "month", "day")
        or not _year_is_supported(parsed.year, candidate)
    ):
        return None
    # Non-strict parsing fills what the text lacks from today's date.
    period = _stated_precision(candidate, parsed, period, data.locale)
    if period is None:
        return None
    if period == "year":
        return f"{parsed.year:04d}", "year"
    if period == "month":
        return f"{parsed.year:04d}-{parsed.month:02d}", "month"
    return parsed.date().isoformat(), "day"


def _normalize_partial(
    original: str, cleaned: str, ctx: NormalizationContext, date_order: str | None
) -> NormalizedValue | None:
    for candidate, repairs in _repair_candidates(cleaned):
        # The day/month ambiguity guard applies to a repaired candidate
        # exactly as it does to the raw input — repairing `d03/04/2024`
        # into `03/04/2024` must not smuggle it past the refusal above.
        if _is_ambiguous_numeric_date(candidate) and date_order is None:
            continue
        partial = _parse_partial(candidate, date_order)
        if partial is None:
            continue
        iso, precision = partial
        confidence = 0.75 if repairs else 0.9
        flags = [QualityFlag.PARTIAL_DATE] if precision != "day" else []
        if repairs:
            flags.append(QualityFlag.PARSER_FALLBACK)
        return _result(
            original,
            iso,
            ctx,
            structured={
                "parsed_date": iso,
                "precision": precision,
                "source_locale": ctx.locale,
                "assumption": f"stated to {precision} precision; no finer component was invented",
                "repairs": repairs,
                "confidence": confidence,
            },
            status=NormalizationStatus.PARSED,
            confidence=confidence,
            flags=flags,
        )
    return None


_DATEPARSER_SETTINGS_BASE: dict[str, object] = {
    "STRICT_PARSING": True,
    "RETURN_AS_TIMEZONE_AWARE": False,
}

# Real-world convention: the US (and a handful of others) predominantly
# write numeric dates Month/Day/Year; nearly everywhere else uses
# Day/Month/Year. This is a coarse, documented heuristic, not a
# per-country lookup table — extend `_MDY_COUNTRIES` as real gaps are
# found, per the same "curated from evidence, not speculation" policy as
# normalizers/country_codes.py.
# Values whose meaning is a RANGE or a qualified point, not a date.
# dateparser flattens all of these to a single day and reports success:
# "1990s" became "1990", inventing year precision out of a decade, and
# "circa 1990" / "1990?" lost the qualifier entirely. Both are exactly
# the precision invention the rest of this module exists to prevent.
#
# EDTF (ISO 8601-2) is the notation for saying so, and `edtf` both reads
# that notation and translates the English phrasings into it. It runs
# ONLY when one of these markers is present: dateparser handles far more
# formats and languages, so the ordinary path must not be rerouted
# through a narrower parser.
# Already-EDTF notation. Matched literally, never inferred: a plain
# "12/05/1990" must NOT look like an interval here, or it would skip the
# day/month ambiguity guard below and get silently resolved.
_EDTF_NOTATION_RE = re.compile(r"^\[|[?~%]|\.\.|\d{2,3}[Xx]\b|\d{4}/\d{4}|^/\d{4}|\d{4}/$")

# English phrasings of the same ideas, which `edtf` translates to EDTF.
_EDTF_WORDS_RE = re.compile(
    r"(\d{3}0s\b"
    r"|\b(circa|ca|cca|approx|approximately|about|around|before|after|early|late|mid)\b)",
    re.IGNORECASE,
)

_EDTF_PRECISION_BY_LENGTH = {4: "year", 7: "month", 10: "day"}


def _edtf_precision(text: str) -> str:
    """Precision of an EDTF string, by what it actually specifies."""
    body = text.rstrip("?~%")
    if "X" in body.upper():
        return "decade" if body.upper().count("X") == 1 else "century"
    if "/" in body or ".." in body or body.startswith("["):
        return "interval"
    return _EDTF_PRECISION_BY_LENGTH.get(len(body), "unknown")


def _normalize_edtf(
    original: str, cleaned: str, ctx: NormalizationContext
) -> NormalizedValue | None:
    """Resolve a qualified or range-valued date to EDTF, or None to let
    the ordinary path handle it.

    Already-EDTF notation is parsed directly. Only English phrasings go
    through `text_to_edtf`, which reads "1990/2000" as the SET
    "[1990, 2000]" rather than the interval it is — so it must never see
    a value that already parses as EDTF on its own.
    """
    parsed = None
    if _EDTF_NOTATION_RE.search(cleaned):
        parsed = _parse_edtf_or_none(cleaned)
    if parsed is None and _EDTF_WORDS_RE.search(cleaned):
        try:
            translated = edtf_natlang.text_to_edtf(cleaned)
        except Exception:
            translated = None
        if translated:
            parsed = _parse_edtf_or_none(translated)
    if parsed is None:
        return None

    text = str(parsed)
    if text.startswith(("[", "{")):
        # edtf renders a set as Python does ("[1667, 1668]"); canonical
        # EDTF has no space, and emitting invalid EDTF from the one code
        # path whose purpose is EDTF would be self-defeating.
        text = text.replace(", ", ",")
    lower = _bound(parsed, "lower_strict")
    upper = _bound(parsed, "upper_strict")
    return _result(
        original,
        text,
        ctx,
        structured={
            "parsed_date": text,
            # The bounds are what make a range queryable: "199X" is not a
            # date you can compare, but 1990-01-01..1999-12-31 is.
            "earliest": lower,
            "latest": upper,
            "precision": _edtf_precision(text),
            "source_format": "EDTF",
            "assumption": "qualified or range-valued date, kept as EDTF rather than flattened",
            "confidence": 0.9,
        },
        status=NormalizationStatus.PARSED,
        confidence=0.9,
        flags=[QualityFlag.PARTIAL_DATE],
    )


def _parse_edtf_or_none(text: str) -> object | None:
    try:
        parsed: object = edtf_parser.parse_edtf(text)
    except Exception:
        return None
    return parsed


def _bound(parsed: object, attribute: str) -> str | None:
    try:
        value = getattr(parsed, attribute)()
    except Exception:
        return None
    return _struct_to_iso(value)


def _struct_to_iso(value: object) -> str | None:
    if value is None:
        return None
    return f"{value.tm_year:04d}-{value.tm_mon:02d}-{value.tm_mday:02d}"  # type: ignore[attr-defined]


_MDY_COUNTRIES = frozenset({"US"})


class _StaticStepSpec:
    def __init__(self, step_id: str, operation: str, reversibility: Reversibility, lossy: bool):
        self.step_id = step_id
        self.operation = operation
        self.claimed_reversibility = reversibility
        self.lossy = lossy


_PARSE_STEP = _StaticStepSpec("date.parse", "date.parse", Reversibility.LOSSY, True)
_STATIC_STEPS: tuple[_StaticStepSpec, ...] = (_PARSE_STEP,)


class DateNormalizer:
    name = "DateNormalizer"
    supported_types = frozenset({FieldSemanticType.DATE, FieldSemanticType.DATETIME})

    def can_handle(self, field_type: FieldSemanticType, ctx: NormalizationContext) -> bool:
        return field_type in self.supported_types

    def normalize(  # noqa: PLR0911 - one early return per refusal, each named
        self, value: str | None, ctx: NormalizationContext
    ) -> NormalizedValue:
        if value is None:
            return _missing(None, MissingKind.NULL, ctx)
        if value.strip() == "":
            return _missing(value, MissingKind.EMPTY_STRING, ctx)

        cleaned = value.strip()

        keep_time = _wants_time(ctx, cleaned)

        # Two shortcuts, tried in order, each returning None to mean "not
        # mine". EDTF comes first so a decade or an interval is never
        # flattened by the parsers below; ISO second because a
        # well-formed ISO value needs no locale inference at all.
        for shortcut in (
            _normalize_edtf(value, cleaned, ctx),
            _normalize_iso(value, cleaned, ctx, keep_time=keep_time),
        ):
            if shortcut is not None:
                return shortcut

        date_order = _infer_date_order(ctx)
        if _is_ambiguous_numeric_date(cleaned) and date_order is None:
            return _ambiguous(value, cleaned, ctx)

        settings = dict(_DATEPARSER_SETTINGS_BASE)
        if date_order is not None:
            settings["DATE_ORDER"] = date_order
        # What `dateparser.parse` does, keeping the locale it detected.
        data = DateDataParser(settings=settings).get_date_data(cleaned)
        parsed = data.date_obj
        if parsed is not None and _letter_beside_a_digit_unread(cleaned, data.locale):
            return _unread_letter(value, ctx)

        if (
            parsed is None
            or not _year_is_supported(parsed.year, cleaned)
            or _stated_precision(cleaned, parsed, "day", data.locale) != "day"
        ):
            return _normalize_partial(value, cleaned, ctx, date_order) or _invalid(value, ctx)

        iso = parsed.isoformat() if keep_time else parsed.date().isoformat()
        assumption = (
            f"resolved using inferred day/month order {date_order}"
            if date_order is not None
            else "unambiguous format, no order assumption needed"
        )
        confidence = 0.85 if date_order is not None else 0.95

        return _result(
            value,
            iso,
            ctx,
            structured={
                "parsed_date": iso,
                "precision": "time" if keep_time else "day",
                "source_locale": ctx.locale,
                "assumption": assumption,
                "confidence": confidence,
            },
            status=NormalizationStatus.PARSED,
            confidence=confidence,
        )

    def normalize_batch(self, values: pa.Array, ctx: NormalizationContext) -> pa.StructArray:
        results = [self.normalize(v, ctx) for v in values.to_pylist()]
        return pa.StructArray.from_arrays(
            [
                pa.array([r.original for r in results], type=pa.large_string()),
                pa.array([r.display for r in results], type=pa.large_string()),
                pa.array([r.comparison for r in results], type=pa.large_string()),
                pa.array([r.normalization_status.value for r in results], type=pa.large_string()),
            ],
            names=["original", "display", "comparison", "status"],
        )

    def validate(self, value: str | None, ctx: NormalizationContext) -> ValidationResult:
        result = self.normalize(value, ctx)
        if result.original_kind is not None:
            return ValidationOutcome(
                is_valid=False, status="MISSING", reason=result.original_kind.value
            )
        if result.normalization_status is NormalizationStatus.AMBIGUOUS:
            return ValidationOutcome(
                is_valid=False, status="AMBIGUOUS", reason="ambiguous day/month order"
            )
        is_valid = result.normalization_status is not NormalizationStatus.INVALID
        return ValidationOutcome(
            is_valid=is_valid,
            status=result.validation_status or "UNKNOWN",
            reason=None if is_valid else "could not parse as a date",
        )

    def explain(self, result: NormalizedValue) -> Explanation:
        if result.normalization_status is NormalizationStatus.AMBIGUOUS:
            return ExplanationText(
                plain_language=(
                    "Could not tell whether this is Day/Month/Year or Month/Day/Year "
                    "without more context, so it was left as-is."
                ),
                technical=f"AMBIGUOUS: candidates={result.structured.get('candidates')}",
            )
        return ExplanationText(
            plain_language=f"Parsed as {result.display}.",
            technical=f"structured={result.structured}",
        )

    def version(self) -> ComponentVersion:
        return ComponentVersionInfo(name=self.name, version=_VERSION)

    def steps(self) -> Sequence[StepSpec]:
        return _STATIC_STEPS

    def inverse(self, step_id: str, value: str) -> str | None:
        return None


def _normalize_iso(
    original: str, cleaned: str, ctx: NormalizationContext, *, keep_time: bool
) -> NormalizedValue | None:
    fast_path = _try_iso_fast_path(cleaned, keep_time=keep_time)
    if fast_path is None:
        return None
    iso_text, iso_precision = fast_path
    return _result(
        original,
        iso_text,
        ctx,
        structured={
            "parsed_date": iso_text,
            "precision": iso_precision,
            "source_format": "ISO8601",
            "assumption": "already ISO 8601, no locale inference needed",
            "confidence": 1.0,
        },
        status=NormalizationStatus.NORMALIZED,
        confidence=1.0,
        flags=[QualityFlag.PARTIAL_DATE] if iso_precision != "day" else [],
    )


def _try_iso_fast_path(value: str, *, keep_time: bool = False) -> tuple[str, str] | None:
    """`(iso_text, precision)`. Truncated to the precision the value
    actually states: `ciso8601` parses `1990-03` into 1990-03-01, and
    emitting that day would be inventing it."""
    # ISO 8601 is ASCII; ciso8601 segfaults on a lone surrogate.
    if not value.isascii():
        return None
    try:
        parsed = ciso8601.parse_datetime(value)
    except (ValueError, IndexError):
        return None
    match = _ISO_PRECISION_RE.match(value)
    if match is not None and match.group(2) is None:
        return f"{parsed.year:04d}", "year"
    if match is not None and match.group(3) is None:
        return f"{parsed.year:04d}-{parsed.month:02d}", "month"
    if keep_time:
        return parsed.isoformat(), "time"
    return parsed.date().isoformat(), "day"


def _is_ambiguous_numeric_date(value: str) -> bool:
    match = _NUMERIC_DMY_RE.match(value)
    if not match:
        return False
    first, second, _year = match.groups()
    return 1 <= int(first) <= 12 and 1 <= int(second) <= 12


def _infer_date_order(ctx: NormalizationContext) -> str | None:
    if ctx.country:
        return "MDY" if ctx.country.upper() in _MDY_COUNTRIES else "DMY"
    if ctx.locale:
        region = ctx.locale.split("-")[-1].upper() if "-" in ctx.locale else None
        if region:
            return "MDY" if region in _MDY_COUNTRIES else "DMY"
    return None


def _result(
    original: str,
    iso_value: str,
    ctx: NormalizationContext,
    *,
    structured: dict[str, object],
    status: NormalizationStatus,
    confidence: float,
    flags: list[QualityFlag] | None = None,
) -> NormalizedValue:
    return NormalizedValue(
        original=original,
        display=iso_value,
        comparison=iso_value,
        search=iso_value,
        structured=structured,
        validation_status="VALID",
        normalization_status=status,
        confidence=confidence,
        flags=flags or [],
        trace=[_parse_trace_step(original, changed=True)],
        lossiness=Reversibility.LOSSY,
        profile_version="",
        env_id="",
        semantic_type=ctx.semantic_type,
        context_hash=ctx.context_hash,
    )


def _ambiguous(original: str, cleaned: str, ctx: NormalizationContext) -> NormalizedValue:
    match = _NUMERIC_DMY_RE.match(cleaned)
    assert match is not None  # only called when _is_ambiguous_numeric_date matched
    first, second, year = match.groups()
    candidates = [
        {"interpretation": "DMY", "day": first, "month": second, "year": year},
        {"interpretation": "MDY", "day": second, "month": first, "year": year},
    ]
    return NormalizedValue(
        original=original,
        display=cleaned,
        structured={"candidates": candidates, "assumption": None},
        validation_status="AMBIGUOUS",
        normalization_status=NormalizationStatus.AMBIGUOUS,
        confidence=0.5,
        flags=[QualityFlag.AMBIGUOUS_DATE],
        trace=[_parse_trace_step(original, changed=False)],
        lossiness=Reversibility.LOSSLESS,
        profile_version="",
        env_id="",
        semantic_type=ctx.semantic_type,
        context_hash=ctx.context_hash,
    )


def _invalid(original: str, ctx: NormalizationContext) -> NormalizedValue:
    return NormalizedValue(
        original=original,
        display=original,
        normalization_status=NormalizationStatus.INVALID,
        validation_status="INVALID",
        confidence=0.0,
        errors=["could not parse as a date"],
        structured={},
        trace=[_parse_trace_step(original, changed=False)],
        lossiness=Reversibility.LOSSLESS,
        profile_version="",
        env_id="",
        semantic_type=ctx.semantic_type,
        context_hash=ctx.context_hash,
    )


def _missing(value: str | None, kind: MissingKind, ctx: NormalizationContext) -> NormalizedValue:
    return NormalizedValue(
        original=value,
        original_kind=kind,
        normalization_status=NormalizationStatus.NORMALIZED,
        validation_status="MISSING",
        confidence=1.0,
        profile_version="",
        env_id="",
        semantic_type=ctx.semantic_type,
        context_hash=ctx.context_hash,
    )


def _parse_trace_step(value: str, *, changed: bool) -> TraceStep:
    return TraceStep(
        step_order=1,
        rule_id="date.parse",
        operation="date.parse",
        params_hash=_PARSE_PARAMS_HASH,
        input_hash=content_hash(value),
        output_hash=content_hash(value),
        input_mask=character_class_mask(value),
        output_mask=character_class_mask(value),
        changed=changed,
        lossy=True,
        reversibility=Reversibility.LOSSY,
        library="dateparser/ciso8601",
        library_version="1.x",
    )

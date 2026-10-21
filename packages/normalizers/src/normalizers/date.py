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
from datetime import date
from functools import cache, lru_cache
from itertools import permutations
from typing import TYPE_CHECKING, Any

import blake3
import ciso8601
import pyarrow as pa
from babel import Locale, UnknownLocaleError, localedata
from babel.languages import get_official_languages
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
    from collections.abc import Iterable, Mapping, Sequence
    from datetime import datetime

    from normcore.interfaces import ComponentVersion, Explanation, StepSpec, ValidationResult

_VERSION = "0.1.0"
_PARSE_PARAMS_HASH = blake3.blake3(b"{}").hexdigest()

_NUMERIC_DMY_RE = re.compile(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})$")
_HHMM_RE = re.compile(r"^(?:[01]\d|2[0-3])[0-5]\d$")

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
    # An hour stated with its meridiem (`3pm`, `11:30 am`) is time, not a
    # date component: dateparser's am/pm words for the detected language.
    date_part = _meridiem_time_re(locale).sub(" ", text) if locale else text
    date_part = _TIME_OF_DAY_RE.sub(" ", date_part)
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


@cache
def _meridiem_time_re(locale: str) -> re.Pattern[str]:
    info = default_loader.get_locale(locale).info
    words = sorted({w for key in ("am", "pm") for w in info.get(key, [])}, key=len, reverse=True)
    if not words:
        return re.compile(r"(?!)")
    alternatives = "|".join(re.escape(w) for w in words)
    return re.compile(
        rf"(?<!\d)\d{{1,2}}(?::\d{{2}}(?::\d{{2}})?)?\s*(?:{alternatives})(?![^\W\d_])",
        re.IGNORECASE,
    )


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
        or not _follows_order(candidate, parsed, date_order)
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


def _also_a_day_and_month(text: str) -> bool:
    """`24/03` is March 2024 or 24 March of no stated year: two numbers, no
    four-digit year, and some order of them is a real day and month. `1/00`
    is not (no day 0, no month 0), so it stays January 2000."""
    if _FOUR_DIGIT_RE.search(text):
        return False
    # The time is no day or month: `11/30 10:30 p.m.` is 30 November or
    # November 2030, and came back as 2030-11.
    numbers = [int(n) for n in _DIGITS_RE.findall(_TIME_OF_DAY_RE.sub(" ", text))]
    if len(numbers) != 2:  # a day and a month
        return False
    for day, month in (numbers, numbers[::-1]):
        try:
            date(2000, month, day)  # a leap year: 29/02 is a real day
        except ValueError:
            continue
        return True
    return False


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
        if precision == "month" and _also_a_day_and_month(candidate):
            return _readings(
                original,
                cleaned,
                ctx,
                [
                    {"interpretation": "month and year", "parsed_date": iso},
                    {"interpretation": "day and month, no year stated"},
                ],
            )
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
    # period "time" when the value states a time of day in any form the
    # parser reads (`3pm`), not only the `hh:mm` shape `_HAS_TIME_RE` sees.
    "RETURN_TIME_AS_PERIOD": True,
}

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
    return f"{value.tm_year:04d}-{value.tm_mon:02d}-{value.tm_mday:02d}"  # type: ignore[attr-defined]  # edtf (untyped) returns a datetime.struct from its bound accessors; mypy sees `object`


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

        if ctx.semantic_type is FieldSemanticType.DATETIME and _HHMM_RE.match(cleaned):
            # ISO 8601 reads four digits as a year (YYYY) and as a basic
            # format time (hhmm): OnTime's `2220` is 22:20, not the year 2220.
            return _readings(
                value,
                cleaned,
                ctx,
                [
                    {"interpretation": "year", "year": cleaned},
                    {"interpretation": "time", "hour": cleaned[:2], "minute": cleaned[2:]},
                ],
            )

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
            or not _follows_order(cleaned, parsed, date_order)
            or not _year_is_supported(parsed.year, cleaned)
            or _stated_precision(cleaned, parsed, "day", data.locale) != "day"
        ):
            return _normalize_partial(value, cleaned, ctx, date_order) or _invalid(value, ctx)

        keep_time = keep_time or (
            ctx.semantic_type is FieldSemanticType.DATETIME and data.period == "time"
        )
        iso = parsed.isoformat() if keep_time else parsed.date().isoformat()
        assumption = (
            f"resolved using inferred day/month order {date_order}"
            if date_order is not None
            else "unambiguous format, no order assumption needed"
        )
        confidence = 0.85 if date_order is not None else 0.95
        evidence = {}
        if date_order is not None and _stated_date_order(ctx) is None:
            assert ctx.column_date_order is not None  # the order came from the column
            assumption = f"resolved using day/month order {date_order}, which the column proves"
            evidence["column_evidence"] = {
                "order": date_order,
                "proving_values": ctx.column_date_order[1],
                "contradicting_values": 0,
            }

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
                **evidence,
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


def _follows_order(value: str, parsed: datetime, date_order: str | None) -> bool:
    """A numeric d/m/y value parsed under a stated order reads in that order.
    dateparser falls back to others: under DMY `1/13/01` came back as
    2013-01-01 (13 the year, 01 the month), an order nothing stated."""
    match = _NUMERIC_DMY_RE.match(value)
    if match is None or date_order not in ("DMY", "MDY"):
        return True
    first, second, _ = (int(g) for g in match.groups())
    day, month = (first, second) if date_order == "DMY" else (second, first)
    return (parsed.day, parsed.month) == (day, month)


def _is_ambiguous_numeric_date(value: str) -> bool:
    match = _NUMERIC_DMY_RE.match(value)
    if not match:
        return False
    first, second, _year = match.groups()
    # Equal day and month (`05/05/2024`) read the same in either order.
    return 1 <= int(first) <= 12 and 1 <= int(second) <= 12 and int(first) != int(second)


@cache
def _cldr_date_order(locale: str) -> str | None:
    """ "DMY" or "MDY" from CLDR's short date pattern for `locale` (ee_GH
    `M/d/yy`, en_GB `dd/MM/y`); None when the pattern is year-first (en_CA
    `y-MM-dd`), which says nothing about a value whose year is last, or when
    CLDR has no such locale."""
    try:
        pattern = Locale.parse(locale).date_formats["short"].pattern
    except (ValueError, UnknownLocaleError):
        return None
    day, month, year = (pattern.find(c) for c in "dMy")
    if min(day, month, year) < 0 or year < min(day, month):
        return None
    return "DMY" if day < month else "MDY"


@cache
def _country_date_order(country: str) -> str | None:
    """The order every official language of `country` agrees on in CLDR, or
    None: Canada's two are year-first, so neither orders `03/04/2024`."""
    orders = {
        _cldr_date_order(locale)
        for language in get_official_languages(country, de_facto=True)
        # A language Babel has no locale for (`no_NO`; nb_NO and nn_NO exist)
        # states nothing; it is not a disagreeing reading.
        if localedata.exists(locale := f"{language}_{country}")
    }
    return orders.pop() if len(orders) == 1 else None


def _stated_date_order(ctx: NormalizationContext) -> str | None:
    """The day/month order the context states, from CLDR (it used to be a
    hand table `{"US"}`, while CLDR has M/d/y locales on four continents). A
    locale with a region names one convention; a bare language (`en`: en-US
    or en-GB?) names none."""
    if ctx.country:
        return _country_date_order(ctx.country.upper())
    if ctx.locale and "-" in ctx.locale:
        return _cldr_date_order(ctx.locale.replace("-", "_"))
    return None


def _infer_date_order(ctx: NormalizationContext) -> str | None:
    """The stated order, else the one the column's own values prove. A column
    contradicting the stated order states nothing, and neither does the context."""
    stated = _stated_date_order(ctx)
    if ctx.column_date_order is None:
        return stated
    proven = ctx.column_date_order[0]
    return proven if stated in (None, proven) else None


# A column mixing both orders evenly shows k agreeing proofs and no other with
# probability 2 * 0.5**k; below ADR-019's delta the column states its order.
_COLUMN_EVIDENCE_DELTA = 0.05


def column_date_evidence(values: Iterable[object]) -> dict[str, Any]:
    """How many distinct numeric d/m/y values in a column can only be day first
    (`13/1/14`) or only month first (`1/13/14`), and the order they prove:
    every proof agreeing, and enough of them (ADR-008 amendment 2026-10-17)."""
    proofs: dict[str, set[str]] = {"DMY": set(), "MDY": set()}
    for value in values:
        match = isinstance(value, str) and _NUMERIC_DMY_RE.match(value.strip())
        if match:
            first, second = int(match[1]), int(match[2])
            if 12 < first <= 31 and 1 <= second <= 12:
                proofs["DMY"].add(match[0])
            elif 12 < second <= 31 and 1 <= first <= 12:
                proofs["MDY"].add(match[0])
    counts = {k: len(v) for k, v in proofs.items()}
    return {**counts, "order": proven_by_column(counts)}


def proven_by_column(counts: Mapping[str, int]) -> str | None:
    """The one reading every proof in a column supports, when there are enough
    proofs (the rule above); None on any contradiction or too few."""
    supported = [k for k, n in counts.items() if n]
    if len(supported) != 1 or 2 * 0.5 ** counts[supported[0]] >= _COLUMN_EVIDENCE_DELTA:
        return None
    return supported[0]


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
    return _readings(
        original,
        cleaned,
        ctx,
        [
            {"interpretation": "DMY", "day": first, "month": second, "year": year},
            {"interpretation": "MDY", "day": second, "month": first, "year": year},
        ],
    )


def _readings(
    original: str, cleaned: str, ctx: NormalizationContext, candidates: list[dict[str, str]]
) -> NormalizedValue:
    """AMBIGUOUS, original kept: the value states several dates."""
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

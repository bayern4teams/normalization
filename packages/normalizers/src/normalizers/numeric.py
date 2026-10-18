"""NumericNormalizer — Source.txt Phase 12, §46.

Locale-aware via Babel/CLDR: comma is NEVER assumed to mean "thousands
separator" without either an explicit locale/country context or an
unambiguous shape in the value itself. Two cases are genuinely
unambiguous without any context and are resolved directly:

1. Both `,` and `.` appear — whichever occurs LAST is the decimal
   separator, regardless of locale convention (`"1.234,56"` and
   `"1,234.56"` both parse correctly this way).
2. A single separator followed by a digit count other than exactly 3
   cannot be a thousands grouping (`"1,23"` or `"1,2345"` must be
   decimal).

A single separator followed by exactly 3 digits (`"1,234"`) is
genuinely ambiguous — `AMBIGUOUS`, never a guess — unless
`NormalizationContext.locale`/`.country` is supplied.
"""

from __future__ import annotations

import re
from decimal import Decimal
from functools import cache
from typing import TYPE_CHECKING, Any

import blake3
import pyarrow as pa
from babel import Locale, UnknownLocaleError
from babel.languages import get_official_languages
from babel.numbers import NumberFormatError, get_decimal_symbol, parse_decimal
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

from normalizers.date import proven_by_column

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from normcore.interfaces import ComponentVersion, Explanation, StepSpec, ValidationResult

_VERSION = "0.1.0"
_PARSE_PARAMS_HASH = blake3.blake3(b"{}").hexdigest()

_PAREN_NEGATIVE_RE = re.compile(r"^\(\s*(.+?)\s*\)$")


class _StaticStepSpec:
    def __init__(self, step_id: str, operation: str, reversibility: Reversibility, lossy: bool):
        self.step_id = step_id
        self.operation = operation
        self.claimed_reversibility = reversibility
        self.lossy = lossy


_PARSE_STEP = _StaticStepSpec("numeric.parse", "numeric.parse", Reversibility.LOSSY, True)
_STATIC_STEPS: tuple[_StaticStepSpec, ...] = (_PARSE_STEP,)


class NumericNormalizer:
    name = "NumericNormalizer"
    supported_types = frozenset({FieldSemanticType.NUMERIC})

    def can_handle(self, field_type: FieldSemanticType, ctx: NormalizationContext) -> bool:
        return field_type in self.supported_types

    def normalize(self, value: str | None, ctx: NormalizationContext) -> NormalizedValue:
        if value is None:
            return _missing(None, MissingKind.NULL, ctx)
        if value.strip() == "":
            return _missing(value, MissingKind.EMPTY_STRING, ctx)

        cleaned = value.strip()
        is_negative_paren = False
        paren_match = _PAREN_NEGATIVE_RE.match(cleaned)
        body = cleaned
        if paren_match:
            is_negative_paren = True
            body = paren_match.group(1)

        # Strip a single leading non-digit currency-symbol-like prefix
        # (e.g. "£1,234.56") — this normalizer only produces the NUMERIC
        # value; a leading currency symbol is CurrencyNormalizer's job,
        # not silently discarded information (kept in `structured`).
        symbol_match = re.match(r"^([^\d\-+.,\s]+)\s*(.+)$", body)
        leading_symbol = None
        if symbol_match:
            leading_symbol, body = symbol_match.group(1), symbol_match.group(2)

        body, locales, mark = _read_by_column(ctx, _resolve_locales(ctx), body)
        if not locales:
            if mark is None and _is_ambiguous_number(body):
                return _ambiguous(value, ctx)
            # Without a locale, Babel has to be told SOMETHING, and the
            # "en_US" fallback below would silently apply US convention to
            # a European value ("1.234,56" -> 1.23456, a 1000x error, and
            # "1,23" -> 123, a 100x one). The two rules in the module
            # docstring resolve those shapes without any locale at all, so
            # they are applied here rather than merely documented.
            body = _canonicalize_separators(body)

        # CLDR's grouping symbol for several locales (e.g. Swiss German,
        # "de_CH") is the TYPOGRAPHIC right single quotation mark
        # (U+2019), not the plain ASCII apostrophe (U+0027) real-world
        # data overwhelmingly uses instead — Babel's parse_decimal is
        # strict about the exact character and rejects the ASCII form
        # outright (found empirically in M5). Apostrophes are never
        # otherwise meaningful in a NUMERIC-typed field, so this
        # normalization is safe and unconditional.
        normalized_body = body.replace("'", "\u2019")

        # Every locale the context names is a reading; the value is what the
        # readings agree on. A country's official languages can disagree
        # (`1,234`: 1234 in en_CA, 1.234 in fr_CA), and then it is AMBIGUOUS.
        readings: dict[Decimal, str | None] = {}
        candidates: list[str | None] = [*locales] or [None]
        for candidate in candidates:
            try:
                parsed = parse_decimal(normalized_body, locale=candidate or "en_US")
            except (NumberFormatError, ValueError):
                continue
            readings.setdefault(parsed, candidate)
        if not readings:
            return _invalid(value, ctx)
        if len(readings) > 1:
            return _ambiguous(value, ctx)
        ((decimal_value, locale),) = readings.items()

        if is_negative_paren:
            decimal_value = -decimal_value

        structured: dict[str, object] = {
            "canonical_value": str(decimal_value),
            "original_locale": locale,
            "leading_symbol": leading_symbol,
            **_column_evidence(ctx, mark),
        }

        canonical = str(decimal_value)
        return NormalizedValue(
            original=value,
            display=canonical,
            comparison=canonical,
            search=canonical,
            structured=structured,
            validation_status="VALID",
            normalization_status=NormalizationStatus.NORMALIZED,
            confidence=1.0 if locale is not None else 0.9,
            trace=[_parse_trace_step(value, changed=canonical != value)],
            lossiness=Reversibility.LOSSY,
            profile_version="",
            env_id="",
            semantic_type=ctx.semantic_type,
            context_hash=ctx.context_hash,
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
        is_valid = result.normalization_status is NormalizationStatus.NORMALIZED
        return ValidationOutcome(
            is_valid=is_valid,
            status=result.validation_status or "UNKNOWN",
            reason=None if is_valid else "could not parse as a number",
        )

    def explain(self, result: NormalizedValue) -> Explanation:
        if result.normalization_status is NormalizationStatus.AMBIGUOUS:
            return ExplanationText(
                plain_language=(
                    "Could not tell whether the separator means thousands or decimal "
                    "without locale context."
                ),
                technical=f"structured={result.structured}",
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


def _resolve_locales(ctx: NormalizationContext) -> list[str]:
    """The locales `ctx` states: its locale, else every official language
    of its country that Babel has data for (`no_NO` is not one: asking for
    it raised UnknownLocaleError out of the normalizer, PART1 N11)."""
    if ctx.locale:
        known = _known(ctx.locale.replace("-", "_"))
        return [known] if known else []
    if ctx.country:
        return list(_locales_for_country(ctx.country.upper()))
    return []


@cache
def _known(locale: str) -> str | None:
    """`locale` when Babel has its data, else None."""
    try:
        Locale.parse(locale)
    except (ValueError, UnknownLocaleError):
        return None
    return locale


@cache
def _locales_for_country(country: str) -> tuple[str, ...]:
    """Taking the first official language was a guess where they differ."""
    return tuple(
        locale
        for language in get_official_languages(country, de_facto=True)
        if (locale := _known(f"{language}_{country}")) is not None
    )


def _read_by_column(
    ctx: NormalizationContext, locales: list[str], body: str
) -> tuple[str, list[str], str | None]:
    """`(body, locales, mark)` once the column's proven decimal mark is applied
    (ADR-011 amendment): only to an ambiguous value the stated locales do not
    already agree on. The body is rewritten to `1234.5` form and the locales
    dropped; when the column contradicts every stated locale, the locales are
    dropped and the body kept, so the value stays AMBIGUOUS."""
    if ctx.column_decimal_mark is None or not _is_ambiguous_number(body):
        return body, locales, None
    mark = ctx.column_decimal_mark[0]
    stated = {get_decimal_symbol(locale) for locale in locales}
    if stated == {mark}:
        return body, locales, None  # the locale reads it the same way
    if stated and mark not in stated:
        return body, [], None
    return body.replace("," if mark == "." else ".", "").replace(mark, "."), [], mark


def _column_evidence(ctx: NormalizationContext, mark: str | None) -> dict[str, object]:
    if mark is None or ctx.column_decimal_mark is None:
        return {}
    return {
        "column_evidence": {
            "decimal_mark": mark,
            "proving_values": ctx.column_decimal_mark[1],
            "contradicting_values": 0,
        }
    }


_NUMBER_RE = re.compile(r"[-+]?(?:\d*[.,])*\d+")


def column_decimal_evidence(values: Iterable[object]) -> dict[str, Any]:
    """How many distinct numbers in a column can only have `.` or only `,` as
    their decimal mark, and the mark they prove (`proven_by_column`). A mark is
    proven by a decimal use that cannot be grouping (`1.5`, `1,234.56`) or by
    the other separator grouping (`1,234,567`: `,` groups, so `.` is decimal)."""
    proofs: dict[str, set[str]] = {".": set(), ",": set()}
    for value in values:
        found = isinstance(value, str) and _NUMBER_RE.search(value)
        if not found:
            continue
        body = found[0].lstrip("-+")
        has = [sep for sep in ".," if sep in body]
        if len(has) == 2:
            proofs["," if body.rfind(",") > body.rfind(".") else "."].add(body)
        elif has and body.count(has[0]) > 1:
            proofs["." if has[0] == "," else ","].add(body)
        elif has and not _is_ambiguous_number(body):
            proofs[has[0]].add(body)
    counts = {k: len(v) for k, v in proofs.items()}
    return {**counts, "mark": proven_by_column(counts)}


def _is_ambiguous_number(body: str) -> bool:
    """Only a SINGLE occurrence of ONE separator type, with exactly 3
    trailing digits, is genuinely ambiguous. Both `,` and `.` present
    disambiguates itself (last one is the decimal separator); repeated
    occurrences of the same separator (`"1,234,567"`) is unambiguous
    thousands grouping — a decimal point cannot repeat."""
    has_comma = "," in body
    has_period = "." in body
    if has_comma == has_period:  # both present, or neither present
        return False
    separator = "," if has_comma else "."
    groups = body.lstrip("-").split(separator)
    if len(groups) != 2:
        return False
    trailing_digit_count = 3
    # `.isdigit()`, not length alone: only digits can form a thousands
    # group, so "1.5e3" is scientific notation rather than an ambiguous
    # grouping and must not be reported AMBIGUOUS.
    return len(groups[1]) == trailing_digit_count and groups[1].isdigit()


def _canonicalize_separators(body: str) -> str:
    """Rewrite a context-free number to plain `1234.56` form.

    Only reached when no locale is available AND the value is not
    ambiguous, so every remaining shape is decidable from the value
    itself by the two rules in the module docstring.
    """
    has_comma = "," in body
    has_period = "." in body
    if not has_comma and not has_period:
        return body
    if has_comma and has_period:
        # Rule 1: whichever separator occurs LAST is the decimal one.
        decimal_sep = "," if body.rfind(",") > body.rfind(".") else "."
        grouping_sep = "." if decimal_sep == "," else ","
        return body.replace(grouping_sep, "").replace(decimal_sep, ".")
    # Rule 2: one separator type. Repeated means grouping ("1.234.567") —
    # a decimal separator cannot repeat. A single one that reaches here
    # already failed the ambiguity test, so it is decimal ("1,23").
    separator = "," if has_comma else "."
    if body.count(separator) > 1:
        return body.replace(separator, "")
    return body.replace(separator, ".")


def _ambiguous(value: str, ctx: NormalizationContext) -> NormalizedValue:
    return NormalizedValue(
        original=value,
        display=value,
        structured={"assumption": None},
        validation_status="AMBIGUOUS",
        normalization_status=NormalizationStatus.AMBIGUOUS,
        confidence=0.5,
        flags=[QualityFlag.AMBIGUOUS_LOCALE],
        trace=[_parse_trace_step(value, changed=False)],
        lossiness=Reversibility.LOSSLESS,
        profile_version="",
        env_id="",
        semantic_type=ctx.semantic_type,
        context_hash=ctx.context_hash,
    )


def _invalid(value: str, ctx: NormalizationContext) -> NormalizedValue:
    return NormalizedValue(
        original=value,
        display=value,
        normalization_status=NormalizationStatus.INVALID,
        validation_status="INVALID",
        confidence=0.0,
        errors=["could not parse as a number"],
        structured={},
        trace=[_parse_trace_step(value, changed=False)],
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
        rule_id="numeric.parse",
        operation="numeric.parse",
        params_hash=_PARSE_PARAMS_HASH,
        input_hash=content_hash(value),
        output_hash=content_hash(value),
        input_mask=character_class_mask(value),
        output_mask=character_class_mask(value),
        changed=changed,
        lossy=True,
        reversibility=Reversibility.LOSSY,
        library="Babel",
        library_version="2.x",
    )

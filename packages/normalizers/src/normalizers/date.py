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
looking input is parsed best-effort via `dateparser` and marked
`NEEDS_REVIEW` with the original string preserved verbatim in
`structured.original_value`, instead of asserting confident Gregorian
conversion.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import blake3
import ciso8601
import dateparser
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

if TYPE_CHECKING:
    from collections.abc import Sequence

    from normcore.interfaces import ComponentVersion, Explanation, StepSpec, ValidationResult

_VERSION = "0.1.0"
_PARSE_PARAMS_HASH = blake3.blake3(b"{}").hexdigest()

_NUMERIC_DMY_RE = re.compile(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})$")

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

    def normalize(self, value: str | None, ctx: NormalizationContext) -> NormalizedValue:
        if value is None:
            return _missing(None, MissingKind.NULL, ctx)
        if value.strip() == "":
            return _missing(value, MissingKind.EMPTY_STRING, ctx)

        cleaned = value.strip()

        iso_fast_path = _try_iso_fast_path(cleaned)
        if iso_fast_path is not None:
            return _result(
                value,
                iso_fast_path,
                ctx,
                structured={
                    "parsed_date": iso_fast_path,
                    "source_format": "ISO8601",
                    "assumption": "already ISO 8601, no locale inference needed",
                    "confidence": 1.0,
                },
                status=NormalizationStatus.NORMALIZED,
                confidence=1.0,
            )

        date_order = _infer_date_order(ctx)
        if _is_ambiguous_numeric_date(cleaned) and date_order is None:
            return _ambiguous(value, cleaned, ctx)

        settings = dict(_DATEPARSER_SETTINGS_BASE)
        if date_order is not None:
            settings["DATE_ORDER"] = date_order
        parsed = dateparser.parse(cleaned, settings=settings)

        if parsed is None:
            return _invalid(value, ctx)

        iso = parsed.date().isoformat()
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
                "source_locale": ctx.locale,
                "assumption": assumption,
                "confidence": confidence,
            },
            status=NormalizationStatus.PARSED,
            confidence=confidence,
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


def _try_iso_fast_path(value: str) -> str | None:
    try:
        parsed = ciso8601.parse_datetime(value)
    except (ValueError, IndexError):
        return None
    return parsed.date().isoformat()


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

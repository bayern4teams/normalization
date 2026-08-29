"""PhoneNormalizer — Source.txt Phase 6 (§36-§38).

`phonenumbers` only — no digit-stripping heuristics of any kind (§4.4
forbids them unless explicitly configured for a named domain, which is
out of scope here). No country inferable from either the number itself
(a leading "+") or context means `AMBIGUOUS`, never a guess (§36).
Extensions are parsed and stored separately in `structured`, never
merged into `e164` (the canonical/comparison form) — confirmed empirically
in M3 that `phonenumbers` itself keeps them apart in E.164 output.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import blake3
import phonenumbers
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

_VERSION = getattr(phonenumbers, "__version__", "8.x")
_PARSE_PARAMS_HASH = blake3.blake3(b"{}").hexdigest()


class _StaticStepSpec:
    def __init__(self, step_id: str, operation: str, reversibility: Reversibility, lossy: bool):
        self.step_id = step_id
        self.operation = operation
        self.claimed_reversibility = reversibility
        self.lossy = lossy


_PARSE_STEP = _StaticStepSpec(
    "phone.parse", "phone.parse", Reversibility.PARTIALLY_REVERSIBLE, False
)
_STATIC_STEPS: tuple[_StaticStepSpec, ...] = (_PARSE_STEP,)


class PhoneNormalizer:
    name = "PhoneNormalizer"
    supported_types = frozenset({FieldSemanticType.PHONE})

    def can_handle(self, field_type: FieldSemanticType, ctx: NormalizationContext) -> bool:
        return field_type in self.supported_types

    def normalize(self, value: str | None, ctx: NormalizationContext) -> NormalizedValue:
        if value is None:
            return _missing(None, MissingKind.NULL, ctx)
        if value.strip() == "":
            return _missing(value, MissingKind.EMPTY_STRING, ctx)

        stripped = value.strip()
        has_explicit_plus = stripped.startswith("+")

        # Region precedence per §37: explicit record context (ctx.country)
        # takes priority over field/profile-level default_region. Source-
        # context and user/project-config levels from the full §37 chain
        # require a source->region mapping dictionary that does not exist
        # yet in this milestone — documented as a known gap in the M3
        # verification pack, not silently skipped.
        region, region_source = _resolve_region(ctx, has_number_prefix=has_explicit_plus)

        if region is None and not has_explicit_plus:
            return _ambiguous_no_region(value, ctx)

        try:
            parsed = phonenumbers.parse(stripped, region)
        except phonenumbers.NumberParseException as exc:
            return _invalid(value, ctx, reason=str(exc))

        is_possible = phonenumbers.is_possible_number(parsed)
        is_valid = phonenumbers.is_valid_number(parsed)
        e164 = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        international_format = phonenumbers.format_number(
            parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL
        )
        national_format = phonenumbers.format_number(
            parsed, phonenumbers.PhoneNumberFormat.NATIONAL
        )
        resolved_region = phonenumbers.region_code_for_number(parsed)

        flags: list[QualityFlag] = []
        if not is_valid:
            flags.append(QualityFlag.PHONE_INVALID)
        if region_source == "default_region":
            flags.append(QualityFlag.PHONE_REGION_INFERRED)

        structured: dict[str, object] = {
            "country_code": parsed.country_code,
            "national_number": str(parsed.national_number),
            "extension": parsed.extension,
            "e164": e164,
            "international_format": international_format,
            "national_format": national_format,
            "is_possible": is_possible,
            "is_valid": is_valid,
            "region": resolved_region,
            "region_source": region_source,
            "validation_message": (
                None if is_valid else "Number is not a valid number for its region."
            ),
        }

        status = NormalizationStatus.PARSED if is_valid else NormalizationStatus.INVALID

        return NormalizedValue(
            original=value,
            display=international_format,
            comparison=e164,
            search=e164,
            structured=structured,
            validation_status="VALID" if is_valid else "INVALID",
            normalization_status=status,
            confidence=1.0 if is_valid else 0.5,
            flags=flags,
            trace=[_parse_trace_step(value, changed=True)],
            lossiness=Reversibility.PARTIALLY_REVERSIBLE,
            profile_version="",
            env_id="",
            semantic_type=ctx.semantic_type,
            context_hash=ctx.context_hash,
        )

    def validate(self, value: str | None, ctx: NormalizationContext) -> ValidationResult:
        result = self.normalize(value, ctx)
        if result.original_kind is not None:
            return ValidationOutcome(
                is_valid=False, status="MISSING", reason=result.original_kind.value
            )
        if result.normalization_status is NormalizationStatus.AMBIGUOUS:
            return ValidationOutcome(
                is_valid=False, status="AMBIGUOUS", reason="no region context available"
            )
        is_valid = bool(result.structured.get("is_valid"))
        return ValidationOutcome(
            is_valid=is_valid,
            status=result.validation_status or "UNKNOWN",
            reason=None if is_valid else "failed phonenumbers validity check",
        )

    def explain(self, result: NormalizedValue) -> Explanation:
        if result.normalization_status is NormalizationStatus.AMBIGUOUS:
            return ExplanationText(
                plain_language=(
                    "No country could be determined for this number, so it was left as-is "
                    "rather than guessed."
                ),
                technical="AMBIGUOUS: no region context and no leading '+' country code.",
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


def _resolve_region(
    ctx: NormalizationContext, *, has_number_prefix: bool
) -> tuple[str | None, str]:
    if has_number_prefix:
        return None, "number_prefix"
    if ctx.country:
        return ctx.country, "explicit"
    if ctx.default_region:
        return ctx.default_region, "default_region"
    return None, "unknown"


def _ambiguous_no_region(value: str, ctx: NormalizationContext) -> NormalizedValue:
    return NormalizedValue(
        original=value,
        display=value,
        normalization_status=NormalizationStatus.AMBIGUOUS,
        validation_status="AMBIGUOUS",
        confidence=0.0,
        structured={"region_source": "unknown"},
        profile_version="",
        env_id="",
        semantic_type=ctx.semantic_type,
        context_hash=ctx.context_hash,
    )


def _invalid(value: str, ctx: NormalizationContext, *, reason: str) -> NormalizedValue:
    return NormalizedValue(
        original=value,
        display=value,
        normalization_status=NormalizationStatus.INVALID,
        validation_status="INVALID",
        confidence=0.0,
        flags=[QualityFlag.PHONE_INVALID],
        errors=[reason],
        structured={},
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
        rule_id="phone.parse",
        operation="phone.parse",
        params_hash=_PARSE_PARAMS_HASH,
        input_hash=content_hash(value),
        output_hash=content_hash(value),
        input_mask=character_class_mask(value),
        output_mask=character_class_mask(value),
        changed=changed,
        lossy=False,
        reversibility=Reversibility.PARTIALLY_REVERSIBLE,
        library="phonenumbers",
        library_version=_VERSION,
    )

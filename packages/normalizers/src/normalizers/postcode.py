"""PostcodeNormalizer — Source.txt §32.

`AddressNormalizer` already validates a postcode that arrives *embedded*
inside a full address string. This handles the equally common case of a
postcode as its *own* field (e.g. a dataset's standalone "zip_code"
column) — `FieldSemanticType.POSTCODE` existed in the enum since M1 but
had no registered normalizer until this module, silently falling
through to `PassthroughNormalizer` (a real gap found during the M7
follow-up self-audit, not something deferred on purpose).

Reuses the exact same `google-i18n-address` validation
(`normalizers.postcode_validation`) `AddressNormalizer` uses, so there is
one real postcode-format-validation implementation, not two.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import blake3
from normcore.context import NormalizationContext
from normcore.enums import (
    FieldSemanticType,
    MissingKind,
    NormalizationStatus,
    Reversibility,
)
from normcore.models import NormalizedValue
from normcore.pii import character_class_mask, content_hash
from normcore.rules import ComponentVersionInfo, ExplanationText, ValidationOutcome
from normcore.trace import TraceStep

from normalizers.country_codes import resolve_country_alpha2
from normalizers.postcode_validation import validate_postcode_format

if TYPE_CHECKING:
    from collections.abc import Sequence

    from normcore.interfaces import ComponentVersion, Explanation, StepSpec, ValidationResult

_VERSION = "0.1.0"
_PARSE_PARAMS_HASH = blake3.blake3(b"{}").hexdigest()


class _StaticStepSpec:
    def __init__(self, step_id: str, operation: str, reversibility: Reversibility, lossy: bool):
        self.step_id = step_id
        self.operation = operation
        self.claimed_reversibility = reversibility
        self.lossy = lossy


_NORMALIZE_STEP = _StaticStepSpec(
    "postcode.normalize", "postcode.normalize", Reversibility.REVERSIBLE, False
)
_STATIC_STEPS: tuple[_StaticStepSpec, ...] = (_NORMALIZE_STEP,)


class PostcodeNormalizer:
    name = "PostcodeNormalizer"
    supported_types = frozenset({FieldSemanticType.POSTCODE})

    def can_handle(self, field_type: FieldSemanticType, ctx: NormalizationContext) -> bool:
        return field_type in self.supported_types

    def normalize(self, value: str | None, ctx: NormalizationContext) -> NormalizedValue:
        if value is None:
            return _missing(None, MissingKind.NULL, ctx)
        if value.strip() == "":
            return _missing(value, MissingKind.EMPTY_STRING, ctx)

        cleaned = " ".join(value.split())
        comparison = cleaned.upper()

        country_alpha2 = resolve_country_alpha2(ctx.country) if ctx.country else None
        if country_alpha2 is None:
            # No usable country context — the same value can be a valid
            # postcode in one country and nonsense in another, so refuse
            # to guess (§32's own "locale-aware" requirement) rather than
            # validating against an arbitrary default.
            return NormalizedValue(
                original=value,
                display=cleaned,
                comparison=comparison,
                search=comparison,
                structured={"country": None, "format_valid": None},
                validation_status="UNKNOWN",
                normalization_status=NormalizationStatus.AMBIGUOUS,
                confidence=0.5,
                warnings=["No country context available to validate postcode format against."],
                trace=[_normalize_trace_step(value, changed=cleaned != value)],
                lossiness=Reversibility.REVERSIBLE,
                profile_version="",
                env_id="",
                semantic_type=ctx.semantic_type,
                context_hash=ctx.context_hash,
            )

        format_valid = validate_postcode_format(cleaned, country_alpha2)
        structured = {"country": country_alpha2, "format_valid": format_valid}

        if format_valid is False:
            return NormalizedValue(
                original=value,
                display=cleaned,
                comparison=comparison,
                search=comparison,
                structured=structured,
                validation_status="INVALID",
                normalization_status=NormalizationStatus.INVALID,
                confidence=0.0,
                errors=[f"does not match the expected postcode format for {country_alpha2}"],
                trace=[_normalize_trace_step(value, changed=cleaned != value)],
                lossiness=Reversibility.REVERSIBLE,
                profile_version="",
                env_id="",
                semantic_type=ctx.semantic_type,
                context_hash=ctx.context_hash,
            )

        return NormalizedValue(
            original=value,
            display=cleaned,
            comparison=comparison,
            search=comparison,
            structured=structured,
            validation_status="VALID" if format_valid else "UNKNOWN",
            normalization_status=NormalizationStatus.NORMALIZED,
            confidence=1.0 if format_valid else 0.7,
            trace=[_normalize_trace_step(value, changed=cleaned != value)],
            lossiness=Reversibility.REVERSIBLE,
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
        is_valid = result.normalization_status is NormalizationStatus.NORMALIZED
        return ValidationOutcome(
            is_valid=is_valid,
            status=result.validation_status or "UNKNOWN",
            reason=None if is_valid else "invalid or unvalidatable postcode format",
        )

    def explain(self, result: NormalizedValue) -> Explanation:
        if result.normalization_status is NormalizationStatus.INVALID:
            return ExplanationText(
                plain_language="Does not match the expected postcode format for this country.",
                technical=f"errors={result.errors}",
            )
        if result.normalization_status is NormalizationStatus.AMBIGUOUS:
            return ExplanationText(
                plain_language=(
                    "Cleaned up formatting only — no country context to validate against."
                ),
                technical=f"structured={result.structured}",
            )
        return ExplanationText(
            plain_language="Whitespace-normalized and format-validated.",
            technical=f"structured={result.structured}",
        )

    def version(self) -> ComponentVersion:
        return ComponentVersionInfo(name=self.name, version=_VERSION)

    def steps(self) -> Sequence[StepSpec]:
        return _STATIC_STEPS

    def inverse(self, step_id: str, value: str) -> str | None:
        return None


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


def _normalize_trace_step(value: str, *, changed: bool) -> TraceStep:
    return TraceStep(
        step_order=1,
        rule_id="postcode.normalize",
        operation="postcode.normalize",
        params_hash=_PARSE_PARAMS_HASH,
        input_hash=content_hash(value),
        output_hash=content_hash(value),
        input_mask=character_class_mask(value),
        output_mask=character_class_mask(value),
        changed=changed,
        lossy=False,
        reversibility=Reversibility.REVERSIBLE,
        library="google-i18n-address",
        library_version="3.x",
    )

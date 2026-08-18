"""BooleanNormalizer — Source.txt Phase 12, §52.

`true/True/TRUE/yes/Yes/Y/1` -> canonical boolean; `maybe`/`unknown`/`N/A`
-> `UNKNOWN_VALUE`/`NOT_APPLICABLE` (never silently coerced to a boolean
guess). The dictionary is deliberately small and explicit — no fuzzy
matching — since a coercion mistake here (treating "maybe" as `false`,
say) would be a silent data-integrity error, not a cosmetic one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import blake3
import pyarrow as pa
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType, MissingKind, NormalizationStatus, Reversibility
from normcore.models import NormalizedValue
from normcore.pii import character_class_mask, content_hash
from normcore.rules import ComponentVersionInfo, ExplanationText, ValidationOutcome
from normcore.trace import TraceStep

if TYPE_CHECKING:
    from collections.abc import Sequence

    from normcore.interfaces import ComponentVersion, Explanation, StepSpec, ValidationResult

_VERSION = "0.1.0"
_PARSE_PARAMS_HASH = blake3.blake3(b"{}").hexdigest()

_TRUE_VALUES = frozenset({"true", "yes", "y", "1", "t"})
_FALSE_VALUES = frozenset({"false", "no", "n", "0", "f"})
# Explicitly recognized as "genuinely don't know" — routed to
# UNKNOWN_VALUE, never coerced toward either boolean.
_UNKNOWN_VALUES = frozenset({"maybe", "unknown", "n/a", "na", "?"})


class _StaticStepSpec:
    def __init__(self, step_id: str, operation: str, reversibility: Reversibility, lossy: bool):
        self.step_id = step_id
        self.operation = operation
        self.claimed_reversibility = reversibility
        self.lossy = lossy


_COERCE_STEP = _StaticStepSpec(
    "boolean.coerce", "boolean.coerce", Reversibility.PARTIALLY_REVERSIBLE, True
)
_STATIC_STEPS: tuple[_StaticStepSpec, ...] = (_COERCE_STEP,)


class BooleanNormalizer:
    name = "BooleanNormalizer"
    supported_types = frozenset({FieldSemanticType.BOOLEAN})

    def can_handle(self, field_type: FieldSemanticType, ctx: NormalizationContext) -> bool:
        return field_type in self.supported_types

    def normalize(self, value: str | None, ctx: NormalizationContext) -> NormalizedValue:
        if value is None:
            return _missing(None, MissingKind.NULL, ctx)
        if value.strip() == "":
            return _missing(value, MissingKind.EMPTY_STRING, ctx)

        lowered = value.strip().casefold()

        if lowered in _UNKNOWN_VALUES:
            return _missing(value, MissingKind.UNKNOWN_VALUE, ctx)

        if lowered in _TRUE_VALUES:
            return _resolved(value, canonical=True, ctx=ctx)
        if lowered in _FALSE_VALUES:
            return _resolved(value, canonical=False, ctx=ctx)

        return _invalid(value, ctx)

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
            reason=None if is_valid else "not a recognized boolean value",
        )

    def explain(self, result: NormalizedValue) -> Explanation:
        if result.original_kind is not None:
            return ExplanationText(
                plain_language=f"Recognized as {result.original_kind.value}, not a boolean.",
                technical=f"original_kind={result.original_kind.value}",
            )
        if result.normalization_status is NormalizationStatus.INVALID:
            return ExplanationText(
                plain_language="Not a recognized boolean value.",
                technical=f"errors={result.errors}",
            )
        return ExplanationText(
            plain_language=f"Coerced to {result.display}.",
            technical=f"structured={result.structured}",
        )

    def version(self) -> ComponentVersion:
        return ComponentVersionInfo(name=self.name, version=_VERSION)

    def steps(self) -> Sequence[StepSpec]:
        return _STATIC_STEPS

    def inverse(self, step_id: str, value: str) -> str | None:
        return None


def _resolved(value: str, *, canonical: bool, ctx: NormalizationContext) -> NormalizedValue:
    display = "true" if canonical else "false"
    return NormalizedValue(
        original=value,
        display=display,
        comparison=display,
        search=display,
        structured={"canonical_value": canonical},
        validation_status="VALID",
        normalization_status=NormalizationStatus.NORMALIZED,
        confidence=1.0,
        trace=[_coerce_trace_step(value, changed=value.strip().casefold() != display)],
        lossiness=Reversibility.PARTIALLY_REVERSIBLE,
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
        errors=["not a recognized boolean value"],
        structured={},
        trace=[_coerce_trace_step(value, changed=False)],
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


def _coerce_trace_step(value: str, *, changed: bool) -> TraceStep:
    return TraceStep(
        step_order=1,
        rule_id="boolean.coerce",
        operation="boolean.coerce",
        params_hash=_PARSE_PARAMS_HASH,
        input_hash=content_hash(value),
        output_hash=content_hash(value),
        input_mask=character_class_mask(value),
        output_mask=character_class_mask(value),
        changed=changed,
        lossy=True,
        reversibility=Reversibility.PARTIALLY_REVERSIBLE,
        library="normalizers",
        library_version=_VERSION,
    )

"""UnitNormalizer — Source.txt Phase 12, §48.

`Pint` parses `"5 km"` / `"5000 m"` into a canonical SI base-unit
representation (`5000 meter` for both), so quantities expressed in
different units of the same dimension compare correctly. A dimension
mismatch (e.g. converting a length to a mass) is never attempted —
`Pint` itself raises on it, and this normalizer never catches that
specific error into a false "converted" result.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import blake3
import pint
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

# One registry per process (Pint's own recommendation) — constructing it
# is expensive, and units/quantities from different registries cannot be
# safely compared, mirroring the "construct once, reuse across the whole
# batch" pattern from normalizers/script.py's language detector.
# pint.UnitRegistry is generic; not worth pinning the type parameter here.
_UREG = pint.UnitRegistry()  # type: ignore[var-annotated]


class _StaticStepSpec:
    def __init__(self, step_id: str, operation: str, reversibility: Reversibility, lossy: bool):
        self.step_id = step_id
        self.operation = operation
        self.claimed_reversibility = reversibility
        self.lossy = lossy


_CONVERT_STEP = _StaticStepSpec("unit.convert", "unit.convert", Reversibility.REVERSIBLE, False)
_STATIC_STEPS: tuple[_StaticStepSpec, ...] = (_CONVERT_STEP,)


class UnitNormalizer:
    name = "UnitNormalizer"
    supported_types = frozenset({FieldSemanticType.QUANTITY})

    def can_handle(self, field_type: FieldSemanticType, ctx: NormalizationContext) -> bool:
        return field_type in self.supported_types

    def normalize(self, value: str | None, ctx: NormalizationContext) -> NormalizedValue:
        if value is None:
            return _missing(None, MissingKind.NULL, ctx)
        if value.strip() == "":
            return _missing(value, MissingKind.EMPTY_STRING, ctx)

        cleaned = value.strip()
        try:
            quantity = _UREG(cleaned)
        except (pint.UndefinedUnitError, pint.DimensionalityError, ValueError) as exc:
            return _invalid(value, ctx, reason=str(exc))

        if not isinstance(quantity, _UREG.Quantity):
            return _invalid(value, ctx, reason="no unit found in value")

        base = quantity.to_base_units()

        structured = {
            "original_value": str(quantity.magnitude),
            "original_unit": str(quantity.units),
            "canonical_value": str(base.magnitude),
            "canonical_unit": str(base.units),
            "dimensionality": str(quantity.dimensionality),
        }
        canonical_display = f"{base.magnitude} {base.units}"

        return NormalizedValue(
            original=value,
            display=canonical_display,
            comparison=canonical_display,
            search=canonical_display,
            structured=structured,
            validation_status="VALID",
            normalization_status=NormalizationStatus.NORMALIZED,
            confidence=1.0,
            trace=[_convert_trace_step(value, changed=True)],
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
            reason=None if is_valid else "not a recognized quantity/unit",
        )

    def explain(self, result: NormalizedValue) -> Explanation:
        if result.normalization_status is NormalizationStatus.INVALID:
            return ExplanationText(
                plain_language="Not a recognized quantity with a unit.",
                technical=f"errors={result.errors}",
            )
        return ExplanationText(
            plain_language=f"Converted to {result.display}.",
            technical=f"structured={result.structured}",
        )

    def version(self) -> ComponentVersion:
        return ComponentVersionInfo(name=self.name, version=_VERSION)

    def steps(self) -> Sequence[StepSpec]:
        return _STATIC_STEPS

    def inverse(self, step_id: str, value: str) -> str | None:
        return None


def _invalid(value: str, ctx: NormalizationContext, *, reason: str) -> NormalizedValue:
    return NormalizedValue(
        original=value,
        display=value,
        normalization_status=NormalizationStatus.INVALID,
        validation_status="INVALID",
        confidence=0.0,
        errors=[reason],
        structured={},
        trace=[_convert_trace_step(value, changed=False)],
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


def _convert_trace_step(value: str, *, changed: bool) -> TraceStep:
    return TraceStep(
        step_order=1,
        rule_id="unit.convert",
        operation="unit.convert",
        params_hash=_PARSE_PARAMS_HASH,
        input_hash=content_hash(value),
        output_hash=content_hash(value),
        input_mask=character_class_mask(value),
        output_mask=character_class_mask(value),
        changed=changed,
        lossy=False,
        reversibility=Reversibility.REVERSIBLE,
        library="Pint",
        library_version=str(pint.__version__),
    )

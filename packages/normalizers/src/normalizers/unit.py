"""UnitNormalizer — Source.txt Phase 12, §48.

`Pint` parses `"5 km"` / `"5000 m"` into a canonical SI base-unit
representation (`5000 meter` for both), so quantities expressed in
different units of the same dimension compare correctly. A dimension
mismatch (e.g. converting a length to a mass) is never attempted —
`Pint` itself raises on it, and this normalizer never catches that
specific error into a false "converted" result.
"""

from __future__ import annotations

import re
import tokenize
from typing import TYPE_CHECKING

import blake3
import pint
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

# One leading number, then everything else is the unit. Only "." is accepted
# as the decimal mark: "1,5 kg" is genuinely ambiguous against thousands
# grouping, so it is refused rather than guessed at.
# Everything building or converting a Quantity is known to raise on bad
# input. pint.PintError is the base of pint's own errors; ArithmeticError and
# MemoryError cover a pathological magnitude or exponent. pint's unit parser
# also raises AssertionError (`12# kg`, `12 kg*`) and, since it tokenizes the
# unit text as Python, tokenize.TokenError on a quote (`12" kg`): both escaped
# the normalizer and failed the whole job (found by fuzzing every printable
# character at every position, tests/unit/test_followups.py).
_PINT_FAILURES = (
    pint.PintError,
    ArithmeticError,
    MemoryError,
    ValueError,
    TypeError,
    AssertionError,
    tokenize.TokenError,
)
_MAGNITUDE_RE = re.compile(r"^([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*(.*)$")
_PARSE_PARAMS_HASH = blake3.blake3(b"{}").hexdigest()

# One registry per process (Pint's own recommendation) — constructing it
# is expensive, and units/quantities from different registries cannot be
# safely compared, mirroring the "construct once, reuse across the whole
# batch" pattern from normalizers/script.py's language detector.
# pint.UnitRegistry is generic; not worth pinning the type parameter here.
_UREG = pint.UnitRegistry()  # type: ignore[var-annotated]  # pint's generic Registry needs a param mypy would infer; default unit registry is intentional here


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

        # Split the magnitude off ourselves and build the Quantity from the
        # pair, instead of handing the whole string to `_UREG(...)`.
        # `_UREG(str)` is pint's expression EVALUATOR, and evaluating a data
        # value rather than parsing it caused three distinct faults:
        #
        #   "5 °C"        -> OffsetUnitCalculusError, because the evaluator
        #                    reads it as 5 * degC and multiplying an offset
        #                    unit is ambiguous. Every temperature, in other
        #                    words — and the error is a TypeError, so the
        #                    old `except ... ValueError` never caught it and
        #                    it escaped the normalizer entirely.
        #   "3 ft 2 in"   -> 0.046 meter ** 2. Juxtaposition means multiply,
        #                    so a compound length silently became an AREA.
        #                    A wrong answer is worse than a refusal.
        #   "2**2**99 kg" -> evaluated for real, exhausting memory. One
        #                    hostile or corrupt cell could take the process
        #                    down, since nothing bounds a per-value parse.
        #
        # `Quantity(magnitude, unit)` has no evaluator: offset units work,
        # a leftover "ft 2 in" is an undefined unit rather than a product,
        # and there is no arithmetic to exploit.
        match = _MAGNITUDE_RE.match(cleaned)
        if match is None:
            return _invalid(value, ctx, reason="no leading numeric magnitude found")
        magnitude_text, unit_text = match.groups()
        # A bare number stays a genuinely dimensionless quantity rather than
        # an error; callers that require a real unit check `dimensionality`.
        # Integer magnitudes stay integers so "5 km" does not become "5.0".
        magnitude = (
            float(magnitude_text)
            if any(c in magnitude_text for c in ".eE")
            else int(magnitude_text)
        )
        try:
            quantity = _UREG.Quantity(magnitude, unit_text or "dimensionless")
        except _PINT_FAILURES as exc:
            return _invalid(value, ctx, reason=str(exc) or type(exc).__name__)

        try:
            base = quantity.to_base_units()
        except _PINT_FAILURES as exc:
            return _invalid(value, ctx, reason=str(exc) or type(exc).__name__)

        structured = {
            # The magnitude exactly as written, not a round-tripped float.
            "original_value": magnitude_text,
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

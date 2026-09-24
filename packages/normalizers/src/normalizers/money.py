"""MoneyNormalizer — an amount and its currency, kept together.

NUMERIC already parses "$1,234.56" to 1234.56, but it drops the "$" into
`structured` and the caller gets a bare number. That is fine for a
measurement and wrong for money: you cannot sum a column whose currency
you discarded, and "100 USD" and "100 JPY" are not the same amount.

MONEY resolves both halves with the normalizers that already own each
job — NumericNormalizer for the amount, CurrencyNormalizer for the
currency — rather than re-implementing locale-aware decimal parsing or
ISO 4217 lookup a second time. `display` is the bare canonical amount so
the destination column can be NUMERIC and SUM/AVG work; the currency
travels in `structured` and in the companion column the clone writes.

An amount with no currency at all is still NORMALIZED (a single-currency
column is the common case and its currency is not in the cell); the
currency is simply absent. A value with no parseable AMOUNT is INVALID —
that is the part a money column exists to hold.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import blake3
import pyarrow as pa
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType, MissingKind, NormalizationStatus, Reversibility
from normcore.models import NormalizedValue
from normcore.pii import character_class_mask, content_hash
from normcore.rules import ComponentVersionInfo, ExplanationText, ValidationOutcome
from normcore.trace import TraceStep

from normalizers.currency import CurrencyNormalizer
from normalizers.numeric import NumericNormalizer

if TYPE_CHECKING:
    from collections.abc import Sequence

    from normcore.interfaces import ComponentVersion, Explanation, StepSpec, ValidationResult

_VERSION = "0.1.0"
_PARSE_PARAMS_HASH = blake3.blake3(b"{}").hexdigest()

# The currency half of a money value: an ISO 4217 code, or a symbol.
# Digits, separators and the sign belong to the amount.
_CURRENCY_PART_RE = re.compile(r"[^\d\s.,()+-]+")

# ISO 4217 minor units. Most currencies have 2; these are the exceptions,
# and they are why the destination column is scaled to 4 rather than 2.
_MINOR_UNITS: dict[str, int] = {
    "BHD": 3, "IQD": 3, "JOD": 3, "KWD": 3, "LYD": 3, "OMR": 3, "TND": 3,
    "BIF": 0, "CLP": 0, "DJF": 0, "GNF": 0, "ISK": 0, "JPY": 0, "KMF": 0,
    "KRW": 0, "PYG": 0, "RWF": 0, "UGX": 0, "UYI": 0, "VND": 0, "VUV": 0,
    "XAF": 0, "XOF": 0, "XPF": 0,
    "CLF": 4, "UYW": 4,
}
_DEFAULT_MINOR_UNITS = 2


class _StaticStepSpec:
    def __init__(self, step_id: str, operation: str, reversibility: Reversibility, lossy: bool):
        self.step_id = step_id
        self.operation = operation
        self.claimed_reversibility = reversibility
        self.lossy = lossy


_PARSE_STEP = _StaticStepSpec("money.parse", "money.parse", Reversibility.LOSSY, True)
_STATIC_STEPS: tuple[_StaticStepSpec, ...] = (_PARSE_STEP,)


class MoneyNormalizer:
    name = "MoneyNormalizer"
    supported_types = frozenset({FieldSemanticType.MONEY})

    def __init__(self) -> None:
        self._numeric = NumericNormalizer()
        self._currency = CurrencyNormalizer()

    def can_handle(self, field_type: FieldSemanticType, ctx: NormalizationContext) -> bool:
        return field_type in self.supported_types

    def normalize(self, value: str | None, ctx: NormalizationContext) -> NormalizedValue:
        if value is None:
            return _missing(None, MissingKind.NULL, ctx)
        if value.strip() == "":
            return _missing(value, MissingKind.EMPTY_STRING, ctx)

        cleaned = value.strip()
        # Split the halves BEFORE delegating. NumericNormalizer only
        # strips a LEADING symbol, so handing it the whole string made
        # every trailing-code spelling ("1234.56 USD", the commonest one
        # in real exports) INVALID.
        currency_text = " ".join(_CURRENCY_PART_RE.findall(cleaned)).strip()
        amount_text = _CURRENCY_PART_RE.sub(" ", cleaned).strip()

        if not amount_text:
            # Nothing but currency/letters ("free", "N/A" already handled
            # upstream): there is no amount, which is the one part a money
            # column must have.
            return _unresolved(value, NormalizationStatus.INVALID, ctx)

        amount = self._numeric.normalize(amount_text, _as(ctx, FieldSemanticType.NUMERIC))
        if amount.display is None or (
            amount.normalization_status is not NormalizationStatus.NORMALIZED
        ):
            # Carry the amount's own verdict: an AMBIGUOUS separator stays
            # ambiguous rather than being downgraded to a flat failure.
            return _unresolved(value, amount.normalization_status, ctx)

        currency_code = None
        if currency_text:
            resolved = self._currency.normalize(currency_text, _as(ctx, FieldSemanticType.CURRENCY))
            if resolved.normalization_status is NormalizationStatus.NORMALIZED:
                currency_code = resolved.comparison

        canonical = str(amount.display)
        structured = {
            "canonical_amount": canonical,
            "currency": currency_code,
            "minor_units": _MINOR_UNITS.get(currency_code or "", _DEFAULT_MINOR_UNITS),
            "currency_source": currency_text or None,
        }
        return NormalizedValue(
            original=value,
            display=canonical,
            comparison=canonical if currency_code is None else f"{canonical} {currency_code}",
            search=canonical,
            structured=structured,
            validation_status="VALID",
            normalization_status=NormalizationStatus.NORMALIZED,
            confidence=amount.confidence,
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
            reason=None if is_valid else "could not parse an amount",
        )

    def explain(self, result: NormalizedValue) -> Explanation:
        currency = result.structured.get("currency")
        if result.normalization_status is not NormalizationStatus.NORMALIZED:
            return ExplanationText(
                plain_language="Could not read an amount from this value.",
                technical=f"status={result.normalization_status.value}",
            )
        suffix = f" in {currency}" if currency else " (no currency in the value)"
        return ExplanationText(
            plain_language=f"Amount {result.display}{suffix}.",
            technical=f"structured={result.structured}",
        )

    def version(self) -> ComponentVersion:
        return ComponentVersionInfo(name=self.name, version=_VERSION)

    def steps(self) -> Sequence[StepSpec]:
        return _STATIC_STEPS

    def inverse(self, step_id: str, value: str) -> str | None:
        return None


def _as(ctx: NormalizationContext, semantic_type: FieldSemanticType) -> NormalizationContext:
    """A sub-context for a delegated normalizer. `context_hash` is derived
    from the context, and the dispatcher asserts the two agree, so the
    delegate must be handed a context that really says what it is."""
    return ctx.model_copy(update={"semantic_type": semantic_type})


def _unresolved(
    value: str, status: NormalizationStatus, ctx: NormalizationContext
) -> NormalizedValue:
    return NormalizedValue(
        original=value,
        display=value,
        normalization_status=status,
        validation_status="INVALID" if status is NormalizationStatus.INVALID else "AMBIGUOUS",
        confidence=0.0,
        errors=["could not parse an amount"],
        structured={"canonical_amount": None, "currency": None},
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
        rule_id="money.parse",
        operation="money.parse",
        params_hash=_PARSE_PARAMS_HASH,
        input_hash=content_hash(value),
        output_hash=content_hash(value),
        input_mask=character_class_mask(value),
        output_mask=character_class_mask(value),
        changed=changed,
        lossy=True,
        reversibility=Reversibility.LOSSY,
        library="normalizers",
        library_version=_VERSION,
    )

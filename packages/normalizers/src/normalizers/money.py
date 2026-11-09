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

Magnitude words are the reason this module cannot just split and delegate.
The first version of that split treated EVERY non-numeric token as part
of the currency half and dropped whatever did not resolve, so
"$10.5 Million" normalized to 10.5 and reported NORMALIZED: a silent
1,000,000x error, found against a real 1.27M-row revenue column where
every value has that shape. Two rules now prevent it:

- A known magnitude word MULTIPLIES the amount ("$10.5 Million" ->
  10500000).
- An alphabetic token that is neither a currency nor a known magnitude is
  AMBIGUOUS. Never dropped — an unexplained word in a money value means
  the value was not understood, and a wrong number is far worse than a
  refused one.

A symbol several currencies share ("$5" with no country) is AMBIGUOUS too,
but the amount was read: it stays in `structured`, beside one reading per
currency CLDR gives that symbol (ADR-011 amendment 2026-11-08).
"""

from __future__ import annotations

import decimal
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

from normalizers.currency import CurrencyNormalizer, resolve_name
from normalizers.numeric import NumericNormalizer

if TYPE_CHECKING:
    from collections.abc import Sequence

    from normcore.interfaces import ComponentVersion, Explanation, StepSpec, ValidationResult

_VERSION = "0.1.0"
_PARSE_PARAMS_HASH = blake3.blake3(b"{}").hexdigest()

# The currency half of a money value: an ISO 4217 code, or a symbol.
# Digits, separators and the sign belong to the amount.
_CURRENCY_PART_RE = re.compile(r"[^\d\s.,()+-]+")

# Multipliers, English SHORT scale, spelled out. Applied to the amount.
#
# ponytail: short scale only, and no single letters. "M"/"B"/"K"/"T" are
# every bit as common in financial data, and are left out deliberately —
# "M" is the CLDR currency symbol for the Lesotho loti, so "10.5M" was
# resolving to 10.5 LSL, wrong in both halves at once. A single letter
# next to a number cannot be told from a currency symbol without asking
# the column, so it stays AMBIGUOUS. Long-scale locales are the other
# ceiling: German "Milliarde" is 10^9 and German "Billion" is 10^12, so
# only English words are listed and anything else is refused rather than
# guessed. Upgrade path for both: require ctx.locale and key this table
# by it.
_MAGNITUDES: dict[str, int] = {
    "hundred": 10**2,
    "thousand": 10**3,
    "million": 10**6,
    "mn": 10**6,
    "billion": 10**9,
    "bn": 10**9,
    "trillion": 10**12,
}

# A single ASCII letter in the currency half is refused even when it DOES
# resolve to a currency, for the "10.5M" reason above.
_SINGLE_LETTER_RE = re.compile(r"^[A-Za-z]$")

_HAS_LETTER_RE = re.compile(r"[^\W\d_]")

# ISO 4217 minor units. Most currencies have 2; these are the exceptions,
# and they are why the destination column is scaled to 4 rather than 2.
_MINOR_UNITS: dict[str, int] = {
    "BHD": 3,
    "IQD": 3,
    "JOD": 3,
    "KWD": 3,
    "LYD": 3,
    "OMR": 3,
    "TND": 3,
    "BIF": 0,
    "CLP": 0,
    "DJF": 0,
    "GNF": 0,
    "ISK": 0,
    "JPY": 0,
    "KMF": 0,
    "KRW": 0,
    "PYG": 0,
    "RWF": 0,
    "UGX": 0,
    "UYI": 0,
    "VND": 0,
    "VUV": 0,
    "XAF": 0,
    "XOF": 0,
    "XPF": 0,
    "CLF": 4,
    "UYW": 4,
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
        if value is None or value.strip() == "":
            kind = MissingKind.NULL if value is None else MissingKind.EMPTY_STRING
            return _missing(value, kind, ctx)

        cleaned = value.strip()
        # Split the halves BEFORE delegating. NumericNormalizer only
        # strips a LEADING symbol, so handing it the whole string made
        # every trailing-code spelling ("1234.56 USD", the commonest one
        # in real exports) INVALID.
        tokens = _CURRENCY_PART_RE.findall(cleaned)
        multiplier, currency_tokens = _split_magnitudes(tokens)
        currency_text = " ".join(currency_tokens).strip()
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

        currency_code, understood = self._currency_half(currency_text, ctx)
        if not understood:
            return _unresolved(value, NormalizationStatus.AMBIGUOUS, ctx)

        canonical = _scaled(str(amount.display), multiplier)
        readings = None if currency_code else self._shared_symbol_codes(currency_text, ctx)
        if readings:
            return _unresolved(value, NormalizationStatus.AMBIGUOUS, ctx).model_copy(
                update={
                    "errors": [
                        f"'{currency_text}' is used by several currencies, not guessed: "
                        "set the column's country or choose a reading"
                    ],
                    "structured": {
                        "canonical_amount": canonical,
                        "currency": None,
                        "currency_source": currency_text,
                        # Whole values, because a verdict is re-normalized as MONEY.
                        "candidates": [f"{canonical} {code}" for code in readings],
                    },
                }
            )
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

    def _currency_half(
        self, currency_text: str, ctx: NormalizationContext
    ) -> tuple[str | None, bool]:
        """(ISO code or None, whether the half was understood at all).

        `understood=False` is the guard that stops a silent wrong number:
        an alphabetic token that is neither a currency nor a known
        magnitude means the value was not understood, and dropping it is
        what turned "$10.5 Million" into 10.5. A bare ambiguous SYMBOL is
        understood — the amount beside it is still good.
        """
        if not currency_text:
            return None, True
        if _SINGLE_LETTER_RE.match(currency_text):
            return None, False
        code = self._resolve(currency_text, ctx)
        if code is not None:
            # CURRENCY finds a code anywhere in its text ("SKU USD"), so the
            # `O` of a damaged `1234.56O USD` was dropped the same way. The
            # amount is already split off here, so several words must BE a
            # currency name ("US dollar"); otherwise some were not read.
            unread = (
                len(currency_text.split()) > 1 and resolve_name(currency_text.casefold()) is None
            )
            return (None, False) if unread else (code, True)
        return None, not _HAS_LETTER_RE.search(currency_text)

    def _resolve(self, currency_text: str, ctx: NormalizationContext) -> str | None:
        resolved = self._currency.normalize(currency_text, _as(ctx, FieldSemanticType.CURRENCY))
        if resolved.normalization_status is NormalizationStatus.NORMALIZED:
            return resolved.comparison
        return None

    def _shared_symbol_codes(self, currency_text: str, ctx: NormalizationContext) -> list[str]:
        if not currency_text:
            return []
        resolved = self._currency.normalize(currency_text, _as(ctx, FieldSemanticType.CURRENCY))
        return list(resolved.structured.get("candidates", []))

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
        # An amount whose only open question is the currency is still money.
        is_valid = (
            result.normalization_status is NormalizationStatus.NORMALIZED
            or result.structured.get("canonical_amount") is not None
        )
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


def _split_magnitudes(tokens: list[str]) -> tuple[int, list[str]]:
    """(multiplier, the tokens that are still the currency half)."""
    multiplier = 1
    remaining: list[str] = []
    for token in tokens:
        scale = _MAGNITUDES.get(token.casefold())
        if scale is None:
            remaining.append(token)
        else:
            multiplier *= scale
    return multiplier, remaining


def _scaled(amount: str, multiplier: int) -> str:
    """Apply a magnitude multiplier without going near a float.

    Returns `amount` untouched when there is no multiplier, so every value
    that has no magnitude word keeps byte-identical output. `format(..., "f")`
    rather than `str()`: Decimal renders 1.05E+7 in exponent form, which is
    not what a money column should contain.
    """
    if multiplier == 1:
        return amount
    try:
        scaled = decimal.Decimal(amount) * multiplier
    except decimal.InvalidOperation:  # pragma: no cover - amount already parsed
        return amount
    return format(scaled.normalize(), "f")


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

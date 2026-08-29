"""CurrencyNormalizer — Source.txt Phase 12, §47.

`$ / USD / US$ / US Dollars` resolve to `USD` only WITH context — a bare
`$` alone stays ambiguous (it is legal tender symbol for over 20
currencies). Inference draws on the value's own currency CODE (ISO 4217,
unambiguous by construction) or symbol PLUS `ctx.country`/`ctx.locale` —
never the symbol alone.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import blake3
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

# ISO 4217 codes are unambiguous by construction — recognizing one in the
# text always resolves confidently, no context required.
_ISO_CODE_RE = re.compile(r"\b([A-Z]{3})\b")

# Symbols are inherently ambiguous (§47) EXCEPT where a symbol is only
# used by one currency in practice — kept deliberately small.
_UNAMBIGUOUS_SYMBOLS: dict[str, str] = {
    "€": "EUR",
    "£": "GBP",
    "¥": "JPY",
}

# "$" specifically requires country/locale context — curated from
# common real-world data, not exhaustive.
_DOLLAR_COUNTRY_MAP: dict[str, str] = {
    "US": "USD",
    "CA": "CAD",
    "AU": "AUD",
    "NZ": "NZD",
    "SG": "SGD",
    "HK": "HKD",
}

_NAME_MAP: dict[str, str] = {
    "us dollar": "USD",
    "us dollars": "USD",
    "united states dollar": "USD",
    "euro": "EUR",
    "euros": "EUR",
    "british pound": "GBP",
    "pound sterling": "GBP",
    "japanese yen": "JPY",
}


class _StaticStepSpec:
    def __init__(self, step_id: str, operation: str, reversibility: Reversibility, lossy: bool):
        self.step_id = step_id
        self.operation = operation
        self.claimed_reversibility = reversibility
        self.lossy = lossy


_RESOLVE_STEP = _StaticStepSpec(
    "currency.resolve", "currency.resolve", Reversibility.PARTIALLY_REVERSIBLE, True
)
_STATIC_STEPS: tuple[_StaticStepSpec, ...] = (_RESOLVE_STEP,)


class CurrencyNormalizer:
    name = "CurrencyNormalizer"
    supported_types = frozenset({FieldSemanticType.CURRENCY})

    def can_handle(self, field_type: FieldSemanticType, ctx: NormalizationContext) -> bool:
        return field_type in self.supported_types

    def normalize(self, value: str | None, ctx: NormalizationContext) -> NormalizedValue:
        if value is None:
            return _missing(None, MissingKind.NULL, ctx)
        if value.strip() == "":
            return _missing(value, MissingKind.EMPTY_STRING, ctx)

        cleaned = value.strip()
        canonical, confidence = _resolve_currency(cleaned, ctx)

        if canonical is None:
            return _ambiguous(value, ctx)

        structured = {
            "original_currency": cleaned,
            "canonical_currency": canonical,
            "currency_confidence": confidence,
        }
        return NormalizedValue(
            original=value,
            display=canonical,
            comparison=canonical,
            search=canonical,
            structured=structured,
            validation_status="VALID",
            normalization_status=NormalizationStatus.NORMALIZED,
            confidence=confidence,
            trace=[_resolve_trace_step(value, changed=True)],
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
        is_valid = result.normalization_status is not NormalizationStatus.AMBIGUOUS
        return ValidationOutcome(
            is_valid=is_valid,
            status=result.validation_status or "UNKNOWN",
            reason=None if is_valid else "ambiguous currency symbol without context",
        )

    def explain(self, result: NormalizedValue) -> Explanation:
        if result.normalization_status is NormalizationStatus.AMBIGUOUS:
            return ExplanationText(
                plain_language="Currency symbol is ambiguous without country/locale context.",
                technical="AMBIGUOUS: bare symbol, no disambiguating context",
            )
        return ExplanationText(
            plain_language=f"Resolved to {result.display}.",
            technical=f"structured={result.structured}",
        )

    def version(self) -> ComponentVersion:
        return ComponentVersionInfo(name=self.name, version=_VERSION)

    def steps(self) -> Sequence[StepSpec]:
        return _STATIC_STEPS

    def inverse(self, step_id: str, value: str) -> str | None:
        return None


def _resolve_currency(cleaned: str, ctx: NormalizationContext) -> tuple[str | None, float]:
    iso_match = _ISO_CODE_RE.search(cleaned)
    if iso_match:
        return iso_match.group(1), 1.0

    lowered = cleaned.casefold()
    if lowered in _NAME_MAP:
        return _NAME_MAP[lowered], 1.0

    for symbol, code in _UNAMBIGUOUS_SYMBOLS.items():
        if symbol in cleaned:
            return code, 0.95

    if "$" in cleaned:
        country = (ctx.country or "").upper()
        if country in _DOLLAR_COUNTRY_MAP:
            return _DOLLAR_COUNTRY_MAP[country], 0.8
        return None, 0.0  # genuinely ambiguous — never guess

    return None, 0.0


def _ambiguous(value: str, ctx: NormalizationContext) -> NormalizedValue:
    return NormalizedValue(
        original=value,
        display=value,
        structured={"original_currency": value, "canonical_currency": None},
        validation_status="AMBIGUOUS",
        normalization_status=NormalizationStatus.AMBIGUOUS,
        confidence=0.0,
        trace=[_resolve_trace_step(value, changed=False)],
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


def _resolve_trace_step(value: str, *, changed: bool) -> TraceStep:
    return TraceStep(
        step_order=1,
        rule_id="currency.resolve",
        operation="currency.resolve",
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

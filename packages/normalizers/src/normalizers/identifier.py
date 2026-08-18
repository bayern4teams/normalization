"""IdentifierNormalizer — Source.txt Phase 11 (§49-§51, §55).

Architecture per §51: generic operations (Unicode-digit normalization,
whitespace/case normalization) always apply; country-specific check-digit
validation via `python-stdnum` applies only when `ctx.country` maps to a
known module in `_STDNUM_REGISTRY` (a curated subset, not the full
stdnum catalog — extend as new country/domain needs arise). There is no
global regex (§51's explicit prohibition).

Two hard invariants, both mandatory golden tests:
- Leading zeros are NEVER removed (§49): `"000123"` stays `"000123"`.
- An identifier is NEVER cast to numeric (§55): comparison/search stay
  string-typed, never `int(value)`.

Separator ambiguity (§111): `"AB-001"` and `"AB001"` are never silently
treated as equal — an internal separator is preserved in `comparison`,
and its presence is flagged `POTENTIAL_COLLISION` so a human can decide
whether the two forms should actually be merged.
"""

from __future__ import annotations

import re
import unicodedata
import uuid as uuid_module
from typing import TYPE_CHECKING, Protocol

import blake3
import pyarrow as pa
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
from stdnum.de import vat as de_vat
from stdnum.fr import siren as fr_siren
from stdnum.gb import vat as gb_vat
from stdnum.us import ein as us_ein

if TYPE_CHECKING:
    from collections.abc import Sequence

    from normcore.interfaces import ComponentVersion, Explanation, StepSpec, ValidationResult

_VERSION = "0.1.0"
_PARSE_PARAMS_HASH = blake3.blake3(b"{}").hexdigest()

_INTERNAL_SEPARATOR_RE = re.compile(r"[A-Za-z0-9][-][A-Za-z0-9]")


class _StdnumModule(Protocol):
    def is_valid(self, value: str) -> bool: ...
    def compact(self, value: str) -> str: ...


# Curated country -> python-stdnum module registry (§51's
# "country-specific" tier). A small, real, working subset — not the full
# stdnum catalog (100+ country/domain modules) — extend as new countries
# are actually needed, per the same evidence-driven policy as
# normalizers/country_codes.py's alias table.
_STDNUM_REGISTRY: dict[str, _StdnumModule] = {
    "US": us_ein,
    "GB": gb_vat,
    "DE": de_vat,
    "FR": fr_siren,
}


class _StaticStepSpec:
    def __init__(self, step_id: str, operation: str, reversibility: Reversibility, lossy: bool):
        self.step_id = step_id
        self.operation = operation
        self.claimed_reversibility = reversibility
        self.lossy = lossy


_NORMALIZE_STEP = _StaticStepSpec(
    "identifier.normalize", "identifier.normalize", Reversibility.REVERSIBLE, False
)
_STATIC_STEPS: tuple[_StaticStepSpec, ...] = (_NORMALIZE_STEP,)


class IdentifierNormalizer:
    name = "IdentifierNormalizer"
    supported_types = frozenset(
        {FieldSemanticType.IDENTIFIER, FieldSemanticType.TAX_ID, FieldSemanticType.CODE}
    )

    def can_handle(self, field_type: FieldSemanticType, ctx: NormalizationContext) -> bool:
        return field_type in self.supported_types

    def normalize(self, value: str | None, ctx: NormalizationContext) -> NormalizedValue:
        if value is None:
            return _missing(None, MissingKind.NULL, ctx)
        if value.strip() == "":
            return _missing(value, MissingKind.EMPTY_STRING, ctx)

        cleaned = _normalize_unicode_digits(value.strip())
        cleaned = cleaned.upper()

        has_internal_separator = bool(_INTERNAL_SEPARATOR_RE.search(cleaned))
        flags: list[QualityFlag] = []
        if has_internal_separator:
            flags.append(QualityFlag.POTENTIAL_COLLISION)

        check_digit_valid: bool | None = None
        identifier_type: str | None = None
        if ctx.semantic_type is FieldSemanticType.TAX_ID and ctx.country:
            module = _STDNUM_REGISTRY.get(ctx.country.upper())
            if module is not None:
                identifier_type = ctx.country.upper()
                try:
                    check_digit_valid = module.is_valid(cleaned)
                except Exception:
                    check_digit_valid = False

        structured: dict[str, object] = {
            "cleaned": cleaned,
            "has_internal_separator": has_internal_separator,
            "check_digit_valid": check_digit_valid,
            "identifier_type": identifier_type,
        }

        status = NormalizationStatus.NORMALIZED
        confidence = 1.0
        if check_digit_valid is False:
            status = NormalizationStatus.INVALID
            confidence = 0.3

        return NormalizedValue(
            original=value,
            display=cleaned,
            comparison=cleaned,
            search=cleaned,
            structured=structured,
            validation_status="VALID" if check_digit_valid is not False else "INVALID",
            normalization_status=status,
            confidence=confidence,
            flags=flags,
            trace=[_normalize_trace_step(value, changed=cleaned != value)],
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
        is_valid = result.structured.get("check_digit_valid") is not False
        return ValidationOutcome(
            is_valid=is_valid,
            status=result.validation_status or "UNKNOWN",
            reason=None if is_valid else "failed check-digit validation",
        )

    def explain(self, result: NormalizedValue) -> Explanation:
        if result.structured.get("has_internal_separator"):
            return ExplanationText(
                plain_language=(
                    "Contains an internal separator; a separator-free variant of this "
                    "identifier is a potential (not automatic) match."
                ),
                technical=f"structured={result.structured}",
            )
        return ExplanationText(
            plain_language="Normalized (case/Unicode-digit cleanup only).",
            technical=f"structured={result.structured}",
        )

    def version(self) -> ComponentVersion:
        return ComponentVersionInfo(name=self.name, version=_VERSION)

    def steps(self) -> Sequence[StepSpec]:
        return _STATIC_STEPS

    def inverse(self, step_id: str, value: str) -> str | None:
        return None


class UuidNormalizer:
    """Registered separately for UUID (§50): canonical lowercase
    hyphenated form. Kept apart from IdentifierNormalizer since UUID
    canonicalization has nothing to do with country/check-digit logic."""

    name = "UuidNormalizer"
    supported_types = frozenset({FieldSemanticType.UUID})

    def can_handle(self, field_type: FieldSemanticType, ctx: NormalizationContext) -> bool:
        return field_type in self.supported_types

    def normalize(self, value: str | None, ctx: NormalizationContext) -> NormalizedValue:
        if value is None:
            return _missing(None, MissingKind.NULL, ctx)
        if value.strip() == "":
            return _missing(value, MissingKind.EMPTY_STRING, ctx)

        cleaned = value.strip()
        try:
            parsed = uuid_module.UUID(cleaned)
        except ValueError:
            return NormalizedValue(
                original=value,
                display=value,
                normalization_status=NormalizationStatus.INVALID,
                validation_status="INVALID",
                confidence=0.0,
                errors=["not a valid UUID"],
                structured={},
                trace=[_normalize_trace_step(value, changed=False)],
                lossiness=Reversibility.LOSSLESS,
                profile_version="",
                env_id="",
                semantic_type=ctx.semantic_type,
                context_hash=ctx.context_hash,
            )

        canonical = str(parsed)
        return NormalizedValue(
            original=value,
            display=canonical,
            comparison=canonical,
            search=canonical,
            structured={"version": parsed.version, "canonical": canonical},
            validation_status="VALID",
            normalization_status=NormalizationStatus.NORMALIZED,
            confidence=1.0,
            trace=[_normalize_trace_step(value, changed=canonical != cleaned)],
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
        is_valid = result.normalization_status is NormalizationStatus.NORMALIZED
        return ValidationOutcome(
            is_valid=is_valid,
            status=result.validation_status or "UNKNOWN",
            reason=None if is_valid else "not a valid UUID",
        )

    def explain(self, result: NormalizedValue) -> Explanation:
        return ExplanationText(
            plain_language=f"Canonical form: {result.display}.",
            technical=f"structured={result.structured}",
        )

    def version(self) -> ComponentVersion:
        return ComponentVersionInfo(name=self.name, version=_VERSION)

    def steps(self) -> Sequence[StepSpec]:
        return _STATIC_STEPS

    def inverse(self, step_id: str, value: str) -> str | None:
        return None


def _normalize_unicode_digits(value: str) -> str:
    """Converts any Unicode decimal digit (Arabic-Indic, Devanagari,
    fullwidth, ...) to its ASCII equivalent, character by character —
    never via `int()`/numeric parsing, so leading zeros and non-digit
    structure are always preserved (§49)."""
    chars = []
    for ch in value:
        digit = unicodedata.decimal(ch, None)
        chars.append(str(digit) if digit is not None else ch)
    return "".join(chars)


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
        rule_id="identifier.normalize",
        operation="identifier.normalize",
        params_hash=_PARSE_PARAMS_HASH,
        input_hash=content_hash(value),
        output_hash=content_hash(value),
        input_mask=character_class_mask(value),
        output_mask=character_class_mask(value),
        changed=changed,
        lossy=False,
        reversibility=Reversibility.REVERSIBLE,
        library="python-stdnum",
        library_version="1.x",
    )

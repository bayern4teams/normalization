"""CountryNormalizer — Source.txt Phase 10, §33.

`United States / USA / US / U.S.` all resolve to `US` via
`normalizers.country_codes.resolve_country_alpha2` (shared with
`AddressNormalizer`'s postal-code-validation lookup, so there is one
country-resolution implementation, not two). `United Kingdom` / `UK` /
`Great Britain` are explicitly flagged, not silently treated as
interchangeable: "UK" is a common but non-ISO abbreviation (resolved via
the same alias table `AddressNormalizer` uses), and "Great Britain" is
geographically narrower than "United Kingdom" (excludes Northern
Ireland) even though both commonly refer to the same ISO entry in casual
usage — the flag exists so a human reviewing normalization output can
see this resolution was an alias/approximation, not an exact ISO code
match.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import blake3
import pyarrow as pa
import pycountry
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

from normalizers.country_codes import resolve_country_alpha2

if TYPE_CHECKING:
    from collections.abc import Sequence

    from normcore.interfaces import ComponentVersion, Explanation, StepSpec, ValidationResult

_VERSION = "0.1.0"
_PARSE_PARAMS_HASH = blake3.blake3(b"{}").hexdigest()

# Aliases resolved via normalizers.country_codes' non-ISO table (rather
# than an exact pycountry lookup) get this flag — "UK" and "Great
# Britain" being §33's own worked examples.
_NON_ISO_ALIASES = frozenset({"uk", "great britain"})


class _StaticStepSpec:
    def __init__(self, step_id: str, operation: str, reversibility: Reversibility, lossy: bool):
        self.step_id = step_id
        self.operation = operation
        self.claimed_reversibility = reversibility
        self.lossy = lossy


_RESOLVE_STEP = _StaticStepSpec(
    "country.resolve", "country.resolve", Reversibility.PARTIALLY_REVERSIBLE, True
)
_STATIC_STEPS: tuple[_StaticStepSpec, ...] = (_RESOLVE_STEP,)


class CountryNormalizer:
    name = "CountryNormalizer"
    supported_types = frozenset({FieldSemanticType.COUNTRY})

    def can_handle(self, field_type: FieldSemanticType, ctx: NormalizationContext) -> bool:
        return field_type in self.supported_types

    def normalize(self, value: str | None, ctx: NormalizationContext) -> NormalizedValue:
        if value is None:
            return _missing(None, MissingKind.NULL, ctx)
        if value.strip() == "":
            return _missing(value, MissingKind.EMPTY_STRING, ctx)

        cleaned = value.strip()
        alpha2 = resolve_country_alpha2(cleaned)
        if alpha2 is None:
            return _unresolved(value, ctx)

        country = pycountry.countries.get(alpha_2=alpha2)
        if country is None:
            return _unresolved(value, ctx)

        via_non_iso_alias = cleaned.casefold() in _NON_ISO_ALIASES
        flags: list[QualityFlag] = []
        warnings: list[str] = []
        if via_non_iso_alias:
            flags.append(QualityFlag.AMBIGUOUS_LOCALE)
            warnings.append(
                f"'{cleaned}' is a common but non-ISO abbreviation, resolved to "
                f"{alpha2} ({country.name}) via an alias table, not an exact code match."
            )

        structured = {
            "country_name": country.name,
            "alpha2": country.alpha_2,
            "alpha3": country.alpha_3,
            "numeric": country.numeric,
            "original": cleaned,
        }

        return NormalizedValue(
            original=value,
            display=country.name,
            comparison=country.alpha_2,
            search=country.alpha_2.casefold(),
            structured=structured,
            validation_status="VALID",
            normalization_status=NormalizationStatus.NORMALIZED,
            confidence=0.85 if via_non_iso_alias else 1.0,
            flags=flags,
            warnings=warnings,
            trace=[_resolve_trace_step(value, changed=True)],
            lossiness=Reversibility.PARTIALLY_REVERSIBLE,
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
        is_valid = result.normalization_status is not NormalizationStatus.INVALID
        return ValidationOutcome(
            is_valid=is_valid,
            status=result.validation_status or "UNKNOWN",
            reason=None if is_valid else "unrecognized country",
        )

    def explain(self, result: NormalizedValue) -> Explanation:
        if result.normalization_status is NormalizationStatus.INVALID:
            return ExplanationText(
                plain_language="Not a recognized country name or code.",
                technical=f"errors={result.errors}",
            )
        return ExplanationText(
            plain_language=f"Resolved to {result.display} ({result.structured.get('alpha2')}).",
            technical=f"structured={result.structured}",
        )

    def version(self) -> ComponentVersion:
        return ComponentVersionInfo(name=self.name, version=_VERSION)

    def steps(self) -> Sequence[StepSpec]:
        return _STATIC_STEPS

    def inverse(self, step_id: str, value: str) -> str | None:
        return None


def _unresolved(value: str, ctx: NormalizationContext) -> NormalizedValue:
    return NormalizedValue(
        original=value,
        display=value,
        normalization_status=NormalizationStatus.INVALID,
        validation_status="INVALID",
        confidence=0.0,
        errors=["not a recognized country name or code"],
        structured={},
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
        rule_id="country.resolve",
        operation="country.resolve",
        params_hash=_PARSE_PARAMS_HASH,
        input_hash=content_hash(value),
        output_hash=content_hash(value),
        input_mask=character_class_mask(value),
        output_mask=character_class_mask(value),
        changed=changed,
        lossy=True,
        reversibility=Reversibility.PARTIALLY_REVERSIBLE,
        library="pycountry",
        library_version="24.x",
    )

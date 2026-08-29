"""LanguageNormalizer — Source.txt Phase 10, §34.

ISO 639 canonicalization via `pycountry.languages.lookup()`:
`English / en / eng` all resolve to the same canonical `en` (alpha_2)
code, falling back to alpha_3 for languages with no two-letter code.
`source_value` is always retained alongside `canonical_code`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import blake3
import pycountry
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


class _StaticStepSpec:
    def __init__(self, step_id: str, operation: str, reversibility: Reversibility, lossy: bool):
        self.step_id = step_id
        self.operation = operation
        self.claimed_reversibility = reversibility
        self.lossy = lossy


_RESOLVE_STEP = _StaticStepSpec(
    "language.resolve", "language.resolve", Reversibility.PARTIALLY_REVERSIBLE, True
)
_STATIC_STEPS: tuple[_StaticStepSpec, ...] = (_RESOLVE_STEP,)


class LanguageNormalizer:
    name = "LanguageNormalizer"
    supported_types = frozenset({FieldSemanticType.LANGUAGE})

    def can_handle(self, field_type: FieldSemanticType, ctx: NormalizationContext) -> bool:
        return field_type in self.supported_types

    def normalize(self, value: str | None, ctx: NormalizationContext) -> NormalizedValue:
        if value is None:
            return _missing(None, MissingKind.NULL, ctx)
        if value.strip() == "":
            return _missing(value, MissingKind.EMPTY_STRING, ctx)

        cleaned = value.strip()
        language = _resolve_language(cleaned)
        if language is None:
            return _unresolved(value, ctx)

        canonical_code = getattr(language, "alpha_2", None) or language.alpha_3

        structured = {
            "source_value": cleaned,
            "canonical_code": canonical_code,
            "language_name": language.name,
        }

        return NormalizedValue(
            original=value,
            display=language.name,
            comparison=canonical_code,
            search=canonical_code,
            structured=structured,
            validation_status="VALID",
            normalization_status=NormalizationStatus.NORMALIZED,
            confidence=1.0,
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
        is_valid = result.normalization_status is not NormalizationStatus.INVALID
        return ValidationOutcome(
            is_valid=is_valid,
            status=result.validation_status or "UNKNOWN",
            reason=None if is_valid else "unrecognized language",
        )

    def explain(self, result: NormalizedValue) -> Explanation:
        if result.normalization_status is NormalizationStatus.INVALID:
            return ExplanationText(
                plain_language="Not a recognized language name or code.",
                technical=f"errors={result.errors}",
            )
        code = result.structured.get("canonical_code")
        return ExplanationText(
            plain_language=f"Resolved to {result.display} ({code}).",
            technical=f"structured={result.structured}",
        )

    def version(self) -> ComponentVersion:
        return ComponentVersionInfo(name=self.name, version=_VERSION)

    def steps(self) -> Sequence[StepSpec]:
        return _STATIC_STEPS

    def inverse(self, step_id: str, value: str) -> str | None:
        return None


def _resolve_language(cleaned: str) -> pycountry.db.Data | None:
    """Tries exact ISO 639 code fields FIRST, before falling back to
    `pycountry.languages.lookup()`'s generic (code-or-name) search.

    Found empirically in M4: `pycountry.languages.lookup("en")` does NOT
    return English — it returns a different, obscure language whose
    `name` field happens to be the two-letter string "En" (alpha_3
    "enc"), because `lookup()` apparently checks name equality before —
    or instead of — an exact alpha_2 code match for short inputs. Trying
    `get(alpha_2=...)` / `get(alpha_3=...)` explicitly first sidesteps
    this entirely for the common case of a real ISO code being passed
    in, and `lookup()` remains the fallback for full names ("English")
    where this bug does not manifest.
    """
    lowered = cleaned.lower()
    if len(lowered) == 2:
        exact = pycountry.languages.get(alpha_2=lowered)
        if exact is not None:
            return cast("pycountry.db.Data", exact)
    if len(lowered) == 3:
        exact = pycountry.languages.get(alpha_3=lowered)
        if exact is not None:
            return cast("pycountry.db.Data", exact)
    try:
        return cast("pycountry.db.Data", pycountry.languages.lookup(cleaned))
    except LookupError:
        return None


def _unresolved(value: str, ctx: NormalizationContext) -> NormalizedValue:
    return NormalizedValue(
        original=value,
        display=value,
        normalization_status=NormalizationStatus.INVALID,
        validation_status="INVALID",
        confidence=0.0,
        errors=["not a recognized language name or code"],
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
        rule_id="language.resolve",
        operation="language.resolve",
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

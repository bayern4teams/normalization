"""CompanyNormalizer — Source.txt Phase 5 (§26-§28).

Legal-suffix stripping is conservative by construction: a suffix is only
removed when it is (1) token-final, (2) matches a dictionary entry, and
(3) the residual base name is non-trivial. `"The Limited"` must NOT
become `"The"` — this is a mandatory golden test (§26), and it is not
hypothetical: `cleanco.basename("The Limited")` (the library named as
this domain's *secondary* source) was verified in M3 to actually return
`"The"`, confirming exactly the failure mode §26 warns about. This module
therefore does NOT call `cleanco` for the primary stripping decision —
only the curated `legal-entity-suffixes.common` dictionary drives
stripping, with an explicit trivial-residual guard.

`jurisdiction_hint` is always a hint, never asserted as fact (§28):
ambiguous suffixes (e.g. "SA", used by many countries) get `None`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import blake3
import pyarrow as pa
from normcore.context import NormalizationContext
from normcore.enums import (
    FieldSemanticType,
    MissingKind,
    NormalizationStatus,
    Reversibility,
)
from normcore.errors import NormalizerFailure
from normcore.models import NormalizedValue
from normcore.pii import character_class_mask, content_hash
from normcore.rules import ComponentVersionInfo, ExplanationText, ValidationOutcome
from normcore.trace import TraceStep
from normcore.unicode_policy import UnicodeForm
from normdict.loader import DictionaryLoader, DictionaryNotFoundError

from normalizers import text_ops
from normalizers.unicode_normalizer import (
    UnicodeNormalizer,
    UnicodeProcessingOptions,
    build_unicode_trace,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from normcore.interfaces import ComponentVersion, Explanation, StepSpec, ValidationResult

_VERSION = "0.1.0"
_SUFFIX_STRIP_PARAMS_HASH = blake3.blake3(b"{}").hexdigest()

# Trailing token-window sizes to try, longest first, so multi-word
# suffixes ("Pty Ltd", "GmbH & Co. KG") are matched before falling back
# to a single trailing token.
_MAX_SUFFIX_TOKENS = 4

# A residual base name consisting only of these (after suffix removal) is
# not a real company name on its own — refuse to strip in that case.
# This is what keeps "The Limited" as "The Limited", not "The".
_TRIVIAL_RESIDUAL_TOKENS = frozenset({"the", "a", "an", "and", "of"})


class _StaticStepSpec:
    def __init__(self, step_id: str, operation: str, reversibility: Reversibility, lossy: bool):
        self.step_id = step_id
        self.operation = operation
        self.claimed_reversibility = reversibility
        self.lossy = lossy


_SUFFIX_STRIP_STEP = _StaticStepSpec(
    "company.strip_legal_suffix",
    "company.strip_legal_suffix",
    Reversibility.PARTIALLY_REVERSIBLE,
    True,
)
_STATIC_STEPS: tuple[_StaticStepSpec, ...] = (
    *(
        _StaticStepSpec(name, spec.operation, spec.claimed_reversibility, spec.lossy)
        for name, spec in text_ops.OPERATIONS.items()
    ),
    _SUFFIX_STRIP_STEP,
)


def _load_suffix_dictionary(loader: DictionaryLoader) -> dict[str, dict[str, object]]:
    try:
        dictionary = loader.load("legal-entity-suffixes.common")
    except DictionaryNotFoundError:
        return {}
    return {str(k).casefold(): dict(v) for k, v in dictionary.entries.items()}


def _normalize_suffix_key(tokens: tuple[str, ...]) -> str:
    return " ".join(t.strip(".").casefold() for t in tokens)


class CompanyNormalizer:
    name = "CompanyNormalizer"
    supported_types = frozenset({FieldSemanticType.COMPANY_NAME})

    def __init__(self, dictionary_loader: DictionaryLoader) -> None:
        self._unicode = UnicodeNormalizer()
        self._suffixes = _load_suffix_dictionary(dictionary_loader)

    def can_handle(self, field_type: FieldSemanticType, ctx: NormalizationContext) -> bool:
        return field_type in self.supported_types

    def normalize(self, value: str | None, ctx: NormalizationContext) -> NormalizedValue:
        if value is None:
            return _missing(None, MissingKind.NULL, ctx)
        if value.strip() == "":
            return _missing(value, MissingKind.EMPTY_STRING, ctx)

        options = UnicodeProcessingOptions(
            form=UnicodeForm.NFC, include_accent_stripped=True, include_confusables=False
        )
        try:
            unicode_result = self._unicode.process(value, options)
        except Exception as exc:
            msg = f"UnicodeNormalizer failed on field {ctx.field_name!r}: {exc}"
            raise NormalizerFailure(msg, operation="unicode_process") from exc

        legal_name = unicode_result.final_value
        trace = build_unicode_trace(unicode_result, enabled=ctx.include_trace)

        match = _find_suffix_match(legal_name, self._suffixes)
        strip_changed = match is not None
        trace = [*trace, _suffix_strip_trace_step(legal_name, changed=strip_changed)]

        if match is not None:
            base_name, suffix_info = match
            organization_type = suffix_info.get("organization_type")
            elf_code = suffix_info.get("elf_code")
            jurisdiction_hint = suffix_info.get("jurisdiction_hint")
            suffix_canonical = suffix_info.get("canonical")
        else:
            base_name = legal_name
            organization_type = None
            elf_code = None
            jurisdiction_hint = None
            suffix_canonical = None

        comparison_base, _ = text_ops.casefold(base_name, ctx.locale)
        comparison_name, _ = text_ops.normalize_punctuation(comparison_base)

        structured: dict[str, object] = {
            "legal_name": legal_name,
            "base_name": base_name,
            "organization_type": organization_type,
            "elf_code": elf_code,
            "jurisdiction_hint": jurisdiction_hint,
            "suffix_canonical": suffix_canonical,
        }

        status = (
            NormalizationStatus.NORMALIZED
            if (strip_changed or unicode_result.changed)
            else NormalizationStatus.UNCHANGED
        )

        return NormalizedValue(
            original=value,
            display=legal_name,
            comparison=comparison_name,
            search=comparison_name,
            structured=structured,
            validation_status="VALID",
            normalization_status=status,
            confidence=1.0,
            trace=trace,
            lossiness=(
                Reversibility.PARTIALLY_REVERSIBLE if strip_changed else Reversibility.LOSSLESS
            ),
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
        return ValidationOutcome(is_valid=True, status="VALID")

    def explain(self, result: NormalizedValue) -> Explanation:
        suffix = result.structured.get("suffix_canonical")
        if suffix:
            return ExplanationText(
                plain_language=f"Recognized legal suffix '{suffix}'.",
                technical=f"structured={result.structured}",
            )
        return ExplanationText(
            plain_language="No recognized legal suffix found; name left as-is.",
            technical=f"structured={result.structured}",
        )

    def version(self) -> ComponentVersion:
        return ComponentVersionInfo(name=self.name, version=_VERSION)

    def steps(self) -> Sequence[StepSpec]:
        return _STATIC_STEPS

    def inverse(self, step_id: str, value: str) -> str | None:
        if step_id.startswith("unicode_normalize_"):
            form_name = step_id.removeprefix("unicode_normalize_").upper()
            form = UnicodeForm(form_name)
            inverse_form = text_ops.inverse_unicode_form(form)
            if inverse_form is None:
                return None
            output, _ = text_ops.unicode_normalize(value, inverse_form)
            return output
        return None


def _find_suffix_match(
    legal_name: str, suffix_dict: dict[str, dict[str, object]]
) -> tuple[str, dict[str, object]] | None:
    """Tries the longest trailing token window first, so multi-word
    suffixes match before a shorter partial match would. Refuses to
    strip if the residual base name would be trivial (empty or made up
    only of stopwords like "the"/"a"/"an") — the guard that keeps
    "The Limited" intact per §26."""
    tokens = legal_name.split()
    if not tokens:
        return None

    for window in range(min(_MAX_SUFFIX_TOKENS, len(tokens)), 0, -1):
        trailing = tuple(tokens[-window:])
        key = _normalize_suffix_key(trailing)
        info = suffix_dict.get(key)
        if info is None:
            continue

        residual_tokens = tokens[:-window]
        residual = " ".join(residual_tokens)
        residual_words = {t.strip(".,").casefold() for t in residual_tokens}
        if not residual_tokens or residual_words <= _TRIVIAL_RESIDUAL_TOKENS:
            continue  # refuse to strip — residual is empty or trivial

        return residual, info

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


def _suffix_strip_trace_step(value: str, *, changed: bool) -> TraceStep:
    return TraceStep(
        step_order=99,
        rule_id="company.strip_legal_suffix",
        operation="company.strip_legal_suffix",
        params_hash=_SUFFIX_STRIP_PARAMS_HASH,
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

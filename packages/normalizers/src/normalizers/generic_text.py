"""GenericTextNormalizer — Source.txt Phase 3 (§9-§19, §53, §54, §56, §63).

The `Normalizer` Protocol implementation registered for `FREE_TEXT`. It
delegates all Unicode-layer work to `UnicodeNormalizer` (this package,
`unicode_normalizer.py`) and adds: missing-value sentinel detection
(§53/§54, dictionary-driven), multi-view assembly (§2), and the
NormalizedValue/trace contract.

Design decisions recorded in docs/verification/M2-verification-pack.md:
- `structured` carries the derived views that have no dedicated
  `NormalizedValue` field (accent_stripped, fingerprint, ngram_fingerprint,
  confusable diagnostics) — §19's variant list is broader than the fixed
  model fields, and `structured` is documented (data contract §2.E) as
  "domain-specific shape per semantic type."
- ASCII transliteration and OpenRefine fingerprints are opt-in
  (`include_ascii=True` / `include_fingerprints=True` constructor flags),
  off by default, matching §16's "never substitutes for the Unicode
  representation, always explicitly flagged" requirement. Per-field
  profile-driven opt-in (rather than a normalizer-instance-wide flag) is
  deferred to the profile-execution wiring milestone (M6/M7): the current
  `Normalizer.normalize(value, ctx)` signature (fixed in M1) does not pass
  a `FieldNormalizationConfig` through to individual normalizers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

# `import pyarrow` below is safe regardless of its position in this
# block: `normalizers/__init__.py` imports `icu` as ITS first statement,
# and Python always fully executes a package's `__init__.py` before any
# of its submodules (this file is `normalizers.generic_text`) — so icu
# has already claimed the process by the time this module's own body
# runs. See docs/adr/ADR-001-unicode-strategy.md's DLL-load-order
# addendum for why this ordering matters at all (PyICU/PyArrow native
# DLL conflict on Windows).
import pyarrow as pa
from normcore.context import NormalizationContext
from normcore.enums import (
    FieldSemanticType,
    MissingKind,
    NormalizationStatus,
    QualityFlag,
    Reversibility,
)
from normcore.errors import NormalizerFailure
from normcore.models import NormalizedValue
from normcore.rules import ComponentVersionInfo, ExplanationText, ValidationOutcome
from normcore.unicode_policy import UnicodeForm
from normdict.loader import DictionaryLoader, DictionaryNotFoundError

from normalizers import text_ops
from normalizers.unicode_normalizer import (
    UnicodeNormalizer,
    UnicodeProcessingOptions,
    UnicodeProcessingResult,
    build_unicode_trace,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from normcore.interfaces import ComponentVersion, Explanation, StepSpec, ValidationResult

_VERSION = "0.1.0"


class _StaticStepSpec:
    def __init__(self, step_id: str, operation: str, reversibility: Reversibility, lossy: bool):
        self.step_id = step_id
        self.operation = operation
        self.claimed_reversibility = reversibility
        self.lossy = lossy


def _build_static_steps() -> tuple[_StaticStepSpec, ...]:
    return tuple(
        _StaticStepSpec(name, spec.operation, spec.claimed_reversibility, spec.lossy)
        for name, spec in text_ops.OPERATIONS.items()
    )


_STATIC_STEPS = _build_static_steps()


def _load_missing_value_sentinels(loader: DictionaryLoader) -> dict[str, str]:
    try:
        dictionary = loader.load("missing-values.common")
    except DictionaryNotFoundError:
        return {}
    return {str(k).casefold(): str(v) for k, v in dictionary.entries.items()}


class GenericTextNormalizer:
    """Registered for `FREE_TEXT`. See module docstring for scope."""

    name = "GenericTextNormalizer"
    supported_types = frozenset({FieldSemanticType.FREE_TEXT})

    def __init__(
        self,
        dictionary_loader: DictionaryLoader,
        *,
        include_ascii: bool = False,
        include_fingerprints: bool = False,
    ) -> None:
        self._unicode = UnicodeNormalizer()
        self._sentinels = _load_missing_value_sentinels(dictionary_loader)
        self._include_ascii = include_ascii
        self._include_fingerprints = include_fingerprints

    def can_handle(self, field_type: FieldSemanticType, ctx: NormalizationContext) -> bool:
        return field_type in self.supported_types

    def normalize(self, value: str | None, ctx: NormalizationContext) -> NormalizedValue:
        if value is None:
            return self._missing(None, MissingKind.NULL, ctx)

        if value == "":
            return self._missing(value, MissingKind.EMPTY_STRING, ctx)

        if value.strip() == "":
            return self._missing(value, MissingKind.EMPTY_STRING, ctx)

        options = UnicodeProcessingOptions(
            form=UnicodeForm.NFC,
            include_accent_stripped=True,
            include_ascii=self._include_ascii,
            include_confusables=True,
            include_fingerprints=self._include_fingerprints,
            casefold_locale=ctx.locale,
        )
        try:
            result = self._unicode.process(value, options)
        except Exception as exc:
            msg = f"UnicodeNormalizer failed on field {ctx.field_name!r}: {exc}"
            raise NormalizerFailure(msg, operation="unicode_process") from exc

        display = result.final_value

        # Sentinel detection runs against the PIPELINE'S OUTPUT
        # (post-repair, post-punctuation-normalization), not the raw
        # input — e.g. a raw en-dash character and its normalized-
        # punctuation form "-" must both be recognized as the same
        # NOT_APPLICABLE sentinel, or feeding a value's own `display`
        # back in as a new `original` (the textbook idempotency check,
        # Source.txt §71) can disagree with the first pass: pass 1 sees
        # the en-dash as ordinary text and normalizes it to "-"; a naive
        # pass 2 checking the RAW value against the dictionary would then
        # treat that "-" as a missing-value sentinel, silently discarding
        # data pass 1 kept.
        # Checking the canonical `display` form in both passes makes this
        # detection idempotent by construction — found via Hypothesis
        # property testing in M2, not by manual review.
        sentinel_kind = self._sentinels.get(display.strip().casefold())
        if sentinel_kind is not None:
            return self._missing(value, MissingKind(sentinel_kind), ctx)

        if display == "":
            # A value that is entirely invisible/control characters (e.g.
            # a lone soft hyphen) normalizes down to the empty string —
            # for the same idempotency reason as the sentinel check
            # above, this must be treated identically to a literal ""
            # input (MissingKind.EMPTY_STRING with display=None), or
            # feeding this value's own `display` back in as a new
            # `original` would disagree with the first pass. Found via
            # Hypothesis property testing in M3.
            return self._missing(value, MissingKind.EMPTY_STRING, ctx)

        trace = build_unicode_trace(result)
        comparison, _ = text_ops.casefold(display, ctx.locale)
        search_base = result.accent_stripped if result.accent_stripped is not None else display
        search, _ = text_ops.casefold(search_base, ctx.locale)

        repaired = _extract_repaired_value(result)
        flags = _build_flags(result, repaired)
        structured = _build_structured(result)
        status = _resolve_status(result, repaired)

        return NormalizedValue(
            original=value,
            original_kind=None,
            repaired=repaired,
            display=display,
            comparison=comparison,
            search=search,
            ascii=result.ascii_form,
            structured=structured,
            validation_status="VALID" if display else "EMPTY_AFTER_NORMALIZATION",
            normalization_status=status,
            confidence=1.0,
            flags=flags,
            warnings=[],
            errors=[],
            trace=trace,
            lossiness=_overall_lossiness(result),
            profile_version="",
            env_id="",
            semantic_type=ctx.semantic_type,
            context_hash=ctx.context_hash,
        )

    def _missing(
        self, value: str | None, kind: MissingKind, ctx: NormalizationContext
    ) -> NormalizedValue:
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

    def normalize_batch(self, values: pa.Array, ctx: NormalizationContext) -> pa.StructArray:
        originals = values.to_pylist()
        results = [self.normalize(v, ctx) for v in originals]
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
        if result.original_kind is not None:
            return ExplanationText(
                plain_language=f"Recognized as a missing value ({result.original_kind.value}).",
                technical=f"original_kind={result.original_kind.value}; no text pipeline ran.",
            )
        changed_steps = [s for s in result.trace if s.changed]
        if not changed_steps:
            return ExplanationText(
                plain_language="No changes were needed.",
                technical="GenericTextNormalizer: all steps reported changed=False.",
            )
        plain = "; ".join(f"{s.operation.replace('_', ' ')}" for s in changed_steps)
        technical = " -> ".join(s.to_explanation_line() for s in changed_steps)
        return ExplanationText(
            plain_language=f"Applied: {plain}.",
            technical=technical,
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


def _extract_repaired_value(result: UnicodeProcessingResult) -> str | None:
    repair_step = next((s for s in result.steps if s.operation == "text_repair"), None)
    if repair_step is not None and repair_step.changed:
        return repair_step.output
    return None


def _build_flags(result: UnicodeProcessingResult, repaired: str | None) -> list[QualityFlag]:
    flags: list[QualityFlag] = []
    if repaired is not None:
        flags.append(QualityFlag.MOJIBAKE_FIXED)
        flags.append(QualityFlag.ENCODING_REPAIRED)
    if any(s.operation.startswith("unicode_normalize_") and s.changed for s in result.steps):
        flags.append(QualityFlag.UNICODE_NORMALIZED)
    if result.confusables is not None and result.confusables.mixed_script_detected:
        flags.append(QualityFlag.MIXED_SCRIPT)
        flags.append(QualityFlag.CONFUSABLE_DETECTED)
    return flags


def _build_structured(result: UnicodeProcessingResult) -> dict[str, object]:
    structured: dict[str, object] = {}
    if result.accent_stripped is not None:
        structured["accent_stripped"] = result.accent_stripped
    if result.fingerprint is not None:
        structured["fingerprint"] = result.fingerprint
    if result.ngram_fingerprint is not None:
        structured["ngram_fingerprint"] = result.ngram_fingerprint
    if result.confusables is not None:
        structured["confusable_skeleton"] = result.confusables.confusable_skeleton
        structured["scripts_present"] = list(result.confusables.scripts_present)
        structured["mixed_script_detected"] = result.confusables.mixed_script_detected
    return structured


def _resolve_status(result: UnicodeProcessingResult, repaired: str | None) -> NormalizationStatus:
    if repaired is not None:
        return NormalizationStatus.REPAIRED
    if result.changed:
        return NormalizationStatus.NORMALIZED
    return NormalizationStatus.UNCHANGED


def _overall_lossiness(result: UnicodeProcessingResult) -> Reversibility:
    if not result.changed:
        return Reversibility.LOSSLESS
    if result.any_lossy_step_applied:
        return Reversibility.LOSSY
    return Reversibility.REVERSIBLE

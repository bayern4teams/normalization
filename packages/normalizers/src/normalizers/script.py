"""ScriptNormalizer — Source.txt Phase 10, §35.

ICU script detection (the dominant Unicode script among the value's
letters) plus `lingua-py` as a language *hint* on short strings. Neither
signal ever triggers transliteration automatically (§35's explicit
prohibition) — both are purely diagnostic fields.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import blake3
import icu
from lingua import LanguageDetectorBuilder
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType, MissingKind, NormalizationStatus, Reversibility
from normcore.models import NormalizedValue
from normcore.pii import character_class_mask, content_hash
from normcore.rules import ComponentVersionInfo, ExplanationText, ValidationOutcome
from normcore.trace import TraceStep

if TYPE_CHECKING:
    from collections.abc import Sequence

    from lingua import LanguageDetector
    from normcore.interfaces import ComponentVersion, Explanation, StepSpec, ValidationResult

_VERSION = "0.1.0"
_PARSE_PARAMS_HASH = blake3.blake3(b"{}").hexdigest()

# Built lazily, once, and shared across every ScriptNormalizer instance
# (n-gram models are expensive to load: ~2.6s, the dominant per-process
# cost measured in the Phase 3 throughput/memory program). Building this
# at MODULE scope — as it previously was — forces every process that
# imports `normalizers` (every Phase 3 pool worker included) to pay it
# whether or not it ever normalizes a SCRIPT field, and it cannot be
# skipped by simply not registering ScriptNormalizer. Lazy + lock-guarded
# so concurrent first callers (M21's GIL-bound run threads) block on one
# real build instead of racing into several redundant ones.
_language_detector: LanguageDetector | None = None
_language_detector_lock = threading.Lock()


def _get_language_detector() -> LanguageDetector:
    global _language_detector  # noqa: PLW0603 - module-level lazy singleton, matches text_ops._get_spoof_checker
    if _language_detector is None:
        with _language_detector_lock:
            if _language_detector is None:
                _language_detector = LanguageDetectorBuilder.from_all_languages().build()
    return _language_detector


class _StaticStepSpec:
    def __init__(self, step_id: str, operation: str, reversibility: Reversibility, lossy: bool):
        self.step_id = step_id
        self.operation = operation
        self.claimed_reversibility = reversibility
        self.lossy = lossy


_DETECT_STEP = _StaticStepSpec("script.detect", "script.detect", Reversibility.LOSSLESS, False)
_STATIC_STEPS: tuple[_StaticStepSpec, ...] = (_DETECT_STEP,)


class ScriptNormalizer:
    name = "ScriptNormalizer"
    supported_types = frozenset({FieldSemanticType.SCRIPT})

    def can_handle(self, field_type: FieldSemanticType, ctx: NormalizationContext) -> bool:
        return field_type in self.supported_types

    def normalize(self, value: str | None, ctx: NormalizationContext) -> NormalizedValue:
        if value is None:
            return _missing(None, MissingKind.NULL, ctx)
        if value.strip() == "":
            return _missing(value, MissingKind.EMPTY_STRING, ctx)

        cleaned = value.strip()
        script, script_confidence = _detect_dominant_script(cleaned)
        language_hint, language_confidence = _detect_language_hint(cleaned)

        structured = {
            "script": script,
            "script_confidence": script_confidence,
            "language_hint": language_hint,
            "language_hint_confidence": language_confidence,
        }

        return NormalizedValue(
            original=value,
            display=value,
            comparison=value,
            search=value,
            structured=structured,
            validation_status="VALID" if script is not None else "UNKNOWN",
            normalization_status=NormalizationStatus.NORMALIZED,
            confidence=script_confidence or 0.0,
            trace=[_detect_trace_step(value, changed=False)],
            lossiness=Reversibility.LOSSLESS,
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
        has_script = result.structured.get("script") is not None
        return ValidationOutcome(
            is_valid=has_script,
            status=result.validation_status or "UNKNOWN",
            reason=None if has_script else "no alphabetic script detected",
        )

    def explain(self, result: NormalizedValue) -> Explanation:
        return ExplanationText(
            plain_language=f"Detected script: {result.structured.get('script')}.",
            technical=f"structured={result.structured}",
        )

    def version(self) -> ComponentVersion:
        return ComponentVersionInfo(name=self.name, version=_VERSION)

    def steps(self) -> Sequence[StepSpec]:
        return _STATIC_STEPS

    def inverse(self, step_id: str, value: str) -> str | None:
        return None


def _detect_dominant_script(value: str) -> tuple[str | None, float]:
    counts: dict[str, int] = {}
    total_letters = 0
    for ch in value:
        if not ch.isalpha():
            continue
        total_letters += 1
        script_name = icu.Script.getScript(ord(ch)).getName()
        if script_name in {"Common", "Inherited"}:
            continue
        counts[script_name] = counts.get(script_name, 0) + 1

    if not counts or total_letters == 0:
        return None, 0.0

    dominant_script, dominant_count = max(counts.items(), key=lambda item: item[1])
    return dominant_script, dominant_count / total_letters


def _detect_language_hint(value: str) -> tuple[str | None, float]:
    letters_only = "".join(ch for ch in value if ch.isalpha())
    if len(letters_only) < 3:
        return None, 0.0
    confidences = _get_language_detector().compute_language_confidence_values(value)
    if not confidences:
        return None, 0.0
    best = confidences[0]
    if best.value <= 0.0:
        return None, 0.0
    return best.language.name, best.value


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


def _detect_trace_step(value: str, *, changed: bool) -> TraceStep:
    return TraceStep(
        step_order=1,
        rule_id="script.detect",
        operation="script.detect",
        params_hash=_PARSE_PARAMS_HASH,
        input_hash=content_hash(value),
        output_hash=content_hash(value),
        input_mask=character_class_mask(value),
        output_mask=character_class_mask(value),
        changed=changed,
        lossy=False,
        reversibility=Reversibility.LOSSLESS,
        library="PyICU/lingua",
        library_version="1.x",
    )

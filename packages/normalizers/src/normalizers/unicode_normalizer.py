"""UnicodeNormalizer — the shared Unicode/text-cleanup engine named in
Source.txt §99's adapter list.

Unlike the other thirteen-plus adapters, `UnicodeNormalizer` is not
registered directly in `NormalizerRegistry` (dispatch keys on
`FieldSemanticType`, and there is no "this field IS Unicode" semantic
type — Unicode cleanup applies as a shared pre-processing stage across
*every* semantic type). Instead it is a reusable, independently
versioned component: `GenericTextNormalizer` (this M2 milestone) is its
first caller, and every semantic-domain adapter landing from M3 onward
(name, company, address, ...) calls the same `UnicodeNormalizer.process()`
before running its own domain-specific logic, so Unicode-layer behavior
(decode/repair/NFC/whitespace/control-char policy) never has to be
reimplemented or drift between adapters. This design decision is recorded
in the M2 verification pack.
"""

from __future__ import annotations

from dataclasses import dataclass

import blake3
from normcore.enums import NormalizationStatus, QualityFlag, Reversibility
from normcore.models import NormalizedValue
from normcore.pii import character_class_mask, content_hash
from normcore.rules import ComponentVersionInfo
from normcore.trace import TraceStep
from normcore.unicode_policy import UnicodeForm

from normalizers import text_ops

_VERSION = "0.1.0"
_EMPTY_PARAMS_HASH = blake3.blake3(b"{}").hexdigest()

# The fixed, ordered default pipeline every call runs before any
# domain-specific per-field steps. Order matters: repair must happen
# before normalization (mojibake can hide behind combining-character
# sequences that NFC would otherwise "successfully" but wrongly compose),
# and whitespace/control cleanup happens last since earlier repair/
# normalization steps can themselves introduce or reveal whitespace runs.
_DEFAULT_STEP_ORDER: tuple[str, ...] = (
    "strip_control_chars",
    "normalize_nbsp",
    "collapse_whitespace",
    "trim",
)

# Bounded outer loop re-running the whole step sequence to a fixed point
# — see the docstring in `UnicodeNormalizer.process()` for why a single
# pass is not always idempotent. Bounded so pathological/oscillating
# input can never hang the pipeline.
_MAX_PIPELINE_PASSES = 3


@dataclass(frozen=True)
class AppliedStep:
    operation: str
    output: str
    changed: bool
    claimed_reversibility: str
    lossy: bool
    library: str
    library_version: str


@dataclass(frozen=True)
class UnicodeProcessingResult:
    original: str
    final_value: str
    steps: tuple[AppliedStep, ...]
    repair_explanations: tuple[str, ...]
    accent_stripped: str | None = None
    ascii_form: str | None = None
    confusables: text_ops.ConfusableReport | None = None
    fingerprint: str | None = None
    ngram_fingerprint: str | None = None

    @property
    def changed(self) -> bool:
        return self.final_value != self.original

    @property
    def any_lossy_step_applied(self) -> bool:
        return any(step.lossy and step.changed for step in self.steps)


@dataclass(frozen=True)
class UnicodeProcessingOptions:
    form: UnicodeForm = UnicodeForm.NFC
    apply_punctuation_normalization: bool = True
    include_accent_stripped: bool = True
    include_ascii: bool = False
    include_confusables: bool = True
    include_fingerprints: bool = False
    casefold_locale: str | None = None


def _run_step_sequence(
    value: str, opts: UnicodeProcessingOptions
) -> tuple[list[AppliedStep], str, list[str]]:
    """One pass of repair -> normalize -> control/whitespace cleanup ->
    punctuation. Returns (applied_steps, final_value, repair_explanations)
    for this pass only — `UnicodeNormalizer.process()` calls this in a
    bounded loop to reach a whole-pipeline fixed point."""
    steps: list[AppliedStep] = []
    current = value

    repaired, repair_changed, explanations = text_ops.repair_mojibake(current)
    steps.append(_build_step("text_repair", repaired, repair_changed))
    current = repaired

    form_op = f"unicode_normalize_{opts.form.value.lower()}"
    normalized, norm_changed = text_ops.unicode_normalize(current, opts.form)
    steps.append(_build_step(form_op, normalized, norm_changed))
    current = normalized

    for op_name in _DEFAULT_STEP_ORDER:
        output, changed = text_ops.apply_named_operation(op_name, current)
        steps.append(_build_step(op_name, output, changed))
        current = output

    if opts.apply_punctuation_normalization:
        output, changed = text_ops.normalize_punctuation(current)
        steps.append(_build_step("normalize_punctuation", output, changed))
        current = output

    return steps, current, explanations


class UnicodeNormalizer:
    """Stateless engine (holds only ICU/ftfy/anyascii handles, which
    `text_ops` already caches at module scope) — safe to construct once
    and share across every distinct value in a batch, per ADR-016."""

    name = "UnicodeNormalizer"

    def version(self) -> ComponentVersionInfo:
        return ComponentVersionInfo(name=self.name, version=_VERSION)

    def process(
        self, value: str, options: UnicodeProcessingOptions | None = None
    ) -> UnicodeProcessingResult:
        opts = options or UnicodeProcessingOptions()
        steps: list[AppliedStep] = []
        current = value
        explanations: list[str] = []

        # The mutating step sequence (repair -> normalize -> control/
        # whitespace cleanup -> punctuation) is re-run to a bounded fixed
        # point, not applied once: `repair_mojibake` is internally
        # convergent (see its own docstring), but the sequence AS A WHOLE
        # is not — Hypothesis found a case where a leading NBSP changes
        # whether ftfy's heuristics flag a trailing 2-character sequence
        # as mojibake, so pass 1 (repair sees the NBSP-prefixed string)
        # and a naive pass 2 (repair sees only what pass 1's later
        # whitespace/trim steps left behind) disagreed. Looping the whole
        # sequence here — not just the repair step — makes
        # `UnicodeNormalizer.process()` idempotent by construction:
        # feeding its own `final_value` back in as a new call's `value`
        # is guaranteed to reach the same fixed point in one call.
        for _ in range(_MAX_PIPELINE_PASSES):
            pass_steps, pass_result, pass_explanations = _run_step_sequence(current, opts)
            steps.extend(pass_steps)
            explanations.extend(pass_explanations)
            if pass_result == current:
                break
            current = pass_result

        accent_stripped = None
        if opts.include_accent_stripped:
            accent_stripped, _ = text_ops.strip_diacritics(current)

        ascii_form = None
        if opts.include_ascii:
            ascii_form, _ = text_ops.transliterate_ascii(current)

        confusables = text_ops.analyze_confusables(current) if opts.include_confusables else None

        fingerprint = None
        ngram_fingerprint = None
        if opts.include_fingerprints:
            fingerprint = text_ops.openrefine_fingerprint(current)
            ngram_fingerprint = text_ops.openrefine_ngram_fingerprint(current)

        return UnicodeProcessingResult(
            original=value,
            final_value=current,
            steps=tuple(steps),
            repair_explanations=tuple(explanations),
            accent_stripped=accent_stripped,
            ascii_form=ascii_form,
            confusables=confusables,
            fingerprint=fingerprint,
            ngram_fingerprint=ngram_fingerprint,
        )


def _build_step(operation: str, output: str, changed: bool) -> AppliedStep:
    spec = text_ops.OPERATIONS[operation]
    return AppliedStep(
        operation=operation,
        output=output,
        changed=changed,
        claimed_reversibility=spec.claimed_reversibility.value,
        lossy=spec.lossy,
        library=spec.library,
        library_version=spec.library_version,
    )


def build_unicode_trace(
    result: UnicodeProcessingResult, *, enabled: bool = True
) -> list[TraceStep]:
    """Converts a `UnicodeProcessingResult`'s applied steps into
    `TraceStep`s (PII-safe hashes/masks, per normcore.pii) — shared by
    every adapter that runs `UnicodeNormalizer.process()` as its first
    stage (`GenericTextNormalizer`, `NameNormalizer`, and later adapters),
    so trace assembly for the Unicode layer is implemented once.

    `enabled=False` (from `NormalizationContext.include_trace`) skips the
    whole thing and returns []. This is where the suppression lives rather
    than in each adapter because all four callers funnel through here, and
    this loop — two content_hash and two character_class_mask calls per
    applied step — is the measured cost, not the adapters' own one-or-two
    extra steps. Default True so every existing caller is unchanged."""
    if not enabled:
        return []
    trace: list[TraceStep] = []
    current_input = result.original
    for order, step in enumerate(result.steps, start=1):
        trace.append(
            TraceStep(
                step_order=order,
                rule_id=step.operation,
                operation=step.operation,
                params_hash=_EMPTY_PARAMS_HASH,
                input_hash=content_hash(current_input),
                output_hash=content_hash(step.output),
                input_mask=character_class_mask(current_input),
                output_mask=character_class_mask(step.output),
                changed=step.changed,
                lossy=step.lossy,
                reversibility=Reversibility(step.claimed_reversibility),
                library=step.library,
                library_version=step.library_version,
            )
        )
        current_input = step.output
    return trace


def disclose_repair(result: NormalizedValue, unicode: UnicodeProcessingResult) -> NormalizedValue:
    """`result` marked as repaired when the text repair step (ftfy) changed
    the input: REPAIRED, the repaired text, the same flags FREE_TEXT sets.
    Names and companies applied the repair silently, at NORMALIZED and
    LOSSLESS: `CafÃ©` -> `Café`, and `ß\x85` -> an NKo digit (PART1 N8)."""
    step = next((s for s in unicode.steps if s.operation == "text_repair"), None)
    if step is None or not step.changed or result.normalization_status in _NOT_ANSWERS:
        return result
    return result.model_copy(
        update={
            "repaired": step.output,
            "normalization_status": NormalizationStatus.REPAIRED,
            "flags": [*result.flags, QualityFlag.MOJIBAKE_FIXED, QualityFlag.ENCODING_REPAIRED],
            "lossiness": Reversibility.LOSSY,
        }
    )


_NOT_ANSWERS = frozenset(
    {
        NormalizationStatus.AMBIGUOUS,
        NormalizationStatus.INVALID,
        NormalizationStatus.FAILED,
        NormalizationStatus.NEEDS_REVIEW,
    }
)

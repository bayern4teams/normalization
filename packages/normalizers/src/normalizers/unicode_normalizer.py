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

from normcore.rules import ComponentVersionInfo
from normcore.unicode_policy import UnicodeForm

from normalizers import text_ops

_VERSION = "0.1.0"

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

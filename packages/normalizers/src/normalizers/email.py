"""EmailNormalizer — Source.txt Phase 7 (§39-§41).

`email-validator` with `check_deliverability=False` always, for
determinism (§41) — this implementation therefore never emits the
deliverability-dependent statuses UNKNOWN/POSSIBLY_DELIVERABLE/
UNDELIVERABLE; only VALID_SYNTAX, INVALID_SYNTAX, and INTERNATIONALIZED
are reachable. Provider-specific rules (Gmail dot-removal, plus-tag
stripping, ...) are OFF by default per §39/§4.5 — this module does not
implement them at all, so that default cannot be violated by omission.

Validated both PRE- and POST-normalization (§39's documented hazard:
`email-validator` itself warns normalization can change a string's
validity in either direction) — see `_validate_both_passes`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import blake3
from email_validator import EmailNotValidError, validate_email
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

if TYPE_CHECKING:
    from collections.abc import Sequence

    from email_validator import ValidatedEmail
    from normcore.interfaces import ComponentVersion, Explanation, StepSpec, ValidationResult

_VERSION = "0.1.0"
_PARSE_PARAMS_HASH = blake3.blake3(b"{}").hexdigest()


class _StaticStepSpec:
    def __init__(self, step_id: str, operation: str, reversibility: Reversibility, lossy: bool):
        self.step_id = step_id
        self.operation = operation
        self.claimed_reversibility = reversibility
        self.lossy = lossy


_PARSE_STEP = _StaticStepSpec(
    "email.parse_and_normalize",
    "email.parse_and_normalize",
    Reversibility.PARTIALLY_REVERSIBLE,
    True,
)
_STATIC_STEPS: tuple[_StaticStepSpec, ...] = (_PARSE_STEP,)


class EmailNormalizer:
    name = "EmailNormalizer"
    supported_types = frozenset({FieldSemanticType.EMAIL})

    def can_handle(self, field_type: FieldSemanticType, ctx: NormalizationContext) -> bool:
        return field_type in self.supported_types

    def normalize(self, value: str | None, ctx: NormalizationContext) -> NormalizedValue:
        if value is None:
            return _missing(None, MissingKind.NULL, ctx)
        if value.strip() == "":
            return _missing(value, MissingKind.EMPTY_STRING, ctx)

        result, display_name, error = _validate_both_passes(value)
        if result is None:
            return _invalid(value, ctx, reason=str(error))

        domain_is_ascii = result.domain == result.ascii_domain
        validation_status = "VALID_SYNTAX" if domain_is_ascii else "INTERNATIONALIZED"

        structured: dict[str, object] = {
            "display_name": display_name,
            "local_part": result.local_part,
            "domain": result.domain,
            "domain_ascii": result.ascii_domain,
            "normalized_address": result.normalized,
        }

        comparison = f"{result.local_part}@{result.domain.casefold()}"
        search = result.normalized.casefold()

        return NormalizedValue(
            original=value,
            display=result.normalized,
            comparison=comparison,
            search=search,
            structured=structured,
            validation_status=validation_status,
            normalization_status=NormalizationStatus.NORMALIZED,
            confidence=1.0,
            trace=[_parse_trace_step(value, changed=result.normalized != value.strip())],
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
            reason=None if is_valid else (result.errors[0] if result.errors else None),
        )

    def explain(self, result: NormalizedValue) -> Explanation:
        if result.normalization_status is NormalizationStatus.INVALID:
            reason = result.errors[0] if result.errors else "invalid syntax"
            return ExplanationText(
                plain_language=f"Not a valid email address: {reason}",
                technical=f"errors={result.errors}",
            )
        return ExplanationText(
            plain_language=f"Normalized to {result.display}.",
            technical=f"structured={result.structured}",
        )

    def version(self) -> ComponentVersion:
        return ComponentVersionInfo(name=self.name, version=_VERSION)

    def steps(self) -> Sequence[StepSpec]:
        return _STATIC_STEPS

    def inverse(self, step_id: str, value: str) -> str | None:
        return None


def _validate_both_passes(
    value: str,
) -> tuple[ValidatedEmail | None, str | None, Exception | None]:
    """Validates the RAW input, then re-validates the NORMALIZED result —
    `email-validator`'s own docs warn normalization can change a string's
    length/validity in either direction, so trusting only one pass is not
    sufficient (§39). Returns (final_result, display_name, error):
    `display_name` is captured from the FIRST pass only, since
    `.normalized` (what the second pass re-validates) is just the
    addr-spec with the display name already stripped out — the second
    pass's own `.display_name` attribute would always be None."""
    try:
        first_pass = validate_email(
            value.strip(),
            check_deliverability=False,
            allow_display_name=True,
        )
    except EmailNotValidError as exc:
        return None, None, exc

    display_name = first_pass.display_name.strip() if first_pass.display_name else None

    try:
        second_pass = validate_email(
            first_pass.normalized,
            check_deliverability=False,
            allow_display_name=True,
        )
    except EmailNotValidError as exc:
        # Normalization produced a string that is no longer valid — a
        # genuine failure mode `email-validator`'s docs call out
        # explicitly, not something we can silently paper over.
        return None, None, exc

    return second_pass, display_name, None


def _invalid(value: str, ctx: NormalizationContext, *, reason: str) -> NormalizedValue:
    return NormalizedValue(
        original=value,
        display=value,
        normalization_status=NormalizationStatus.INVALID,
        validation_status="INVALID_SYNTAX",
        confidence=0.0,
        flags=[QualityFlag.EMAIL_INVALID],
        errors=[reason],
        structured={},
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
        rule_id="email.parse_and_normalize",
        operation="email.parse_and_normalize",
        params_hash=_PARSE_PARAMS_HASH,
        input_hash=content_hash(value),
        output_hash=content_hash(value),
        input_mask=character_class_mask(value),
        output_mask=character_class_mask(value),
        changed=changed,
        lossy=True,
        reversibility=Reversibility.PARTIALLY_REVERSIBLE,
        library="email-validator",
        library_version="2.x",
    )

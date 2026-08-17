"""Error handling and field-level error policy — Source.txt §68, §69.

Never crash the full pipeline because one value is malformed. Every error is
recorded with enough context to diagnose it (field, record, operation,
error, severity, a raw-safe preview, the rule, and the library version) and
then handled according to the field's configured ErrorPolicy.
"""

from __future__ import annotations

from pydantic import BaseModel

from normcore.enums import ErrorPolicy


class NormalizationError(BaseModel):
    field: str
    record_ref: str
    operation: str
    error: str
    severity: str  # "warning" | "error" | "critical"
    safe_preview: str  # masked/truncated — never raw PII, see normcore.pii
    rule_id: str | None = None
    library_version: str | None = None


class NormalizerFailure(Exception):
    """Raised by a Normalizer implementation when it cannot process a value.

    Caught by the dispatch layer (normcore.dispatch) and translated into a
    NormalizationError plus a policy-driven outcome — never propagates out
    of a run.
    """

    def __init__(self, message: str, *, operation: str, rule_id: str | None = None) -> None:
        super().__init__(message)
        self.operation = operation
        self.rule_id = rule_id


def apply_error_policy(
    policy: ErrorPolicy,
    *,
    original_value: str | None,
) -> tuple[str | None, str]:
    """Resolve (output_value, status) for a failed normalization according
    to the field's configured ErrorPolicy. Returns a NormalizationStatus
    value as a plain string to avoid a circular import with enums usage
    sites that only need the string.
    """
    if policy is ErrorPolicy.FAIL_RECORD:
        # Caller (batch/run orchestration) is responsible for aborting the
        # whole record; this function only resolves the field-level output.
        return original_value, "FAILED"
    if policy is ErrorPolicy.SKIP_FIELD:
        return original_value, "FAILED"
    if policy is ErrorPolicy.RETURN_ORIGINAL:
        return original_value, "INVALID"
    if policy is ErrorPolicy.RETURN_NULL:
        return None, "INVALID"
    if policy is ErrorPolicy.MARK_INVALID:
        return original_value, "INVALID"
    msg = f"Unhandled ErrorPolicy: {policy!r}"
    raise AssertionError(msg)

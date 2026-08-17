"""Normalization trace — Source.txt §65.

Every transformed value must be able to show Original -> Step 1 -> Step 2
-> ... -> Final, machine-readable, with each step's operation, rule,
whether it changed the value, whether it was lossy, its declared/verified
reversibility class, and which library (and version) performed it.

Trace entries never carry raw values by default — see normcore.pii.
"""

from __future__ import annotations

from pydantic import BaseModel

from normcore.enums import Reversibility


class TraceStep(BaseModel):
    step_order: int
    rule_id: str
    operation: str
    params_hash: str
    input_hash: str
    output_hash: str
    input_mask: str
    output_mask: str
    changed: bool
    lossy: bool
    reversibility: Reversibility
    library: str | None = None
    library_version: str | None = None
    duration_us: int | None = None

    def to_explanation_line(self) -> str:
        """Plain-language line for the "Why did this change?" UX (§117).

        Callers assemble a full explanation from a StepSpec-provided human
        description; this method just formats the mechanical parts that are
        always available regardless of which normalizer produced the step.
        """
        verb = "changed" if self.changed else "checked, no change"
        lossy_note = " (lossy — original preserved)" if self.lossy else ""
        return f"Step {self.step_order}: {self.operation} — {verb}{lossy_note}"

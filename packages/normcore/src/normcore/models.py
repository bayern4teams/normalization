"""Core domain model — Source.txt §7, §107, §133.

NormalizedValue is the one output contract every Normalizer implementation
produces. It never collapses the distinct value types Source.txt §0
requires kept separate: original, repaired, display, comparison, search,
ascii, structured. No field here is optional in the sense of "sometimes
skip it because it's redundant" — a field being null/empty IS the answer
for that view when appropriate (e.g. `ascii` stays null unless ASCII
transliteration was actually requested for this field).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from normcore.enums import (
    FieldSemanticType,
    MissingKind,
    NormalizationStatus,
    QualityFlag,
    Reversibility,
)
from normcore.trace import TraceStep


class NormalizedValue(BaseModel):
    """Source.txt §107 data contract / §133 output contract.

    Field-for-field mirrors of this model exist as a JSON Schema (for the
    API) and an Arrow struct schema (for the sidecar store) — both are
    generated FROM this model, never hand-maintained separately, so they
    cannot drift. See docs/normalization-data-contract.md (M1) for the
    generation mechanism and packages/normcore/src/normcore/schema_export.py.
    """

    # --- the six distinct value types, Source.txt §0 / §2 ---
    original: str | None
    original_kind: MissingKind | None = None
    repaired: str | None = None
    display: str | None = None
    comparison: str | None = None
    search: str | None = None
    ascii: str | None = None
    structured: dict[str, Any] = Field(default_factory=dict)

    # --- status / confidence / diagnostics ---
    validation_status: str | None = None
    normalization_status: NormalizationStatus
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    flags: list[QualityFlag] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    # --- explainability / reproducibility, Source.txt §64, §65, §73 ---
    trace: list[TraceStep] = Field(default_factory=list)
    lossiness: Reversibility = Reversibility.LOSSLESS
    profile_version: str
    env_id: str
    semantic_type: FieldSemanticType
    context_hash: str

    def is_lossy(self) -> bool:
        return self.lossiness is Reversibility.LOSSY or any(step.lossy for step in self.trace)

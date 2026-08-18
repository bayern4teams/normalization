"""Normalization profiling — Source.txt §77.

A per-field preview summary shown before running the full pipeline:
rows/changed/unchanged/warnings/errors/potentially-lossy counts plus the
top transformation patterns actually observed — computed from a real
batch of `NormalizedValue` results (typically the same batch `/preview`
or an executed run already produced), not estimated.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from normcore.enums import NormalizationStatus, Reversibility
from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from collections.abc import Sequence

    from normcore.models import NormalizedValue

_TOP_PATTERNS_LIMIT = 10


class TransformationPatternCount(BaseModel):
    model_config = ConfigDict(frozen=True)

    operation: str
    count: int


class FieldProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    field_name: str
    rows: int
    changed: int
    unchanged: int
    warnings: int
    errors: int
    potentially_lossy: int
    top_transformation_patterns: list[TransformationPatternCount]


def profile_field(field_name: str, results: Sequence[NormalizedValue]) -> FieldProfile:
    changed = sum(1 for r in results if r.normalization_status is not NormalizationStatus.UNCHANGED)
    unchanged = len(results) - changed
    warnings = sum(len(r.warnings) for r in results)
    errors = sum(len(r.errors) for r in results)
    # "Potentially lossy" counts VALUES, not steps — a value with >= 1
    # lossy step in its trace, or a top-level LOSSY/PARTIALLY_REVERSIBLE
    # lossiness classification, matching §80's per-rule classification
    # applied at the value level here.
    potentially_lossy = sum(
        1
        for r in results
        if r.lossiness in (Reversibility.LOSSY, Reversibility.PARTIALLY_REVERSIBLE)
        or any(step.lossy for step in r.trace)
    )

    operation_counts: Counter[str] = Counter()
    for result in results:
        for step in result.trace:
            if step.changed:
                operation_counts[step.operation] += 1

    top_patterns = [
        TransformationPatternCount(operation=operation, count=count)
        for operation, count in operation_counts.most_common(_TOP_PATTERNS_LIMIT)
    ]

    return FieldProfile(
        field_name=field_name,
        rows=len(results),
        changed=changed,
        unchanged=unchanged,
        warnings=warnings,
        errors=errors,
        potentially_lossy=potentially_lossy,
        top_transformation_patterns=top_patterns,
    )

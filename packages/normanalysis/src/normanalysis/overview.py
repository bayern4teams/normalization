"""Normalization overview dashboard aggregation — Source.txt §90.

Aggregates exactly the counters §90's own worked example shows (fields
analyzed, fields normalized, rows processed, values changed, warnings,
potential collisions, ambiguous values, errors) from real profile/run
state — nothing here is estimated or sampled.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from normcore.enums import NormalizationStatus
from pydantic import BaseModel, ConfigDict

from normanalysis.impact import compute_impact

if TYPE_CHECKING:
    from collections.abc import Sequence

    from normcore.models import NormalizedValue
    from normcore.run import NormalizationRun


class OverviewReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    fields_analyzed: int
    fields_normalized: int
    rows_processed: int
    values_changed: int
    warnings: int
    potential_collisions: int
    ambiguous_values: int
    errors: int


def compute_overview(
    profile_field_refs: Sequence[str],
    executed_runs: Sequence[tuple[NormalizationRun, str, Sequence[NormalizedValue]]],
) -> OverviewReport:
    """`executed_runs` is (run, field_name, results) for every run that
    has actually been executed — a run created but never fed values
    contributes nothing here, correctly, since nothing was normalized."""
    analyzed_fields = set(profile_field_refs) | {field_name for _, field_name, _ in executed_runs}
    normalized_fields = {field_name for _, field_name, _ in executed_runs}

    rows_processed = sum(run.metrics.records_processed for run, _, _ in executed_runs)
    values_changed = sum(run.metrics.changed_values for run, _, _ in executed_runs)
    warnings = sum(run.metrics.warnings for run, _, _ in executed_runs)
    errors = sum(run.metrics.errors for run, _, _ in executed_runs)

    potential_collisions = 0
    for _, field_name, results in executed_runs:
        originals = [r.original for r in results]
        impact = compute_impact(field_name, originals, results)
        if impact.new_collisions > 0:
            potential_collisions += impact.new_collisions

    ambiguous_values = sum(
        1
        for _, _, results in executed_runs
        for r in results
        if r.normalization_status is NormalizationStatus.AMBIGUOUS
    )

    return OverviewReport(
        fields_analyzed=len(analyzed_fields),
        fields_normalized=len(normalized_fields),
        rows_processed=rows_processed,
        values_changed=values_changed,
        warnings=warnings,
        potential_collisions=potential_collisions,
        ambiguous_values=ambiguous_values,
        errors=errors,
    )

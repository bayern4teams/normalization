"""Bounded per-(table, column) rollup statistics — M18
(docs/plan/M13-M22-program-plan.md), Source.txt §90/§93 rearchitected.

`GET /overview` and `GET /quality` (M7) were unbounded: they looped
every known run, hydrated its FULL per-value result set (via
`store.get_execution`), and re-derived every aggregate number from
scratch on every request. At the row counts M17 makes real (a single
`Person.fullName` column run is ~11.8M rows), that means materializing
millions of `NormalizedValue` objects into Python on every dashboard
load — the exact OOM risk the M13-M22 plan flagged as its #2 top risk.

`ColumnStats` is the bounded (a fixed, small number of scalar fields
per (run, table, column), regardless of how many rows that column had)
replacement: computed ONCE, either from an in-memory result batch
(`compute_column_stats_from_results`, used by the pasted-values/
single-column `execute_run` path, whose result batch is already
capped and in memory) or by a DuckDB aggregate query pushed down over
the sidecar's Parquet files (`normio.sidecar_store.SidecarStore.
compute_column_stats`, used by M17's per-column chunked streaming
path, which never materializes per-value results in Python at all).
`compute_overview_from_stats`/`compute_quality_from_stats` below then
rebuild the exact same `OverviewReport`/`QualityReport` shapes M7
already returns, from a list of these bounded rows — `/overview` and
`/quality` never call `get_execution`/read per-value data again.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from normcore.enums import FieldSemanticType, NormalizationStatus
from pydantic import BaseModel, ConfigDict

from normanalysis.impact import compute_impact
from normanalysis.overview import OverviewReport
from normanalysis.quality import QUALITY_METRIC_DEFS, QualityMetric, QualityReport

if TYPE_CHECKING:
    from collections.abc import Sequence

    from normcore.models import NormalizedValue


class ColumnStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    table: str
    column: str
    semantic_type: str
    rows_processed: int
    rows_changed: int
    rows_ambiguous: int
    warnings_total: int
    errors_total: int
    unique_before: int
    unique_after: int
    quality_metric_name: str | None = None
    quality_issue_count: int | None = None


def _field_identity(table: str, column: str) -> str:
    """`table.column` for a real multi-column run; bare `table` for the
    legacy pasted-values/single-column shape (`column=""`), matching the
    identifier `compute_overview`'s pre-M18 `field_name` already used."""
    return f"{table}.{column}" if column else table


def compute_column_stats_from_results(
    *,
    table: str,
    column: str,
    semantic_type: FieldSemanticType,
    originals: Sequence[str | None],
    results: Sequence[NormalizedValue],
) -> ColumnStats:
    """The in-memory path — used by `execute_run`'s already-bounded
    (M10's row cap) pasted-values/single-column-source batch, where
    `results` is already fully materialized and small enough that
    iterating it once more in Python to compute these rollups is cheap."""
    rows_changed = sum(
        1 for r in results if r.normalization_status is not NormalizationStatus.UNCHANGED
    )
    rows_ambiguous = sum(
        1 for r in results if r.normalization_status is NormalizationStatus.AMBIGUOUS
    )
    warnings_total = sum(len(r.warnings) for r in results)
    errors_total = sum(len(r.errors) for r in results)

    field_identity = _field_identity(table, column)
    impact = compute_impact(field_identity, originals, results)

    quality_metric_name: str | None = None
    quality_issue_count: int | None = None
    metric_def = next((m for m in QUALITY_METRIC_DEFS if m.semantic_type is semantic_type), None)
    if metric_def is not None:
        quality_metric_name = metric_def.name
        quality_issue_count = sum(1 for r in results if metric_def.predicate(r))

    return ColumnStats(
        table=table,
        column=column,
        semantic_type=semantic_type.value,
        rows_processed=len(results),
        rows_changed=rows_changed,
        rows_ambiguous=rows_ambiguous,
        warnings_total=warnings_total,
        errors_total=errors_total,
        unique_before=impact.unique_before,
        unique_after=impact.unique_after,
        quality_metric_name=quality_metric_name,
        quality_issue_count=quality_issue_count,
    )


def compute_overview_from_stats(
    profile_field_refs: Sequence[str],
    stats: Sequence[ColumnStats],
) -> OverviewReport:
    """Bounded replacement for `compute_overview` — same `OverviewReport`
    shape, computed from `ColumnStats` rows instead of full result
    batches. `potential_collisions` sums only POSITIVE per-column deltas
    (`unique_before - unique_after`), matching `compute_overview`'s own
    original per-run loop (`if impact.new_collisions > 0: ...`) exactly —
    a column whose normalization increased distinctness does not
    subtract from the total."""
    stat_fields = {_field_identity(s.table, s.column) for s in stats}
    analyzed_fields = set(profile_field_refs) | stat_fields

    return OverviewReport(
        fields_analyzed=len(analyzed_fields),
        fields_normalized=len(stat_fields),
        rows_processed=sum(s.rows_processed for s in stats),
        values_changed=sum(s.rows_changed for s in stats),
        warnings=sum(s.warnings_total for s in stats),
        potential_collisions=sum(max(s.unique_before - s.unique_after, 0) for s in stats),
        ambiguous_values=sum(s.rows_ambiguous for s in stats),
        errors=sum(s.errors_total for s in stats),
    )


def compute_quality_from_stats(stats: Sequence[ColumnStats]) -> QualityReport:
    """Bounded replacement for `compute_quality_report` — same
    `QualityReport` shape, summing each metric's precomputed
    `quality_issue_count`/`rows_processed` across every `ColumnStats` row
    of the matching semantic type, rather than re-evaluating the
    predicate over full result batches."""
    metrics = []
    for metric_def in QUALITY_METRIC_DEFS:
        matching = [s for s in stats if s.semantic_type == metric_def.semantic_type.value]
        metrics.append(
            QualityMetric(
                name=metric_def.name,
                semantic_type=metric_def.semantic_type.value,
                count=sum(s.quality_issue_count or 0 for s in matching),
                total_evaluated=sum(s.rows_processed for s in matching),
            )
        )
    return QualityReport(metrics=metrics)

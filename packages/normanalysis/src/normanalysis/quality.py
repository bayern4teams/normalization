"""Quality dashboard aggregation — Source.txt §93.

Tallies exactly the metric set §93 names, by semantic type, across every
executed run currently known to the caller. Each metric only draws from
runs whose semantic type is actually relevant to it (e.g. "invalid phone
values" only looks at PHONE runs) — a metric with no matching runs
correctly reports 0, never a fabricated or estimated number.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from normcore.enums import FieldSemanticType, NormalizationStatus, QualityFlag
from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from normcore.models import NormalizedValue


@dataclass(frozen=True, slots=True)
class QualityMetricDef:
    """One quality-dashboard metric definition — the predicate expressed
    twice, once as a real Python callable (used here, against a batch of
    already-materialized `NormalizedValue` results) and once as an
    equivalent DuckDB SQL fragment (`sql_predicate`, M18, used by
    `normanalysis.column_stats` to compute the SAME count by pushing the
    predicate down into a query over the sidecar's Parquet files, without
    ever materializing per-value results for a multi-million-row column).
    A golden test (`tests/golden/test_m18_quality_predicate_parity.py`)
    proves both forms agree on the same synthetic dataset — the real
    guard against the two definitions drifting apart."""

    name: str
    semantic_type: FieldSemanticType
    predicate: Callable[[NormalizedValue], bool]
    sql_predicate: str


# `sql_predicate` operates over the sidecar Parquet schema
# (`normcore.contract.NORMALIZED_VALUE_ARROW_SCHEMA`): `normalization_status`
# is a plain string column, `flags` a LIST<VARCHAR>, `structured_json` a
# JSON-encoded string column, `original_kind` a plain string column.
QUALITY_METRIC_DEFS: tuple[QualityMetricDef, ...] = (
    QualityMetricDef(
        name="Invalid phone values",
        semantic_type=FieldSemanticType.PHONE,
        predicate=lambda r: (
            r.normalization_status is NormalizationStatus.INVALID
            or QualityFlag.PHONE_INVALID in r.flags
        ),
        sql_predicate=("normalization_status = 'INVALID' OR list_contains(flags, 'PHONE_INVALID')"),
    ),
    QualityMetricDef(
        name="Ambiguous dates",
        semantic_type=FieldSemanticType.DATE,
        predicate=lambda r: (
            r.normalization_status is NormalizationStatus.AMBIGUOUS
            or QualityFlag.AMBIGUOUS_DATE in r.flags
        ),
        sql_predicate=(
            "normalization_status = 'AMBIGUOUS' OR list_contains(flags, 'AMBIGUOUS_DATE')"
        ),
    ),
    QualityMetricDef(
        name="Failed addresses",
        semantic_type=FieldSemanticType.ADDRESS,
        predicate=lambda r: (
            r.normalization_status in (NormalizationStatus.INVALID, NormalizationStatus.FAILED)
            or QualityFlag.ADDRESS_PARSE_PARTIAL in r.flags
        ),
        sql_predicate=(
            "normalization_status IN ('INVALID', 'FAILED') "
            "OR list_contains(flags, 'ADDRESS_PARSE_PARTIAL')"
        ),
    ),
    QualityMetricDef(
        name="Malformed emails",
        semantic_type=FieldSemanticType.EMAIL,
        predicate=lambda r: (
            r.normalization_status is NormalizationStatus.INVALID
            or QualityFlag.EMAIL_INVALID in r.flags
        ),
        sql_predicate=("normalization_status = 'INVALID' OR list_contains(flags, 'EMAIL_INVALID')"),
    ),
    QualityMetricDef(
        name="Unknown country codes",
        semantic_type=FieldSemanticType.COUNTRY,
        predicate=lambda r: r.normalization_status is NormalizationStatus.INVALID,
        sql_predicate="normalization_status = 'INVALID'",
    ),
    QualityMetricDef(
        name="Unrecognized units",
        semantic_type=FieldSemanticType.QUANTITY,
        predicate=lambda r: r.normalization_status is NormalizationStatus.INVALID,
        sql_predicate="normalization_status = 'INVALID'",
    ),
    QualityMetricDef(
        name="Unsupported scripts",
        semantic_type=FieldSemanticType.SCRIPT,
        predicate=lambda r: r.structured.get("script") is None and r.original_kind is None,
        sql_predicate=(
            "json_extract_string(structured_json, '$.script') IS NULL AND original_kind IS NULL"
        ),
    ),
)


class QualityMetric(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    semantic_type: str
    count: int
    total_evaluated: int


class QualityReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    metrics: list[QualityMetric]


def compute_quality_report(
    run_batches: Sequence[tuple[FieldSemanticType, Sequence[NormalizedValue]]],
) -> QualityReport:
    by_type: dict[FieldSemanticType, list[NormalizedValue]] = {}
    for semantic_type, results in run_batches:
        by_type.setdefault(semantic_type, []).extend(results)

    metrics = [
        _metric(
            metric_def.name,
            metric_def.semantic_type,
            by_type.get(metric_def.semantic_type, []),
            metric_def.predicate,
        )
        for metric_def in QUALITY_METRIC_DEFS
    ]

    return QualityReport(metrics=metrics)


def _metric(
    name: str,
    semantic_type: FieldSemanticType,
    results: Sequence[NormalizedValue],
    predicate: Callable[[NormalizedValue], bool],
) -> QualityMetric:
    count = sum(1 for r in results if predicate(r))
    return QualityMetric(
        name=name,
        semantic_type=semantic_type.value,
        count=count,
        total_evaluated=len(results),
    )

"""Quality dashboard aggregation — Source.txt §93.

Tallies exactly the metric set §93 names, by semantic type, across every
executed run currently known to the caller. Each metric only draws from
runs whose semantic type is actually relevant to it (e.g. "invalid phone
values" only looks at PHONE runs) — a metric with no matching runs
correctly reports 0, never a fabricated or estimated number.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from normcore.enums import FieldSemanticType, NormalizationStatus, QualityFlag
from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from normcore.models import NormalizedValue


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

    metrics: list[QualityMetric] = []

    metrics.append(
        _metric(
            "Invalid phone values",
            FieldSemanticType.PHONE,
            by_type.get(FieldSemanticType.PHONE, []),
            lambda r: (
                r.normalization_status is NormalizationStatus.INVALID
                or QualityFlag.PHONE_INVALID in r.flags
            ),
        )
    )
    metrics.append(
        _metric(
            "Ambiguous dates",
            FieldSemanticType.DATE,
            by_type.get(FieldSemanticType.DATE, []),
            lambda r: (
                r.normalization_status is NormalizationStatus.AMBIGUOUS
                or QualityFlag.AMBIGUOUS_DATE in r.flags
            ),
        )
    )
    metrics.append(
        _metric(
            "Failed addresses",
            FieldSemanticType.ADDRESS,
            by_type.get(FieldSemanticType.ADDRESS, []),
            lambda r: (
                r.normalization_status in (NormalizationStatus.INVALID, NormalizationStatus.FAILED)
                or QualityFlag.ADDRESS_PARSE_PARTIAL in r.flags
            ),
        )
    )
    metrics.append(
        _metric(
            "Malformed emails",
            FieldSemanticType.EMAIL,
            by_type.get(FieldSemanticType.EMAIL, []),
            lambda r: (
                r.normalization_status is NormalizationStatus.INVALID
                or QualityFlag.EMAIL_INVALID in r.flags
            ),
        )
    )
    metrics.append(
        _metric(
            "Unknown country codes",
            FieldSemanticType.COUNTRY,
            by_type.get(FieldSemanticType.COUNTRY, []),
            lambda r: r.normalization_status is NormalizationStatus.INVALID,
        )
    )
    metrics.append(
        _metric(
            "Unrecognized units",
            FieldSemanticType.QUANTITY,
            by_type.get(FieldSemanticType.QUANTITY, []),
            lambda r: r.normalization_status is NormalizationStatus.INVALID,
        )
    )
    metrics.append(
        _metric(
            "Unsupported scripts",
            FieldSemanticType.SCRIPT,
            by_type.get(FieldSemanticType.SCRIPT, []),
            lambda r: r.structured.get("script") is None and r.original_kind is None,
        )
    )

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

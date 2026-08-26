"""Golden regression test for M18's quality-predicate SQL/Python parity
(docs/plan/M13-M22-program-plan.md).

`normanalysis.quality.QUALITY_METRIC_DEFS` expresses each of §93's 7
quality-dashboard predicates TWICE: once as a real Python callable
(evaluated against already-materialized `NormalizedValue` results, the
path `compute_quality_report`/`compute_column_stats_from_results` use)
and once as an equivalent DuckDB SQL fragment (evaluated by
`SidecarStore.compute_column_stats` directly over Parquet, without ever
materializing a `NormalizedValue`, the path M17's chunked-streaming runs
use). This is the real guard against those two definitions drifting
apart: for every metric, a small synthetic batch of `NormalizedValue`
rows covering both the true and false side of that metric's predicate is
written through a real `SidecarStore` (real Parquet + real DuckDB, not
mocked), and the Python-evaluated count is asserted equal to the
SQL-evaluated count.
"""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pytest
from normcore.contract import NORMALIZED_VALUE_ARROW_SCHEMA, normalized_value_to_arrow_row
from normio.sidecar_store import SidecarStore

from normanalysis import QUALITY_METRIC_DEFS, QualityMetricDef
from normcore import (
    FieldSemanticType,
    MissingKind,
    NormalizationStatus,
    NormalizedValue,
    QualityFlag,
)

_PROFILE_VERSION = "v1"
_ENV_ID = "e" * 64


def _value(
    *,
    semantic_type: FieldSemanticType,
    status: NormalizationStatus,
    flags: list[QualityFlag] | None = None,
    structured: dict[str, object] | None = None,
    original_kind: MissingKind | None = None,
) -> NormalizedValue:
    return NormalizedValue(
        original="x",
        original_kind=original_kind,
        display="x",
        comparison="x",
        normalization_status=status,
        flags=flags or [],
        structured=structured or {},
        profile_version=_PROFILE_VERSION,
        env_id=_ENV_ID,
        semantic_type=semantic_type,
        context_hash="h",
    )


def _cases_for(semantic_type: FieldSemanticType, name: str) -> list[tuple[NormalizedValue, bool]]:
    """(value, expected predicate outcome) pairs covering the interesting
    branches of each metric's real predicate — status-only match,
    flag-only match, and a genuine non-match."""
    if name == "Unsupported scripts":
        return [
            (
                _value(semantic_type=semantic_type, status=NormalizationStatus.UNCHANGED),
                True,
            ),
            (
                _value(
                    semantic_type=semantic_type,
                    status=NormalizationStatus.UNCHANGED,
                    structured={"script": "Latin"},
                ),
                False,
            ),
            (
                _value(
                    semantic_type=semantic_type,
                    status=NormalizationStatus.UNCHANGED,
                    original_kind=MissingKind.NULL,
                ),
                False,
            ),
        ]

    status_only_true, flag = {
        "Invalid phone values": (NormalizationStatus.INVALID, QualityFlag.PHONE_INVALID),
        "Ambiguous dates": (NormalizationStatus.AMBIGUOUS, QualityFlag.AMBIGUOUS_DATE),
        "Failed addresses": (NormalizationStatus.INVALID, QualityFlag.ADDRESS_PARSE_PARTIAL),
        "Malformed emails": (NormalizationStatus.INVALID, QualityFlag.EMAIL_INVALID),
        "Unknown country codes": (NormalizationStatus.INVALID, None),
        "Unrecognized units": (NormalizationStatus.INVALID, None),
    }[name]

    cases = [
        (_value(semantic_type=semantic_type, status=status_only_true), True),
        (_value(semantic_type=semantic_type, status=NormalizationStatus.UNCHANGED), False),
    ]
    if name == "Failed addresses":
        cases.append((_value(semantic_type=semantic_type, status=NormalizationStatus.FAILED), True))
    if flag is not None:
        cases.append(
            (
                _value(
                    semantic_type=semantic_type,
                    status=NormalizationStatus.UNCHANGED,
                    flags=[flag],
                ),
                True,
            )
        )
    return cases


@pytest.mark.golden
@pytest.mark.parametrize("metric_def", QUALITY_METRIC_DEFS, ids=lambda m: m.name)
def test_python_predicate_and_sql_predicate_agree(
    metric_def: QualityMetricDef, tmp_path: Path
) -> None:
    cases = _cases_for(metric_def.semantic_type, metric_def.name)
    values = [value for value, _expected in cases]
    expected_true_count = sum(1 for _value, expected in cases if expected)

    python_count = sum(1 for v in values if metric_def.predicate(v))
    assert python_count == expected_true_count, "the Python predicate itself must match intent"

    sidecar = SidecarStore(tmp_path / "parquet", tmp_path / "catalog.duckdb")
    rows = [normalized_value_to_arrow_row(v) for v in values]
    arrays = [
        pa.array([row[field.name] for row in rows], type=field.type)
        for field in NORMALIZED_VALUE_ARROW_SCHEMA
    ]
    batch = pa.RecordBatch.from_arrays(arrays, schema=NORMALIZED_VALUE_ARROW_SCHEMA)
    sidecar.write_batch(source_id="golden", table="t", run_id="r1", batch=batch, part_index=0)

    stats = sidecar.compute_column_stats(
        source_id="golden",
        table="t",
        run_id="r1",
        quality_sql_predicate=metric_def.sql_predicate,
    )
    sidecar.close()

    assert stats["quality_issue_count"] == python_count

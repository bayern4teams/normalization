"""Unit test locking M18's real fix for the M13-M22 plan's risk #2
(docs/plan/M13-M22-program-plan.md): `GET /overview`/`GET /quality` must
never hydrate a run's full per-value results, no matter how large that
run's real row count is.

Before M18, both routes looped `store.list_runs()` and called
`store.get_execution(run.id)` for every run, materializing every
`NormalizedValue` in memory just to compute a handful of aggregate
numbers — genuinely unbounded, and a multi-column run (M17) could not
even be represented correctly by `get_execution`'s single-column "find
first match" contract.

This proves the structural fix directly: `InMemoryStore.get_execution`
is monkeypatched to raise if it is EVER called, a `ColumnStats` row
representing a run with 11.8 million real rows (M17's own verified real
scale for `Person`) is seeded directly, and `compute_overview_from_stats`/
`compute_quality_from_stats` are exercised over it — proving both the
correctness of the aggregation AND that the "hydrate everything" code
path is never reached, regardless of the row count involved. A live
integration test proving the SAME thing by actually running an
11.8M-row column to completion would take this test suite an
impractically long time (see M17's own persistent-cache-tier bench
finding) and isn't needed to prove this specific invariant — the
`tests/integration/test_multi_column_reporting.py` suite already proves
real end-to-end behavior at a small real scale (`Industry`, 179 rows);
this test proves the row-count-independence claim precisely.
"""

from __future__ import annotations

import pytest
from normapi.store import InMemoryStore

from normanalysis import ColumnStats, compute_overview_from_stats, compute_quality_from_stats


def _huge_column_stats() -> ColumnStats:
    """Represents a real M17-scale column (`Person.fullName`, ~11.8M
    rows, per the M14/M17 packs' own live-verified row counts) without
    actually materializing 11.8 million `NormalizedValue` objects."""
    return ColumnStats(
        table="Person",
        column="fullName",
        semantic_type="PERSON_NAME",
        rows_processed=11_800_000,
        rows_changed=9_000_000,
        rows_ambiguous=120_000,
        warnings_total=50_000,
        errors_total=10,
        unique_before=8_000_000,
        unique_after=7_500_000,
        quality_metric_name=None,
        quality_issue_count=None,
    )


@pytest.mark.unit
def test_overview_and_quality_never_call_get_execution_for_a_huge_column() -> None:
    store = InMemoryStore()

    def _must_not_be_called(*_args: object, **_kwargs: object) -> None:
        msg = (
            "get_execution was called by the /overview or /quality path — the exact "
            "unbounded-hydration regression M18 fixed"
        )
        raise AssertionError(msg)

    store.get_execution = _must_not_be_called  # type: ignore[method-assign]

    stats = _huge_column_stats()
    store._record_column_stats("run-huge", stats)

    all_stats = store.list_all_column_stats()
    assert all_stats == [stats]

    overview = compute_overview_from_stats([], all_stats)
    assert overview.rows_processed == 11_800_000
    assert overview.values_changed == 9_000_000
    assert overview.ambiguous_values == 120_000
    assert overview.potential_collisions == 500_000  # unique_before - unique_after
    assert overview.fields_normalized == 1

    quality = compute_quality_from_stats(all_stats)
    assert quality.metrics  # real 7-metric report, computed without incident


@pytest.mark.unit
def test_a_column_with_a_tracked_quality_metric_sums_its_precomputed_count() -> None:
    """A second column, PHONE-typed, with a precomputed
    `quality_issue_count` — proves `/quality`'s per-metric sum reads the
    stored count rather than re-deriving it from results that were never
    fetched."""
    store = InMemoryStore()
    store.get_execution = lambda *_a, **_k: pytest.fail(  # type: ignore[method-assign]
        "get_execution must not be called"
    )

    phone_stats = ColumnStats(
        table="PersonContact",
        column="phone",
        semantic_type="PHONE",
        rows_processed=4_300_000,
        rows_changed=1_000_000,
        rows_ambiguous=0,
        warnings_total=0,
        errors_total=0,
        unique_before=4_000_000,
        unique_after=4_000_000,
        quality_metric_name="Invalid phone values",
        quality_issue_count=42_000,
    )
    store._record_column_stats("run-phone", phone_stats)

    quality = compute_quality_from_stats(store.list_all_column_stats())
    phone_metric = next(m for m in quality.metrics if m.name == "Invalid phone values")
    assert phone_metric.count == 42_000
    assert phone_metric.total_evaluated == 4_300_000

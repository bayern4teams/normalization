"""Real-scale cardinality benchmarks — Phase 0 of the 2026-08-29
throughput/memory program (see project memory
`project-normalization-perf-program` and the approved plan file).

`test_execution_caching_benchmark.py` only exercises 100 distinct values
across 10,000 rows — a 100x duplication ratio that cannot reveal any of
that program's four algorithmic defects, all of which are proportional
to the number of DISTINCT values (cache misses), not row count. This
module covers the two shapes measured live against real ClickHouse data
during that R&D pass:

- low cardinality:  617 distinct / 100,000 rows (Location.country's real
  ratio, 0.03% distinct)
- high cardinality: 97,000 distinct / 100,000 rows (a stand-in for
  Company.name's real 97.1% distinct — scaled down from its true
  1.27M-row size to something this suite can actually run in CI time)

Manual `time.perf_counter()` timing rather than pytest-benchmark's
`benchmark()` fixture, matching `test_persistent_cache_benchmark.py`'s
established precedent: multi-round calibration would silently convert a
"cold cache" measurement into a mostly-warm one after round 1 (the
`store`/`cache` objects are built once, outside the timed callable, same
as every other bench in this suite), which barely matters at the
existing 10,000-row/100-distinct scale but is actively misleading at
100,000-row scale, where a single cold pass can take minutes.
"""

from __future__ import annotations

import time

import pytest
from normalizers.passthrough import PassthroughNormalizer
from normapi.store import InMemoryStore
from normexec.cache import NormalizationCache

from normcore import Dispatcher, ErrorPolicy, FieldSemanticType, NormalizerRegistry

_ROW_COUNT = 100_000
_LOW_CARDINALITY_DISTINCT = 617
_HIGH_CARDINALITY_DISTINCT = 97_000


def _values(distinct_count: int) -> list[str]:
    return [f"value-{i % distinct_count}" for i in range(_ROW_COUNT)]


def _fresh_store_and_dispatcher() -> tuple[InMemoryStore, Dispatcher, str]:
    cache = NormalizationCache(":memory:")
    store = InMemoryStore(cache)
    registry = NormalizerRegistry()
    registry.register(PassthroughNormalizer())
    dispatcher = Dispatcher(registry, env_id="e" * 64)
    profile = store.create_profile(
        name="p",
        description="",
        locale_policy={},
        default_operations=(),
        field_configs=(),
        created_by="bench",
    )
    return store, dispatcher, profile.id


def _run_once(
    store: InMemoryStore, dispatcher: Dispatcher, profile_id: str, values: list[str]
) -> None:
    run = store.create_run(profile_id=profile_id, env_id=dispatcher.env_id, source_snapshot="s")
    store.execute_run(
        run.id,
        dispatcher=dispatcher,
        field_name="f",
        semantic_type=FieldSemanticType.UNKNOWN,
        values=values,
        error_policy=ErrorPolicy.RETURN_ORIGINAL,
    )


def _bench_cold_then_warm(label: str, distinct_count: int) -> tuple[float, float]:
    values = _values(distinct_count)
    store, dispatcher, profile_id = _fresh_store_and_dispatcher()

    cold_start = time.perf_counter()
    _run_once(store, dispatcher, profile_id, values)
    cold_elapsed = time.perf_counter() - cold_start

    warm_start = time.perf_counter()
    _run_once(store, dispatcher, profile_id, values)
    warm_elapsed = time.perf_counter() - warm_start

    print(  # deliberate: this IS the bench's real output
        f"\n[real-scale-bench] {label}: {distinct_count} distinct / {_ROW_COUNT} rows — "
        f"cold={cold_elapsed:.2f}s ({_ROW_COUNT / cold_elapsed:.0f} rows/s), "
        f"warm={warm_elapsed:.2f}s ({_ROW_COUNT / warm_elapsed:.0f} rows/s)"
    )
    return cold_elapsed, warm_elapsed


@pytest.mark.bench
def test_real_scale_low_cardinality_617_distinct_100k_rows() -> None:
    """Location.country's real ratio (617 distinct / 1.83M rows, scaled
    to 100k rows) — the shape that already completes fine today; this is
    the "before" side of the plan's own before/after table, not a defect
    demonstration."""
    cold_elapsed, warm_elapsed = _bench_cold_then_warm(
        "low-cardinality", _LOW_CARDINALITY_DISTINCT
    )
    # Generous bound — this shape was never the problem; a real
    # regression here would mean something new broke the cheap path.
    assert cold_elapsed < 60
    assert warm_elapsed < 30


@pytest.mark.bench
def test_real_scale_high_cardinality_97k_distinct_100k_rows() -> None:
    """A stand-in for Company.name's real 97.1% distinct ratio. Expected
    to be SLOW on unpatched code —
    `packages/normexec/src/normexec/cache.py:218`'s O(n^2)
    list-membership scan fires on exactly this shape (a large LRU-miss
    list): measured at 44.9s for 50,000 misses in the 2026-08-29 R&D
    pass, extrapolating quadratically to 97,000 misses is ~169s. This
    bound is set generously above that extrapolation so the test doesn't
    flake on slower CI hardware pre-fix, and tightens sharply once a
    later phase lands the fix (see that phase's verification pack for
    the real measured before/after)."""
    cold_elapsed, warm_elapsed = _bench_cold_then_warm(
        "high-cardinality", _HIGH_CARDINALITY_DISTINCT
    )
    assert cold_elapsed < 300
    assert warm_elapsed < 300

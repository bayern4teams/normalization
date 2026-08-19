"""Performance baseline for the M8 distinct-value dedup + cache wiring
into `InMemoryStore.execute_run` — Source.txt §102 ("repeated values
should be normalized once per profile/version"), §103, Gate G8
requirement.

Uses a realistic duplicate-heavy shape (100 distinct values repeated
across 10,000 rows — a 100x duplication ratio, typical for a
low-cardinality field like country/currency/boolean) to demonstrate the
real throughput effect of the M8 fix, not just its correctness.
"""

from __future__ import annotations

import pytest
from normalizers.passthrough import PassthroughNormalizer
from normapi.store import InMemoryStore
from normcore.context import NormalizationContext
from normcore.models import NormalizedValue
from normexec.cache import NormalizationCache

from normcore import Dispatcher, ErrorPolicy, FieldSemanticType, NormalizerRegistry

_ROW_COUNT = 10_000
_DISTINCT_COUNT = 100


def _values() -> list[str]:
    return [f"value-{i % _DISTINCT_COUNT}" for i in range(_ROW_COUNT)]


def _fresh_store_and_dispatcher(*, with_cache: bool) -> tuple[InMemoryStore, Dispatcher, str]:
    cache = NormalizationCache(":memory:") if with_cache else None
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


@pytest.mark.bench
def test_bench_execute_run_10000_rows_100_distinct_no_cache(benchmark: object) -> None:
    values = _values()
    store, dispatcher, profile_id = _fresh_store_and_dispatcher(with_cache=False)
    benchmark(_run_once, store, dispatcher, profile_id, values)  # type: ignore[operator]


@pytest.mark.bench
def test_bench_execute_run_10000_rows_100_distinct_with_cache_cold(benchmark: object) -> None:
    """First pass — cache starts empty, so this measures the same real
    work as the no-cache case plus cache-write overhead (expected to be
    close to, not faster than, the no-cache baseline)."""
    values = _values()
    store, dispatcher, profile_id = _fresh_store_and_dispatcher(with_cache=True)
    benchmark(_run_once, store, dispatcher, profile_id, values)  # type: ignore[operator]


@pytest.mark.bench
def test_bench_execute_run_10000_rows_100_distinct_with_cache_warm(benchmark: object) -> None:
    """Cache already warmed by a prior identical run — this is the
    realistic "repeated dataset reprocessed" scenario §102 describes,
    and is where the real speedup should show up."""
    values = _values()
    store, dispatcher, profile_id = _fresh_store_and_dispatcher(with_cache=True)
    _run_once(store, dispatcher, profile_id, values)  # warm the cache once, not timed

    benchmark(_run_once, store, dispatcher, profile_id, values)  # type: ignore[operator]


@pytest.mark.bench
def test_distinct_value_dedup_reduces_real_normalize_calls(benchmark: object) -> None:
    """Not a timing benchmark — a direct, real measurement of the call-
    count reduction itself, recorded alongside the timing numbers above
    so a future reader can see *why* the cache-warm case is faster."""

    class _Counting(PassthroughNormalizer):
        def __init__(self) -> None:
            self.calls = 0

        def normalize(self, value: str | None, ctx: NormalizationContext) -> NormalizedValue:
            self.calls += 1
            return super().normalize(value, ctx)

    counting = _Counting()
    registry = NormalizerRegistry()
    registry.register(counting)
    dispatcher = Dispatcher(registry, env_id="e" * 64)
    store = InMemoryStore(NormalizationCache(":memory:"))
    profile = store.create_profile(
        name="p",
        description="",
        locale_policy={},
        default_operations=(),
        field_configs=(),
        created_by="bench",
    )
    run = store.create_run(profile_id=profile.id, env_id=dispatcher.env_id, source_snapshot="s")
    store.execute_run(
        run.id,
        dispatcher=dispatcher,
        field_name="f",
        semantic_type=FieldSemanticType.UNKNOWN,
        values=_values(),
        error_policy=ErrorPolicy.RETURN_ORIGINAL,
    )
    # 10,000 rows, 100 distinct values -> real calls bounded by distinct
    # count (plus a small, sampled number of invariant-check calls —
    # see tests/unit/test_execution_caching.py's comment on why that
    # subsystem deliberately bypasses the cache).
    assert counting.calls < _ROW_COUNT
    assert counting.calls < _DISTINCT_COUNT * 2

    def _noop() -> int:
        return counting.calls

    benchmark(_noop)  # type: ignore[operator]

"""Proves the DistinctValuePlanner's central claim mechanically (per
ADR-016 / spike 6): the Dispatcher/Normalizer is invoked once per DISTINCT
value, never once per row, and the cache further reduces calls across
separate planner invocations sharing the same env_id/profile/context.
"""

from __future__ import annotations

import polars as pl
import pytest
from normalizers.passthrough import PassthroughNormalizer

from normcore import (
    Dispatcher,
    FieldSemanticType,
    NormalizationContext,
    NormalizationProfile,
    NormalizerRegistry,
)
from normexec import DistinctValuePlanner, NormalizationCache


class _CountingNormalizer(PassthroughNormalizer):
    """Wraps PassthroughNormalizer's behavior but counts real (non-cached)
    normalize() invocations, so tests can assert on call volume directly.
    """

    def __init__(self) -> None:
        self.call_count = 0

    def normalize(self, value, ctx):  # type: ignore[no-untyped-def]
        self.call_count += 1
        return super().normalize(value, ctx)


def _profile() -> NormalizationProfile:
    return NormalizationProfile(
        id="p1",
        name="test",
        version="v1",
        created_at="2026-08-17T00:00:00Z",
        updated_at="2026-08-17T00:00:00Z",
        created_by="test",
    )


def _context() -> NormalizationContext:
    return NormalizationContext(field_name="city", semantic_type=FieldSemanticType.ADDRESS)


@pytest.mark.unit
def test_planner_calls_dispatcher_once_per_distinct_value_not_per_row() -> None:
    n_rows, n_distinct = 10_000, 25
    values = [f"city_{i % n_distinct}" for i in range(n_rows)]
    df = pl.DataFrame({"row_id": range(n_rows), "city": values})

    normalizer = _CountingNormalizer()
    registry = NormalizerRegistry()
    registry.register(normalizer)
    dispatcher = Dispatcher(registry, env_id="e" * 64)
    planner = DistinctValuePlanner(dispatcher)

    result = planner.normalize_column(df, "city", FieldSemanticType.ADDRESS, _context(), _profile())

    assert normalizer.call_count == n_distinct
    assert len(result) == n_rows
    assert result["city__display"].null_count() == 0
    # every row's derived comparison matches its own source value, not some
    # other row's — proving the join-back is keyed correctly, not just
    # "some value from the lookup table"
    assert (result["city__comparison"] == result["city"].str.to_lowercase()).all()


@pytest.mark.unit
def test_planner_with_cache_avoids_recomputation_across_calls() -> None:
    df = pl.DataFrame({"city": ["alpha", "beta", "alpha", "gamma"]})

    normalizer = _CountingNormalizer()
    registry = NormalizerRegistry()
    registry.register(normalizer)
    dispatcher = Dispatcher(registry, env_id="e" * 64)

    with NormalizationCache(":memory:") as cache:
        planner = DistinctValuePlanner(dispatcher, cache=cache)
        ctx = _context()
        profile = _profile()

        planner.normalize_column(df, "city", FieldSemanticType.ADDRESS, ctx, profile)
        assert normalizer.call_count == 3  # alpha, beta, gamma — 3 distinct values
        assert cache.stats.misses == 3
        assert cache.stats.hits == 0

        # Second call, same profile/context/env_id -> every distinct value
        # should be served from cache, zero new dispatcher calls.
        planner.normalize_column(df, "city", FieldSemanticType.ADDRESS, ctx, profile)
        assert normalizer.call_count == 3  # unchanged
        assert cache.stats.hits == 3


@pytest.mark.unit
def test_planner_null_values_never_reach_the_dispatcher() -> None:
    df = pl.DataFrame({"city": ["alpha", None, "alpha", None]})

    normalizer = _CountingNormalizer()
    registry = NormalizerRegistry()
    registry.register(normalizer)
    dispatcher = Dispatcher(registry, env_id="e" * 64)
    planner = DistinctValuePlanner(dispatcher)

    result = planner.normalize_column(df, "city", FieldSemanticType.ADDRESS, _context(), _profile())

    assert normalizer.call_count == 1  # only "alpha" is a real value
    assert result["city__display"].null_count() == 2  # nulls pass through as null


@pytest.mark.unit
def test_planner_on_computed_fires_once_per_real_call_and_never_for_cache_hits() -> None:
    """Source.txt §122 needs genuine per-computation latency samples —
    `on_computed` must fire once per real (non-cache-hit) call, and not
    at all once a later call finds everything already cached. Callers
    are expected to pass already-distinct values (as every real caller
    does — see `normalize_column`'s `.unique()` and `store.py`'s
    `dict.fromkeys()`), so this uses a genuinely distinct input list."""
    registry = NormalizerRegistry()
    registry.register(PassthroughNormalizer())
    dispatcher = Dispatcher(registry, env_id="e" * 64)
    ctx = _context()
    profile = _profile()

    observed: list[tuple[str, float]] = []

    def on_computed(value: str, result: object, duration: float) -> None:
        del result
        observed.append((value, duration))

    with NormalizationCache(":memory:") as cache:
        planner = DistinctValuePlanner(dispatcher, cache=cache)
        planner.distinct_value_results(
            ["a", "b"], FieldSemanticType.ADDRESS, ctx, profile, on_computed=on_computed
        )
        assert [v for v, _ in observed] == ["a", "b"]  # once per real computation
        assert all(d >= 0 for _, d in observed)

        observed.clear()
        planner.distinct_value_results(
            ["a", "b"], FieldSemanticType.ADDRESS, ctx, profile, on_computed=on_computed
        )
        assert observed == []  # both now cache hits — no real computation happened


@pytest.mark.unit
def test_planner_on_computed_also_fires_without_a_cache() -> None:
    registry = NormalizerRegistry()
    registry.register(PassthroughNormalizer())
    dispatcher = Dispatcher(registry, env_id="e" * 64)
    planner = DistinctValuePlanner(dispatcher)

    observed: list[str] = []
    planner.distinct_value_results(
        ["x", "y"],
        FieldSemanticType.ADDRESS,
        _context(),
        _profile(),
        on_computed=lambda value, result, duration: observed.append(value),
    )
    assert observed == ["x", "y"]


@pytest.mark.unit
def test_planner_to_arrow_produces_valid_struct_array() -> None:
    df = pl.DataFrame({"city": ["alpha", "beta", "alpha"]})

    registry = NormalizerRegistry()
    registry.register(PassthroughNormalizer())
    dispatcher = Dispatcher(registry, env_id="e" * 64)
    planner = DistinctValuePlanner(dispatcher)

    struct_array = planner.normalize_column_to_arrow(
        df, "city", FieldSemanticType.ADDRESS, _context(), _profile()
    )

    assert len(struct_array) == 3
    row0 = struct_array[0].as_py()
    assert row0["display"] == "alpha"
    assert row0["comparison"] == "alpha"

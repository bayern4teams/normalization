"""Unit tests for `normexec.parallel` — Phase 3 of the throughput/memory
program. `DistinctValueWorkerPool` tests spawn REAL OS processes (the
`spawn` start method, matching what the pool always uses), so they are
marked `slow_fork` (excluded from mutmut's per-mutant reruns, same reason
every other real-socket/real-process test in this suite is) and kept to a
minimal registry (CountryNormalizer only — no dictionary loading) so pool
startup stays fast enough for a normal test run.
"""

from __future__ import annotations

import icu  # noqa: F401 - DLL load-order guard, see normcli/run_cmd.py
import pytest
from normalizers.country import CountryNormalizer
from normalizers.passthrough import PassthroughNormalizer
from normcore.context import NormalizationContext
from normcore.rules import NormalizationProfile
from normexec.parallel import (
    POOL_EXCLUDED_SEMANTIC_TYPES,
    DistinctValueWorkerPool,
    parallel_workers_from_env,
)
from normexec.planner import DistinctValuePlanner

from normcore import Dispatcher, FieldSemanticType, NormalizerRegistry


def _build_test_dispatcher() -> Dispatcher:
    """Module-level (picklable) dispatcher factory — a minimal registry,
    not the real 20-normalizer one, so spawned test workers start in a
    fraction of the ~6s the real registry measured on this machine."""
    registry = NormalizerRegistry()
    registry.register(PassthroughNormalizer())
    registry.register(CountryNormalizer())
    return Dispatcher(registry, env_id="test-env")


def _ctx(semantic_type: FieldSemanticType) -> NormalizationContext:
    return NormalizationContext(field_name="field", semantic_type=semantic_type)


def _profile() -> NormalizationProfile:
    return NormalizationProfile(
        id="p1",
        name="test",
        version="v1",
        created_at="2026-08-29T00:00:00Z",
        updated_at="2026-08-29T00:00:00Z",
        created_by="test",
    )


@pytest.mark.unit
def test_pool_excludes_address_and_script_permanently() -> None:
    assert FieldSemanticType.ADDRESS in POOL_EXCLUDED_SEMANTIC_TYPES
    assert FieldSemanticType.SCRIPT in POOL_EXCLUDED_SEMANTIC_TYPES


@pytest.mark.unit
def test_parallel_workers_from_env_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NORM_PARALLEL_WORKERS", raising=False)
    assert parallel_workers_from_env() == 0


@pytest.mark.unit
def test_parallel_workers_from_env_explicit_zero_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NORM_PARALLEL_WORKERS", "0")
    assert parallel_workers_from_env() == 0


@pytest.mark.unit
def test_parallel_workers_from_env_positive_value_is_explicit_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NORM_PARALLEL_WORKERS", "5")
    assert parallel_workers_from_env() == 5


@pytest.mark.unit
def test_parallel_workers_from_env_negative_value_derives_from_cpu_quota(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NORM_PARALLEL_WORKERS", "-1")
    assert parallel_workers_from_env(cpu_quota=4) == 3


@pytest.mark.unit
def test_parallel_workers_from_env_auto_never_goes_below_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NORM_PARALLEL_WORKERS", "-1")
    assert parallel_workers_from_env(cpu_quota=1) == 1


@pytest.mark.unit
def test_parallel_workers_from_env_garbage_value_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NORM_PARALLEL_WORKERS", "not-a-number")
    assert parallel_workers_from_env() == 0


@pytest.mark.unit
@pytest.mark.slow_fork
def test_pool_normalize_batch_matches_serial_dispatcher_byte_identical() -> None:
    dispatcher = _build_test_dispatcher()
    ctx = _ctx(FieldSemanticType.COUNTRY)
    profile = _profile()
    values = ["US", "de", "  France  ", "US", "Not A Real Country"]

    serial = [dispatcher.normalize(v, FieldSemanticType.COUNTRY, ctx, profile) for v in values]

    pool = DistinctValueWorkerPool(_build_test_dispatcher, workers=2)
    try:
        pooled = pool.normalize_batch(values, FieldSemanticType.COUNTRY, ctx, profile)
    finally:
        pool.shutdown()

    assert len(pooled) == len(serial)
    for expected, actual in zip(serial, pooled, strict=True):
        assert actual.display == expected.display
        assert actual.normalization_status == expected.normalization_status
        assert actual.context_hash == expected.context_hash


@pytest.mark.unit
@pytest.mark.slow_fork
def test_pool_normalize_batch_preserves_input_order() -> None:
    ctx = _ctx(FieldSemanticType.COUNTRY)
    profile = _profile()
    # Distinct-per-position values so a shuffled result would be detectable.
    values = [f"COUNTRY_{i}" for i in range(20)]

    pool = DistinctValueWorkerPool(_build_test_dispatcher, workers=4)
    try:
        pooled = pool.normalize_batch(values, FieldSemanticType.COUNTRY, ctx, profile)
    finally:
        pool.shutdown()

    expected_originals = values
    actual_originals = [r.original for r in pooled]
    assert actual_originals == expected_originals


@pytest.mark.unit
@pytest.mark.slow_fork
def test_pool_workers_property_reports_configured_count() -> None:
    pool = DistinctValueWorkerPool(_build_test_dispatcher, workers=3)
    try:
        assert pool.workers == 3
    finally:
        pool.shutdown()


@pytest.mark.unit
def test_pool_rejects_zero_or_negative_workers() -> None:
    with pytest.raises(ValueError, match="workers must be >= 1"):
        DistinctValueWorkerPool(_build_test_dispatcher, workers=0)


@pytest.mark.unit
@pytest.mark.slow_fork
def test_planner_with_pool_produces_identical_results_to_planner_without_pool() -> None:
    """End-to-end: DistinctValuePlanner wired to a real pool must return
    byte-identical NormalizedValues to the same planner with no pool at
    all — the pool is a performance path, never an output-changing one.
    """
    dispatcher = _build_test_dispatcher()
    ctx = _ctx(FieldSemanticType.COUNTRY)
    profile = _profile()
    values: list[str | None] = ["US", "DE", "US", None, "FR", "DE", "??", None]

    serial_planner = DistinctValuePlanner(dispatcher, cache=None, pool=None)
    serial_results = serial_planner.normalize_values(
        values, FieldSemanticType.COUNTRY, ctx, profile
    )

    pool = DistinctValueWorkerPool(_build_test_dispatcher, workers=2)
    try:
        pooled_planner = DistinctValuePlanner(dispatcher, cache=None, pool=pool)
        pooled_results = pooled_planner.normalize_values(
            values, FieldSemanticType.COUNTRY, ctx, profile
        )
    finally:
        pool.shutdown()

    assert len(pooled_results) == len(serial_results)
    for expected, actual in zip(serial_results, pooled_results, strict=True):
        assert actual.display == expected.display
        assert actual.normalization_status == expected.normalization_status
        assert actual.original == expected.original


@pytest.mark.unit
@pytest.mark.slow_fork
def test_planner_never_pools_address_even_with_a_pool_configured() -> None:
    """ADDRESS is permanently excluded — this must hold even when a pool
    IS configured and would otherwise be eligible, guarding against the
    exclusion list ever silently shrinking."""
    dispatcher = _build_test_dispatcher()
    pool = DistinctValueWorkerPool(_build_test_dispatcher, workers=2)
    try:
        planner = DistinctValuePlanner(dispatcher, cache=None, pool=pool)
        computed = planner._compute_values(
            ["123 Main St"],
            FieldSemanticType.ADDRESS,
            _ctx(FieldSemanticType.ADDRESS),
            _profile(),
            on_computed=None,
        )
        assert len(computed) == 1
        # No pool decision was ever recorded for ADDRESS — proves the
        # exclusion short-circuited before any calibration/pool logic ran.
        assert FieldSemanticType.ADDRESS not in planner._pool_decisions
    finally:
        pool.shutdown()


@pytest.mark.unit
def test_normalize_batch_returns_empty_list_for_empty_input() -> None:
    pool = DistinctValueWorkerPool(_build_test_dispatcher, workers=1)
    try:
        result = pool.normalize_batch(
            [], FieldSemanticType.COUNTRY, _ctx(FieldSemanticType.COUNTRY), _profile()
        )
        assert result == []
    finally:
        pool.shutdown()

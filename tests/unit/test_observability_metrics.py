"""Real observability metrics through the live execution path — Source.txt
§122 ("Track: values processed, values changed, values unchanged, parser
failures, validation failures, cache hit ratio, average/p95/p99 latency,
library calls, rows/sec").

`NormalizationRunMetrics` carried none of these beyond the basic counters
until this M8 fix — `RunRecorder`'s new `record_computation()` hook (fed by
`DistinctValuePlanner`'s `on_computed` callback, see test_planner.py) and
the `status`-aware `record_value()` populate them for real, through
`InMemoryStore.execute_run()`, the same live path every `/runs` call goes
through — not just in isolated `RunRecorder` unit tests
(test_run_recorder.py already covers the counting logic itself).
"""

from __future__ import annotations

import pytest
from normalizers.email import EmailNormalizer
from normapi.store import InMemoryStore
from normexec.cache import NormalizationCache

from normcore import Dispatcher, ErrorPolicy, FieldSemanticType, NormalizerRegistry


def _store_and_dispatcher() -> tuple[InMemoryStore, Dispatcher]:
    store = InMemoryStore(NormalizationCache(":memory:"))
    registry = NormalizerRegistry()
    registry.register(EmailNormalizer())
    dispatcher = Dispatcher(registry, env_id="e" * 64)
    return store, dispatcher


@pytest.mark.unit
def test_real_run_reports_validation_failures_and_library_calls() -> None:
    store, dispatcher = _store_and_dispatcher()
    profile = store.create_profile(
        name="p",
        description="",
        locale_policy={},
        default_operations=(),
        field_configs=(),
        created_by="u",
    )
    run = store.create_run(profile_id=profile.id, env_id=dispatcher.env_id, source_snapshot="s")

    finished = store.execute_run(
        run.id,
        dispatcher=dispatcher,
        field_name="email",
        semantic_type=FieldSemanticType.EMAIL,
        values=["valid@example.com", "not-an-email", "another-bad-one"],
        error_policy=ErrorPolicy.RETURN_ORIGINAL,
    )

    assert finished.metrics.records_processed == 3
    assert finished.metrics.validation_failures == 2  # the two malformed addresses
    assert finished.metrics.library_calls > 0  # email-validator really ran
    assert finished.metrics.avg_latency_ms > 0  # real wall-clock samples, not a stub 0.0
    assert finished.metrics.duration_seconds > 0
    assert finished.metrics.rows_per_second > 0


@pytest.mark.unit
def test_repeated_values_do_not_inflate_latency_or_library_call_samples() -> None:
    """A duplicated raw value is deduped by the planner — its
    library-call/latency contribution should be counted once, not once
    per row, exactly as cache_hits/cache_misses already are."""
    store, dispatcher = _store_and_dispatcher()
    profile = store.create_profile(
        name="p",
        description="",
        locale_policy={},
        default_operations=(),
        field_configs=(),
        created_by="u",
    )
    run = store.create_run(profile_id=profile.id, env_id=dispatcher.env_id, source_snapshot="s")

    finished = store.execute_run(
        run.id,
        dispatcher=dispatcher,
        field_name="email",
        semantic_type=FieldSemanticType.EMAIL,
        values=["a@example.com"] * 10,  # 10 rows, 1 distinct value
        error_policy=ErrorPolicy.RETURN_ORIGINAL,
    )

    assert finished.metrics.records_processed == 10  # every row still counted
    # Exactly one real computation happened -> library_calls reflects ONE
    # normalize() call's trace, not ten. EmailNormalizer's real trace makes
    # exactly one email-validator call per computation (see email.py).
    assert finished.metrics.library_calls == 1


@pytest.mark.unit
def test_cache_hit_ratio_reflects_real_cross_run_reuse() -> None:
    store, dispatcher = _store_and_dispatcher()
    profile = store.create_profile(
        name="p",
        description="",
        locale_policy={},
        default_operations=(),
        field_configs=(),
        created_by="u",
    )

    run_a = store.create_run(profile_id=profile.id, env_id=dispatcher.env_id, source_snapshot="s1")
    store.execute_run(
        run_a.id,
        dispatcher=dispatcher,
        field_name="email",
        semantic_type=FieldSemanticType.EMAIL,
        values=["a@example.com"],
        error_policy=ErrorPolicy.RETURN_ORIGINAL,
    )

    run_b = store.create_run(profile_id=profile.id, env_id=dispatcher.env_id, source_snapshot="s2")
    finished_b = store.execute_run(
        run_b.id,
        dispatcher=dispatcher,
        field_name="email",
        semantic_type=FieldSemanticType.EMAIL,
        values=["a@example.com"],  # already cached from run_a
        error_policy=ErrorPolicy.RETURN_ORIGINAL,
    )

    assert finished_b.metrics.cache_hit_ratio == pytest.approx(1.0)
    assert finished_b.metrics.library_calls == 0  # served from cache, no real library call

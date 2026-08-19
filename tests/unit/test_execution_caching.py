"""Real caching/dedup through the live execution path — Source.txt §102
("Repeated values should be normalized once per profile/version"), §103
(the normalization cache itself).

`normexec`'s `DistinctValuePlanner`/`NormalizationCache` were built and
unit-tested in M1 but never actually connected to `InMemoryStore.
execute_run()` — the real, live path every `/runs` and eventually
`/preview` call goes through — until this M8 fix. These tests prove the
wiring itself, not just that the underlying `normexec` primitives work
in isolation (already covered by `test_planner.py`/`test_cache.py`).
"""

from __future__ import annotations

import pytest
from normalizers.passthrough import PassthroughNormalizer
from normapi.store import InMemoryStore
from normcore.context import NormalizationContext
from normcore.models import NormalizedValue
from normexec.cache import NormalizationCache

from normcore import Dispatcher, ErrorPolicy, FieldSemanticType, NormalizerRegistry


class _CountingNormalizer(PassthroughNormalizer):
    """Wraps PassthroughNormalizer but counts real `.normalize()` calls,
    so tests can assert the dispatcher was genuinely invoked fewer times
    than there are input rows — proof of real dedup, not just that the
    final results happen to look right."""

    def __init__(self) -> None:
        self.call_count = 0

    def normalize(self, value: str | None, ctx: NormalizationContext) -> NormalizedValue:
        self.call_count += 1
        return super().normalize(value, ctx)


def _store_and_dispatcher(
    cache: NormalizationCache | None,
) -> tuple[InMemoryStore, Dispatcher, _CountingNormalizer]:
    store = InMemoryStore(cache)
    registry = NormalizerRegistry()
    counting = _CountingNormalizer()
    registry.register(counting)
    dispatcher = Dispatcher(registry, env_id="e" * 64)
    return store, dispatcher, counting


@pytest.mark.unit
class TestDistinctValueDedupWithinOneRun:
    def test_duplicate_values_only_normalize_once(self) -> None:
        store, dispatcher, counting = _store_and_dispatcher(cache=None)
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
            field_name="f",
            semantic_type=FieldSemanticType.UNKNOWN,
            values=["a", "b", "a", "a", "b", "c"],
            error_policy=ErrorPolicy.RETURN_ORIGINAL,
        )
        assert finished.metrics.records_processed == 6  # every row still counted
        # Only 3 distinct values -> at most 3 real calls from the dedup
        # path itself. `execute_run` also runs §71's runtime-sampled
        # invariant check (M6), which deliberately calls the dispatcher
        # directly (bypassing the cache, on purpose — it exists to catch
        # a normalizer that ISN'T actually deterministic/idempotent, which
        # a cache-hit would trivially and wrongly "pass"), so the total
        # can exceed 3 by a small, sampled amount — the real invariant
        # this test protects is "fewer real calls than input rows", not
        # an exact count coupled to that separate subsystem.
        assert counting.call_count < 6
        assert counting.call_count <= 3 + 2  # 3 distinct + <=2 sampled invariant-check calls

        execution = store.get_execution(run.id)
        assert execution is not None
        assert len(execution.results) == 6  # every row still gets a real result, in order

    def test_null_values_also_deduped_to_one_real_call(self) -> None:
        store, dispatcher, counting = _store_and_dispatcher(cache=None)
        profile = store.create_profile(
            name="p",
            description="",
            locale_policy={},
            default_operations=(),
            field_configs=(),
            created_by="u",
        )
        run = store.create_run(profile_id=profile.id, env_id=dispatcher.env_id, source_snapshot="s")

        store.execute_run(
            run.id,
            dispatcher=dispatcher,
            field_name="f",
            semantic_type=FieldSemanticType.UNKNOWN,
            values=[None, "a", None, None],
            error_policy=ErrorPolicy.RETURN_ORIGINAL,
        )
        assert counting.call_count == 2  # one real call for "a", one for None

    def test_result_order_matches_input_order_even_with_duplicates(self) -> None:
        store, dispatcher, _ = _store_and_dispatcher(cache=None)
        profile = store.create_profile(
            name="p",
            description="",
            locale_policy={},
            default_operations=(),
            field_configs=(),
            created_by="u",
        )
        run = store.create_run(profile_id=profile.id, env_id=dispatcher.env_id, source_snapshot="s")

        store.execute_run(
            run.id,
            dispatcher=dispatcher,
            field_name="f",
            semantic_type=FieldSemanticType.UNKNOWN,
            values=["z", "a", "z", "m"],
            error_policy=ErrorPolicy.RETURN_ORIGINAL,
        )
        execution = store.get_execution(run.id)
        assert execution is not None
        assert [r.original for r in execution.results] == ["z", "a", "z", "m"]


@pytest.mark.unit
class TestCacheReuseAcrossRuns:
    def test_second_run_with_overlapping_values_hits_the_cache(self) -> None:
        cache = NormalizationCache(":memory:")
        store, dispatcher, counting = _store_and_dispatcher(cache=cache)
        profile = store.create_profile(
            name="p",
            description="",
            locale_policy={},
            default_operations=(),
            field_configs=(),
            created_by="u",
        )

        run_a = store.create_run(
            profile_id=profile.id, env_id=dispatcher.env_id, source_snapshot="s1"
        )
        store.execute_run(
            run_a.id,
            dispatcher=dispatcher,
            field_name="f",
            semantic_type=FieldSemanticType.UNKNOWN,
            values=["a", "b"],
            error_policy=ErrorPolicy.RETURN_ORIGINAL,
        )
        calls_after_run_a = counting.call_count

        run_b = store.create_run(
            profile_id=profile.id, env_id=dispatcher.env_id, source_snapshot="s2"
        )
        finished_b = store.execute_run(
            run_b.id,
            dispatcher=dispatcher,
            field_name="f",
            semantic_type=FieldSemanticType.UNKNOWN,
            values=["a", "a", "c"],
            error_policy=ErrorPolicy.RETURN_ORIGINAL,
        )
        # "a" was already cached from run_a (same field_name/semantic_type
        # -> same context_hash, same profile_version, same env_id); run_b
        # has 3 rows but only 2 distinct values, one of which ("a") is
        # already cached, so run_b's dedup path itself makes at most 1
        # real call ("c") — the invariant sampler may add a few more
        # direct (cache-bypassing) calls on top, same caveat as above.
        assert finished_b.metrics.cache_hits >= 1
        assert cache.stats.hits >= 1
        assert counting.call_count - calls_after_run_a <= 1 + 2

    def test_a_run_without_a_cache_still_works_and_records_zero_cache_activity(self) -> None:
        store, dispatcher, _ = _store_and_dispatcher(cache=None)
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
            field_name="f",
            semantic_type=FieldSemanticType.UNKNOWN,
            values=["a", "a"],
            error_policy=ErrorPolicy.RETURN_ORIGINAL,
        )
        assert finished.metrics.cache_hits == 0
        assert finished.metrics.cache_misses == 0

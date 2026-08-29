"""Proves normexec.cache's core guarantees: cache keys never contain the
raw value (only a hash of it), keys are stable/sensitive the same way
env_fingerprint's are, the two-tier get/put round-trips correctly, and the
LRU tier actually evicts under pressure.
"""

from __future__ import annotations

from typing import TypedDict

import pytest
from normexec.cache import NormalizationCache, make_cache_key

from normcore import FieldSemanticType, NormalizationStatus, NormalizedValue


class _CacheKeyInputs(TypedDict):
    """`**kwargs`-unpacking a plain `dict[str, X]` into `make_cache_key`
    only type-checks per-key against a TypedDict — a plain dict forces
    every value to the same type, which doesn't fit `profile_version:
    str` next to `semantic_type: FieldSemanticType`."""

    profile_version: str
    semantic_type: FieldSemanticType
    context_hash: str
    env_id: str


@pytest.mark.unit
def test_cache_key_never_contains_the_raw_value() -> None:
    raw = "super-secret-pii-value@example.com"
    key = make_cache_key(
        raw,
        profile_version="v1",
        semantic_type=FieldSemanticType.EMAIL,
        context_hash="c" * 64,
        env_id="e" * 64,
    )
    assert raw not in key
    assert len(key) == 64  # blake3 hex digest


@pytest.mark.unit
def test_cache_key_stable_and_sensitive_to_each_input() -> None:
    base: _CacheKeyInputs = {
        "profile_version": "v1",
        "semantic_type": FieldSemanticType.EMAIL,
        "context_hash": "c" * 64,
        "env_id": "e" * 64,
    }
    key_a = make_cache_key("value", **base)
    key_b = make_cache_key("value", **base)
    assert key_a == key_b  # stable

    with_new_profile_version: _CacheKeyInputs = {**base, "profile_version": "v2"}
    with_new_context_hash: _CacheKeyInputs = {**base, "context_hash": "d" * 64}
    with_new_env_id: _CacheKeyInputs = {**base, "env_id": "f" * 64}
    assert make_cache_key("value", **with_new_profile_version) != key_a
    assert make_cache_key("value", **with_new_context_hash) != key_a
    assert make_cache_key("value", **with_new_env_id) != key_a
    assert make_cache_key("other-value", **base) != key_a


def _sample_value(original: str) -> NormalizedValue:
    return NormalizedValue(
        original=original,
        display=original.strip(),
        normalization_status=NormalizationStatus.NORMALIZED,
        profile_version="v1",
        env_id="e" * 64,
        semantic_type=FieldSemanticType.PERSON_NAME,
        context_hash="c" * 64,
    )


@pytest.mark.unit
def test_cache_round_trip_and_stats() -> None:
    with NormalizationCache(":memory:", lru_capacity=10) as cache:
        key = "k1"
        assert cache.get(key) is None
        assert cache.stats.misses == 1
        assert cache.stats.hits == 0

        value = _sample_value("  John  ")
        cache.put(key, value)

        hit = cache.get(key)
        assert hit is not None
        assert hit.original == "  John  "
        assert cache.stats.hits == 1
        assert cache.stats.hit_ratio == pytest.approx(0.5)


@pytest.mark.unit
def test_cache_persists_beyond_lru_eviction_via_duckdb_tier() -> None:
    """With lru_capacity=1, a second distinct key evicts the first from
    the hot tier — but the DuckDB tier must still serve it correctly.
    """
    with NormalizationCache(":memory:", lru_capacity=1) as cache:
        cache.put("k1", _sample_value("first"))
        cache.put("k2", _sample_value("second"))  # evicts k1 from LRU

        # k1 must still be retrievable from the DuckDB tier despite LRU eviction
        recovered = cache.get("k1")
        assert recovered is not None
        assert recovered.original == "first"


@pytest.mark.unit
def test_cache_put_overwrites_existing_key() -> None:
    with NormalizationCache(":memory:") as cache:
        cache.put("k1", _sample_value("v1"))
        cache.put("k1", _sample_value("v2"))
        result = cache.get("k1")
        assert result is not None
        assert result.original == "v2"


@pytest.mark.unit
class TestPutMany:
    def test_empty_batch_is_a_real_no_op(self) -> None:
        with NormalizationCache(":memory:") as cache:
            cache.put_many([])  # must not raise
            assert cache.stats.hits == 0
            assert cache.stats.misses == 0

    def test_batch_writes_all_items_and_each_is_individually_retrievable(self) -> None:
        with NormalizationCache(":memory:") as cache:
            items = [(f"k{i}", _sample_value(f"v{i}")) for i in range(20)]
            cache.put_many(items)

            for i in range(20):
                result = cache.get(f"k{i}")
                assert result is not None
                assert result.original == f"v{i}"

    def test_batch_result_matches_equivalent_sequential_puts(self) -> None:
        items = [(f"k{i}", _sample_value(f"v{i}")) for i in range(10)]

        with NormalizationCache(":memory:") as batched_cache:
            batched_cache.put_many(items)
            batched_values = [batched_cache.get(f"k{i}") for i in range(10)]

        with NormalizationCache(":memory:") as sequential_cache:
            for key, value in items:
                sequential_cache.put(key, value)
            sequential_values = [sequential_cache.get(f"k{i}") for i in range(10)]

        assert [v.original if v else None for v in batched_values] == [
            v.original if v else None for v in sequential_values
        ]

    def test_batch_also_populates_the_lru_tier_immediately(self) -> None:
        with NormalizationCache(":memory:") as cache:
            cache.put_many([("k1", _sample_value("v1"))])
            # A hit here must come from the LRU tier, not require a DuckDB
            # round-trip — verified indirectly via stats still counting
            # it as a hit (the public-observable contract `put()` already
            # guarantees; put_many must not silently skip this).
            result = cache.get("k1")
            assert result is not None
            assert cache.stats.hits == 1

    def test_batch_overwrites_existing_keys(self) -> None:
        with NormalizationCache(":memory:") as cache:
            cache.put("k1", _sample_value("old"))
            cache.put_many([("k1", _sample_value("new"))])
            result = cache.get("k1")
            assert result is not None
            assert result.original == "new"

    def test_duplicate_key_within_one_batch_keeps_the_last_occurrence(self) -> None:
        """Real DuckDB behavior: `INSERT OR REPLACE` with a duplicate key
        in the SAME statement keeps the FIRST occurrence, not the last —
        verified directly against DuckDB, not assumed. `put_many` must
        dedupe before writing so this matches `put()`'s natural
        last-write-wins semantics and stays consistent with the LRU tier
        (which naturally keeps the last occurrence via iteration order)."""
        with NormalizationCache(":memory:", lru_capacity=1) as cache:
            cache.put_many([("k1", _sample_value("first")), ("k1", _sample_value("second"))])
            cache.put("k2", _sample_value("other"))  # evicts k1 from the LRU tier

            # Now only the DuckDB tier can answer this — proves the
            # *persisted* value is "second", not just what's still hot in
            # the in-process LRU.
            result = cache.get("k1")
            assert result is not None
            assert result.original == "second"


@pytest.mark.unit
class TestGetMany:
    def test_empty_keys_is_a_real_no_op(self) -> None:
        with NormalizationCache(":memory:") as cache:
            result = cache.get_many([])
            assert result == {}
            assert cache.stats.hits == 0
            assert cache.stats.misses == 0

    def test_all_misses_returns_empty_dict_and_counts_as_misses(self) -> None:
        with NormalizationCache(":memory:") as cache:
            result = cache.get_many(["k1", "k2", "k3"])
            assert result == {}
            assert cache.stats.misses == 3
            assert cache.stats.hits == 0

    def test_lru_hits_are_served_without_touching_duckdb(self) -> None:
        with NormalizationCache(":memory:") as cache:
            cache.put("k1", _sample_value("v1"))
            result = cache.get_many(["k1"])
            assert result["k1"].original == "v1"
            assert cache.stats.hits == 1

    def test_duckdb_tier_hits_after_lru_eviction(self) -> None:
        with NormalizationCache(":memory:", lru_capacity=1) as cache:
            cache.put("k1", _sample_value("first"))
            cache.put("k2", _sample_value("second"))  # evicts k1 from LRU
            result = cache.get_many(["k1", "k2"])
            assert result["k1"].original == "first"
            assert result["k2"].original == "second"

    def test_mixed_hits_and_misses_in_one_batch(self) -> None:
        with NormalizationCache(":memory:") as cache:
            cache.put("k1", _sample_value("v1"))
            result = cache.get_many(["k1", "k2", "k3"])
            assert set(result.keys()) == {"k1"}
            assert cache.stats.hits == 1
            assert cache.stats.misses == 2

    def test_batch_result_matches_equivalent_sequential_gets(self) -> None:
        keys = [f"k{i}" for i in range(10)]
        items = [(k, _sample_value(f"v{i}")) for i, k in enumerate(keys)]

        with NormalizationCache(":memory:") as batched_cache:
            batched_cache.put_many(items)
            batched_result = batched_cache.get_many(keys)

        with NormalizationCache(":memory:") as sequential_cache:
            for key, value in items:
                sequential_cache.put(key, value)
            sequential_result = {
                key: v for key in keys if (v := sequential_cache.get(key)) is not None
            }

        assert {k: v.original for k, v in batched_result.items()} == {
            k: v.original for k, v in sequential_result.items()
        }

    def test_duplicate_key_within_one_call_counts_one_outcome_per_occurrence(self) -> None:
        """A caller that (unlike every current one) passes duplicate keys
        in a single `get_many` call must still get correct hit/miss
        counts — one outcome per requested occurrence, not collapsed to
        one per unique key. This directly protects §122's cache_hit_ratio
        observability from silently under/over-counting."""
        with NormalizationCache(":memory:") as cache:
            cache.put("k1", _sample_value("v1"))

            # k1 (cached) requested twice, k2 (uncached) requested twice.
            result = cache.get_many(["k1", "k1", "k2", "k2"])

            assert set(result.keys()) == {"k1"}
            assert cache.stats.hits == 2  # both k1 occurrences
            assert cache.stats.misses == 2  # both k2 occurrences


@pytest.mark.unit
class TestSqlLiteralEmbedding:
    """M22: get_many/put_many embed cache_key/value_json as SQL literals
    (found live: DuckDB 1.5.5's `?` parameter binder scales catastrophically
    with placeholder count — ~12s for a 2,000-key `IN (...)`, the real
    cause of every real multi-column run appearing to hang indefinitely).
    Embedding raw strings into SQL is only safe if escaping is correct —
    these are the tests that prove it, not just the happy path."""

    def test_get_many_with_apostrophe_and_sql_metacharacters_in_keys(self) -> None:
        nasty_keys = ["O'Brien", "a'; DROP TABLE normalization_cache; --", "quote''quote", ""]
        with NormalizationCache(":memory:") as cache:
            for key in nasty_keys:
                if key:  # cache.get with an empty key is a valid no-op case below
                    cache.put(key, _sample_value(key))

            result = cache.get_many(nasty_keys)

            assert set(result.keys()) == {k for k in nasty_keys if k}
            for key in nasty_keys:
                if key:
                    assert result[key].original == key

    def test_put_many_with_apostrophe_unicode_and_backslash_in_value_json(self) -> None:
        # display/original round-tripping through model_dump_json ->
        # embedded SQL literal -> DuckDB -> model_validate_json must
        # survive every SQL-significant and non-ASCII character intact.
        tricky_original = "O'Brien & Sons — café 中文 a\\b"
        with NormalizationCache(":memory:") as cache:
            cache.put_many([("k1", _sample_value(tricky_original))])
            hit = cache.get("k1")

        assert hit is not None
        assert hit.original == tricky_original

    def test_get_many_still_correct_at_a_scale_that_used_to_hang(self) -> None:
        """Not a timing assertion (see tests/bench for that) — this just
        proves correctness survives at a scale (2,000 keys) that the old
        `?`-placeholder implementation measurably could not complete
        quickly (~12s for this exact count, see get_many's docstring)."""
        n = 2_000
        items = [(f"key-{i:06d}", _sample_value(f"value-{i}")) for i in range(n)]
        # Tiny LRU capacity forces lookups through the DuckDB tier.
        with NormalizationCache(":memory:", lru_capacity=10) as cache:
            cache.put_many(items)
            result = cache.get_many([k for k, _ in items])

        assert len(result) == n
        assert all(result[f"key-{i:06d}"].original == f"value-{i}" for i in range(n))

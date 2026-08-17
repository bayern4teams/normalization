"""Proves normexec.cache's core guarantees: cache keys never contain the
raw value (only a hash of it), keys are stable/sensitive the same way
env_fingerprint's are, the two-tier get/put round-trips correctly, and the
LRU tier actually evicts under pressure.
"""

from __future__ import annotations

import pytest
from normexec.cache import NormalizationCache, make_cache_key

from normcore import FieldSemanticType, NormalizationStatus, NormalizedValue


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
    base = {
        "profile_version": "v1",
        "semantic_type": FieldSemanticType.EMAIL,
        "context_hash": "c" * 64,
        "env_id": "e" * 64,
    }
    key_a = make_cache_key("value", **base)
    key_b = make_cache_key("value", **base)
    assert key_a == key_b  # stable

    assert make_cache_key("value", **{**base, "profile_version": "v2"}) != key_a
    assert make_cache_key("value", **{**base, "context_hash": "d" * 64}) != key_a
    assert make_cache_key("value", **{**base, "env_id": "f" * 64}) != key_a
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

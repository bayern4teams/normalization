"""Two-tier normalization cache — Source.txt §103; design decision in
docs/adr/ADR-016-performance-architecture.md.

Tier 1: in-process bounded LRU, for hot repeated lookups within a single
run/process.
Tier 2: DuckDB-backed persistent cache, for cross-run reuse.

Cache keys are blake3 hashes over (raw_value_hash, profile_version,
semantic_type, context_hash, env_id) — the raw value itself never appears
in a key, satisfying §103's "never leak sensitive raw values through cache
keys" requirement. env_id's participation means any upstream library or
dictionary change automatically invalidates stale entries (ADR-014).
"""

from __future__ import annotations

import json
from collections import OrderedDict
from pathlib import Path
from typing import TYPE_CHECKING

import blake3
import duckdb
from normcore.models import NormalizedValue

if TYPE_CHECKING:
    from normcore.enums import FieldSemanticType


def make_cache_key(
    raw_value: str,
    *,
    profile_version: str,
    semantic_type: FieldSemanticType,
    context_hash: str,
    env_id: str,
) -> str:
    raw_hash = blake3.blake3(raw_value.encode("utf-8")).hexdigest()
    payload = json.dumps(
        {
            "raw_value_hash": raw_hash,
            "profile_version": profile_version,
            "semantic_type": semantic_type.value,
            "context_hash": context_hash,
            "env_id": env_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return blake3.blake3(payload.encode("utf-8")).hexdigest()


class _LruCache:
    """Minimal bounded LRU — stdlib `functools.lru_cache` doesn't expose
    per-instance hit/miss counters or support non-hashable-key eviction
    policy tuning the way this needs, so this is a small dedicated
    implementation rather than a wrapper around it.
    """

    def __init__(self, capacity: int) -> None:
        self._capacity = capacity
        self._data: OrderedDict[str, NormalizedValue] = OrderedDict()

    def get(self, key: str) -> NormalizedValue | None:
        if key not in self._data:
            return None
        self._data.move_to_end(key)
        return self._data[key]

    def put(self, key: str, value: NormalizedValue) -> None:
        self._data[key] = value
        self._data.move_to_end(key)
        if len(self._data) > self._capacity:
            self._data.popitem(last=False)

    def __len__(self) -> int:
        return len(self._data)


class CacheStats:
    def __init__(self) -> None:
        self.hits = 0
        self.misses = 0

    @property
    def total(self) -> int:
        return self.hits + self.misses

    @property
    def hit_ratio(self) -> float:
        return self.hits / self.total if self.total else 0.0


class NormalizationCache:
    """Two-tier cache. `duckdb_path` may be `":memory:"` for a
    process-local-only persistent tier (useful in tests / single-run CLI
    invocations), or a file path for genuine cross-run reuse.
    """

    def __init__(self, duckdb_path: str | Path = ":memory:", *, lru_capacity: int = 50_000) -> None:
        self._lru = _LruCache(lru_capacity)
        self._conn = duckdb.connect(str(duckdb_path))
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS normalization_cache ("
            "  cache_key VARCHAR PRIMARY KEY,"
            "  value_json VARCHAR NOT NULL"
            ")"
        )
        self.stats = CacheStats()

    def get(self, key: str) -> NormalizedValue | None:
        hit = self._lru.get(key)
        if hit is not None:
            self.stats.hits += 1
            return hit

        row = self._conn.execute(
            "SELECT value_json FROM normalization_cache WHERE cache_key = ?", [key]
        ).fetchone()
        if row is None:
            self.stats.misses += 1
            return None

        value = NormalizedValue.model_validate_json(row[0])
        self._lru.put(key, value)  # promote to hot tier
        self.stats.hits += 1
        return value

    def put(self, key: str, value: NormalizedValue) -> None:
        self._lru.put(key, value)
        self._conn.execute(
            "INSERT OR REPLACE INTO normalization_cache (cache_key, value_json) VALUES (?, ?)",
            [key, value.model_dump_json()],
        )

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> NormalizationCache:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

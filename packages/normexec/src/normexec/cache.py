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

M18 (docs/plan/M13-M22-program-plan.md): every `self._conn` (DuckDB) and
`self._lru` access is guarded by `self._lock`. A real bug, found via live
verification (the same root cause and fix as `normio.sidecar_store.
SidecarStore`'s M18 fix — see that module's docstring): this cache is one
shared instance handed to every run (`normapi.app.create_app()` builds it
once), and a single `duckdb.Connection` is not thread-safe for concurrent
`execute()`/`fetchone()` calls from multiple threads. This has been a
LATENT risk since M8 (this cache was first wired into live execution
then), but M17's worker pool is what made genuinely concurrent runs
sharing one cache instance routine rather than rare — surfaced here by a
live M18 test running two multi-column executions concurrently, which
failed with corrupted DuckDB result rows (e.g. `ValueError: not enough
values to unpack`) traced back to this class, not the sidecar.
"""

from __future__ import annotations

import json
import threading
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
        self._lock = threading.Lock()
        self._conn = duckdb.connect(str(duckdb_path))
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS normalization_cache ("
            "  cache_key VARCHAR PRIMARY KEY,"
            "  value_json VARCHAR NOT NULL"
            ")"
        )
        self.stats = CacheStats()

    def get(self, key: str) -> NormalizedValue | None:
        with self._lock:
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
        with self._lock:
            self._lru.put(key, value)
            self._conn.execute(
                "INSERT OR REPLACE INTO normalization_cache (cache_key, value_json) VALUES (?, ?)",
                [key, value.model_dump_json()],
            )

    def get_many(self, keys: list[str]) -> dict[str, NormalizedValue]:
        """Bulk variant of `get()` — checks the in-process LRU tier per key
        (cheap, no I/O), then issues ONE batched DuckDB query for whatever
        isn't hot, instead of one `SELECT` per miss. Same root cause as
        `put_many`: DuckDB's per-statement overhead makes N individual
        lookups far slower than one `IN (...)` query for the same N keys
        (measured: ~200ms for 50 individual misses vs. a single batched
        query for the same 50). Missing keys from `keys` are simply absent
        from the returned dict, not represented as `None` values.

        `keys` may contain duplicates (the returned dict is naturally
        deduplicated by key) — `stats.hits`/`stats.misses` still count
        one outcome per requested key occurrence, not per unique key, so
        a caller that (unlike every current one) doesn't pre-dedupe still
        gets correct hit/miss accounting.
        """
        if not keys:
            return {}

        with self._lock:
            results: dict[str, NormalizedValue] = {}
            duckdb_lookup_keys: list[str] = []
            for key in keys:
                if key in results:
                    continue
                hit = self._lru.get(key)
                if hit is not None:
                    results[key] = hit
                elif key not in duckdb_lookup_keys:
                    duckdb_lookup_keys.append(key)

            if duckdb_lookup_keys:
                placeholders = ", ".join(["?"] * len(duckdb_lookup_keys))
                rows = self._conn.execute(
                    f"SELECT cache_key, value_json FROM normalization_cache "
                    f"WHERE cache_key IN ({placeholders})",
                    duckdb_lookup_keys,
                ).fetchall()
                for cache_key, value_json in rows:
                    value = NormalizedValue.model_validate_json(value_json)
                    self._lru.put(cache_key, value)
                    results[cache_key] = value

            hits = sum(1 for key in keys if key in results)
            self.stats.hits += hits
            self.stats.misses += len(keys) - hits
            return results

    def put_many(self, items: list[tuple[str, NormalizedValue]]) -> None:
        """Bulk variant of `put()` — one DuckDB statement for the whole
        batch instead of one per item. Real, measured difference: DuckDB
        (an OLAP engine, not built for many small individual
        transactional writes) costs ~830ms for 50 individual `put()`
        calls in-process vs. ~320ms for one `put_many()` call over the
        same 50 items — found and fixed during M8 performance work, not
        a hypothetical optimization. `DistinctValuePlanner` uses this for
        every batch of newly-computed distinct values instead of calling
        `put()` in its loop.

        `items` is deduplicated by key first, keeping the LAST occurrence
        — matching `put()`'s natural "last write wins" semantics. Without
        this, DuckDB's `INSERT OR REPLACE` resolves an intra-statement
        duplicate key by keeping the FIRST occurrence (verified against
        real DuckDB behavior, not assumed), which would silently disagree
        with the LRU tier (updated in iteration order, so it naturally
        keeps the last) — a real two-tier data inconsistency for any
        caller that doesn't pre-dedupe like the current one does.
        """
        if not items:
            return
        deduped = dict(items)  # last occurrence per key wins, like put()
        placeholders = ", ".join(["(?, ?)"] * len(deduped))
        flat_params: list[str] = []
        for key, value in deduped.items():
            flat_params.extend((key, value.model_dump_json()))

        with self._lock:
            for key, value in deduped.items():
                self._lru.put(key, value)
            self._conn.execute(
                f"INSERT OR REPLACE INTO normalization_cache (cache_key, value_json) "
                f"VALUES {placeholders}",
                flat_params,
            )

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> NormalizationCache:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

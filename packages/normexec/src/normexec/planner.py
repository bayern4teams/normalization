"""Distinct-value-first execution planner — Source.txt §102, §104;
decision in docs/adr/ADR-016-performance-architecture.md.

Normalizes the DISTINCT values in a column exactly once (checking the
cache first), then joins the small per-distinct-value result set back onto
every row via Polars. Call volume to the Dispatcher/Normalizer is bounded
by cardinality, not row count — proven mechanically in
spikes/06_polars_arrow_distinct_value.py (100,000 rows / 500 distinct
values -> exactly 500 normalize() calls).
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import polars as pl
import pyarrow as pa

from normexec.cache import make_cache_key

if TYPE_CHECKING:
    from collections.abc import Callable

    from normcore.context import NormalizationContext
    from normcore.dispatch import Dispatcher
    from normcore.enums import FieldSemanticType
    from normcore.models import NormalizedValue
    from normcore.rules import NormalizationProfile

    from normexec.cache import NormalizationCache

# Flat columns extracted from NormalizedValue for the join-back step. The
# full NormalizedValue (including trace, warnings, structured) is available
# per-distinct-value via `normalize_column`'s returned mapping; the joined
# DataFrame carries only these commonly-needed scalar fields inline for
# convenience. Callers needing the full object graph should use
# `distinct_value_results` directly.
_JOIN_COLUMNS = ("display", "comparison", "search", "ascii", "normalization_status", "confidence")


class DistinctValuePlanner:
    def __init__(self, dispatcher: Dispatcher, cache: NormalizationCache | None = None) -> None:
        self._dispatcher = dispatcher
        self._cache = cache

    def distinct_value_results(
        self,
        distinct_values: list[str],
        semantic_type: FieldSemanticType,
        context: NormalizationContext,
        profile: NormalizationProfile,
        *,
        on_computed: Callable[[str, NormalizedValue, float], None] | None = None,
    ) -> dict[str, NormalizedValue]:
        """Normalize each distinct value exactly once, cache-aware.
        Returns {raw_value: NormalizedValue}.

        `on_computed`, if given, fires once per REAL (non-cache-hit)
        dispatcher call with `(value, result, duration_seconds)` — the
        real per-call wall-clock cost, not attributable to a cache hit.
        Source.txt §122's latency/library-call metrics need genuine
        per-computation samples, so callers (normanalysis's RunRecorder)
        hook in here rather than timing at the row level, where duplicate
        rows sharing one deduped result would corrupt the percentiles.
        """
        if self._cache is None:
            results: dict[str, NormalizedValue] = {}
            for value in distinct_values:
                start = time.perf_counter()
                result = self._dispatcher.normalize(value, semantic_type, context, profile)
                duration = time.perf_counter() - start
                if on_computed is not None:
                    on_computed(value, result, duration)
                results[value] = result
            return results

        # Both lookups and writes are batched into a single DuckDB
        # statement each (`get_many`/`put_many`) rather than one
        # statement per distinct value — DuckDB (an OLAP engine) has
        # real, measured per-statement overhead that makes many small
        # individual reads or writes far slower than one batched
        # equivalent (found during M8 performance work: ~200ms for 50
        # individual misses / ~830ms for 50 individual puts, vs. a
        # single batched call for the same 50 in each case).
        keys_by_value = {
            value: make_cache_key(
                value,
                profile_version=profile.version,
                semantic_type=semantic_type,
                context_hash=context.context_hash,
                env_id=self._dispatcher.env_id,
            )
            for value in distinct_values
        }
        cached = self._cache.get_many(list(keys_by_value.values()))

        results = {}
        pending_writes: list[tuple[str, NormalizedValue]] = []
        for value in distinct_values:
            key = keys_by_value[value]
            hit = cached.get(key)
            if hit is not None:
                results[value] = hit
                continue

            start = time.perf_counter()
            result = self._dispatcher.normalize(value, semantic_type, context, profile)
            duration = time.perf_counter() - start
            if on_computed is not None:
                on_computed(value, result, duration)
            results[value] = result
            pending_writes.append((key, result))

        if pending_writes:
            self._cache.put_many(pending_writes)

        return results

    def normalize_values(
        self,
        values: list[str | None],
        semantic_type: FieldSemanticType,
        context: NormalizationContext,
        profile: NormalizationProfile,
        *,
        on_computed: Callable[[str, NormalizedValue, float], None] | None = None,
        on_cache_stat: Callable[[bool], None] | None = None,
    ) -> list[NormalizedValue]:
        """Normalizes a full ordered list of raw values (repeats and
        `None`s allowed) via `distinct_value_results`, resolving each
        position back to its real result. `None` is computed once,
        outside the planner (it isn't a valid `list[str]` distinct-value
        element, but is just as legitimately repeatable within a run) —
        `on_cache_stat`, if given, fires once per distinct non-null value
        with whether it was a real cache hit (attributed from LOCAL
        per-call state, since a globally-shared cache's before/after
        counters can be corrupted by concurrent unrelated activity).

        The one shared entry point for "normalize this run's worth of
        values" — both the pasted-values/single-column path
        (`normapi.store.InMemoryStore._normalize_deduped`, M8) and the
        M17 chunked-streaming path (`normexec.stream`) call this instead
        of each re-implementing the same None-handling and cache-hit
        attribution logic."""
        distinct_non_null = list(dict.fromkeys(v for v in values if v is not None))
        computed_values: set[str] = set()

        def _on_computed(value: str, result: NormalizedValue, duration: float) -> None:
            computed_values.add(value)
            if on_computed is not None:
                on_computed(value, result, duration)

        by_value = self.distinct_value_results(
            distinct_non_null, semantic_type, context, profile, on_computed=_on_computed
        )

        if self._cache is not None and on_cache_stat is not None:
            for value in distinct_non_null:
                on_cache_stat(value not in computed_values)

        none_result = (
            self._dispatcher.normalize(None, semantic_type, context, profile)
            if any(v is None for v in values)
            else None
        )

        def resolve(value: str | None) -> NormalizedValue:
            if value is None:
                if none_result is None:  # pragma: no cover - unreachable, see none_result above
                    msg = "internal error: encountered a None value without a precomputed result"
                    raise AssertionError(msg)
                return none_result
            return by_value[value]

        return [resolve(value) for value in values]

    def normalize_column(
        self,
        df: pl.DataFrame,
        column: str,
        semantic_type: FieldSemanticType,
        context: NormalizationContext,
        profile: NormalizationProfile,
    ) -> pl.DataFrame:
        """Returns `df` with additional `{column}__<view>` columns joined
        back from the distinct-value result set. Null values in the source
        column pass through as null in every derived column, never sent to
        the dispatcher (a null is not a "value" to normalize — see
        MissingValueNormalizer, M2, for actual missing-sentinel handling).
        """
        distinct_values = df.select(pl.col(column).drop_nulls().unique()).to_series().to_list()
        results = self.distinct_value_results(distinct_values, semantic_type, context, profile)

        lookup_rows = {
            "__lookup_key": list(results.keys()),
            **{
                f"{column}__{field}": [getattr(results[v], field) for v in results]
                for field in _JOIN_COLUMNS
            },
        }
        lookup = pl.DataFrame(lookup_rows)

        return df.join(lookup, left_on=column, right_on="__lookup_key", how="left")

    def normalize_column_to_arrow(
        self,
        df: pl.DataFrame,
        column: str,
        semantic_type: FieldSemanticType,
        context: NormalizationContext,
        profile: NormalizationProfile,
    ) -> pa.StructArray:
        """Same as `normalize_column`, but returns a single Arrow
        StructArray of the joined-back derived columns — the shape written
        to the Parquet sidecar store (ADR-013).
        """
        joined = self.normalize_column(df, column, semantic_type, context, profile)
        arrow_table = joined.select(
            [pl.col(f"{column}__{field}").alias(field) for field in _JOIN_COLUMNS]
        ).to_arrow()

        return pa.StructArray.from_arrays(
            [arrow_table.column(name).combine_chunks() for name in arrow_table.column_names],
            names=list(arrow_table.column_names),
        )

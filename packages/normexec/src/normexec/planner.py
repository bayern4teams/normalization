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
        # Results a caller keeps across calls for as long as this planner
        # lives (the clone executor: one job). Keyed and bounded by the caller.
        self.memo: dict[tuple[object, ...], dict[str, NormalizedValue]] = {}

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
        self._prepare_batch(distinct_values, semantic_type, context)

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

    def _prepare_batch(
        self,
        distinct_values: list[str],
        semantic_type: FieldSemanticType,
        context: NormalizationContext,
    ) -> None:
        """Give a normalizer one shot at the whole distinct-value list
        before it is asked for them one at a time.

        This exists for normalizers whose real cost is a per-value round
        trip to something external: `AddressNormalizer` was issuing ONE
        HTTP request per address to the libpostal sidecar, even though
        that sidecar's /parse endpoint has always accepted a list. The
        planner is the only place that holds the full distinct set, so
        the hook belongs here.

        Probed with getattr rather than declared on the Normalizer
        Protocol: exactly one normalizer implements it, every other one
        (and every test double) is unaffected, and a normalizer that
        cannot batch should not be forced to define a no-op. Failures are
        the hook's own problem to swallow — it is an optimization, and
        the per-value path below stays correct on its own.
        """
        normalizer = self._dispatcher.registry.get(semantic_type)
        prepare = getattr(normalizer, "prepare_batch", None)
        if prepare is not None:
            prepare(distinct_values, context)

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

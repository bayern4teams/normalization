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

from typing import TYPE_CHECKING

import polars as pl
import pyarrow as pa

from normexec.cache import make_cache_key

if TYPE_CHECKING:
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
    ) -> dict[str, NormalizedValue]:
        """Normalize each distinct value exactly once, cache-aware.
        Returns {raw_value: NormalizedValue}.
        """
        results: dict[str, NormalizedValue] = {}
        for value in distinct_values:
            cache_key = None
            if self._cache is not None:
                cache_key = make_cache_key(
                    value,
                    profile_version=profile.version,
                    semantic_type=semantic_type,
                    context_hash=context.context_hash,
                    env_id=self._dispatcher.env_id,
                )
                cached = self._cache.get(cache_key)
                if cached is not None:
                    results[value] = cached
                    continue

            result = self._dispatcher.normalize(value, semantic_type, context, profile)
            results[value] = result

            if self._cache is not None and cache_key is not None:
                self._cache.put(cache_key, result)

        return results

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

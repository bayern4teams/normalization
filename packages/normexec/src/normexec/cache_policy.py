"""Cardinality-aware cache policy — Phase 3 item 2 of the throughput/memory
program (`C:\\Users\\rezas\\.claude\\plans\\humming-frolicking-shore.md`).

The plan's own measured cardinality table motivates this: `Location.country`
(0.03% distinct) gets a real 2972x dedup factor from caching, while
`Company.name` (97.1% distinct) or `PersonContact.contactString` (99.9%
distinct) essentially never repeat — every cache write for those columns is
pure cost (LRU churn, a DuckDB statement) for a hit that will not happen,
either within the same run (the planner already dedupes distinct values
before this layer ever sees them) or across future runs (the values
themselves are ~unique, so a future run over the same table would ask about
different values, not the same ones).

`CACHE_SKIP_DISTINCT_RATIO_THRESHOLD` is a structural cache-economics
threshold, not a hardware-calibrated one — it says something about the DATA
(how often a value recurs), never about how fast this machine is. That is a
real, deliberate distinction from the plan's "thresholds must be calibrated
at runtime" rule, which targets per-value TIMING decisions (the process-pool
break-even point in `normexec.parallel`/`normexec.planner`) that genuinely
do depend on the machine and the workload. 0.5 is chosen to cleanly separate
the plan's own worked examples without being tuned to any single one of
them: every "keep caching" column in that table (country 0.03%, city 3.2%,
firstName 4.1%, zip 8.1%, lastName 11.5%, title 23.3%) sits far below it,
and every "skip" column (fullName 76.8%, Company.name 97.1%, contactString
99.9%) sits far above it.
"""

from __future__ import annotations

from typing import Literal

from normcore.run import ColumnCachePolicy

CACHE_SKIP_DISTINCT_RATIO_THRESHOLD = 0.5

CachePolicySource = Literal["connector_estimate", "first_chunk_sample"]


def decide_cache_policy(
    *,
    table: str,
    column: str,
    distinct_ratio: float | None,
    source: CachePolicySource,
) -> ColumnCachePolicy:
    """`distinct_ratio` is `None` when there was nothing to estimate from
    (an empty table, or an empty first chunk) — `use_cache` stays `True`
    in that case, the same as this run's pre-Phase-3 default, since there
    is no data yet to justify skipping the cache."""
    use_cache = distinct_ratio is None or distinct_ratio < CACHE_SKIP_DISTINCT_RATIO_THRESHOLD
    return ColumnCachePolicy(
        table=table,
        column=column,
        use_cache=use_cache,
        distinct_ratio=distinct_ratio,
        source=source,
    )

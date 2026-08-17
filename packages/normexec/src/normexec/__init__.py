"""normexec — Polars/DuckDB/Arrow batch execution engine: the
distinct-value-first planner and two-tier cache described in
docs/adr/ADR-016-performance-architecture.md.
"""

from normexec.cache import CacheStats, NormalizationCache, make_cache_key
from normexec.planner import DistinctValuePlanner

__all__ = [
    "CacheStats",
    "DistinctValuePlanner",
    "NormalizationCache",
    "make_cache_key",
]

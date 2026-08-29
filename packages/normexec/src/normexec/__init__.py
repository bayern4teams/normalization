"""normexec — Polars/DuckDB/Arrow batch execution engine: the
distinct-value-first planner and two-tier cache described in
docs/adr/ADR-016-performance-architecture.md.

`import icu` is deliberately the first statement in this file, before any
other import — see `normalizers/__init__.py`'s identical guard for the
full explanation (PyICU/PyArrow DLL load-order conflict on Windows).
This package's own `normexec.planner` imports `pyarrow` at module scope,
so simply importing the `normexec` PACKAGE (which Python always does
before any of its submodules, including when a Phase 3 process-pool
worker unpickles a `normexec.parallel._worker_init` reference in a fresh
process that has imported nothing yet) already reaches pyarrow — found
by a real `BrokenProcessPool` crash in
`tests/unit/test_parallel_pool.py` during the throughput/memory
program's Phase 3 work, not by inspection.
"""

import icu  # noqa: F401 - see module docstring; must stay the first import

from normexec.cache import CacheStats, NormalizationCache, make_cache_key
from normexec.env_fingerprint import EnvFingerprintInputs, compute_env_id, gather
from normexec.planner import DistinctValuePlanner

__all__ = [
    "CacheStats",
    "DistinctValuePlanner",
    "EnvFingerprintInputs",
    "NormalizationCache",
    "compute_env_id",
    "gather",
    "make_cache_key",
]

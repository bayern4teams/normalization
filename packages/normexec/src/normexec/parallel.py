"""Process-pool parallel distinct-value normalization — Phase 3 of the
throughput/memory program (`C:\\Users\\rezas\\.claude\\plans\\humming-frolicking-shore.md`).

Threads are proven useless for this (0.90x on real normalizers, measured
in that program's R&D pass — pure-Python CPU work is GIL-bound). This
trades IPC cost (pickle a batch of values + context + profile out, pickle
a batch of `NormalizedValue` results back) against per-value compute
cost, so it only pays off above a break-even point — and that point is
measured against THIS run's real environment and THIS column's real
per-value cost, never a hardcoded number (the program's own non-negotiable
rule: thresholds must be calibrated at runtime).

Off by default (`NORM_PARALLEL_WORKERS` unset or `0`). Worker count sizing
reads the real cgroup CPU quota (`normexec.resources`), never
`os.cpu_count()` directly, so a CPU-quota-limited container doesn't
overcommit its host.

Two semantic types are permanently excluded from the pool, each for a
different real, measured reason — both guarded by
`tests/unit/test_parallel_pool.py::test_pool_excludes_address_and_script_permanently`
and `::test_planner_never_pools_address_even_with_a_pool_configured` so
neither list shrinks by accident:

- ADDRESS: `AddressNormalizer` talks to a synchronous, single-worker
  libpostal sidecar — network-bound, not GIL-bound, so a pool buys
  nothing — and its circuit-breaker state change IS observable output.
  Splitting one column's calls across N processes would fragment that
  breaker's state across processes, which is a determinism break, not
  just a missed optimization.
- SCRIPT: measured directly during this program's Phase 3 R&D — a worker
  that normalizes even ONE SCRIPT value grows from ~152MB to ~1.5GB RSS
  (`lingua`'s `LanguageDetectorBuilder.from_all_languages()`, built
  lazily but still built the first time it's needed) and never shrinks
  back for the rest of the pool's lifetime. A handful of such workers
  would threaten the whole container's memory budget, which the program's
  plan already flags as fragile (the `api` service has no `mem_limit`).
"""

from __future__ import annotations

import multiprocessing as mp
import os
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from typing import TYPE_CHECKING

from normcore.enums import FieldSemanticType

from normexec.resources import detect_cpu_quota

if TYPE_CHECKING:
    from collections.abc import Sequence

    from normcore.context import NormalizationContext
    from normcore.dispatch import Dispatcher
    from normcore.models import NormalizedValue
    from normcore.rules import NormalizationProfile

POOL_EXCLUDED_SEMANTIC_TYPES = frozenset({FieldSemanticType.ADDRESS, FieldSemanticType.SCRIPT})

_ENV_WORKERS = "NORM_PARALLEL_WORKERS"

DispatcherFactory = Callable[[], "Dispatcher"]


def parallel_workers_from_env(*, cpu_quota: int | None = None) -> int:
    """0 (the default, whether unset or explicitly `"0"`) = disabled.
    A negative value = auto: derive from the real cgroup CPU quota, minus
    one core of headroom for the process driving the pool. A positive
    value = an explicit override (e.g. a benchmark holding worker count
    fixed across repeated runs). Any unparseable value is treated as
    disabled rather than raising, matching this codebase's other
    env-configured numeric knobs.
    """
    raw = os.environ.get(_ENV_WORKERS, "0").strip()
    try:
        configured = int(raw)
    except ValueError:
        configured = 0
    if configured == 0:
        return 0
    if configured > 0:
        return configured
    quota = cpu_quota if cpu_quota is not None else detect_cpu_quota()
    return max(1, quota - 1)


# Set once per worker process by `_worker_init`, read by every task that
# process executes — the standard `ProcessPoolExecutor` pattern for
# "construct expensive state once per process" (mirrors
# `NormalizerRegistry`'s own "construct once, reuse across the whole
# distinct-value batch" rule, just at the process level instead of the
# call level).
_worker_dispatcher: Dispatcher | None = None


def _worker_init(factory: DispatcherFactory) -> None:
    global _worker_dispatcher  # noqa: PLW0603 - per-process singleton, see module docstring
    _worker_dispatcher = factory()


def _worker_normalize_batch(
    values: list[str],
    semantic_type: FieldSemanticType,
    context: NormalizationContext,
    profile: NormalizationProfile,
) -> list[NormalizedValue]:
    if _worker_dispatcher is None:  # pragma: no cover - initializer contract
        msg = "pool worker's dispatcher was never initialized — _worker_init did not run"
        raise RuntimeError(msg)
    return [_worker_dispatcher.normalize(v, semantic_type, context, profile) for v in values]


class DistinctValueWorkerPool:
    """Owns one `ProcessPoolExecutor`, created once and meant to be reused
    across every column and chunk in a run — worker startup (importing
    the full normalizer stack) was measured at several seconds per
    worker; amortizing that across a whole run rather than paying it per
    chunk or per column is the entire point of owning the pool at this
    level rather than inside a single `stream_column` call.

    Always uses the `spawn` start method explicitly, regardless of
    platform default (Linux defaults to `fork`): several native
    extensions this codebase depends on (PyICU, DuckDB) are not
    documented as fork-after-import-safe, and the program's own IPC/RSS
    measurements were taken under `spawn` — using anything else would
    make those numbers not apply to what actually runs.
    """

    def __init__(self, factory: DispatcherFactory, *, workers: int) -> None:
        if workers < 1:
            msg = f"workers must be >= 1, got {workers}"
            raise ValueError(msg)
        self._workers = workers
        self._executor = ProcessPoolExecutor(
            max_workers=workers,
            mp_context=mp.get_context("spawn"),
            initializer=_worker_init,
            initargs=(factory,),
        )

    @property
    def workers(self) -> int:
        return self._workers

    def normalize_batch(
        self,
        values: Sequence[str],
        semantic_type: FieldSemanticType,
        context: NormalizationContext,
        profile: NormalizationProfile,
    ) -> list[NormalizedValue]:
        """Normalizes `values` across the pool and returns results in the
        SAME order as `values` — collected via `future.result()` in
        submission order, never `as_completed` order, so cache-write
        order and downstream row-join behavior stay byte-identical to the
        serial path. Costs nothing (every result is needed before the
        caller can proceed regardless) and removes an entire class of
        "is this ordering observable?" question.

        Split into `self._workers` roughly-equal batches so every worker
        stays busy without submitting one task per value (which would pay
        this pool's per-task overhead — not just per-batch — once per
        value, defeating the whole point of batching context/profile
        pickling cost across many values).
        """
        values = list(values)
        if not values:
            return []
        batch_size = max(1, -(-len(values) // self._workers))  # ceil div, no float rounding
        batches = [values[i : i + batch_size] for i in range(0, len(values), batch_size)]
        futures = [
            self._executor.submit(_worker_normalize_batch, batch, semantic_type, context, profile)
            for batch in batches
        ]
        results: list[NormalizedValue] = []
        for future in futures:
            results.extend(future.result())
        return results

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True)

    def __enter__(self) -> DistinctValueWorkerPool:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.shutdown()

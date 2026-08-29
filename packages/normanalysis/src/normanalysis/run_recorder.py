"""Run recording — Source.txt §70.

`RunRecorder` accumulates the counters a `NormalizationRun` reports
(records/fields processed, changed/unchanged values, warnings, errors,
cache hits/misses) as normalization actually happens, and produces
updated, immutable `NormalizationRun` snapshots — never mutates the run
object in place, consistent with every other domain model in this
codebase being frozen. This is the real run-tracking logic; normapi's
InMemoryStore (M1 scaffold) will be replaced by a persistence layer that
uses this same recorder, not a separate implementation of the same
counting logic.
"""

from __future__ import annotations

import random
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from normcore import NormalizationRun, NormalizationRunMetrics, NormalizationStatus, RunStatus

if TYPE_CHECKING:
    from normcore import ColumnCachePolicy, NormalizedValue


class InvalidRunTransitionError(RuntimeError):
    pass


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Nearest-rank percentile — no interpolation, so p95/p99 always
    equal a real observed sample rather than a synthesized value between
    two samples, which matters for latency reporting (§122)."""
    if not sorted_values:
        return 0.0
    index = min(len(sorted_values) - 1, int(pct * len(sorted_values)))
    return sorted_values[index]


# Phase 1 (2026-08-29 throughput program): `_latencies_s` used to be an
# unbounded list — every real (non-cache-hit) normalize() call appended
# to it for the life of the run, so a `Person.fullName`-scale run
# (~9.06M distinct values) would accumulate ~290MB of pure float
# accumulator. Reservoir sampling (Algorithm R) caps memory at this many
# floats regardless of run size, while keeping a statistically
# representative uniform random sample for percentile/average reporting
# — the one intentional behavior change in this phase: p95/p99/avg
# latency become estimates over a bounded sample rather than exact
# values over the full population once a run exceeds this size. Latency
# metrics were already real `time.perf_counter()` wall-clock, never
# claimed reproducible and already excluded by name from
# `normcli diff --require-identical`'s comparison (see `diff_cmd.py`) —
# so this does not touch ADR-014's determinism guarantee.
_LATENCY_RESERVOIR_SIZE = 10_000


class RunRecorder:
    def __init__(self, run: NormalizationRun) -> None:
        if run.status is not RunStatus.PENDING:
            msg = f"RunRecorder must be constructed with a PENDING run, got status={run.status}"
            raise InvalidRunTransitionError(msg)
        self._run = run
        self._records_processed = 0
        self._fields_processed = 0
        self._changed_values = 0
        self._unchanged_values = 0
        self._warnings = 0
        self._errors = 0
        self._cache_hits = 0
        self._cache_misses = 0
        self._parser_failures = 0
        self._validation_failures = 0
        self._library_calls = 0
        self._latencies_s: list[float] = []
        self._latency_samples_seen = 0
        self._latency_rng = random.Random()
        self._started_monotonic: float | None = None
        # Phase 3 item 2 (2026-08-29 throughput program): one entry per
        # column a cache policy was actually decided for — empty for a
        # run with no cache configured at all (nothing to decide). A
        # plain list, not keyed by (table, column): a resumed/restarted
        # column could in principle report twice, and keeping every real
        # decision (rather than silently overwriting) is more honest for
        # an audit trail than deduplicating one away.
        self._cache_policy: list[ColumnCachePolicy] = []

    @property
    def records_processed(self) -> int:
        """The one counter mid-run progress reporting actually needs
        (e.g. `normapi.store`'s `on_chunk_committed`) — a plain
        attribute read, not a full `snapshot()` (which sorts/percentiles
        the entire latency sample on every call)."""
        return self._records_processed

    def start(self) -> NormalizationRun:
        self._started_monotonic = time.perf_counter()
        self._run = self._run.model_copy(update={"status": RunStatus.RUNNING})
        return self.snapshot()

    def record_value(self, *, changed: bool, status: NormalizationStatus | None = None) -> None:
        self._records_processed += 1
        if changed:
            self._changed_values += 1
        else:
            self._unchanged_values += 1
        if status is NormalizationStatus.FAILED:
            self._parser_failures += 1
        elif status is NormalizationStatus.INVALID:
            self._validation_failures += 1

    def record_field(self) -> None:
        self._fields_processed += 1

    def record_cache(self, *, hit: bool) -> None:
        if hit:
            self._cache_hits += 1
        else:
            self._cache_misses += 1

    def record_computation(
        self, _value: str, result: NormalizedValue, duration_seconds: float
    ) -> None:
        """Called once per real (non-cache-hit) normalize() call — see
        `DistinctValuePlanner.distinct_value_results`'s `on_computed`
        hook. Feeds §122's latency percentiles and library-call count
        from genuine per-computation samples, not per-row (a row reusing
        a deduped/cached result didn't really re-invoke anything).

        Reservoir sampling (Algorithm R), not an unbounded append — see
        `_LATENCY_RESERVOIR_SIZE`'s comment. The first
        `_LATENCY_RESERVOIR_SIZE` samples are always kept; after that,
        each new sample replaces a uniformly random existing slot with
        probability `_LATENCY_RESERVOIR_SIZE / n`, which is the standard
        proof-carrying construction for "a uniform random sample of the
        full stream without knowing its length in advance."
        """
        self._latency_samples_seen += 1
        if len(self._latencies_s) < _LATENCY_RESERVOIR_SIZE:
            self._latencies_s.append(duration_seconds)
        else:
            replace_index = self._latency_rng.randint(0, self._latency_samples_seen - 1)
            if replace_index < _LATENCY_RESERVOIR_SIZE:
                self._latencies_s[replace_index] = duration_seconds
        self._library_calls += sum(1 for step in result.trace if step.library is not None)

    def record_cache_policy(self, decision: ColumnCachePolicy) -> None:
        """Called at most twice per column (`normexec.stream.stream_column`:
        once if the connector supplies a real estimate up front, once —
        the fallback — after the first chunk, never both)."""
        self._cache_policy.append(decision)

    def record_warning(self) -> None:
        self._warnings += 1

    def record_error(self) -> None:
        self._errors += 1

    def _elapsed_seconds(self) -> float:
        if self._started_monotonic is None:
            return 0.0
        return time.perf_counter() - self._started_monotonic

    def snapshot(self) -> NormalizationRun:
        """A NormalizationRun reflecting counters recorded so far, without
        changing the run's status/finished_at — safe to call mid-run for
        progress reporting."""
        elapsed = self._elapsed_seconds()
        latencies_ms = sorted(d * 1000 for d in self._latencies_s)
        avg_latency_ms = sum(latencies_ms) / len(latencies_ms) if latencies_ms else 0.0

        return self._run.model_copy(
            update={
                "cache_policy": tuple(self._cache_policy),
                "metrics": NormalizationRunMetrics(
                    records_processed=self._records_processed,
                    fields_processed=self._fields_processed,
                    changed_values=self._changed_values,
                    unchanged_values=self._unchanged_values,
                    warnings=self._warnings,
                    errors=self._errors,
                    cache_hits=self._cache_hits,
                    cache_misses=self._cache_misses,
                    parser_failures=self._parser_failures,
                    validation_failures=self._validation_failures,
                    library_calls=self._library_calls,
                    duration_seconds=elapsed,
                    rows_per_second=(self._records_processed / elapsed if elapsed > 0 else 0.0),
                    avg_latency_ms=avg_latency_ms,
                    p95_latency_ms=_percentile(latencies_ms, 0.95),
                    p99_latency_ms=_percentile(latencies_ms, 0.99),
                )
            }
        )

    def finish(self, status: RunStatus) -> NormalizationRun:
        if status is RunStatus.PENDING or status is RunStatus.RUNNING:
            msg = f"finish() requires a terminal status, got {status}"
            raise InvalidRunTransitionError(msg)
        self._run = self.snapshot().model_copy(
            update={"status": status, "finished_at": datetime.now(UTC).isoformat()}
        )
        return self._run

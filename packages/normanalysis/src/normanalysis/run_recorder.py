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

from datetime import UTC, datetime

from normcore import NormalizationRun, NormalizationRunMetrics, RunStatus


class InvalidRunTransitionError(RuntimeError):
    pass


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

    def start(self) -> NormalizationRun:
        self._run = self._run.model_copy(update={"status": RunStatus.RUNNING})
        return self.snapshot()

    def record_value(self, *, changed: bool) -> None:
        self._records_processed += 1
        if changed:
            self._changed_values += 1
        else:
            self._unchanged_values += 1

    def record_field(self) -> None:
        self._fields_processed += 1

    def record_cache(self, *, hit: bool) -> None:
        if hit:
            self._cache_hits += 1
        else:
            self._cache_misses += 1

    def record_warning(self) -> None:
        self._warnings += 1

    def record_error(self) -> None:
        self._errors += 1

    def snapshot(self) -> NormalizationRun:
        """A NormalizationRun reflecting counters recorded so far, without
        changing the run's status/finished_at — safe to call mid-run for
        progress reporting."""
        return self._run.model_copy(
            update={
                "metrics": NormalizationRunMetrics(
                    records_processed=self._records_processed,
                    fields_processed=self._fields_processed,
                    changed_values=self._changed_values,
                    unchanged_values=self._unchanged_values,
                    warnings=self._warnings,
                    errors=self._errors,
                    cache_hits=self._cache_hits,
                    cache_misses=self._cache_misses,
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

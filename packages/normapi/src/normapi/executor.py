"""A bounded worker pool for run execution — M17 of the M13-M22 program.

Replaces M11's raw `threading.Thread(daemon=True)` per run (one
unbounded thread for every in-flight run, no ceiling at all) with a
fixed-size pool: `max_workers` threads pulling tasks off one queue.

Also owns the real fix for "a run left RUNNING forever": at startup,
`reconcile_running_runs()` finds every run Postgres still shows as
RUNNING (necessarily meaning the PREVIOUS process died mid-execution —
no live process could still be running it) and marks it FAILED with a
clear, honest `failure_reason`. A run's own chunk-level progress
(`run_chunks`, `PostgresMetadataStore.get_last_chunk`) survives this —
resuming it back into RUNNING is a deliberate, disclosed follow-up
action (not done automatically at boot in this milestone), not data
loss.
"""

from __future__ import annotations

import queue
import threading
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from normcore import RunStatus

if TYPE_CHECKING:
    from collections.abc import Callable

    from normapi.postgres_store import PostgresMetadataStore
    from normapi.store import InMemoryStore


class RunExecutor:
    """`max_workers` daemon threads pulling `Callable[[], None]` tasks
    off one `queue.Queue` — a real concurrency ceiling on in-flight run
    execution, unlike one raw thread per run."""

    def __init__(self, max_workers: int = 4) -> None:
        self._queue: queue.Queue[Callable[[], None] | None] = queue.Queue()
        self._workers = [
            threading.Thread(target=self._worker_loop, daemon=True) for _ in range(max_workers)
        ]
        for worker in self._workers:
            worker.start()

    def submit(self, task: Callable[[], None]) -> None:
        self._queue.put(task)

    def _worker_loop(self) -> None:
        while True:
            task = self._queue.get()
            if task is None:
                self._queue.task_done()
                break
            try:
                task()
            except Exception:
                # A task is responsible for recording its own run's
                # FAILED status (see InMemoryStore._run_execution_worker,
                # or M17's multi-column equivalent) — an exception
                # escaping here means that responsibility was already
                # discharged (or the task itself is buggy, in which case
                # silently dying is no worse than the pre-M17 raw-thread
                # behavior it replaces, and strictly better: this worker
                # keeps serving the next task instead of leaking a dead
                # thread).
                pass
            finally:
                self._queue.task_done()

    def shutdown(self, *, timeout: float = 5.0) -> None:
        """Signals every worker to stop after its current task and waits
        up to `timeout` seconds per worker — used by tests and a clean
        process shutdown, not on the live-request path."""
        for _ in self._workers:
            self._queue.put(None)
        for worker in self._workers:
            worker.join(timeout=timeout)


def reconcile_running_runs(store: InMemoryStore, pg_store: PostgresMetadataStore) -> list[str]:
    """Marks every run Postgres shows as RUNNING as FAILED — called once
    at app startup, before the app serves a single request. Returns the
    run ids actually reconciled (empty on a clean boot with nothing
    stuck). A run's own `run_chunks`/`run_columns` progress is left
    untouched; a future explicit resume action (not built in M17) is
    what would pick that back up, not this reconciliation pass itself.
    """
    reconciled: list[str] = []
    for run_id in pg_store.list_running_run_ids():
        run = pg_store.get_run(run_id)
        if run is None:
            continue
        failed = run.model_copy(
            update={
                "status": RunStatus.FAILED,
                "finished_at": datetime.now(UTC).isoformat(),
                "failure_reason": "process restarted",
            }
        )
        pg_store.save_run(failed)
        store.refresh_run(failed)
        reconciled.append(run_id)
    return reconciled

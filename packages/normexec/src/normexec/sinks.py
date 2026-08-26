"""RunSink — where a chunk's normalized results go. M17 of the
M13-M22 program (docs/plan/M13-M22-program-plan.md).

Kept as a Protocol specifically so M19's `DestinationRunSink` (writing
normalized data into a real destination database) can be added as a
second implementation without reopening `stream.py`'s chunk loop — the
loop calls `sink.write_chunk(...)` once per chunk regardless of which
sink is plugged in.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from normio.sidecar_store import SidecarStore

if TYPE_CHECKING:
    import pyarrow as pa


@runtime_checkable
class RunSink(Protocol):
    def write_chunk(
        self, *, run_id: str, table: str, column: str, chunk_index: int, batch: pa.RecordBatch
    ) -> None:
        """Persists one chunk's normalized results. Called once per
        chunk, in order, for a given `(table, column)` — `chunk_index`
        is that column's own chunk sequence number, not a global counter
        across the whole run."""
        ...

    def finish(self, *, run_id: str, table: str, column: str) -> None:
        """Called once a `(table, column)`'s last chunk has been written
        — a no-op for sinks with nothing to flush (like
        `SidecarRunSink`, since `write_chunk` already persists
        synchronously), but a real hook for a sink that batches or opens
        a transaction per column (M19's destination writer)."""
        ...


class SidecarRunSink:
    """The only `RunSink` through M17 — writes each chunk straight to
    the Arrow/Parquet sidecar (ADR-013's bulk-data tier), reusing
    `SidecarStore.write_batch` unchanged (M9-built, real since M1's
    schema)."""

    def __init__(self, sidecar: SidecarStore, *, source_id: str) -> None:
        self._sidecar = sidecar
        self._source_id = source_id

    def write_chunk(
        self, *, run_id: str, table: str, column: str, chunk_index: int, batch: pa.RecordBatch
    ) -> None:
        self._sidecar.write_batch(
            source_id=self._source_id,
            table=table,
            column=column,
            run_id=run_id,
            batch=batch,
            part_index=chunk_index,
        )

    def finish(self, *, run_id: str, table: str, column: str) -> None:
        pass

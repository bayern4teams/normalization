"""SourceConnector protocol — Source.txt §8, §105; decision in
docs/adr/ADR-013-normalization-storage.md.

Sources are read-only, always. This Protocol has NO write/update/delete/
insert method at all — not an unimplemented one, an absent one. A
connector class cannot "accidentally" expose a write path through this
interface because the interface itself has no vocabulary for it. Every
concrete connector additionally opens its underlying client with
read-only credentials/session options as a second, independent layer of
enforcement (defense in depth: interface shape + actual DB-level
permissions), verified in tests/integration/test_readonly_connectors.py
by attempting a real write and asserting it is rejected by the database,
not just by our code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    import pyarrow as pa


@dataclass(frozen=True)
class ColumnInfo:
    """One column's name + native (engine-level) type string, as reported
    by the source. A data shape, not a behavior interface — deliberately
    NOT part of the `SourceConnector` Protocol (only the clone-job
    discovery routes consume it; FileConnector/MongoConnector are out of
    scope and would need dummy implementations if the Protocol grew it).
    """

    name: str
    native_type: str


@runtime_checkable
class SourceConnector(Protocol):
    """Read-only access to one source system. `source_id` identifies the
    source for `NormalizationContext.source` and for sidecar-store
    partitioning (ADR-013).
    """

    source_id: str

    def list_tables(self) -> Sequence[str]:
        """Table/collection names visible to the configured read-only
        credentials."""
        ...

    def read_table(
        self,
        table: str,
        *,
        columns: Sequence[str] | None = None,
        batch_size: int = 100_000,
    ) -> Iterator[pa.RecordBatch]:
        """Streams `table` as Arrow RecordBatches. Every batch includes a
        `source_row_key` column (Source.txt §106) — a stable, unique
        identifier for each row within this table, so downstream joins
        (e.g. DistinctValuePlanner's join-back, or the sidecar store's
        keying) never depend on row order.
        """
        ...

    def close(self) -> None: ...

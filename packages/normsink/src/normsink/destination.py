"""`DestinationConnector` — the write vocabulary `normio.SourceConnector`
deliberately does not have (ADR-013, decision 6 of the M13-M22 program).
Physically a separate Protocol in a separate package, not an extension of
`SourceConnector`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Sequence

    import pyarrow as pa


@dataclass(frozen=True, slots=True)
class DestinationColumnSpec:
    """One destination column's real shape — mirrors the source's column
    order and name always; `destination_type` is the source's own type
    string verbatim for an unmapped column, or a real typed ClickHouse
    type (`Nullable(Decimal(38,9))`/`Nullable(Date)`/`Nullable(DateTime64(3))`)
    for a mapped NUMERIC/DATE/DATETIME column — see
    `normsink.typed_values`'s module docstring for the extraction
    contract that produces the values going into a typed column."""

    name: str
    destination_type: str
    is_mapped: bool


@runtime_checkable
class DestinationConnector(Protocol):
    """Write vocabulary for one destination database. Every method here
    is exactly the "no write vocabulary" absence `normio.SourceConnector`
    is deliberately missing — kept in this separate package so that
    absence stays literally true."""

    def ensure_database(self) -> None:
        """Creates the destination database if it does not already
        exist. Idempotent — safe to call on every run."""
        ...

    def ensure_table(
        self, table: str, *, columns: Sequence[DestinationColumnSpec], key_columns: Sequence[str]
    ) -> None:
        """Creates the mirrored table if it does not already exist, with
        `columns` in the source's own order — same engine family as the
        source (`ReplacingMergeTree`), `ORDER BY` the same real key
        columns the source uses, which is what makes re-running the same
        run idempotent by construction (a repeated insert for the same
        key replaces, not duplicates)."""
        ...

    def ensure_side_table(self, table: str) -> None:
        """Creates `{table}__normalization_issues` if it does not already
        exist — quality/warnings/lossiness data lives here, never as
        extra columns on the mirrored table (decision 6)."""
        ...

    def insert_batch(self, table: str, batch: pa.RecordBatch) -> None:
        """Inserts one chunk's worth of complete destination rows —
        every column in `ensure_table`'s own order present in every row,
        mapped columns holding normalized/typed values, unmapped columns
        holding the source's verbatim value."""
        ...

    def insert_side_table_batch(self, table: str, batch: pa.RecordBatch) -> None:
        """Inserts one chunk's worth of normalization-issue rows into
        `{table}__normalization_issues`."""
        ...

    def close(self) -> None: ...

"""Catalog value objects — Source.txt §105, M14 of the M13-M22 program
(docs/plan/M13-M22-program-plan.md).

`TableSpec`/`ColumnSpec` describe a source table's structure independently
of any one connector's implementation, so normapi's catalog routes (M16)
and the chunked reader (M17) share one vocabulary instead of each
connector inventing its own shape.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ColumnSpec:
    """One column's shape, as reported by the source's own catalog
    (e.g. ClickHouse's `system.columns`, or SQLAlchemy's `Inspector`)."""

    name: str
    type: str
    nullable: bool
    is_primary_key: bool


@dataclass(frozen=True, slots=True)
class TableSpec:
    """One table's shape. `approx_rows` and `engine` are best-effort,
    sourced from catalog statistics rather than `COUNT(*)` — they exist
    for UI display and streaming-progress estimates, not for correctness
    (a real streaming read never trusts `approx_rows` as an exact bound)."""

    name: str
    columns: tuple[ColumnSpec, ...]
    engine: str | None = None
    approx_rows: int | None = None

    @property
    def primary_key(self) -> tuple[str, ...]:
        """Real key columns, in catalog-declared order — the columns a
        streaming read paginates by (M14's `read_chunk`) and a
        destination write uses for `ORDER BY` (M19). Derived from the
        source's own primary-key metadata, never parsed out of a
        sorting-key expression string (see ClickHouseConnector.table_spec
        for why that distinction is load-bearing)."""
        return tuple(c.name for c in self.columns if c.is_primary_key)

    @property
    def has_created_at(self) -> bool:
        return any(c.name == "created_at" for c in self.columns)

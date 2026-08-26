"""Optional connector capabilities — catalog introspection and chunked,
resumable reads. Source.txt §105, M14 of the M13-M22 program.

Kept as Protocols SEPARATE from `SourceConnector` (normio/connector.py),
deliberately — that Protocol's complete absence of anything beyond
`list_tables`/`read_table`/`close` is load-bearing for ADR-013 and three
existing verification packs. These are additive read capabilities, not a
relaxation of that contract: a connector implements them by simply having
the extra methods, and callers capability-check with
`isinstance(connector, CatalogConnector)` before use, since not every
connector kind implements them yet (M14 scope: ClickHouse, Postgres,
MySQL — Mongo/file get an explicit 501 per the M13-M22 plan's
out-of-scope list, not a silent AttributeError).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from normio.connector import SourceConnector

if TYPE_CHECKING:
    from collections.abc import Sequence

    import pyarrow as pa

    from normio.catalog import ColumnSpec, TableSpec


@runtime_checkable
class CatalogConnector(Protocol):
    """Structure introspection: what databases/tables/columns exist, and
    a few sample values — the read side of Connect/Explore (decision 6's
    3-step UI, built in M21 on top of M16's catalog routes)."""

    def list_databases(self) -> Sequence[str]:
        """Databases visible to the configured credentials, excluding the
        source's own built-in system catalogs."""
        ...

    def list_columns(self, table: str) -> tuple[ColumnSpec, ...]:
        """Typed column metadata for `table`, in catalog-declared order."""
        ...

    def table_spec(self, table: str) -> TableSpec: ...

    def sample_rows(self, table: str, *, limit: int = 5) -> pa.Table:
        """Up to `limit` arbitrary rows of `table`, every column — for a
        human to eyeball, not a statistically meaningful sample."""
        ...

    def sample_values(self, table: str, column: str, *, limit: int = 5) -> Sequence[object]:
        """Up to `limit` distinct, non-null values of one column. Pushed
        down as `LIMIT` at the source rather than fetched via
        `sample_rows` + client-side dedup, so it stays fast on a
        multi-million-row table."""
        ...


class CatalogSourceConnector(SourceConnector, CatalogConnector, Protocol):
    """A connector known to satisfy both `SourceConnector` and
    `CatalogConnector` — purely a typing convenience for callers (like
    normapi's catalog routes, M16) that already did an `isinstance`
    capability check and want the narrowed type back, so
    `.list_tables()` (from `SourceConnector`) and `.list_databases()`
    (from `CatalogConnector`) both type-check on the same object without
    a `cast`. Not itself used at runtime for isinstance checks — the two
    Protocols above stay separate for that (see this module's own
    docstring for why)."""


@runtime_checkable
class StreamingSourceConnector(Protocol):
    """Keyset-paginated, chunked reads — no `OFFSET`, so page N is exactly
    as fast as page 1 (verified in M14's live bench against `Person`,
    ~11.8M rows). This is what `normexec/stream.py` (M17) drives; unlike
    `SourceConnector.read_table`, a caller controls chunk boundaries and
    can resume from `after_key` after a crash."""

    def read_chunk(
        self,
        table: str,
        *,
        key_columns: Sequence[str],
        columns: Sequence[str] | None = None,
        after_key: tuple[object, ...] | None = None,
        limit: int = 100_000,
        since: object | None = None,
    ) -> pa.RecordBatch | None:
        """One page of up to `limit` rows ordered by `key_columns`,
        strictly greater than `after_key` (a tuple positionally matching
        `key_columns`, or `None` for the first page). Returns `None` once
        the table is exhausted — the caller's stop condition.

        `since`, when given, additionally restricts to rows whose
        `created_at` column (if the table has one) is greater than it —
        M20 wires this to a real incremental-run watermark. A table
        without a `created_at` column raises `ValueError` if `since` is
        passed, rather than silently ignoring the filter.

        Every returned batch carries a `source_row_key` column derived
        from the real `key_columns` values (never a positional index —
        see `packages/normapi/src/normapi/store.py`'s `row_ordinal` fix
        in this same milestone for why a positional key is unsafe to
        depend on downstream).
        """
        ...


class StreamingCatalogSourceConnector(
    SourceConnector, CatalogConnector, StreamingSourceConnector, Protocol
):
    """M18: a connector known to satisfy `SourceConnector`,
    `CatalogConnector`, AND `StreamingSourceConnector` — the same typing
    convenience as `CatalogSourceConnector` above, for M17's multi-column
    streaming worker, which needs `.close()` (from `SourceConnector`) on
    the same object it calls `.read_chunk()`/`.table_spec()` on. Not
    itself used for isinstance checks — the three Protocols stay separate
    for that (see this module's own docstring for why)."""

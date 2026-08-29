"""ClickHouseConnector — Source.txt §105.

ClickHouse is columnar and Arrow-friendly, so this connector uses
`clickhouse_connect`'s native Arrow export rather than row-by-row
materialization, which the other connectors need for interop with
non-Arrow-native drivers.

M14 (docs/plan/M13-M22-program-plan.md) adds catalog introspection
(`CatalogConnector`) and keyset-paginated chunked reads
(`StreamingSourceConnector`) — both Protocols from `normio.capabilities`,
kept separate from the base read-only `SourceConnector` contract.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import clickhouse_connect
import pyarrow as pa

from normio.catalog import ColumnSpec, TableSpec

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

# ClickHouse's own built-in catalogs — never real user data, always
# excluded from list_databases(). Deliberately does NOT also exclude
# "default": it is a real, if often-empty, user database from
# ClickHouse's own perspective, and hardcoding it out would silently
# hide a genuine database in a deployment that actually uses it.
_SYSTEM_DATABASES = frozenset({"system", "information_schema", "INFORMATION_SCHEMA"})

# ASCII unit separator — joins composite key column values into one
# source_row_key string. Chosen over "|" or ":" because it is vanishingly
# unlikely to appear in real column data (unlike those two, which show up
# in phone numbers, URLs, timestamps).
_KEY_SEPARATOR = "\x1f"


class ClickHouseConnector:
    def __init__(
        self,
        source_id: str,
        host: str,
        *,
        port: int = 8123,
        username: str,
        password: str,
        database: str,
    ) -> None:
        self.source_id = source_id
        self._client = clickhouse_connect.get_client(
            host=host, port=port, username=username, password=password, database=database
        )
        self._database = database
        # M22 finding, live-verified against the real ClickHouse behind
        # M22's own containerized deployment: `clickhouse_connect`'s
        # client is NOT safe for concurrent calls from multiple threads
        # ("Attempt to execute concurrent queries within the same
        # session") — a real, reproducible race the moment two catalog-
        # browsing requests against the same pooled connection (M16's
        # `SourceRegistry.get_by_connection`, reused across requests by
        # design) land on FastAPI's thread pool at the same time, e.g.
        # ExplorePage's parallel columns+samples queries. Same root cause
        # M18 already found and fixed for DuckDB — the fix here is the
        # same shape: serialize every real call into the client.
        self._lock = threading.Lock()
        # Phase 2 (2026-08-29 throughput program): `read_chunk` validates
        # its `table`/`columns` arguments against `list_tables()`/
        # `list_columns()` on EVERY chunk — up to 2 real `system.tables`/
        # `system.columns` round trips per chunk, for schema that cannot
        # change mid-run (a connector instance is per-run — M17's
        # streaming loop and M14's catalog browsing both construct a new
        # one per request/run, never share one across schema changes).
        # Cached here, invalidated never, for exactly that reason.
        self._table_names_cache: list[str] | None = None
        self._columns_cache: dict[str, tuple[ColumnSpec, ...]] = {}

    def list_tables(self) -> Sequence[str]:
        if self._table_names_cache is None:
            with self._lock:
                result = self._client.query(
                    "SELECT name FROM system.tables WHERE database = {db:String} ORDER BY name",
                    parameters={"db": self._database},
                )
            self._table_names_cache = [row[0] for row in result.result_rows]
        # A fresh list each call, matching the pre-cache contract — a
        # caller mutating its own copy must not corrupt the cache.
        return list(self._table_names_cache)

    def list_databases(self) -> Sequence[str]:
        with self._lock:
            result = self._client.query("SELECT name FROM system.databases ORDER BY name")
        return [row[0] for row in result.result_rows if row[0] not in _SYSTEM_DATABASES]

    def list_columns(self, table: str) -> tuple[ColumnSpec, ...]:
        """Typed column metadata, in catalog-declared order.
        `is_in_primary_key` is read directly from `system.columns` —
        NOT derived by parsing the table's sorting-key expression, which
        can be an arbitrary expression (e.g. `PersonContact`'s real
        sorting key is `personID, assumeNotNull(contactString)`, but
        `is_in_primary_key` still cleanly reports `personID` and
        `contactString` as the two key columns — verified live against
        the real origin2 database)."""
        if table not in self._columns_cache:
            with self._lock:
                result = self._client.query(
                    "SELECT name, type, is_in_primary_key FROM system.columns "
                    "WHERE database = %(db)s AND table = %(t)s ORDER BY position",
                    parameters={"db": self._database, "t": table},
                )
            self._columns_cache[table] = tuple(
                ColumnSpec(
                    name=name,
                    type=col_type,
                    nullable=col_type.startswith("Nullable("),
                    is_primary_key=bool(is_pk),
                )
                for name, col_type, is_pk in result.result_rows
            )
        return self._columns_cache[table]  # ColumnSpec is frozen — safe to share

    def _column_names(self, table: str) -> set[str]:
        return {c.name for c in self.list_columns(table)}

    def table_spec(self, table: str) -> TableSpec:
        with self._lock:
            result = self._client.query(
                "SELECT engine, total_rows FROM system.tables "
                "WHERE database = %(db)s AND name = %(t)s",
                parameters={"db": self._database, "t": table},
            )
        if not result.result_rows:
            msg = f"Unknown table: {table!r}"
            raise ValueError(msg)
        engine, total_rows = result.result_rows[0]
        return TableSpec(
            name=table,
            columns=self.list_columns(table),
            engine=engine,
            approx_rows=int(total_rows) if total_rows is not None else None,
        )

    def sample_rows(self, table: str, *, limit: int = 5) -> pa.Table:
        if table not in set(self.list_tables()):
            msg = f"Unknown table: {table!r}"
            raise ValueError(msg)
        with self._lock:
            return self._client.query_arrow(f"SELECT * FROM `{table}` LIMIT {int(limit)}")

    def sample_values(self, table: str, column: str, *, limit: int = 5) -> Sequence[object]:
        if column not in self._column_names(table):
            msg = f"Unknown column for table {table!r}: {column!r}"
            raise ValueError(msg)
        with self._lock:
            result = self._client.query(
                f"SELECT DISTINCT `{column}` FROM `{table}` WHERE `{column}` IS NOT NULL "
                f"LIMIT {int(limit)}"
            )
        return [row[0] for row in result.result_rows]

    def count_null(self, table: str, column: str) -> int:
        if column not in self._column_names(table):
            msg = f"Unknown column for table {table!r}: {column!r}"
            raise ValueError(msg)
        with self._lock:
            result = self._client.query(f"SELECT count(*) FROM `{table}` WHERE `{column}` IS NULL")
        count: int = result.result_rows[0][0]
        return count

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
        if not key_columns:
            msg = "read_chunk requires at least one key column"
            raise ValueError(msg)
        if table not in set(self.list_tables()):
            msg = f"Unknown table: {table!r}"
            raise ValueError(msg)
        known_columns = self._column_names(table)
        unknown_keys = set(key_columns) - known_columns
        if unknown_keys:
            msg = f"Unknown key columns for table {table!r}: {sorted(unknown_keys)}"
            raise ValueError(msg)

        if columns is not None:
            unknown = set(columns) - known_columns
            if unknown:
                msg = f"Unknown columns for table {table!r}: {sorted(unknown)}"
                raise ValueError(msg)
            select_columns = list(columns)
        else:
            select_columns = [c.name for c in self.list_columns(table)]

        # Key columns are always fetched, even if the caller's `columns`
        # didn't request them — source_row_key needs their real values,
        # and the extra columns are dropped from the result before
        # returning.
        fetch_columns = list(dict.fromkeys([*select_columns, *key_columns]))
        where_sql, parameters = _build_keyset_where(
            table=table,
            key_columns=key_columns,
            known_columns=known_columns,
            after_key=after_key,
            since=since,
        )

        column_list = ", ".join(f"`{c}`" for c in fetch_columns)
        order_by = ", ".join(f"`{c}`" for c in key_columns)
        query = f"SELECT {column_list} FROM `{table}`"
        if where_sql:
            query += f" WHERE {where_sql}"
        query += f" ORDER BY {order_by} LIMIT {int(limit)}"

        with self._lock:
            arrow_table = self._client.query_arrow(query, parameters=parameters or None)
        if arrow_table.num_rows == 0:
            return None

        batch = arrow_table.combine_chunks().to_batches(max_chunksize=arrow_table.num_rows)[0]
        keys = _row_keys(batch, fetch_columns, key_columns)
        batch = batch.append_column("source_row_key", keys)
        if fetch_columns != select_columns:
            batch = batch.select([*select_columns, "source_row_key"])
        return batch

    def read_table(
        self,
        table: str,
        *,
        columns: Sequence[str] | None = None,
        batch_size: int = 100_000,
    ) -> Iterator[pa.RecordBatch]:
        known_tables = set(self.list_tables())
        if table not in known_tables:
            msg = f"Unknown table: {table!r}"
            raise ValueError(msg)

        # Table AND column identifiers are both validated against
        # system.tables/system.columns above, never taken as raw
        # caller-controlled SQL — ClickHouse's driver has no parameterized
        # identifier support, so this validate-then-format is the
        # injection defense here (not a naive f-string query).
        known_columns = self._column_names(table)
        if columns is not None:
            unknown = set(columns) - known_columns
            if unknown:
                msg = f"Unknown columns for table {table!r}: {sorted(unknown)}"
                raise ValueError(msg)
            select_columns = list(columns)
        else:
            select_columns = [c.name for c in self.list_columns(table)]

        key_columns = self.table_spec(table).primary_key
        # A table with no declared primary key has no stable identity to
        # key by — fall back to a positional key, same limitation the
        # previous implementation always had, now explicit rather than
        # silently assumed for every table.
        use_positional_key = not key_columns
        fetch_columns = (
            select_columns
            if use_positional_key
            else list(dict.fromkeys([*select_columns, *key_columns]))
        )
        column_list = ", ".join(f"`{c}`" for c in fetch_columns)
        query = f"SELECT {column_list} FROM `{table}`"

        row_offset = 0
        with self._lock, self._client.query_arrow_stream(query) as stream:
            for block in stream:
                # `query_arrow_stream` yields one RecordBatch per network
                # block from ClickHouse (size determined by the server,
                # not by `batch_size`) — re-split via a single-batch Table
                # so an unusually large or small `batch_size` is still
                # honored rather than silently ignored.
                sub_batches = pa.Table.from_batches([block]).to_batches(max_chunksize=batch_size)
                for batch in sub_batches:
                    if use_positional_key:
                        keys = pa.array(
                            [f"{table}:{row_offset + i}" for i in range(batch.num_rows)],
                            type=pa.large_string(),
                        )
                        out_batch = batch.append_column("source_row_key", keys)
                    else:
                        keys = _row_keys(batch, fetch_columns, key_columns)
                        out_batch = batch.append_column("source_row_key", keys)
                        if fetch_columns != select_columns:
                            out_batch = out_batch.select([*select_columns, "source_row_key"])
                    yield out_batch
                    row_offset += batch.num_rows

    def close(self) -> None:
        self._client.close()


def _build_keyset_where(
    *,
    table: str,
    key_columns: Sequence[str],
    known_columns: set[str],
    after_key: tuple[object, ...] | None,
    since: object | None,
) -> tuple[str, dict[str, object]]:
    """Builds `read_chunk`'s WHERE clause + bind parameters: the tuple
    comparison for keyset pagination, plus the optional `created_at`
    watermark filter. Split out from `read_chunk` itself only to keep
    that method's branch count under ruff's PLR0912 threshold."""
    clauses: list[str] = []
    parameters: dict[str, object] = {}
    if after_key is not None:
        if len(after_key) != len(key_columns):
            msg = "after_key must have exactly one value per key_columns entry"
            raise ValueError(msg)
        key_tuple = ", ".join(f"`{c}`" for c in key_columns)
        param_names = [f"after_{i}" for i in range(len(after_key))]
        param_tuple = ", ".join(f"%({name})s" for name in param_names)
        parameters.update(zip(param_names, after_key, strict=True))
        clauses.append(f"({key_tuple}) > ({param_tuple})")
    if since is not None:
        if "created_at" not in known_columns:
            msg = f"Table {table!r} has no created_at column to filter by `since`"
            raise ValueError(msg)
        clauses.append("`created_at` > %(since)s")
        parameters["since"] = since
    return " AND ".join(clauses), parameters


def _row_keys(
    batch: pa.RecordBatch, fetch_columns: list[str], key_columns: Sequence[str]
) -> pa.Array:
    key_indices = [fetch_columns.index(c) for c in key_columns]
    key_columns_data = [batch.column(i) for i in key_indices]
    return pa.array(
        [
            _KEY_SEPARATOR.join(str(col[i].as_py()) for col in key_columns_data)
            for i in range(batch.num_rows)
        ],
        type=pa.large_string(),
    )

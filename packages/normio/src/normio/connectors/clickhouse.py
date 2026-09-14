"""ClickHouseConnector — Source.txt §105.

ClickHouse is columnar and Arrow-friendly, so this connector uses
`clickhouse_connect`'s native Arrow export rather than row-by-row
materialization, which the other connectors need for interop with
non-Arrow-native drivers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import clickhouse_connect
import pyarrow as pa

from normio.connector import ColumnInfo

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence


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

    def list_tables(self) -> Sequence[str]:
        result = self._client.query(
            "SELECT name FROM system.tables WHERE database = {db:String} ORDER BY name",
            parameters={"db": self._database},
        )
        return [row[0] for row in result.result_rows]

    def list_databases(self) -> Sequence[str]:
        """Server-level database discovery (decision #1) — same shape as
        `list_tables` above."""
        result = self._client.query("SELECT name FROM system.databases ORDER BY name")
        return [row[0] for row in result.result_rows]

    def get_columns(self, table: str) -> Sequence[ColumnInfo]:
        """Public name+native-type listing for the clone-job DDL/type
        passthrough path. `_list_columns` (just below) stays as-is —
        `read_table` only needs the name set, not the types."""
        result = self._client.query(
            "SELECT name, type FROM system.columns WHERE database = {db:String} AND table = {t:String} ORDER BY position",
            parameters={"db": self._database, "t": table},
        )
        return [ColumnInfo(name=row[0], native_type=row[1]) for row in result.result_rows]

    def get_table_engine_info(self, table: str) -> tuple[str, Sequence[str]]:
        """(engine, order_by_columns) for clone-job DDL replication
        (decision #11) — `system.tables.sorting_key` is the ORDER BY
        expression ClickHouse itself reports back as a comma-separated
        column list for the common case (plain column names, no
        expressions)."""
        result = self._client.query(
            "SELECT engine, sorting_key FROM system.tables "
            "WHERE database = {db:String} AND name = {t:String}",
            parameters={"db": self._database, "t": table},
        )
        engine, sorting_key = result.result_rows[0]
        order_by = [c.strip() for c in sorting_key.split(",") if c.strip()]
        return engine, order_by

    def _list_columns(self, table: str) -> set[str]:
        result = self._client.query(
            "SELECT name FROM system.columns WHERE database = {db:String} AND table = {t:String}",
            parameters={"db": self._database, "t": table},
        )
        return {row[0] for row in result.result_rows}

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
        if columns is not None:
            known_columns = self._list_columns(table)
            unknown = set(columns) - known_columns
            if unknown:
                msg = f"Unknown columns for table {table!r}: {sorted(unknown)}"
                raise ValueError(msg)
            column_list = ", ".join(f"`{c}`" for c in columns)
        else:
            column_list = "*"
        query = f"SELECT {column_list} FROM `{table}`"

        arrow_table = self._client.query_arrow(query)
        row_offset = 0
        for batch in arrow_table.to_batches(max_chunksize=batch_size):
            keys = pa.array(
                [f"{table}:{row_offset + i}" for i in range(batch.num_rows)],
                type=pa.large_string(),
            )
            yield batch.append_column("source_row_key", keys)
            row_offset += batch.num_rows

    def close(self) -> None:
        self._client.close()

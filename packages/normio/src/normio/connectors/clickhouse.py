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
            host=host,
            port=port,
            username=username,
            password=password,
            database=database,
            # No session. The driver opens one by default, and a session
            # SERIALIZES every query on the client: a streaming read that is
            # not consumed to the end leaves it locked, and the next query
            # on the same connector dies with SESSION_IS_LOCKED.
            #
            # `_sample_column_values` reads one batch of each table and
            # returns, which is exactly that shape. It went unnoticed for as
            # long as it did because a small table arrives as a single block
            # the driver has already finished sending — every test, fixture
            # and probe here. On the first real source (1.27M rows, many
            # parts) the stream is genuinely mid-flight, and autodetect died
            # on the second table.
            #
            # Closing the generator does NOT release it; only not having a
            # session does. Nothing in this connector needs one — sessions
            # exist for temporary tables and session-scoped settings, and a
            # read-only connector uses neither.
            autogenerate_session_id=False,
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
            "SELECT name, type FROM system.columns "
            "WHERE database = {db:String} AND table = {t:String} ORDER BY position",
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
        # ORDER BY the table's own sorting key, ALWAYS. ClickHouse gives no
        # row-order guarantee for an unordered SELECT, and it genuinely
        # varies: the same `SELECT companyID FROM Company LIMIT 5 OFFSET
        # 300000` returned two completely disjoint row sets on consecutive
        # runs against a real 1.27M-row table (parts are read in parallel,
        # so arrival order follows whichever part finishes first).
        #
        # That is a correctness bug, not a cosmetic one, because
        # `source_row_key` below is assigned by ARRIVAL POSITION and the
        # clone executor's resume (decision #10) skips every row whose
        # offset is <= the last checkpoint. With an unstable order, a
        # resumed ClickHouse job skips an arbitrary set of rows and
        # reprocesses a different arbitrary set — silently producing a
        # clone with both duplicates and holes. The existing integration
        # test misses this because its table is small enough to be one
        # part read by one thread, which happens to be stable.
        #
        # Free in practice: EXPLAIN reports `Read type: InOrder` with a
        # prefix sort description, i.e. ClickHouse streams the already-
        # sorted parts and merges them rather than sorting anything, so
        # there is no full-sort memory spike.
        #
        # The key comes from `get_table_engine_info`, the same source and
        # the same comma-split that Phase 1 already uses to CREATE the
        # destination table's ORDER BY — if that DDL was valid, this is.
        _, order_by = self.get_table_engine_info(table)
        order_clause = " ORDER BY " + ", ".join(f"`{c}`" for c in order_by) if order_by else ""
        query = f"SELECT {column_list} FROM `{table}`{order_clause}"

        # query_arrow() (what this used to call) materializes the ENTIRE
        # result set as one in-memory Arrow table before yielding the first
        # batch — the `batch_size` below then only sliced an
        # already-fully-resident table, and the generator frame held it
        # alive for the whole iteration. Measured at 962 MiB for a single
        # 1.27M-row table, on top of everything else in a 4g container.
        # query_arrow_stream() yields one block per ClickHouse block
        # (max_block_size, ~65k rows), so peak is one block, not one table.
        # Measured A/B, same 1.27M-row table, same 200k rows consumed, same
        # 4g container: 1,595 MB peak RSS via query_arrow() vs. 318 MB via
        # the stream (81 MB interpreter baseline in both). The old peak was
        # also independent of how many rows the caller actually consumed —
        # the whole table was paid for before the first batch came out.
        #
        # Blocks are re-sliced to `batch_size` here rather than consumed
        # whole, so this still honors the caller's chunk size (which is
        # also the clone executor's checkpoint-commit boundary). `.slice()`
        # is zero-copy. It is used instead of `.to_batches(max_chunksize=)`
        # because the driver's docstring claims this yields pa.Table but it
        # actually yields pa.RecordBatch, which has no `.to_batches` —
        # found by running it, not by reading the docs. Slicing works
        # identically on both types, so this needs no isinstance branch and
        # survives the driver settling on either one.
        with self._client.query_arrow_stream(query) as stream:
            row_offset = 0
            for block in stream:
                for start in range(0, block.num_rows, batch_size):
                    batch = block.slice(start, batch_size)
                    keys = pa.array(
                        [f"{table}:{row_offset + i}" for i in range(batch.num_rows)],
                        type=pa.large_string(),
                    )
                    yield batch.append_column("source_row_key", keys)
                    row_offset += batch.num_rows

    def close(self) -> None:
        self._client.close()

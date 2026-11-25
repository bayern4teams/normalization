"""ClickHouseConnector — Source.txt §105.

ClickHouse is columnar and Arrow-friendly, so this connector uses
`clickhouse_connect`'s native Arrow export rather than row-by-row
materialization, which the other connectors need for interop with
non-Arrow-native drivers.
"""

from __future__ import annotations

import errno
import os
import queue
import re
import shutil
import tempfile
import threading
from typing import TYPE_CHECKING, Any, NamedTuple

import clickhouse_connect
import pyarrow as pa

from normio.connector import ColumnInfo
from normio.connectors.clickhouse_destination import quote_identifier
from normio.connectors.sort_keys import split_sorting_key

# A name in `system.tables.sorting_key`, which ClickHouse formats with a
# name backquoted (and escaped) only when it needs it: `a.b`, `b\`t`, id.
_KEY_NAME = re.compile(r"`((?:[^`\\]|\\.)*)`|([A-Za-z_][A-Za-z0-9_]*)")
_KEY_STRING_LITERAL = re.compile(r"'(?:[^'\\]|\\.)*'")

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence


class SortKey(NamedTuple):
    """A table's sort key as `system.tables` reports it."""

    engine: str
    # Each top-level element as SQL: a name quoted, an expression verbatim.
    sql: list[str]
    # Every column the key reads, in key order.
    columns: list[str]


def _key_name(match: re.Match[str]) -> str:
    quoted, bare = match.groups()
    return re.sub(r"\\(.)", r"\1", quoted) if quoted is not None else bare


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
        hostaddr: str | None = None,
    ) -> None:
        self.source_id = source_id
        self._client = clickhouse_connect.get_client(
            # ADR-022: connect to the checked address, keep the name for the TLS check.
            host=hostaddr or host,
            server_host_name=host if hostaddr else None,
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
        """(engine, key_columns) for clone-job DDL replication (decision #11)."""
        key = self.get_sort_key(table)
        return key.engine, key.columns

    def get_sort_key(self, table: str) -> SortKey:
        """The sort key from `system.tables.sorting_key`. An expression's
        columns come from scanning its text against the table's columns, so
        a function name is not mistaken for one.

        ponytail: `sorting_key` drops DESC (experimental reverse keys), so a
        descending key is copied ascending; only the physical order differs,
        the key columns and dedupe do not (owner, 2026-11-09: "Keep ascending").
        To keep DESC, read `create_table_query`."""
        result = self._client.query(
            "SELECT engine, sorting_key FROM system.tables "
            "WHERE database = {db:String} AND name = {t:String}",
            parameters={"db": self._database, "t": table},
        )
        engine, sorting_key = result.result_rows[0]
        sql: list[str] = []
        columns: list[str] = []
        table_columns: set[str] | None = None
        for part in split_sorting_key(sorting_key):
            name = _KEY_NAME.fullmatch(part)
            if name:
                columns.append(_key_name(name))
                sql.append(quote_identifier(columns[-1]))
                continue
            sql.append(part)
            if table_columns is None:
                table_columns = self._list_columns(table)
            found = [_key_name(m) for m in _KEY_NAME.finditer(_KEY_STRING_LITERAL.sub("", part))]
            columns += [c for c in found if c in table_columns]
        return SortKey(engine, sql, list(dict.fromkeys(columns)))

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
            column_list = ", ".join(map(quote_identifier, columns))
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
        # the same sorting-key parse that Phase 1 already uses to CREATE the
        # destination table's ORDER BY — if that DDL was valid, this is.
        order_by = self.get_sort_key(table).sql
        order_clause = " ORDER BY " + ", ".join(order_by) if order_by else ""
        query = f"SELECT {column_list} FROM {quote_identifier(table)}{order_clause}"

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
        yield from _spooled(lambda: self._client.query_arrow_stream(query), table, batch_size)

    def check_spool_space(self, tables: Sequence[str]) -> None:
        """Refuse up front when the read spool may not fit on disk.

        `read_table` spools one table at a time under $TMPDIR, at most all
        of it when the consumer is slow. The estimate is the largest table's
        compressed size on the server (`system.tables.total_bytes`): the
        zstd spool measured 0.71-0.98 of it on OnTime, NYC taxi and TPC-H
        lineitem/orders. A table the server reports no size for counts 0.
        """
        if not tables:
            return
        sizes = dict(
            self._client.query(
                "SELECT name, ifNull(total_bytes, 0) FROM system.tables "
                "WHERE database = {db:String} AND name IN {tables:Array(String)}",
                parameters={"db": self._database, "tables": list(tables)},
            ).result_rows
        )
        table, need = max(sizes.items(), key=lambda kv: kv[1], default=("", 0))
        spool_dir = tempfile.gettempdir()
        free = shutil.disk_usage(spool_dir).free
        if need > free:
            msg = (
                f"Not enough disk for the ClickHouse read spool: table {table!r} may need "
                f"{need:,} bytes under {spool_dir}, which has {free:,} free. Free space "
                f"there, or set TMPDIR to a directory with room and restart the service."
            )
            raise OSError(errno.ENOSPC, msg)

    def close(self) -> None:
        self._client.close()


_SPOOL_OPTIONS = pa.ipc.IpcWriteOptions(compression="zstd")


def _spooled(
    open_stream: Callable[[], Any], table: str, batch_size: int
) -> Iterator[pa.RecordBatch]:
    """The server stream, drained on a background thread into compressed
    Arrow files on local disk, and yielded from there.

    Reading the HTTP stream lazily meant not reading it at all while the
    caller normalized a chunk. ClickHouse gives up on a client that stops
    reading for `http_send_timeout` (30 s by default, a server setting a
    read-only user cannot change): OnTime died twice that way, after
    155,648 and 296,478 of 1,598,468 rows, with SOCKET_TIMEOUT on the
    server and an IncompleteRead on the client minutes later. Draining here
    means the server is never waiting on normalization; memory stays at a
    block, and each file is deleted as soon as it has been read back. The
    one SELECT also keeps its snapshot of the table, which paging with
    LIMIT/OFFSET would not.

    ponytail: disk holds whatever is drained but not yet consumed, at most
    the whole table compressed, under $TMPDIR. Add a byte cap that pauses
    the drain (well inside the server timeout) if a disk ever fills.
    """
    ready: queue.Queue[str | BaseException | None] = queue.Queue()
    stop = threading.Event()
    with tempfile.TemporaryDirectory(prefix="norm-ch-spool-") as spool:

        def drain() -> None:
            try:
                with open_stream() as stream:
                    for n, block in enumerate(stream):
                        if stop.is_set():
                            return
                        path = os.path.join(spool, f"{n}.arrow")
                        with (
                            pa.OSFile(path, "wb") as sink,
                            pa.ipc.new_file(sink, block.schema, options=_SPOOL_OPTIONS) as out,
                        ):
                            out.write(block)
                        ready.put(path)
                ready.put(None)
            except BaseException as exc:  # re-raised in the reader
                ready.put(exc)

        drainer = threading.Thread(target=drain, name=f"ch-spool:{table}", daemon=True)
        drainer.start()
        try:
            row_offset = 0
            while (item := ready.get()) is not None:
                if isinstance(item, BaseException):
                    raise item
                with pa.OSFile(item) as source:
                    block = pa.ipc.open_file(source).read_all().combine_chunks()
                os.remove(item)
                block = _invalid_text_as_binary(block)
                # Re-sliced to `batch_size` (the executor's checkpoint
                # boundary); `.slice()` is zero-copy.
                for batch in block.to_batches():
                    for start in range(0, batch.num_rows, batch_size):
                        part = batch.slice(start, batch_size)
                        keys = pa.array(
                            [f"{table}:{row_offset + i}" for i in range(part.num_rows)],
                            type=pa.large_string(),
                        )
                        yield part.append_column("source_row_key", keys)
                        row_offset += part.num_rows
        finally:
            stop.set()
            drainer.join()


def _invalid_text_as_binary(block: pa.Table) -> pa.Table:
    """A ClickHouse String is bytes; it arrives typed as Arrow `string`,
    which promises UTF-8, and one value that is not (`ED A0 80`) made
    `to_pylist()` raise and failed the whole job. Such a column is handed
    over as binary for this block instead: every value arrives as the
    source bytes, nothing is replaced or dropped, and the executor decides
    what bytes mean for a normalized column."""
    for i, field in enumerate(block.schema):
        if not (pa.types.is_string(field.type) or pa.types.is_large_string(field.type)):
            continue
        try:
            block.column(i).validate(full=True)
        except pa.ArrowInvalid:
            binary = pa.large_binary() if pa.types.is_large_string(field.type) else pa.binary()
            column = pa.chunked_array(
                [chunk.view(binary) for chunk in block.column(i).chunks], type=binary
            )
            block = block.set_column(i, field.with_type(binary), column)
    return block

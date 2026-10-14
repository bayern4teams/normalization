"""ClickHouseDestination — write-capable ClickHouse connector for the
DB-clone-and-normalize feature. Deliberately a separate class from the
read-only `ClickHouseConnector` — same rationale as `PostgresDestination`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import clickhouse_connect

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from normio.connector import ColumnInfo

# FieldSemanticType -> ClickHouse column type when the column is NOT typed
# natively: String, for the same reason as
# postgres_destination.SEMANTIC_TYPE_TO_PG_TYPE. NUMERIC, MONEY and BOOLEAN
# are typed natively via `normio.storage_types` (`column_overrides`), behind
# the `storage_types.coerce` pre-insert cast; DATE/DATETIME stay String
# (partial EDTF dates, ADR-020).
SEMANTIC_TYPE_TO_CH_TYPE: dict[str, str] = dict.fromkeys(
    (
        "PERSON_NAME",
        "GIVEN_NAME",
        "FAMILY_NAME",
        "COMPANY_NAME",
        "EMAIL",
        "PHONE",
        "ADDRESS",
        "POSTCODE",
        "COUNTRY",
        "LANGUAGE",
        "SCRIPT",
        "DATE",
        "DATETIME",
        "IDENTIFIER",
        "UUID",
        "TAX_ID",
        "URL",
        "NUMERIC",
        "CURRENCY",
        "QUANTITY",
        "MONEY",
        "BOOLEAN",
        "FREE_TEXT",
        "CODE",
        "UNKNOWN",
    ),
    "String",
)

PASSTHROUGH_CH_TYPE = "String"


def quote_identifier(name: str) -> str:
    """A ClickHouse identifier, backquoted with `\\` and `` ` `` escaped.
    Names come from source metadata and can hold anything; an unescaped
    backtick broke the DDL (and was an injection path)."""
    return "`" + name.replace("\\", "\\\\").replace("`", "\\`") + "`"


# Every column is wrapped in Nullable(...) at create_table time
# (including ORDER BY columns) since origin values can be null anywhere —
# ClickHouse recommends avoiding Nullable in ORDER BY for performance;
# correctness for a clone target comes first here.


class ClickHouseDestination:
    """Write-capable, server-level (no `database` at construction). Unlike
    `ClickHouseConnector`, no readonly profile is requested."""

    def __init__(self, host: str, port: int, username: str, password: str) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._clients: dict[str, Any] = {}

    def _client_for(self, database: str) -> Any:
        client = self._clients.get(database)
        if client is None:
            client = clickhouse_connect.get_client(
                host=self._host,
                port=self._port,
                username=self._username,
                password=self._password,
                database=database,
            )
            self._clients[database] = client
        return client

    def database_exists(self, database: str) -> bool:
        """Decision #6 — the app never issues CREATE DATABASE; this is the
        verification step after the user runs it by hand."""
        result = self._client_for("default").query(
            "SELECT 1 FROM system.databases WHERE name = {db:String}", parameters={"db": database}
        )
        return len(result.result_rows) > 0

    def create_table(
        self,
        database: str,
        table: str,
        columns: Sequence[ColumnInfo],
        *,
        order_by: Sequence[str] = (),
        engine: str = "MergeTree",
        semantic_types: Mapping[str, str] | None = None,
        column_overrides: Mapping[str, str] | None = None,
        extra_columns: Mapping[str, str] | None = None,
    ) -> None:
        """Empty-table DDL only (Phase 1, decision #5), replicating the
        origin's ORDER BY/table engine (decision #11). `semantic_types`
        maps column name -> FieldSemanticType for configured (normalized)
        columns, replaced in place (decision #7). Passthrough
        (unconfigured) columns keep the origin's own native type string
        as-is (only re-wrapped in Nullable if it isn't already) — valid
        DDL here because source and destination are always the same
        engine (scope decision at the top of the plan). ORDER BY columns
        are NEVER wrapped in Nullable regardless — ClickHouse hard-rejects
        a nullable sorting key unless `allow_nullable_key` is set (found
        by actually running this DDL against real ClickHouse, not by
        reasoning about the type system)."""
        semantic_types = semantic_types or {}
        column_overrides = column_overrides or {}
        order_by_set = set(order_by)
        defs = [
            quote_identifier(col.name)
            + " "
            + self._column_type(
                col,
                semantic_types,
                column_overrides,
                nullable=col.name not in order_by_set,
            )
            for col in columns
        ]
        # Companion columns (a MONEY column's currency) are never part of
        # the replicated sorting key, so they are always nullable.
        defs += [
            f"{quote_identifier(name)} Nullable({t})" for name, t in (extra_columns or {}).items()
        ]
        column_defs = ", ".join(defs)
        order_clause = ", ".join(map(quote_identifier, order_by)) if order_by else "tuple()"
        ddl = (
            f"CREATE TABLE {quote_identifier(database)}.{quote_identifier(table)} ({column_defs}) "
            f"ENGINE = {engine} ORDER BY ({order_clause})"
        )
        if "MergeTree" in engine:
            # vertical_merge_algorithm_min_rows_to_activate = 0: every merge of
            # a wide table (>= vertical_merge_algorithm_min_columns_to_activate
            # columns) runs one column at a time. By default a merge of small
            # parts runs horizontally, holding every column's buffers for
            # every part at once: measured on 262 OnTime parts of 2,000 rows
            # (110 columns), 44 horizontal merges peaked at 562 MiB each (497
            # average), the same parts merged vertically at 14 MiB. That is
            # what took a 4 GB server to its cap after four hours. Bigger
            # inserts were not the fix: one 131,072-row INSERT used 611 MiB.
            #
            # non_replicated_deduplication_window = 1 remembers the last
            # block's dedup token, so a resume that replays it is dropped
            # (`bulk_insert`). One: a job has one block in flight per table,
            # and the DDL has no PARTITION BY, so one INSERT is one block.
            ddl += (
                " SETTINGS vertical_merge_algorithm_min_rows_to_activate = 0,"
                " non_replicated_deduplication_window = 1"
            )
        self._client_for(database).command(ddl)

    @staticmethod
    def _column_type(
        col: ColumnInfo,
        semantic_types: Mapping[str, str],
        column_overrides: Mapping[str, str],
        *,
        nullable: bool,
    ) -> str:
        semantic_type = semantic_types.get(col.name)
        base = (
            column_overrides.get(col.name)
            or (SEMANTIC_TYPE_TO_CH_TYPE.get(semantic_type, PASSTHROUGH_CH_TYPE))
            if semantic_type
            else col.native_type
        )
        if not nullable:
            # Strip an existing Nullable() wrapper too — an ORDER BY
            # column's origin type must never be forced/kept nullable.
            return base[len("Nullable(") : -1] if base.startswith("Nullable(") else base
        return base if base.startswith("Nullable(") else f"Nullable({base})"

    def bulk_insert(
        self,
        database: str,
        table: str,
        rows: Sequence[Mapping[str, object]],
        *,
        primary_key: Sequence[str] = (),
        dedup_token: str | None = None,
    ) -> None:
        """One INSERT, so one part: the caller sizes the block and
        checkpoints after it. `dedup_token` makes
        a resumed job's replay of a block that had already committed a
        no-op (ClickHouse has no ON CONFLICT); see `create_table`."""
        if not rows:
            return
        columns = list(rows[0].keys())
        client = self._client_for(database)
        # Pre-quoted: the driver leaves a table name containing `.` unquoted
        # and ignores `database` for it. Column names it quotes itself.
        # ponytail: the driver takes a name that starts and ends with a
        # quote character as already quoted (a column literally named `"x"`);
        # pass column_type_names with pre-quoted names if one turns up.
        full_table = f"{quote_identifier(database)}.{quote_identifier(table)}"
        data = [[row[c] for c in columns] for row in rows]
        settings = {"insert_deduplication_token": dedup_token} if dedup_token else None
        client.insert(full_table, data, column_names=columns, settings=settings)

    def swap_table(self, database: str, table: str, staging: str) -> None:
        """Replace `table` with `staging`, then drop the original.

        `EXCHANGE TABLES` is atomic in ClickHouse (Atomic database engine,
        the default), so there is no window where the table is missing.
        Used for in-place normalization: peak extra storage is the largest
        SINGLE table, not a second copy of the whole database.

        `ALTER TABLE ... UPDATE` was the obvious alternative and is the
        wrong tool — a mutation rewrites whole parts asynchronously, so it
        costs the same storage anyway and gives no point at which the
        table is known to be done.
        """
        client = self._client_for(database)
        db = quote_identifier(database)
        client.command(
            f"EXCHANGE TABLES {db}.{quote_identifier(table)} AND {db}.{quote_identifier(staging)}"
        )
        client.command(f"DROP TABLE {db}.{quote_identifier(staging)}")

    def drop_table(self, database: str, table: str) -> None:
        self._client_for(database).command(
            f"DROP TABLE IF EXISTS {quote_identifier(database)}.{quote_identifier(table)}"
        )

    def close(self) -> None:
        for client in self._clients.values():
            client.close()

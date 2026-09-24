"""ClickHouseDestination — write-capable ClickHouse connector for the
DB-clone-and-normalize feature. Deliberately a separate class from the
read-only `ClickHouseConnector` — same rationale as `PostgresDestination`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import clickhouse_connect

from normio.connectors._sql_base import ROW_CHUNK_SIZE

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from normio.connector import ColumnInfo

# FieldSemanticType -> ClickHouse column type. Every value is String —
# deliberately, not an oversight; same reasoning as
# postgres_destination.SEMANTIC_TYPE_TO_PG_TYPE (found via a real e2e run
# against messy real-world data): decision #8 requires a failed value's
# ORIGINAL raw string to always land in the cell, and a column typed e.g.
# Date/Float64/UUID/Bool rejects a raw string that isn't already
# well-formed for that type — exactly the malformed values decision #8
# exists to handle. There is no per-row column typing in SQL — the type
# is fixed at CREATE TABLE time, before any row's success/failure is
# known — so only a text-compatible type can always hold both a
# successful `display` and a failed fallback.
# ponytail: every value collapsed to String for decision #8 safety, not
# genuinely typed Date/Float64/etc — revisit only if the executor gains
# real pre-insert type validation/casting (route a value that won't cast
# through the same error-report path as a normalization failure, instead
# of relying on the DB to reject it) that could safely re-differentiate
# per type.
SEMANTIC_TYPE_TO_CH_TYPE: dict[str, str] = dict.fromkeys(
    (
        "PERSON_NAME", "GIVEN_NAME", "FAMILY_NAME", "COMPANY_NAME", "EMAIL", "PHONE",
        "ADDRESS", "POSTCODE", "COUNTRY", "LANGUAGE", "SCRIPT", "DATE", "DATETIME",
        "IDENTIFIER", "UUID", "TAX_ID", "URL", "NUMERIC", "CURRENCY", "QUANTITY",
        "MONEY", "BOOLEAN", "FREE_TEXT", "CODE", "UNKNOWN",
    ),
    "String",
)

PASSTHROUGH_CH_TYPE = "String"
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
            f"`{col.name}` "
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
        defs += [f"`{name}` Nullable({t})" for name, t in (extra_columns or {}).items()]
        column_defs = ", ".join(defs)
        order_clause = ", ".join(f"`{c}`" for c in order_by) if order_by else "tuple()"
        ddl = f"CREATE TABLE `{database}`.`{table}` ({column_defs}) ENGINE = {engine} ORDER BY ({order_clause})"
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
        primary_key: Sequence[str] = (),  # noqa: ARG002 - unused; matches PostgresDestination's signature so callers need no isinstance branch
    ) -> None:
        """Chunked native batch insert via `clickhouse_connect` — same
        `ROW_CHUNK_SIZE` chunk-commit boundary as the Postgres destination,
        doubling as the checkpoint-commit boundary (decision #10).
        # ponytail: no insert-dedup guard on resume (ClickHouse has no
        # `ON CONFLICT`) — a crash inside the in-flight chunk could
        # double-insert on resume. Acceptable for now since the
        # checkpoint only advances on a chunk that has already committed;
        # add a dedup key (e.g. a ReplacingMergeTree on source_row_key) if
        # resumed jobs on ClickHouse become a real requirement.
        """
        if not rows:
            return
        columns = list(rows[0].keys())
        client = self._client_for(database)
        for start in range(0, len(rows), ROW_CHUNK_SIZE):
            chunk = rows[start : start + ROW_CHUNK_SIZE]
            data = [[row[c] for c in columns] for row in chunk]
            client.insert(table, data, column_names=columns, database=database)

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
        client.command(f"EXCHANGE TABLES `{database}`.`{table}` AND `{database}`.`{staging}`")
        client.command(f"DROP TABLE `{database}`.`{staging}`")

    def drop_table(self, database: str, table: str) -> None:
        self._client_for(database).command(f"DROP TABLE IF EXISTS `{database}`.`{table}`")

    def close(self) -> None:
        for client in self._clients.values():
            client.close()

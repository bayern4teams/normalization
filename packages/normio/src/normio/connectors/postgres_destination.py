"""PostgresDestination — write-capable Postgres connector for the
DB-clone-and-normalize feature. Deliberately a separate class from the
read-only `PostgresConnector` (see the plan's layering decisions: the
destination always needs a second, differently-credentialed connection
anyway, so sharing the class would be misleading, not lazy).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import psycopg
import sqlalchemy as sa
from psycopg.conninfo import make_conninfo

from normio.connectors._sql_base import DESTINATION_INSERT_CHUNK_ROWS

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from normio.connector import ColumnInfo


def _normalise_pg_type_name(sql_type: str) -> str:
    """A DDL type string (as `get_columns`/format_type report them, or as
    the semantic mapping emits them) in the same normalised shape
    information_schema.data_type reports it, so `create_table`'s expected
    mapping and a pre-existing table are compared in one space: length/
    precision suffixes dropped (`character varying(255)` -> `character
    varying`), arrays collapsed to `ARRAY` (data_type says `ARRAY` for
    every element type — coarse, and deliberately so: an element-type
    change is rare and a wrong `ARRAY` verdict only costs the user a
    clear mismatch message, never a silent wrong clone)."""
    t = sql_type.strip().lower()
    if t.endswith("[]"):
        return "ARRAY"
    t = re.sub(r"\s*\([^)]*\)", "", t)
    if t in ("varchar", "char"):  # aliases format_type can emit for domains
        return "character varying" if t == "varchar" else "character"
    return t

# FieldSemanticType -> Postgres column type when the column is NOT typed
# natively: TEXT, which can always hold both a normalized `display` and
# decision #8's ORIGINAL raw string for a failed value. Native types for
# NUMERIC, MONEY and BOOLEAN come from `normio.storage_types` (passed in as
# `column_overrides`, on by default via `typed_destination_columns`), and
# `storage_types.coerce` is the pre-insert cast that sends a value which
# will not fit to NULL plus an error row instead of to the INSERT.
# DATE/DATETIME stay TEXT on purpose: partial EDTF dates (ADR-020).
SEMANTIC_TYPE_TO_PG_TYPE: dict[str, str] = dict.fromkeys(
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
    "TEXT",
)

PASSTHROUGH_PG_TYPE = "TEXT"


def quote_identifier(name: str) -> str:
    """A Postgres identifier, quoted and escaped. Every table and column
    name here comes from SOURCE metadata, so it can hold anything: `.`,
    spaces, `-`, `%`, and `"` itself (which, unescaped, was also an
    injection path). Real Norway and GLEIF columns could not be cloned."""
    return '"' + name.replace('"', '""') + '"'


def build_postgres_dsn(
    host: str,
    port: int,
    username: str,
    password: str,
    database: str,
    *,
    hostaddr: str | None = None,
) -> str:
    """A libpq connection string. Built by libpq's own quoting, never an f-string:
    a password or name holding `@`, `/`, `,` or `?` cannot change the server or
    the options (ADR-022). `hostaddr` is the address already checked; libpq
    connects to it and keeps `host` as the name."""
    extra = {"hostaddr": hostaddr} if hostaddr else {}
    return make_conninfo(
        host=host, port=port, user=username, password=password, dbname=database, **extra
    )


def engine_from_dsn(dsn: str, **kwargs: Any) -> sa.Engine:
    """An engine for a libpq connection string (`build_postgres_dsn`) or a SQLAlchemy URL.
    SQLAlchemy cannot carry `hostaddr` in a URL, so for a connection string psycopg
    opens the connection. A `postgresql://` URL gets the psycopg3 driver explicitly,
    not SQLAlchemy's default (psycopg2, not a project dependency)."""
    if re.match(r"[A-Za-z][A-Za-z0-9+.-]*://", dsn):  # a libpq string starts with `host=`
        return sa.create_engine(dsn.replace("postgresql://", "postgresql+psycopg://", 1), **kwargs)
    return sa.create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(dsn), **kwargs)


class PostgresDestination:
    """Write-capable, server-level (no `database` at construction — mirrors
    the server-level saved-connection shape, decision #13). No
    `postgresql_readonly` execution option: this one writes."""

    def __init__(
        self, host: str, port: int, username: str, password: str, hostaddr: str | None = None
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._hostaddr = hostaddr
        # One connection per call site (database_exists queries the
        # always-present `postgres` catalog database) — cheap, and this
        # method is called once per job verification, not per row.
        self._admin_engine = engine_from_dsn(self._dsn("postgres"))
        self._db_engines: dict[str, sa.Engine] = {}

    def _dsn(self, database: str) -> str:
        return build_postgres_dsn(
            self._host,
            self._port,
            self._username,
            self._password,
            database,
            hostaddr=self._hostaddr,
        )

    def _engine_for(self, database: str) -> sa.Engine:
        engine = self._db_engines.get(database)
        if engine is None:
            engine = engine_from_dsn(self._dsn(database))
            self._db_engines[database] = engine
        return engine

    def database_exists(self, database: str) -> bool:
        """Decision #6 — the app never issues CREATE DATABASE; this is the
        verification step after the user runs it by hand."""
        with self._admin_engine.connect() as conn:
            row = conn.execute(
                sa.text("SELECT 1 FROM pg_database WHERE datname = :db"), {"db": database}
            ).first()
        return row is not None

    def table_columns(self, database: str, table: str) -> dict[str, str] | None:
        """The destination table's columns as name -> `data_type`, or None
        when the table does not exist. `data_type` is the normalised name
        (`text`, `jsonb`, `uuid`, `smallint`, `ARRAY`), which is exactly
        the space the expected-DDL mapping's scalar types live in."""
        with self._engine_for(database).connect() as conn:
            rows = conn.execute(
                sa.text(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_schema = current_schema() AND table_name = :t "
                    "ORDER BY ordinal_position"
                ),
                {"t": table},
            ).all()
        return {str(r[0]): str(r[1]) for r in rows} if rows else None

    def primary_key_columns(self, database: str, table: str) -> list[str]:
        with self._engine_for(database).connect() as conn:
            rows = conn.execute(
                sa.text(
                    "SELECT a.attname FROM pg_index i "
                    "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
                    "WHERE i.indrelid = CAST(:t AS regclass) AND i.indisprimary "
                    "ORDER BY array_position(i.indkey, a.attnum)"
                ),
                {"t": table},
            ).all()
        return [r[0] for r in rows]

    def expected_columns(
        self,
        columns: Sequence[ColumnInfo],
        *,
        semantic_types: Mapping[str, str],
        column_overrides: Mapping[str, str],
        extra_columns: Mapping[str, str],
    ) -> dict[str, str]:
        """The exact name -> type mapping `create_table` would issue, as
        normalised data_type names — the comparison half of reuse, so a
        table `create_table` would build and a table already there can
        never be judged by two different rules."""
        out: dict[str, str] = {}
        for col in columns:
            sql_type = (
                column_overrides.get(col.name)
                or SEMANTIC_TYPE_TO_PG_TYPE.get(semantic_types[col.name], PASSTHROUGH_PG_TYPE)
                if col.name in semantic_types
                else col.native_type
            )
            out[col.name] = _normalise_pg_type_name(sql_type)
        for name, sql_type in extra_columns.items():
            out[name] = _normalise_pg_type_name(sql_type)
        return out

    def create_table(
        self,
        database: str,
        table: str,
        columns: Sequence[ColumnInfo],
        *,
        primary_key: Sequence[str] = (),
        semantic_types: Mapping[str, str] | None = None,
        column_overrides: Mapping[str, str] | None = None,
        extra_columns: Mapping[str, str] | None = None,
    ) -> None:
        """Empty-table DDL only (Phase 1, decision #5). `semantic_types`
        maps column name -> FieldSemanticType for configured (normalized)
        columns, replaced in place (decision #7). Passthrough
        (unconfigured) columns keep the origin's own native type string
        as-is — valid DDL here because source and destination are always
        the same engine (scope decision at the top of the plan)."""
        semantic_types = semantic_types or {}
        # `column_overrides` carries a native (non-TEXT) type for a column
        # the executor has decided to type properly — see
        # normio.storage_types. It wins over the TEXT default, and is
        # empty when the job turned `typed_destination_columns` off.
        column_overrides = column_overrides or {}
        column_defs = [
            quote_identifier(col.name)
            + " "
            + (
                column_overrides.get(col.name)
                or SEMANTIC_TYPE_TO_PG_TYPE.get(semantic_types[col.name], PASSTHROUGH_PG_TYPE)
                if col.name in semantic_types
                else col.native_type
            )
            for col in columns
        ]
        # Companion columns the normalizer produces alongside a value it
        # would otherwise have to discard (a MONEY column's currency).
        extra = (extra_columns or {}).items()
        column_defs += [f"{quote_identifier(name)} {sql_type}" for name, sql_type in extra]
        if primary_key:
            pk_cols = ", ".join(map(quote_identifier, primary_key))
            column_defs.append(f"PRIMARY KEY ({pk_cols})")
        ddl = f"CREATE TABLE {quote_identifier(table)} ({', '.join(column_defs)})"
        with self._engine_for(database).begin() as conn:
            conn.execute(sa.text(ddl))

    def bulk_insert(
        self,
        database: str,
        table: str,
        rows: Sequence[Mapping[str, object]],
        *,
        primary_key: Sequence[str] = (),
    ) -> None:
        """Chunked insert — same chunk loop as `PgPersistence.save_execution`
        (`DESTINATION_INSERT_CHUNK_ROWS`, one transaction per chunk); chunk-commit
        boundaries double as checkpoint-commit boundaries for resumability
        (decision #10). `ON CONFLICT DO NOTHING` on the replicated primary
        key (decision #11) makes re-inserting an already-committed chunk on
        resume a no-op instead of a duplicate row.
        # ponytail: tables with no primary key get no such guard — a crash
        # after a chunk commits and before its checkpoint commits replays it
        # on resume, so those rows are written twice. Add a
        # synthetic dedup key (e.g. persisting source_row_key) if resumed
        # jobs on PK-less tables become a real requirement.
        """
        if not rows:
            return
        columns = list(rows[0].keys())
        col_list = ", ".join(map(quote_identifier, columns))
        # Positional bind names: a `:name` built from a column name breaks
        # on `.`, space, `-`, `:` or `%`.
        placeholders = ", ".join(f":c{i}" for i in range(len(columns)))
        conflict_clause = ""
        if primary_key:
            pk_cols = ", ".join(map(quote_identifier, primary_key))
            conflict_clause = f" ON CONFLICT ({pk_cols}) DO NOTHING"
        insert_sql = sa.text(
            f"INSERT INTO {quote_identifier(table)} ({col_list}) "
            f"VALUES ({placeholders}){conflict_clause}"
        )
        engine = self._engine_for(database)
        for start in range(0, len(rows), DESTINATION_INSERT_CHUNK_ROWS):
            chunk = rows[start : start + DESTINATION_INSERT_CHUNK_ROWS]
            params = [{f"c{i}": row[c] for i, c in enumerate(columns)} for row in chunk]
            with engine.begin() as conn:
                conn.execute(insert_sql, params)

    def close(self) -> None:
        self._admin_engine.dispose()
        for engine in self._db_engines.values():
            engine.dispose()

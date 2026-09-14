"""PostgresDestination — write-capable Postgres connector for the
DB-clone-and-normalize feature. Deliberately a separate class from the
read-only `PostgresConnector` (see the plan's layering decisions: the
destination always needs a second, differently-credentialed connection
anyway, so sharing the class would be misleading, not lazy).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from normio.connectors._sql_base import ROW_CHUNK_SIZE

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from normio.connector import ColumnInfo

# FieldSemanticType -> Postgres column type. 24 semantic types x 2 engines
# is a lookup table, not a reason to pull in a SQL-DDL-generation library.
# ponytail: plain dict + string-built DDL, not a schema library — revisit
# only if a 3rd engine's type rules stop fitting a dict.
SEMANTIC_TYPE_TO_PG_TYPE: dict[str, str] = {
    "PERSON_NAME": "TEXT",
    "GIVEN_NAME": "TEXT",
    "FAMILY_NAME": "TEXT",
    "COMPANY_NAME": "TEXT",
    "EMAIL": "TEXT",
    "PHONE": "TEXT",
    "ADDRESS": "TEXT",
    "POSTCODE": "TEXT",
    "COUNTRY": "TEXT",
    "LANGUAGE": "TEXT",
    "SCRIPT": "TEXT",
    "DATE": "DATE",
    "DATETIME": "TIMESTAMPTZ",
    "IDENTIFIER": "TEXT",
    "UUID": "UUID",
    "TAX_ID": "TEXT",
    "URL": "TEXT",
    "NUMERIC": "NUMERIC",
    "CURRENCY": "NUMERIC",
    "QUANTITY": "NUMERIC",
    "BOOLEAN": "BOOLEAN",
    "FREE_TEXT": "TEXT",
    "CODE": "TEXT",
    "UNKNOWN": "TEXT",
}

PASSTHROUGH_PG_TYPE = "TEXT"


class PostgresDestination:
    """Write-capable, server-level (no `database` at construction — mirrors
    the server-level saved-connection shape, decision #13). No
    `postgresql_readonly` execution option: this one writes."""

    def __init__(self, host: str, port: int, username: str, password: str) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        # One connection per call site (database_exists queries the
        # always-present `postgres` catalog database) — cheap, and this
        # method is called once per job verification, not per row.
        self._admin_engine = sa.create_engine(self._dsn("postgres"))
        self._db_engines: dict[str, sa.Engine] = {}

    def _dsn(self, database: str) -> str:
        return (
            f"postgresql+psycopg://{self._username}:{self._password}"
            f"@{self._host}:{self._port}/{database}"
        )

    def _engine_for(self, database: str) -> sa.Engine:
        engine = self._db_engines.get(database)
        if engine is None:
            engine = sa.create_engine(self._dsn(database))
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

    def create_table(
        self,
        database: str,
        table: str,
        columns: Sequence[ColumnInfo],
        *,
        primary_key: Sequence[str] = (),
        semantic_types: Mapping[str, str] | None = None,
    ) -> None:
        """Empty-table DDL only (Phase 1, decision #5). `semantic_types`
        maps column name -> FieldSemanticType for configured (normalized)
        columns, replaced in place (decision #7). Passthrough
        (unconfigured) columns keep the origin's own native type string
        as-is — valid DDL here because source and destination are always
        the same engine (scope decision at the top of the plan)."""
        semantic_types = semantic_types or {}
        column_defs = [
            f'"{col.name}" '
            + (
                SEMANTIC_TYPE_TO_PG_TYPE.get(semantic_types[col.name], PASSTHROUGH_PG_TYPE)
                if col.name in semantic_types
                else col.native_type
            )
            for col in columns
        ]
        if primary_key:
            pk_cols = ", ".join(f'"{c}"' for c in primary_key)
            column_defs.append(f"PRIMARY KEY ({pk_cols})")
        ddl = f'CREATE TABLE "{table}" ({", ".join(column_defs)})'
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
        (`ROW_CHUNK_SIZE`, one transaction per chunk); chunk-commit
        boundaries double as checkpoint-commit boundaries for resumability
        (decision #10). `ON CONFLICT DO NOTHING` on the replicated primary
        key (decision #11) makes re-inserting an already-committed chunk on
        resume a no-op instead of a duplicate row.
        # ponytail: tables with no primary key get no such guard — a crash
        # inside the in-flight chunk could double-insert on resume. Add a
        # synthetic dedup key (e.g. persisting source_row_key) if resumed
        # jobs on PK-less tables become a real requirement.
        """
        if not rows:
            return
        columns = list(rows[0].keys())
        col_list = ", ".join(f'"{c}"' for c in columns)
        placeholders = ", ".join(f":{c}" for c in columns)
        conflict_clause = ""
        if primary_key:
            pk_cols = ", ".join(f'"{c}"' for c in primary_key)
            conflict_clause = f" ON CONFLICT ({pk_cols}) DO NOTHING"
        insert_sql = sa.text(f'INSERT INTO "{table}" ({col_list}) VALUES ({placeholders}){conflict_clause}')
        engine = self._engine_for(database)
        for start in range(0, len(rows), ROW_CHUNK_SIZE):
            chunk = rows[start : start + ROW_CHUNK_SIZE]
            with engine.begin() as conn:
                conn.execute(insert_sql, list(chunk))

    def close(self) -> None:
        self._admin_engine.dispose()
        for engine in self._db_engines.values():
            engine.dispose()

"""PostgresDestination — write-capable Postgres connector for the
DB-clone-and-normalize feature. Deliberately a separate class from the
read-only `PostgresConnector` (see the plan's layering decisions: the
destination always needs a second, differently-credentialed connection
anyway, so sharing the class would be misleading, not lazy).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from normio.connectors._sql_base import DESTINATION_INSERT_CHUNK_ROWS

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from normio.connector import ColumnInfo

# FieldSemanticType -> Postgres column type. Every value is TEXT —
# deliberately, not an oversight. Found via a real e2e run against messy
# real-world data: decision #8 requires a failed value's ORIGINAL raw
# string to always land in the cell, and a column typed e.g. DATE/
# NUMERIC/UUID/BOOLEAN rejects any raw string that isn't already
# well-formed for that type at INSERT time — which happens for exactly
# the malformed values decision #8 exists to handle (e.g. a source
# "foundingdate" of "d1989-12-11" correctly flagged INVALID by
# DateNormalizer, correctly falls back to the original string, then
# can't be inserted into a native DATE column — taking the whole chunk's
# transaction, and therefore the whole job, down with it, since even the
# error-report row for that value never got a chance to be written).
# There is no per-row column typing in SQL — the type is fixed at CREATE
# TABLE time, before any row's success/failure is known — so the only
# type that can ALWAYS hold both a successful `display` and a failed
# fallback is a text-compatible one. 24 semantic types x 2 engines is a
# lookup table, not a reason to pull in a SQL-DDL-generation library.
# ponytail: every value collapsed to TEXT for decision #8 safety, not
# genuinely typed DATE/NUMERIC/etc — revisit only if the executor gains
# real pre-insert type validation/casting (route a value that won't cast
# through the same error-report path as a normalization failure, instead
# of relying on the DB to reject it) that could safely re-differentiate
# per type.
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
        # normio.storage_types. It wins over the all-TEXT default, and is
        # empty unless the job opted in.
        column_overrides = column_overrides or {}
        column_defs = [
            f'"{col.name}" '
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
        column_defs += [f'"{name}" {sql_type}' for name, sql_type in (extra_columns or {}).items()]
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
        (`DESTINATION_INSERT_CHUNK_ROWS`, one transaction per chunk); chunk-commit
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
        insert_sql = sa.text(
            f'INSERT INTO "{table}" ({col_list}) VALUES ({placeholders}){conflict_clause}'
        )
        engine = self._engine_for(database)
        for start in range(0, len(rows), DESTINATION_INSERT_CHUNK_ROWS):
            chunk = rows[start : start + DESTINATION_INSERT_CHUNK_ROWS]
            with engine.begin() as conn:
                conn.execute(insert_sql, list(chunk))

    def swap_table(self, database: str, table: str, staging: str) -> None:
        """Replace `table` with `staging`, then drop the original.

        For in-place normalization, where there is no second database to
        write into. Peak extra storage becomes the largest SINGLE table
        rather than a whole copy of the source, because the staging table
        is swapped in and the original dropped one table at a time.

        The two renames are one transaction, so a crash leaves either the
        original or the normalized table in place and never neither. The
        DROP is deliberately outside it: holding the original's storage
        until commit would defeat the point of the exercise.

        ponytail: index and constraint names still follow the ORIGINAL
        table (Postgres does not rename them with the table), so the
        swapped-in table carries names like "t__norm_pkey". Cosmetic, and
        renaming every constraint is a lot of DDL for a cosmetic win —
        revisit if something reads constraint names.
        """
        retired = f"{staging}_retired"
        with self._engine_for(database).begin() as conn:
            conn.execute(sa.text(f'ALTER TABLE "{table}" RENAME TO "{retired}"'))
            conn.execute(sa.text(f'ALTER TABLE "{staging}" RENAME TO "{table}"'))
        with self._engine_for(database).begin() as conn:
            conn.execute(sa.text(f'DROP TABLE "{retired}"'))

    def drop_table(self, database: str, table: str) -> None:
        with self._engine_for(database).begin() as conn:
            conn.execute(sa.text(f'DROP TABLE IF EXISTS "{table}"'))

    def close(self) -> None:
        self._admin_engine.dispose()
        for engine in self._db_engines.values():
            engine.dispose()

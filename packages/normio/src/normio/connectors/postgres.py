"""PostgresConnector — Source.txt §105."""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from normio.connector import ColumnInfo
from normio.connectors._sql_base import SqlConnectorBase

if TYPE_CHECKING:
    from collections.abc import Sequence


# The server's own namespaces, which are never a clone source.
_SERVER_SCHEMAS = frozenset({"information_schema", "pg_catalog", "pg_toast"})


class PostgresConnector(SqlConnectorBase):
    def __init__(self, source_id: str, dsn: str, schema: str | None = None) -> None:
        """`schema` names the namespace inside `dsn`'s database that this
        connector's table names are relative to; None uses the
        connection's own default (the first entry on `search_path`,
        normally `public`).

        Every lookup below has to honour it or none of them can: with the
        schema applied to `list_tables` alone, a table would be discovered
        and then fail to have columns, a key, or rows. That is why this is
        one constructor argument rather than a per-call parameter.
        """
        self.source_id = source_id
        self._schema = schema
        # postgresql+psycopg:// selects the psycopg3 driver explicitly
        # rather than relying on SQLAlchemy's default (psycopg2, not a
        # project dependency).
        normalized_dsn = dsn.replace("postgresql://", "postgresql+psycopg://", 1)
        self._engine = sa.create_engine(
            normalized_dsn,
            # Sets the session to PostgreSQL's native read-only transaction
            # mode — any INSERT/UPDATE/DELETE/DDL on this connection fails
            # at the database level, not just because our code never issues
            # one. Confirmed in tests/integration/test_readonly_connectors.py.
            execution_options={"postgresql_readonly": True},
        )

    def list_databases(self) -> Sequence[str]:
        """Server-level database discovery (decision #1) — queried from
        the server itself, never a network port scan."""
        with self._engine.connect() as conn:
            rows = conn.execute(
                sa.text(
                    "SELECT datname FROM pg_database WHERE datistemplate = false ORDER BY datname"
                )
            ).all()
        return [row[0] for row in rows]

    def list_schemas(self) -> Sequence[str]:
        """Namespaces inside this database that hold tables of their own,
        with the server's built-ins left out.

        Exists so that "this database has no tables" can be answered with
        WHERE the tables are instead of just repeating itself: a real
        13-table source kept all of them in a named schema, and every
        discovery call, being relative to `public`, reported nothing at
        all.
        """
        inspector = sa.inspect(self._engine)
        return [
            schema
            for schema in inspector.get_schema_names()
            if schema not in _SERVER_SCHEMAS and inspector.get_table_names(schema=schema)
        ]

    def get_columns(self, table: str) -> Sequence[ColumnInfo]:
        """Columns with native type strings, for the clone-job DDL/type
        passthrough path. Same inspector idiom as
        `SqlConnectorBase.list_tables` just above."""
        inspector = sa.inspect(self._engine)
        return [
            ColumnInfo(name=c["name"], native_type=str(c["type"]))
            for c in inspector.get_columns(table, schema=self._schema)
        ]

    def get_primary_key(self, table: str) -> Sequence[str]:
        """Primary-key column names, for clone-job DDL replication
        (decision #11) and resumable insert dedup (`ON CONFLICT DO
        NOTHING`, decision #10). Empty if the table has none."""
        inspector = sa.inspect(self._engine)
        constraint = inspector.get_pk_constraint(table, schema=self._schema)
        return list(constraint.get("constrained_columns") or [])

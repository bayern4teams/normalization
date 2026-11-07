"""PostgresConnector — Source.txt §105."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import sqlalchemy as sa

from normio.connector import ColumnInfo
from normio.connectors._sql_base import SqlConnectorBase
from normio.connectors.postgres_destination import engine_from_dsn, quote_identifier

if TYPE_CHECKING:
    from collections.abc import Sequence


_COLUMNS_SQL = sa.text(
    "SELECT a.attname, CASE WHEN b.typnamespace = 'pg_catalog'::regnamespace "
    "THEN format_type(b.oid, CASE WHEN t.typtype = 'd' THEN t.typtypmod ELSE a.atttypmod END) "
    "ELSE 'text' END "
    "FROM pg_attribute a JOIN pg_type t ON t.oid = a.atttypid "
    "JOIN pg_type b ON b.oid = CASE WHEN t.typtype = 'd' THEN t.typbasetype ELSE t.oid END "
    "WHERE a.attrelid = CAST(:rel AS regclass) AND a.attnum > 0 AND NOT a.attisdropped "
    "ORDER BY a.attnum"
)

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
        # Sets the session to PostgreSQL's native read-only transaction
        # mode — any INSERT/UPDATE/DELETE/DDL on this connection fails
        # at the database level, not just because our code never issues
        # one. Confirmed in tests/integration/test_readonly_connectors.py.
        self._engine = engine_from_dsn(dsn, execution_options={"postgresql_readonly": True})

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
        """Columns with the type string the clone's DDL will use for a
        passthrough column, so it must be one the DESTINATION can create.

        SQLAlchemy's reflected type rendered `text[]` as a bare `ARRAY`
        and a domain as `DOMAIN`, so Pagila's `CREATE TABLE film` was a
        syntax error. Postgres formats its own types instead
        (`format_type`), with one rule for what the destination database
        may not have: a domain becomes its base type (the values fit; the
        CHECK is not copied), and any type that is not built in (an enum,
        an extension's `citext` or `vector`, arrays of those) becomes
        `text`, which holds every such value as the text Postgres prints.
        ponytail: one level of domain; a domain over a domain also falls
        to `text`. Resolve the chain recursively if one turns up.
        """
        relation = (
            f"{quote_identifier(self._schema)}.{quote_identifier(table)}"
            if self._schema
            else quote_identifier(table)
        )
        with self._engine.connect() as conn:
            rows = conn.execute(_COLUMNS_SQL, {"rel": relation}).all()
        return [ColumnInfo(name=name, native_type=native_type) for name, native_type in rows]

    def _row_order(self, sql_table: sa.Table) -> list[Any]:
        """The primary key, or for a table without one its physical order
        (`ctid`): stable while the table is unchanged, which a resume of an
        unchanged source is all it needs. Costs a sort the unordered scan
        did not."""
        return list(sql_table.primary_key.columns) or [sa.literal_column("ctid")]

    def get_primary_key(self, table: str) -> Sequence[str]:
        """Primary-key column names, for clone-job DDL replication
        (decision #11) and resumable insert dedup (`ON CONFLICT DO
        NOTHING`, decision #10). Empty if the table has none."""
        inspector = sa.inspect(self._engine)
        constraint = inspector.get_pk_constraint(table, schema=self._schema)
        return list(constraint.get("constrained_columns") or [])

"""PostgresConnector — Source.txt §105."""

from __future__ import annotations

import sqlalchemy as sa

from normio.connectors._sql_base import SqlConnectorBase


class PostgresConnector(SqlConnectorBase):
    def __init__(self, source_id: str, dsn: str) -> None:
        self.source_id = source_id
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

"""MySQLConnector — Source.txt §105.

MySQL/PyMySQL has no engine-level "read-only transaction" execution option
equivalent to PostgreSQL's, so read-only enforcement here rests entirely on
the DSN's user having only SELECT grants at the database level (see
tests/integration/fixtures/mysql-init/ for how the demo container
provisions a genuinely restricted `readonly_user`).
"""

from __future__ import annotations

import sqlalchemy as sa

from normio.connectors._sql_base import SqlConnectorBase


class MySQLConnector(SqlConnectorBase):
    def __init__(self, source_id: str, dsn: str) -> None:
        self.source_id = source_id
        normalized_dsn = dsn.replace("mysql://", "mysql+pymysql://", 1)
        self._engine = sa.create_engine(normalized_dsn)

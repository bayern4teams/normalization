"""Concrete SourceConnector implementations — one per source type
Source.txt §105 requires: PostgreSQL, MySQL, flat files (CSV/Parquet/
Excel), MongoDB, ClickHouse. Every implementation is read-only; see
normio.connector for the interface-level enforcement and
docs/adr/ADR-013-normalization-storage.md for the design rationale.

`PostgresDestination`/`ClickHouseDestination` are the write-capable
counterparts for the DB-clone-and-normalize feature — deliberately
separate classes, not part of the read-only SourceConnector family above.
"""

from normio.connectors.clickhouse import ClickHouseConnector
from normio.connectors.clickhouse_destination import ClickHouseDestination
from normio.connectors.file import FileConnector
from normio.connectors.mongo import MongoConnector
from normio.connectors.mysql import MySQLConnector
from normio.connectors.postgres import PostgresConnector
from normio.connectors.postgres_destination import PostgresDestination

__all__ = [
    "ClickHouseConnector",
    "ClickHouseDestination",
    "FileConnector",
    "MongoConnector",
    "MySQLConnector",
    "PostgresConnector",
    "PostgresDestination",
]

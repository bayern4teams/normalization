"""Concrete SourceConnector implementations — one per source type
Source.txt §105 requires: PostgreSQL, MySQL, flat files (CSV/Parquet/
Excel), MongoDB, ClickHouse. Every implementation is read-only; see
normio.connector for the interface-level enforcement and
docs/adr/ADR-013-normalization-storage.md for the design rationale.
"""

from normio.connectors.clickhouse import ClickHouseConnector
from normio.connectors.file import FileConnector
from normio.connectors.mongo import MongoConnector
from normio.connectors.mysql import MySQLConnector
from normio.connectors.postgres import PostgresConnector

__all__ = [
    "ClickHouseConnector",
    "FileConnector",
    "MongoConnector",
    "MySQLConnector",
    "PostgresConnector",
]

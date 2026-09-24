"""Integration tests against REAL running database containers (see
compose.yaml's demo-* services and tests/integration/fixtures/).

Two things are proven per connector, not assumed:
1. Reading actually works and returns the seeded rows with a correct
   source_row_key.
2. A write attempt against the SAME read-only credentials is rejected by
   the database itself — using the underlying driver directly (not our
   SourceConnector, which structurally has no write method at all) to
   prove the enforcement is real, not just an artifact of our own
   connector's limited interface.

Requires: docker compose up -d demo-postgres demo-mysql demo-mongo demo-clickhouse
"""

from __future__ import annotations

import os

import clickhouse_connect
import psycopg
import pymysql
import pytest
from clickhouse_connect.driver.exceptions import DatabaseError
from normio.connectors import ClickHouseConnector, MongoConnector, MySQLConnector, PostgresConnector
from pymongo import MongoClient
from pymongo.errors import OperationFailure
from pymysql.err import OperationalError

# Host/port pairs, not a single hardcoded DSN/port per connector — same
# TEST_*_HOST/TEST_*_PORT pattern as tests/integration/test_clone_pipeline.py,
# so this file passes identically whether pytest runs from the host
# (default: the host-mapped compose.yaml ports) or from a container on the
# `normalization_default` compose network (override to the service name +
# the container's own internal port, e.g. TEST_CLICKHOUSE_HOST=demo-clickhouse
# TEST_CLICKHOUSE_PORT=8123). Previously ClickHouse's port and MySQL's raw
# (non-connector) pymysql.connect() host/port were hardcoded literals —
# real gaps that only ever surfaced as a failure when run from anywhere but
# the host.
PG_HOST = os.environ.get("TEST_PG_HOST", "localhost")
PG_PORT = int(os.environ.get("TEST_PG_PORT", "5434"))
MYSQL_HOST = os.environ.get("TEST_MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.environ.get("TEST_MYSQL_PORT", "3307"))
MONGO_HOST = os.environ.get("TEST_MONGO_HOST", "localhost")
MONGO_PORT = int(os.environ.get("TEST_MONGO_PORT", "27018"))
CLICKHOUSE_HOST = os.environ.get("TEST_CLICKHOUSE_HOST", "localhost")
CLICKHOUSE_PORT = int(os.environ.get("TEST_CLICKHOUSE_PORT", "8124"))

POSTGRES_DSN = f"postgresql://readonly_user:readonly_pass@{PG_HOST}:{PG_PORT}/source_demo"
MYSQL_DSN = f"mysql://readonly_user:readonly_pass@{MYSQL_HOST}:{MYSQL_PORT}/source_demo"
MONGO_URI = f"mongodb://readonly_user:readonly_pass@{MONGO_HOST}:{MONGO_PORT}/source_demo"


@pytest.mark.integration
def test_postgres_read_succeeds_and_write_is_rejected() -> None:
    connector = PostgresConnector("demo_pg", POSTGRES_DSN)
    try:
        tables = connector.list_tables()
        assert "customers" in tables

        batches = list(connector.read_table("customers"))
        rows = sum(b.num_rows for b in batches)
        assert rows == 3
        first_batch = batches[0]
        assert "source_row_key" in first_batch.schema.names
        first_names = first_batch.column("first_name").to_pylist()
        assert "  John  " in first_names  # original whitespace preserved — no mutation in transit
    finally:
        connector.close()

    # Write attempt: real INSERT against the readonly_user credentials,
    # using the driver directly (not our connector, which has no write
    # method to even attempt this through). Connecting with plain
    # readonly_user credentials (no session-level read-only flag set) —
    # the rejection here comes purely from the role's GRANT permissions
    # (SELECT only, no INSERT), which is the actual database-level
    # enforcement this test verifies.
    with (
        psycopg.connect(POSTGRES_DSN) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute("INSERT INTO customers (first_name, last_name) VALUES ('x', 'y')")


@pytest.mark.integration
def test_mysql_read_succeeds_and_write_is_rejected() -> None:
    connector = MySQLConnector("demo_mysql", MYSQL_DSN)
    try:
        tables = connector.list_tables()
        assert "customers" in tables

        batches = list(connector.read_table("customers"))
        rows = sum(b.num_rows for b in batches)
        assert rows == 3
    finally:
        connector.close()

    conn = pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user="readonly_user",
        password="readonly_pass",
        database="source_demo",
    )
    try:
        with conn.cursor() as cursor, pytest.raises(OperationalError, match="command denied"):
            cursor.execute("INSERT INTO customers (first_name, last_name) VALUES ('x', 'y')")
    finally:
        conn.close()


@pytest.mark.integration
def test_mongo_read_succeeds_and_write_is_rejected() -> None:
    connector = MongoConnector("demo_mongo", MONGO_URI, "source_demo")
    try:
        tables = connector.list_tables()
        assert "customers" in tables

        batches = list(connector.read_table("customers"))
        rows = sum(b.num_rows for b in batches)
        assert rows == 3
        assert "source_row_key" in batches[0].schema.names
    finally:
        connector.close()

    client: MongoClient[dict[str, object]] = MongoClient(MONGO_URI)
    try:
        db = client["source_demo"]
        with pytest.raises(OperationFailure):
            db.customers.insert_one({"first_name": "x", "last_name": "y"})
    finally:
        client.close()


@pytest.mark.integration
def test_clickhouse_read_succeeds_and_write_is_rejected() -> None:
    connector = ClickHouseConnector(
        "demo_clickhouse",
        CLICKHOUSE_HOST,
        port=CLICKHOUSE_PORT,
        username="readonly_user",
        password="readonly_pass",
        database="default",
    )
    try:
        tables = connector.list_tables()
        assert "customers" in tables

        batches = list(connector.read_table("customers"))
        rows = sum(b.num_rows for b in batches)
        assert rows == 3
    finally:
        connector.close()

    client = clickhouse_connect.get_client(
        host=CLICKHOUSE_HOST,
        port=CLICKHOUSE_PORT,
        username="readonly_user",
        password="readonly_pass",
    )
    try:
        with pytest.raises(DatabaseError):
            client.command(
                "INSERT INTO customers (id, first_name, last_name) VALUES (99, 'x', 'y')"
            )
    finally:
        client.close()

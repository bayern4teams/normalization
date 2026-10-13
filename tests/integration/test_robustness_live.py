"""Live counterparts of tests/unit/test_robustness.py, against REAL Postgres and
ClickHouse (compose.yaml's demo-postgres / demo-clickhouse, `writable_user`).

Each test creates its own uniquely named database and drops it afterwards.
Locally, point the ports at an isolated stack (TEST_PG_PORT etc.); the
defaults are compose.yaml's, the same as test_clone_pipeline.py.
"""

from __future__ import annotations

import os
import time
import uuid
from typing import TYPE_CHECKING, Any

import clickhouse_connect
import psycopg
import pytest
from normio.connector import ColumnInfo
from normio.connectors import ClickHouseConnector, PostgresConnector
from normio.connectors.clickhouse_destination import ClickHouseDestination
from normio.connectors.clickhouse_destination import quote_identifier as ch_q
from normio.connectors.postgres_destination import PostgresDestination
from normio.connectors.postgres_destination import quote_identifier as pg_q

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.integration

PG_HOST = os.environ.get("TEST_PG_HOST", "localhost")
PG_PORT = int(os.environ.get("TEST_PG_PORT", "5434"))
CH_HOST = os.environ.get("TEST_CLICKHOUSE_HOST", "localhost")
CH_PORT = int(os.environ.get("TEST_CLICKHOUSE_PORT", "8124"))
_W = {"username": "writable_user", "password": "writable_pass"}

# Real column names from the Norway and GLEIF registers, plus every character
# class that broke a generated statement.
NAMES = [
    "organisasjonsform.kode",
    "Entity.LegalName",
    "zip code",
    "x-y",
    "p:q",
    "50%",
    'qu"ote',
    "b`t",
    "back\\slash",
]


def _pg_dsn(database: str) -> str:
    return f"postgresql://{_W['username']}:{_W['password']}@{PG_HOST}:{PG_PORT}/{database}"


@pytest.fixture
def pg_db() -> Iterator[str]:
    name = f"robust_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(_pg_dsn("postgres"), autocommit=True) as conn:
        conn.execute(f"CREATE DATABASE {pg_q(name)}")
    yield name
    with psycopg.connect(_pg_dsn("postgres"), autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {pg_q(name)} WITH (FORCE)")


@pytest.fixture
def ch() -> Any:
    return clickhouse_connect.get_client(host=CH_HOST, port=CH_PORT, **_W)


@pytest.fixture
def ch_db(ch: Any) -> Iterator[str]:
    name = f"robust_{uuid.uuid4().hex[:8]}"
    ch.command(f"CREATE DATABASE {ch_q(name)}")
    yield name
    ch.command(f"DROP DATABASE IF EXISTS {ch_q(name)}")


def _rows(n: int) -> list[dict[str, Any]]:
    return [{c: f"{i}|{c}" for c in NAMES} for i in range(n)]


class TestIdentifiers:
    def test_postgres_round_trip_with_hostile_names(self, pg_db: str) -> None:
        dest = PostgresDestination(PG_HOST, PG_PORT, _W["username"], _W["password"])
        table = 'enheter.v1 "x"'
        cols = [ColumnInfo(name=c, native_type="text") for c in NAMES]
        dest.create_table(pg_db, table, cols, primary_key=[NAMES[0]])
        rows = _rows(5)
        dest.bulk_insert(pg_db, table, rows, primary_key=[NAMES[0]])
        dest.bulk_insert(pg_db, table, rows, primary_key=[NAMES[0]])  # resume no-op
        dest.close()
        source = PostgresConnector("s", _pg_dsn(pg_db))
        assert [c.name for c in source.get_columns(table)] == NAMES
        got = [r for b in source.read_table(table) for r in b.to_pylist()]
        source.close()
        assert [{c: r[c] for c in NAMES} for r in got] == rows

    def test_clickhouse_round_trip_with_hostile_names(self, ch: Any, ch_db: str) -> None:
        table = "lei.golden `copy`"
        cols = ", ".join(f"{ch_q(c)} String" for c in NAMES)
        ch.command(
            f"CREATE TABLE {ch_q(ch_db)}.{ch_q(table)} ({cols}) "
            f"ENGINE = MergeTree ORDER BY ({ch_q(NAMES[0])}, {ch_q('b`t')})"
        )
        rows = _rows(5)
        ch.insert(
            f"{ch_q(ch_db)}.{ch_q(table)}", [list(r.values()) for r in rows], column_names=NAMES
        )

        source = ClickHouseConnector("s", CH_HOST, port=CH_PORT, database=ch_db, **_W)
        _, order_by = source.get_table_engine_info(table)
        assert order_by == [NAMES[0], "b`t"]
        got = [r for b in source.read_table(table) for r in b.to_pylist()]
        assert [{c: r[c] for c in NAMES} for r in got] == rows

        dest = ClickHouseDestination(CH_HOST, CH_PORT, _W["username"], _W["password"])
        dest.create_table(ch_db, "out.x", source.get_columns(table), order_by=order_by)
        dest.bulk_insert(ch_db, "out.x", [{c: r[c] for c in NAMES} for r in got])
        dest.close()
        source.close()
        assert ch.command(f"SELECT count() FROM {ch_q(ch_db)}.{ch_q('out.x')}") == 5


class TestClickHouseStreamSurvivesASlowConsumer:
    def test_a_pause_longer_than_the_server_send_timeout_loses_nothing(
        self, ch: Any, ch_db: str
    ) -> None:
        """Incompressible rows so the result outgrows every socket buffer, then a
        pause longer than the server's http_send_timeout (30 s by default) after
        the first batch, the shape of one slow chunk. Before the fix the server
        dropped the stream (57,344 of 400,000 rows arrived)."""
        rows = 400_000
        ch.command(
            f"CREATE TABLE {ch_q(ch_db)}.noise (id UInt64, s String) ENGINE = MergeTree ORDER BY id"
        )
        ch.command(
            f"INSERT INTO {ch_q(ch_db)}.noise "
            f"SELECT number, randomPrintableASCII(200) FROM numbers({rows})"
        )
        timeout = int(
            ch.command("SELECT value FROM system.settings WHERE name = 'http_send_timeout'")
        )
        source = ClickHouseConnector("s", CH_HOST, port=CH_PORT, database=ch_db, **_W)
        seen = 0
        for i, batch in enumerate(source.read_table("noise", batch_size=100_000)):
            seen += batch.num_rows
            if i == 0:
                time.sleep(timeout + 5)
        source.close()
        assert seen == rows

"""Live counterparts of tests/unit/test_followups.py, against REAL Postgres and
ClickHouse (compose.yaml's demo-postgres / demo-clickhouse, `writable_user`).

Each test creates its own uniquely named database and drops it afterwards.
Locally, point the ports at an isolated stack (TEST_PG_PORT etc.).
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import uuid
from typing import TYPE_CHECKING, Any

import clickhouse_connect
import psycopg
import pytest
from normapi.pg_persistence import PgPersistence
from normio.connectors.clickhouse_destination import quote_identifier as ch_q
from normio.connectors.postgres_destination import quote_identifier as pg_q

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = pytest.mark.integration

PG_HOST = os.environ.get("TEST_PG_HOST", "localhost")
PG_PORT = int(os.environ.get("TEST_PG_PORT", "5434"))
CH_HOST = os.environ.get("TEST_CLICKHOUSE_HOST", "localhost")
CH_PORT = int(os.environ.get("TEST_CLICKHOUSE_PORT", "8124"))
_W = {"username": "writable_user", "password": "writable_pass"}
ROWS, BLOCK = 30_000, 10_000


def _pg_dsn(database: str) -> str:
    return f"postgresql://{_W['username']}:{_W['password']}@{PG_HOST}:{PG_PORT}/{database}"


@pytest.fixture
def pg_db() -> Iterator[str]:
    name = f"followup_{uuid.uuid4().hex[:8]}"
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
    name = f"followup_{uuid.uuid4().hex[:8]}"
    ch.command(f"CREATE DATABASE {ch_q(name)}")
    yield name
    ch.command(f"DROP DATABASE IF EXISTS {ch_q(name)}")


# One table, end to end, in a child process that dies (os._exit, no cleanup,
# no except block: what a SIGKILL or an OOM kill leaves) right after the
# second block's INSERT has committed and before its checkpoint: the one
# place a resume can write rows twice. The parent then resumes it.
_RUN = textwrap.dedent(
    """
    import os, sys
    from normapi.app import build_dispatcher
    from normapi.clone_executor import _normalize_table
    from normapi.pg_persistence import PgPersistence
    from normexec.planner import DistinctValuePlanner
    from normio.connectors import ClickHouseConnector, PostgresConnector
    from normio.connectors.clickhouse_destination import ClickHouseDestination
    from normio.connectors.postgres_destination import PostgresDestination

    engine, src_db, dst_db, meta, host, port, block, die_after = sys.argv[1:9]
    port, block, die_after = int(port), int(block), int(die_after)
    w = {"username": "writable_user", "password": "writable_pass"}
    if engine == "clickhouse":
        source = ClickHouseConnector("s", host, port=port, database=src_db, **w)
        dest = ClickHouseDestination(host, port, **w)
    else:
        dsn = f"postgresql://writable_user:writable_pass@{host}:{port}/{src_db}"
        source = PostgresConnector("s", dsn)
        dest = PostgresDestination(host, port, **w)
    dest.insert_block_rows = lambda *a: block
    inserted = 0
    real_insert = dest.bulk_insert

    def insert(*a, **k):
        global inserted
        real_insert(*a, **k)
        inserted += 1
        if inserted == die_after:
            os._exit(137)

    dest.bulk_insert = insert
    store = PgPersistence(meta)
    job = store.get_clone_job("j")
    _normalize_table(
        "t", job=job, job_id="j", source=source, dest=dest, source_engine=engine,
        persistence=store, planner=DistinctValuePlanner(build_dispatcher(env_id="e"), None),
        pool=None, progress=job["progress"], in_place=False, entity_countries={},
        adjudication=None,
    )
    """
)


def _job_with_error_rows() -> dict[str, Any]:
    return {
        "source_connection_id": "s",
        "destination_database": "",
        "field_configs": {"t": {"amt": "MONEY"}},
        "destination_plan": {"t": {"typed_columns": {}}},
        "progress": {"checkpoints": {}, "rows_done": 0, "current_table": None},
        "country": "US",
        "locale": "en-US",
        "status": "FAILED",
    }


def _kill_then_resume(engine: str, src_db: str, dst_db: str, meta: str, port: int) -> None:
    store = PgPersistence(meta)
    store.ensure_schema()
    store.create_clone_job("j", {**_job_with_error_rows(), "destination_database": dst_db})
    args = [
        engine,
        src_db,
        dst_db,
        meta,
        PG_HOST if engine == "postgres" else CH_HOST,
        str(port),
        str(BLOCK),
    ]
    killed = subprocess.run([sys.executable, "-c", _RUN, *args, "2"], check=False)
    assert killed.returncode == 137
    assert store.get_clone_job("j")["progress"]["checkpoints"]["t"] == BLOCK - 1
    resumed = subprocess.run([sys.executable, "-c", _RUN, *args, "0"], check=False)
    assert resumed.returncode == 0


class TestKilledMidRunResumesExactly:
    def test_clickhouse(self, ch: Any, ch_db: str, tmp_path: Path) -> None:
        src = f"{ch_db}_src"
        ch.command(f"CREATE DATABASE {ch_q(src)}")
        try:
            ch.command(f"CREATE TABLE {ch_q(src)}.t (id UInt64, amt String) ORDER BY id")
            ch.command(
                f"INSERT INTO {ch_q(src)}.t SELECT number, "
                f"if(number % 3 = 2, 'not money', concat(toString(number), '.00')) "
                f"FROM numbers({ROWS})"
            )
            # Phase 1's DDL for this table, so the dedup window is what Phase 1 sets.
            from normio.connector import ColumnInfo  # noqa: PLC0415
            from normio.connectors.clickhouse_destination import (  # noqa: PLC0415
                ClickHouseDestination,
            )

            dest = ClickHouseDestination(CH_HOST, CH_PORT, **_W)
            dest.create_table(
                ch_db,
                "t",
                [
                    ColumnInfo(name="id", native_type="UInt64"),
                    ColumnInfo(name="amt", native_type="String"),
                ],
                order_by=["id"],
            )
            dest.close()
            meta = f"sqlite:///{tmp_path}/m.db"
            _kill_then_resume("clickhouse", src, ch_db, meta, CH_PORT)

            count, distinct = ch.query(
                f"SELECT count(), uniqExact(id) FROM {ch_q(ch_db)}.t"
            ).result_rows[0]
            assert (count, distinct) == (ROWS, ROWS)
            errors = PgPersistence(meta).count_clone_job_errors("j")
            assert errors == ROWS // 3
        finally:
            ch.command(f"DROP DATABASE IF EXISTS {ch_q(src)}")

    def test_postgres_with_a_primary_key(self, pg_db: str, tmp_path: Path) -> None:
        with psycopg.connect(_pg_dsn(pg_db), autocommit=True) as conn:
            conn.execute("CREATE TABLE t (id bigint PRIMARY KEY, amt text)")
            conn.execute(
                "INSERT INTO t SELECT g, CASE WHEN g % 3 = 2 THEN 'not money' "
                f"ELSE g || '.00' END FROM generate_series(0, {ROWS - 1}) g"
            )
        dst = f"{pg_db}_dst"
        with psycopg.connect(_pg_dsn("postgres"), autocommit=True) as conn:
            conn.execute(f"CREATE DATABASE {pg_q(dst)}")
        try:
            with psycopg.connect(_pg_dsn(dst), autocommit=True) as conn:
                conn.execute("CREATE TABLE t (id bigint PRIMARY KEY, amt text)")
            meta = f"sqlite:///{tmp_path}/m.db"
            _kill_then_resume("postgres", pg_db, dst, meta, PG_PORT)
            with psycopg.connect(_pg_dsn(dst)) as conn:
                row = conn.execute("SELECT count(*), count(DISTINCT id) FROM t").fetchone()
            assert row == (ROWS, ROWS)
            assert PgPersistence(meta).count_clone_job_errors("j") == ROWS // 3
        finally:
            with psycopg.connect(_pg_dsn("postgres"), autocommit=True) as conn:
                conn.execute(f"DROP DATABASE IF EXISTS {pg_q(dst)} WITH (FORCE)")


class TestAFailedJobCanBeClaimed:
    def test_on_postgres(self, pg_db: str) -> None:
        store = PgPersistence(_pg_dsn(pg_db))
        store.ensure_schema()
        store.create_clone_job("j", {"status": "FAILED", "error": "MEMORY_LIMIT_EXCEEDED"})
        assert store.claim_clone_job("j")
        assert store.get_clone_job("j")["status"] == "RUNNING"
        store.create_clone_job("k", {"status": "COMPLETED"})
        assert not store.claim_clone_job("k")

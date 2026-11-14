"""D38: a clone job killed in the middle of a table resumes through the real
start path (`clone_executor.start_phase2`) and ends with the same destination
rows and error rows as an unbroken run of the same job.

Three tables, 100-row blocks: the kill falls after the third block of the
second table has been INSERTed and before its checkpoint, the one place a
resume can write rows twice. The kill is a fault injected at a fixed insert
count, not a timer, so the run always reaches it (the benchmark's
time-based kill points never were, `docs/plans/round3/FINAL_REPORT.md` §5).

Every app step runs in a child process: the block sizes are read from the
environment at import time, and the killed child must die with no cleanup.
Point it at a server with TEST_PG_* / TEST_CLICKHOUSE_*; it creates and drops
its own `norm_r4_*` databases.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import textwrap
import uuid
from typing import Any

import clickhouse_connect
import psycopg
import pytest
from cryptography.fernet import Fernet
from normapi.pg_persistence import PgPersistence
from normio.connectors.clickhouse_destination import quote_identifier as ch_q
from normio.connectors.postgres_destination import quote_identifier as pg_q

pytestmark = pytest.mark.integration

PG_HOST = os.environ.get("TEST_PG_HOST", "localhost")
PG_PORT = int(os.environ.get("TEST_PG_PORT", "5434"))
PG_USER = os.environ.get("TEST_PG_USER", "writable_user")
PG_PASSWORD = os.environ.get("TEST_PG_PASSWORD", "writable_pass")
CH_HOST = os.environ.get("TEST_CLICKHOUSE_HOST", "localhost")
CH_PORT = int(os.environ.get("TEST_CLICKHOUSE_PORT", "8124"))
CH_USER = os.environ.get("TEST_CLICKHOUSE_USER", "writable_user")
CH_PASSWORD = os.environ.get("TEST_CLICKHOUSE_PASSWORD", "writable_pass")

BLOCK = 100
KILL_AFTER_INSERT = 6  # t_a: 250 rows = inserts 1-3; t_b: inserts 4-13
TABLES = {"t_a": 250, "t_b": 1000, "t_c": 30}
COUNTRIES = ["GB", "uk", "Germany", "xx-unknown", "France"]

_CHILD = textwrap.dedent(
    """
    import json, os, sys, time
    from normapi import clone_executor
    from normapi.app import build_dispatcher
    from normapi.pg_persistence import PgPersistence
    from normio.connectors.clickhouse_destination import ClickHouseDestination
    from normio.connectors.postgres_destination import PostgresDestination

    mode, meta = sys.argv[1], sys.argv[2]
    store = PgPersistence(meta)
    store.ensure_schema()
    if mode == "create":
        engine, host, port, user, password, src, dst = sys.argv[3:10]
        conns = [
            store.save_connection(n, engine=engine, host=host, port=int(port), username=user,
                                  password=password)["connection_id"]
            for n in ("src", "dst")
        ]
        job = clone_executor.create_clone_job(store, request={
            "source_connection_id": conns[0], "source_database": src,
            "destination_connection_id": conns[1], "destination_database": dst,
            "field_configs": {"t_a": {"amt": "MONEY"}, "t_b": {"country": "COUNTRY"}},
        })
        print(json.dumps(job["job_id"]))
        sys.exit(0)
    job_id, die_after = sys.argv[3], int(sys.argv[4])
    if mode == "schema":
        clone_executor.verify_and_create_schema(store, job_id)
        sys.exit(0)
    inserted = 0
    for cls in (ClickHouseDestination, PostgresDestination):
        real = cls.bulk_insert

        def insert(self, *a, _real=real, **k):
            global inserted
            _real(self, *a, **k)
            inserted += 1
            if inserted == die_after:
                os._exit(137)  # what a SIGKILL or an OOM kill leaves: no cleanup at all

        cls.bulk_insert = insert
    assert clone_executor.start_phase2(store, build_dispatcher(env_id="d38"), None, job_id)
    while (job := store.get_clone_job(job_id))["status"] not in ("COMPLETED", "FAILED"):
        time.sleep(0.05)
    print(json.dumps({"status": job["status"], "error": job.get("error"),
                      "rows_done": job["progress"]["rows_done"]}))
    """
)


def _child(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", _CHILD, *args],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )


def _ok(result: subprocess.CompletedProcess[str]) -> Any:
    assert result.returncode == 0, result.stderr[-3000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


class _Pg:
    engine, host, port, user, password = "postgres", PG_HOST, PG_PORT, PG_USER, PG_PASSWORD

    def _dsn(self, db: str) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{db}"

    def admin(self, sql: str) -> None:
        with psycopg.connect(self._dsn("postgres"), autocommit=True) as conn:
            conn.execute(sql)

    def create_source(self, db: str) -> None:
        self.admin(f"CREATE DATABASE {pg_q(db)}")
        with psycopg.connect(self._dsn(db), autocommit=True) as conn:
            for table, rows in TABLES.items():
                conn.execute(f"CREATE TABLE {table} (id bigint PRIMARY KEY, v text)")
                conn.cursor().executemany(
                    f"INSERT INTO {table} VALUES (%s, %s)",
                    [(i, _value(table, i)) for i in range(rows)],
                )
            for table, column in (("t_a", "amt"), ("t_b", "country"), ("t_c", "note")):
                conn.execute(f"ALTER TABLE {table} RENAME COLUMN v TO {column}")

    def rows(self, db: str, table: str) -> list[tuple[Any, ...]]:
        with psycopg.connect(self._dsn(db)) as conn:
            return conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()

    def drop(self, db: str) -> None:
        self.admin(f"DROP DATABASE IF EXISTS {pg_q(db)} WITH (FORCE)")


class _Ch:
    engine, host, port, user, password = "clickhouse", CH_HOST, CH_PORT, CH_USER, CH_PASSWORD

    def _client(self) -> Any:
        return clickhouse_connect.get_client(
            host=self.host, port=self.port, username=self.user, password=self.password
        )

    def admin(self, sql: str) -> None:
        self._client().command(sql)

    def create_source(self, db: str) -> None:
        ch = self._client()
        ch.command(f"CREATE DATABASE {ch_q(db)}")
        for table, rows in TABLES.items():
            column = {"t_a": "amt", "t_b": "country", "t_c": "note"}[table]
            # No sorting key and several parts: the read order may change between
            # two reads, so a resume must not depend on it.
            ch.command(
                f"CREATE TABLE {ch_q(db)}.{table} (id Int64, {column} Nullable(String)) "
                "ENGINE = MergeTree ORDER BY tuple()"
            )
            for part in range(2):
                ids = range(part, rows, 2)
                ch.insert(
                    f"{ch_q(db)}.{table}",
                    [[i, _value(table, i)] for i in ids],
                    column_names=["id", column],
                )

    def rows(self, db: str, table: str) -> list[tuple[Any, ...]]:
        return list(
            self._client().query(f"SELECT * FROM {ch_q(db)}.{table} ORDER BY id").result_rows
        )

    def drop(self, db: str) -> None:
        self.admin(f"DROP DATABASE IF EXISTS {ch_q(db)}")


def _value(table: str, i: int) -> str:
    if table == "t_a":
        return "not money" if i % 5 == 4 else f"{i}.50 USD"
    if table == "t_b":
        return COUNTRIES[i % len(COUNTRIES)]
    return f"note {i}"


def _digest(rows: list[tuple[Any, ...]]) -> str:
    return hashlib.sha256(repr(rows).encode()).hexdigest()


@pytest.mark.parametrize("server", [_Pg(), _Ch()], ids=["postgres", "clickhouse"])
def test_killed_mid_table_resumes_to_the_unbroken_result(server: Any) -> None:
    run = f"norm_r4_{uuid.uuid4().hex[:8]}"
    src, killed_db, full_db = f"{run}_src", f"{run}_killed", f"{run}_full"
    env = {
        **os.environ,
        "NORM_SECRET_KEY": Fernet.generate_key().decode(),
        "NORM_DESTINATION_INSERT_CHUNK_ROWS": str(BLOCK),
        "NORM_SOURCE_READ_BATCH_ROWS": str(BLOCK),
    }
    server.create_source(src)
    try:
        metas: dict[str, str] = {}
        jobs: dict[str, str] = {}
        for dst in (killed_db, full_db):
            # The job store needs Postgres (claim_clone_job), whatever the clone's engine.
            meta_db = f"norm_app_r4_{dst.removeprefix('norm_r4_')}"
            _Pg().admin(f"CREATE DATABASE {pg_q(meta_db)}")
            metas[dst] = _Pg()._dsn(meta_db)
            jobs[dst] = _ok(
                _child(
                    env,
                    "create",
                    metas[dst],
                    server.engine,
                    server.host,
                    str(server.port),
                    server.user,
                    server.password,
                    src,
                    dst,
                )
            )
            server.admin(f"CREATE DATABASE {(pg_q if server.engine == 'postgres' else ch_q)(dst)}")
            assert _child(env, "schema", metas[dst], jobs[dst], "0").returncode == 0

        full = _ok(_child(env, "run", metas[full_db], jobs[full_db], "0"))
        assert full["status"] == "COMPLETED", full

        killed = _child(env, "run", metas[killed_db], jobs[killed_db], str(KILL_AFTER_INSERT))
        assert killed.returncode == 137, killed.stderr[-3000:]
        # Mid-table: t_a done, three t_b blocks written (the third not checkpointed), t_c untouched.
        assert [len(server.rows(killed_db, t)) for t in TABLES] == [250, 3 * BLOCK, 0]
        resumed = _ok(_child(env, "run", metas[killed_db], jobs[killed_db], "0"))
        assert resumed["status"] == "COMPLETED", resumed

        assert resumed["rows_done"] == full["rows_done"] == sum(TABLES.values())
        for table, count in TABLES.items():
            want, got = server.rows(full_db, table), server.rows(killed_db, table)
            assert len(want) == count
            assert _digest(got) == _digest(want), table

        def errors(dst: str) -> list[tuple[Any, ...]]:
            page = PgPersistence(metas[dst]).load_clone_job_errors_page(
                jobs[dst], limit=10_000, offset=0
            )
            # Without row_index: an unsorted ClickHouse table may arrive in another
            # order on the second read, and the offset names the arrival order.
            return sorted(
                ((e["table_name"], e["field"], e["original"], e["error"]) for e in page), key=repr
            )

        want_errors = errors(full_db)
        assert want_errors, "the dataset is built to produce error rows"
        assert errors(killed_db) == want_errors
    finally:
        for db in (src, killed_db, full_db):
            server.drop(db)
        for dst in (killed_db, full_db):
            _Pg().drop(f"norm_app_r4_{dst.removeprefix('norm_r4_')}")

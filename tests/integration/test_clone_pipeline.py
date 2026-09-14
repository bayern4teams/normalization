"""End-to-end DB-clone-and-normalize integration tests against REAL
running Postgres and ClickHouse containers (compose.yaml's demo-postgres/
demo-clickhouse — the same containers test_readonly_connectors.py uses for
the origin side). A second database on the SAME demo container stands in
for "a second, write-capable credential, same server" (decision #2) — see
tests/integration/fixtures/{postgres,clickhouse}-init for the added
`writable_user` role/user.

Proves, against real databases, not mocks:
1. Phase 1 DDL correctness (types/PK replicated on Postgres, ORDER BY/
   engine replicated on ClickHouse).
2. Phase 2 population: real normalization lands in the destination cell,
   a deliberately-bad value lands with its ORIGINAL value plus a recorded
   error (decision #8/#9).
3. Resume: re-invoking the executor on an already-fully-processed
   (crash-simulated back to RUNNING) job does not duplicate rows
   (decision #10).
4. The origin is never written to.

Requires: docker compose up -d postgres demo-postgres demo-clickhouse
"""

from __future__ import annotations

import os
import time
import uuid

import clickhouse_connect
import psycopg
import pytest
from cryptography.fernet import Fernet
from normalizers.email import EmailNormalizer
from normalizers.passthrough import PassthroughNormalizer
from normapi import clone_executor
from normapi.pg_persistence import PgPersistence
from normcore import Dispatcher, NormalizerRegistry

APP_PG_DSN = os.environ.get(
    "TEST_APP_PG_DSN", "postgresql://normalization:normalization@localhost:5535/normalization"
)
PG_HOST = os.environ.get("TEST_PG_HOST", "localhost")
PG_PORT = int(os.environ.get("TEST_PG_PORT", "5434"))
CH_HOST = os.environ.get("TEST_CLICKHOUSE_HOST", "localhost")
CH_PORT = int(os.environ.get("TEST_CLICKHOUSE_PORT", "8124"))

_TERMINAL = {"COMPLETED", "FAILED"}


@pytest.fixture(autouse=True)
def _secret_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NORM_SECRET_KEY", Fernet.generate_key().decode())


@pytest.fixture
def persistence() -> PgPersistence:
    p = PgPersistence(APP_PG_DSN)
    p.ensure_schema()
    return p


def _dispatcher() -> Dispatcher:
    registry = NormalizerRegistry()
    registry.register(PassthroughNormalizer())
    registry.register(EmailNormalizer())
    return Dispatcher(registry, env_id="test-clone-pipeline")


def _wait_for_terminal(persistence: PgPersistence, job_id: str, timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = persistence.get_clone_job(job_id)
        if job["status"] in _TERMINAL:
            return job
        time.sleep(0.1)
    msg = f"clone job {job_id} did not reach a terminal status within {timeout}s"
    raise TimeoutError(msg)


@pytest.mark.integration
def test_postgres_clone_pipeline_ddl_population_errors_and_resume(persistence: PgPersistence) -> None:
    dest_database = f"clone_pg_{uuid.uuid4().hex[:8]}"

    source_conn = persistence.save_connection(
        str(uuid.uuid4()), engine="postgres", host=PG_HOST, port=PG_PORT,
        username="readonly_user", password="readonly_pass",
    )
    dest_conn = persistence.save_connection(
        str(uuid.uuid4()), engine="postgres", host=PG_HOST, port=PG_PORT,
        username="writable_user", password="writable_pass",
    )

    job = clone_executor.create_clone_job(
        persistence,
        request={
            "source_connection_id": source_conn["connection_id"],
            "source_database": "source_demo",
            "destination_connection_id": dest_conn["connection_id"],
            "destination_database": dest_database,
            "field_configs": {"clone_source": {"email": "EMAIL"}},
        },
    )
    job_id = job["job_id"]
    assert job["status"] == "PENDING_DB_CREATE"
    assert {"customers", "clone_source"} <= set(job["tables"])

    # Decision #6: the app never issues CREATE DATABASE — run it by hand,
    # exactly the text the app would show the user, via the WRITABLE
    # (destination) credential against the always-present `postgres`
    # maintenance database.
    admin_dsn = f"postgresql://writable_user:writable_pass@{PG_HOST}:{PG_PORT}/postgres"
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(clone_executor.create_database_sql(dest_database))

    job = clone_executor.verify_and_create_schema(persistence, job_id)
    assert job["status"] == "SCHEMA_READY"

    dest_dsn = f"postgresql://writable_user:writable_pass@{PG_HOST}:{PG_PORT}/{dest_database}"
    with psycopg.connect(dest_dsn) as conn:
        rows = conn.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = 'clone_source' ORDER BY ordinal_position"
        ).fetchall()
        columns = dict(rows)
        assert columns["email"] == "text"  # EMAIL semantic type -> TEXT (SEMANTIC_TYPE_TO_PG_TYPE)
        pk_cols = conn.execute(
            "SELECT a.attname FROM pg_index i "
            "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
            "WHERE i.indrelid = 'clone_source'::regclass AND i.indisprimary"
        ).fetchall()
        assert [c[0] for c in pk_cols] == ["id"]
        assert conn.execute("SELECT count(*) FROM clone_source").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM customers").fetchone()[0] == 0

    started = clone_executor.start_phase2(persistence, _dispatcher(), None, job_id)
    assert started is True
    job = _wait_for_terminal(persistence, job_id)
    assert job["status"] == "COMPLETED", job.get("error")
    assert job["progress"]["rows_done"] == 5  # 3 customers + 2 clone_source
    assert sorted(job["progress"]["tables_completed"]) == sorted(job["tables"])

    with psycopg.connect(dest_dsn) as conn:
        rows = dict(conn.execute("SELECT id, email FROM clone_source ORDER BY id").fetchall())
        assert rows[1] != "Valid.User@EXAMPLE.com"  # real normalization happened
        assert rows[1].endswith("@example.com")
        assert rows[2] == "not-an-email"  # decision #8: failed value falls back to original
        assert conn.execute("SELECT count(*) FROM customers").fetchone()[0] == 3

    errors = persistence.load_clone_job_errors_page(job_id, limit=100, offset=0)
    bad_value_errors = [e for e in errors if e["table_name"] == "clone_source" and e["field"] == "email"]
    assert len(bad_value_errors) == 1
    assert bad_value_errors[0]["original"] == "not-an-email"
    assert bad_value_errors[0]["error"]

    # Resume proof (decision #10): simulate a crash by resetting an
    # already-fully-completed job back to RUNNING, then invoke the
    # executor again. The checkpoint already covers every row, so this
    # must skip everything and NOT duplicate rows.
    job["status"] = "RUNNING"
    persistence.save_clone_job(job_id, job)
    started_again = clone_executor.start_phase2(persistence, _dispatcher(), None, job_id)
    assert started_again is True
    job = _wait_for_terminal(persistence, job_id)
    assert job["status"] == "COMPLETED"
    assert job["progress"]["rows_done"] == 5  # unchanged — nothing re-inserted

    with psycopg.connect(dest_dsn) as conn:
        assert conn.execute("SELECT count(*) FROM clone_source").fetchone()[0] == 2
        assert conn.execute("SELECT count(*) FROM customers").fetchone()[0] == 3

    # Origin untouched.
    origin_dsn = f"postgresql://readonly_user:readonly_pass@{PG_HOST}:{PG_PORT}/source_demo"
    with psycopg.connect(origin_dsn) as conn:
        origin_rows = conn.execute("SELECT id, email FROM clone_source ORDER BY id").fetchall()
        assert origin_rows == [(1, "Valid.User@EXAMPLE.com"), (2, "not-an-email")]


@pytest.mark.integration
def test_clickhouse_clone_pipeline_ddl_population_errors_and_resume(persistence: PgPersistence) -> None:
    dest_database = f"clone_ch_{uuid.uuid4().hex[:8]}"

    source_conn = persistence.save_connection(
        str(uuid.uuid4()), engine="clickhouse", host=CH_HOST, port=CH_PORT,
        username="readonly_user", password="readonly_pass",
    )
    dest_conn = persistence.save_connection(
        str(uuid.uuid4()), engine="clickhouse", host=CH_HOST, port=CH_PORT,
        username="writable_user", password="writable_pass",
    )

    job = clone_executor.create_clone_job(
        persistence,
        request={
            "source_connection_id": source_conn["connection_id"],
            "source_database": "default",
            "destination_connection_id": dest_conn["connection_id"],
            "destination_database": dest_database,
            "field_configs": {"clone_source": {"email": "EMAIL"}},
        },
    )
    job_id = job["job_id"]
    assert job["status"] == "PENDING_DB_CREATE"
    assert {"customers", "clone_source"} <= set(job["tables"])

    admin_client = clickhouse_connect.get_client(
        host=CH_HOST, port=CH_PORT, username="writable_user", password="writable_pass"
    )
    admin_client.command(clone_executor.create_database_sql(dest_database))
    admin_client.close()

    job = clone_executor.verify_and_create_schema(persistence, job_id)
    assert job["status"] == "SCHEMA_READY"

    dest_client = clickhouse_connect.get_client(
        host=CH_HOST, port=CH_PORT, username="writable_user", password="writable_pass",
        database=dest_database,
    )
    col_result = dest_client.query(
        "SELECT name, type FROM system.columns WHERE database = {db:String} AND table = 'clone_source'",
        parameters={"db": dest_database},
    )
    col_types = dict(col_result.result_rows)
    assert col_types["email"] == "Nullable(String)"  # EMAIL semantic type -> String, wrapped Nullable
    engine_result = dest_client.query(
        "SELECT engine, sorting_key FROM system.tables WHERE database = {db:String} AND name = 'clone_source'",
        parameters={"db": dest_database},
    )
    engine_name, sorting_key = engine_result.result_rows[0]
    assert engine_name == "MergeTree"
    assert sorting_key == "id"
    assert dest_client.query("SELECT count() FROM clone_source").result_rows[0][0] == 0
    assert dest_client.query("SELECT count() FROM customers").result_rows[0][0] == 0

    started = clone_executor.start_phase2(persistence, _dispatcher(), None, job_id)
    assert started is True
    job = _wait_for_terminal(persistence, job_id)
    assert job["status"] == "COMPLETED", job.get("error")
    assert job["progress"]["rows_done"] == 5
    assert sorted(job["progress"]["tables_completed"]) == sorted(job["tables"])

    rows = dict(
        dest_client.query("SELECT id, email FROM clone_source ORDER BY id").result_rows
    )
    assert rows[1] != "Valid.User@EXAMPLE.com"
    assert rows[1].endswith("@example.com")
    assert rows[2] == "not-an-email"
    assert dest_client.query("SELECT count() FROM customers").result_rows[0][0] == 3

    errors = persistence.load_clone_job_errors_page(job_id, limit=100, offset=0)
    bad_value_errors = [e for e in errors if e["table_name"] == "clone_source" and e["field"] == "email"]
    assert len(bad_value_errors) == 1
    assert bad_value_errors[0]["original"] == "not-an-email"

    job["status"] = "RUNNING"
    persistence.save_clone_job(job_id, job)
    started_again = clone_executor.start_phase2(persistence, _dispatcher(), None, job_id)
    assert started_again is True
    job = _wait_for_terminal(persistence, job_id)
    assert job["status"] == "COMPLETED"
    assert job["progress"]["rows_done"] == 5

    assert dest_client.query("SELECT count() FROM clone_source").result_rows[0][0] == 2
    assert dest_client.query("SELECT count() FROM customers").result_rows[0][0] == 3
    dest_client.close()

    origin_client = clickhouse_connect.get_client(
        host=CH_HOST, port=CH_PORT, username="readonly_user", password="readonly_pass"
    )
    origin_rows = origin_client.query("SELECT id, email FROM clone_source ORDER BY id").result_rows
    assert list(origin_rows) == [(1, "Valid.User@EXAMPLE.com"), (2, "not-an-email")]
    origin_client.close()

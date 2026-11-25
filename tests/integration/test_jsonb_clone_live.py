"""The live `company.aliases` incident, end to end against the REAL demo
Postgres (tests/integration/fixtures/postgres-init/02-jsonb-demo.sql).

Two bugs in one jsonb column, both reported to the UI as the same
withheld `InvalidTextRepresentation`:

1. mixed-shape chunks (null/list/dict together): Arrow cannot unify, the
   old `_to_arrow` fallback `str()`d the values into PYTHON syntax —
   fixed in v0.1.2 (test_jsonb_arrow_fallback.py keeps the fallback
   honest).
2. uniform-shape chunks (all lists — the COMMON case, and exactly what
   killed the coworker's re-runs on v0.1.2): Arrow SUCCEEDS, the fallback
   never runs, raw Python lists reach the INSERT, and psycopg adapts a
   list to a SQL ARRAY: `invalid input syntax for type json`. Fixed at
   the source-read boundary (json columns are selected as text).

Also proven here (the same incident's follow-ups):
- the destination stores the JSON document, not text-of-JSON and not a
  SQL array;
- re-running a clone over a destination whose tables exist from a
  crashed/failed earlier run REUSES a structurally identical table
  instead of dying on `relation already exists` (the coworker's second
  failure mode), and a structurally different table fails with a named,
  actionable message.

Requires: docker compose up -d postgres demo-postgres (fixture 02 applied).
"""

from __future__ import annotations

import os
import time
import uuid

import psycopg
import pytest
from cryptography.fernet import Fernet
from normalizers.passthrough import PassthroughNormalizer
from normapi.pg_persistence import PgPersistence

from normapi import clone_executor
from normcore import Dispatcher, NormalizerRegistry

pytestmark = pytest.mark.integration

APP_PG_DSN = os.environ.get(
    "TEST_APP_PG_DSN", "postgresql://normalization:***@localhost:5535/normalization"
)
PG_HOST = os.environ.get("TEST_PG_HOST", "localhost")
PG_PORT = int(os.environ.get("TEST_PG_PORT", "5434"))

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
    return Dispatcher(registry, env_id="test-jsonb-clone")


def _wait_for_terminal(persistence: PgPersistence, job_id: str, timeout: float = 120.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = persistence.get_clone_job(job_id)
        if job["status"] in _TERMINAL:
            return job
        time.sleep(0.2)
    msg = f"clone job {job_id} did not reach a terminal status within {timeout}s"
    raise TimeoutError(msg)


def _clone_job(persistence: PgPersistence, dest_database: str, create_database: bool = True) -> str:
    source_conn = persistence.save_connection(
        str(uuid.uuid4()),
        engine="postgres",
        host=PG_HOST,
        port=PG_PORT,
        username="readonly_user",
        password="***",
    )
    dest_conn = persistence.save_connection(
        str(uuid.uuid4()),
        engine="postgres",
        host=PG_HOST,
        port=PG_PORT,
        username="writable_user",
        password="***",
    )
    job = clone_executor.create_clone_job(
        persistence,
        request={
            "source_connection_id": source_conn["connection_id"],
            "source_database": "jsonb_demo",
            "destination_connection_id": dest_conn["connection_id"],
            "destination_database": dest_database,
            "field_configs": {},
        },
    )
    admin_dsn = f"postgresql://writable_user:***@{PG_HOST}:{PG_PORT}/postgres"
    if create_database:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(clone_executor.create_database_sql(dest_database))
    job = clone_executor.verify_and_create_schema(persistence, job["job_id"])
    assert job["status"] == "SCHEMA_READY"
    return job["job_id"]


def test_jsonb_uniform_and_mixed_chunks_clone_into_jsonb_columns(
    persistence: PgPersistence,
) -> None:
    dest_database = f"jsonb_clone_{uuid.uuid4().hex[:8]}"
    job_id = _clone_job(persistence, dest_database)

    started = clone_executor.start_phase2(persistence, _dispatcher(), None, job_id)
    assert started is True
    job = _wait_for_terminal(persistence, job_id)
    # Before the source-read fix this FAILED on the first INSERT with the
    # all-lists chunk (psycopg SQL-array adaptation).
    assert job["status"] == "COMPLETED", job.get("error")

    dest_dsn = f"postgresql://writable_user:***@{PG_HOST}:{PG_PORT}/{dest_database}"
    with psycopg.connect(dest_dsn) as conn:
        assert conn.execute("SELECT count(*) FROM jsonb_source").fetchone()[0] == 4000
        # Stored AS jsonb documents (a SQL array would fail jsonb_typeof;
        # text-of-JSON in a jsonb column is impossible by type).
        shapes = conn.execute(
            "SELECT jsonb_typeof(tags), count(*) FROM jsonb_source GROUP BY 1"
        ).fetchall()
        assert dict(shapes) == {"array": 2000, "object": 2000}
        payload = conn.execute(
            "SELECT jsonb_typeof(payload), count(*) FROM jsonb_source GROUP BY 1"
        ).fetchall()
        assert dict(payload) == {"array": 1333, None: 1333, "object": 1334}
        # Round-trip faithfulness, not just validity.
        row = conn.execute(
            "SELECT payload, tags FROM jsonb_source WHERE id = 1"
        ).fetchone()
        assert row[0] == {"k": 1}
        assert row[1] == ["x"]
        row = conn.execute(
            "SELECT payload, tags FROM jsonb_source WHERE id = 2001"
        ).fetchone()
        assert row[1] == {"deep": {"n": [1, 2]}}

    admin_dsn = f"postgresql://writable_user:***@{PG_HOST}:{PG_PORT}/postgres"
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE {dest_database}")


def test_existing_matching_destination_table_is_reused_not_fatal(
    persistence: PgPersistence,
) -> None:
    """The coworker's second failure mode: a new job over a destination a
    crashed run already created. Identical structure -> reuse (the resume
    story); the job must COMPLETE, not die on `relation already exists`."""
    dest_database = f"jsonb_reuse_{uuid.uuid4().hex[:8]}"
    first = _clone_job(persistence, dest_database)
    clone_executor.start_phase2(persistence, _dispatcher(), None, first)
    job = _wait_for_terminal(persistence, first)
    assert job["status"] == "COMPLETED", job.get("error")

    # A fresh job, same destination database, same plan: Phase 1 must
    # accept the existing table instead of raising DuplicateTable.
    second = _clone_job(persistence, dest_database, create_database=False)
    clone_executor.start_phase2(persistence, _dispatcher(), None, second)
    job2 = _wait_for_terminal(persistence, second)
    assert job2["status"] == "COMPLETED", job2.get("error")

    dest_dsn = f"postgresql://writable_user:***@{PG_HOST}:{PG_PORT}/{dest_database}"
    # ON CONFLICT DO NOTHING on the replicated PK: the re-run is a no-op,
    # no duplicated rows (decision #11 doing its job on the reuse path).
    with psycopg.connect(dest_dsn) as conn:
        assert conn.execute("SELECT count(*) FROM jsonb_source").fetchone()[0] == 4000
    admin_dsn = f"postgresql://writable_user:***@{PG_HOST}:{PG_PORT}/postgres"
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE {dest_database}")


def test_existing_different_destination_table_names_the_difference(
    persistence: PgPersistence,
) -> None:
    """A leftover table from a DIFFERENT plan is not this job's table:
    the job fails with the names and types that differ — never a
    withheld, useless message."""
    dest_database = f"jsonb_mismatch_{uuid.uuid4().hex[:8]}"
    admin_dsn = f"postgresql://writable_user:***@{PG_HOST}:{PG_PORT}/postgres"
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(f"CREATE DATABASE {dest_database}")
    dest_dsn = f"postgresql://writable_user:***@{PG_HOST}:{PG_PORT}/{dest_database}"
    with psycopg.connect(dest_dsn, autocommit=True) as conn:
        # Same table name, wrong structure: text instead of jsonb, and a
        # column the plan would not create.
        conn.execute("CREATE TABLE jsonb_source (id integer PRIMARY KEY, payload text, extra int)")

    # Build the job by hand (skip _clone_job's CREATE DATABASE — it exists).
    source_conn = persistence.save_connection(
        str(uuid.uuid4()),
        engine="postgres",
        host=PG_HOST,
        port=PG_PORT,
        username="readonly_user",
        password="***",
    )
    dest_conn = persistence.save_connection(
        str(uuid.uuid4()),
        engine="postgres",
        host=PG_HOST,
        port=PG_PORT,
        username="writable_user",
        password="***",
    )
    job = clone_executor.create_clone_job(
        persistence,
        request={
            "source_connection_id": source_conn["connection_id"],
            "source_database": "jsonb_demo",
            "destination_connection_id": dest_conn["connection_id"],
            "destination_database": dest_database,
            "field_configs": {},
        },
    )
    with pytest.raises(clone_executor.CloneJobStateError) as excinfo:
        clone_executor.verify_and_create_schema(persistence, job["job_id"])
    message = str(excinfo.value)
    assert "already exists" in message and "does not match" in message
    assert "payload" in message  # names the mismatching column
    assert "text" in message  # and what it found vs expects
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE {dest_database}")

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

import decimal
import os
import time
import uuid

import clickhouse_connect
import psycopg
import pytest
from cryptography.fernet import Fernet
from normalizers.boolean import BooleanNormalizer
from normalizers.date import DateNormalizer
from normalizers.email import EmailNormalizer
from normalizers.money import MoneyNormalizer
from normalizers.numeric import NumericNormalizer
from normalizers.passthrough import PassthroughNormalizer
from normapi.pg_persistence import PgPersistence

from normapi import clone_executor
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
    registry.register(DateNormalizer())
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
def test_postgres_clone_pipeline_ddl_population_errors_and_resume(
    persistence: PgPersistence,
) -> None:
    dest_database = f"clone_pg_{uuid.uuid4().hex[:8]}"

    source_conn = persistence.save_connection(
        str(uuid.uuid4()),
        engine="postgres",
        host=PG_HOST,
        port=PG_PORT,
        username="readonly_user",
        password="readonly_pass",
    )
    dest_conn = persistence.save_connection(
        str(uuid.uuid4()),
        engine="postgres",
        host=PG_HOST,
        port=PG_PORT,
        username="writable_user",
        password="writable_pass",
    )

    job = clone_executor.create_clone_job(
        persistence,
        request={
            "source_connection_id": source_conn["connection_id"],
            "source_database": "source_demo",
            "destination_connection_id": dest_conn["connection_id"],
            "destination_database": dest_database,
            "field_configs": {"clone_source": {"email": "EMAIL", "founded": "DATE"}},
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
        # DATE semantic type ALSO -> text, deliberately, not a native `date`
        # column: a failed value's raw fallback (decision #8) must always be
        # insertable, and no native type guarantees that. Regression for a
        # real bug (see SEMANTIC_TYPE_TO_PG_TYPE's docstring).
        assert columns["founded"] == "text"
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
    # 3 customers + 2 clone_source + 3 typed_source: a clone copies EVERY
    # table in the source database, so adding a fixture table moves this.
    assert job["progress"]["rows_done"] == 8
    assert sorted(job["progress"]["tables_completed"]) == sorted(job["tables"])

    with psycopg.connect(dest_dsn) as conn:
        rows = conn.execute("SELECT id, email, founded FROM clone_source ORDER BY id").fetchall()
        by_id = {r[0]: (r[1], r[2]) for r in rows}
        email1, founded1 = by_id[1]
        assert email1 != "Valid.User@EXAMPLE.com"  # real normalization happened
        assert email1.endswith("@example.com")
        assert founded1 == "1989-12-11"  # valid date, normalized cleanly
        email2, founded2 = by_id[2]
        assert email2 == "not-an-email"  # decision #8: failed value falls back to original
        assert founded2 == "no-date-here"  # same, for the DATE column — this used to crash the job
        assert conn.execute("SELECT count(*) FROM customers").fetchone()[0] == 3

    errors = persistence.load_clone_job_errors_page(job_id, limit=100, offset=0)
    bad_value_errors = {
        (e["field"], e["original"]): e["error"] for e in errors if e["table_name"] == "clone_source"
    }
    assert bad_value_errors.get(("email", "not-an-email"))
    assert bad_value_errors.get(("founded", "no-date-here"))

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
    assert job["progress"]["rows_done"] == 8  # unchanged — nothing re-inserted

    with psycopg.connect(dest_dsn) as conn:
        assert conn.execute("SELECT count(*) FROM clone_source").fetchone()[0] == 2
        assert conn.execute("SELECT count(*) FROM customers").fetchone()[0] == 3

    # Origin untouched.
    origin_dsn = f"postgresql://readonly_user:readonly_pass@{PG_HOST}:{PG_PORT}/source_demo"
    with psycopg.connect(origin_dsn) as conn:
        origin_rows = conn.execute("SELECT id, email FROM clone_source ORDER BY id").fetchall()
        assert origin_rows == [(1, "Valid.User@EXAMPLE.com"), (2, "not-an-email")]


@pytest.mark.integration
def test_clickhouse_clone_pipeline_ddl_population_errors_and_resume(
    persistence: PgPersistence,
) -> None:
    dest_database = f"clone_ch_{uuid.uuid4().hex[:8]}"

    source_conn = persistence.save_connection(
        str(uuid.uuid4()),
        engine="clickhouse",
        host=CH_HOST,
        port=CH_PORT,
        username="readonly_user",
        password="readonly_pass",
    )
    dest_conn = persistence.save_connection(
        str(uuid.uuid4()),
        engine="clickhouse",
        host=CH_HOST,
        port=CH_PORT,
        username="writable_user",
        password="writable_pass",
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
        host=CH_HOST,
        port=CH_PORT,
        username="writable_user",
        password="writable_pass",
        database=dest_database,
    )
    col_result = dest_client.query(
        "SELECT name, type FROM system.columns "
        "WHERE database = {db:String} AND table = 'clone_source'",
        parameters={"db": dest_database},
    )
    col_types = dict(col_result.result_rows)
    assert (
        col_types["email"] == "Nullable(String)"
    )  # EMAIL semantic type -> String, wrapped Nullable
    engine_result = dest_client.query(
        "SELECT engine, sorting_key FROM system.tables "
        "WHERE database = {db:String} AND name = 'clone_source'",
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

    rows = dict(dest_client.query("SELECT id, email FROM clone_source ORDER BY id").result_rows)
    assert rows[1] != "Valid.User@EXAMPLE.com"
    assert rows[1].endswith("@example.com")
    assert rows[2] == "not-an-email"
    assert dest_client.query("SELECT count() FROM customers").result_rows[0][0] == 3

    errors = persistence.load_clone_job_errors_page(job_id, limit=100, offset=0)
    bad_value_errors = [
        e for e in errors if e["table_name"] == "clone_source" and e["field"] == "email"
    ]
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


def _typed_dispatcher() -> Dispatcher:
    registry = NormalizerRegistry()
    registry.register(PassthroughNormalizer())
    registry.register(NumericNormalizer())
    registry.register(MoneyNormalizer())
    registry.register(BooleanNormalizer())
    return Dispatcher(registry, env_id="test-typed-clone")


def _run_to_completion(
    persistence: PgPersistence, dispatcher: Dispatcher, job_id: str, dest_database: str
) -> dict:
    """Phase 1 + the by-hand CREATE DATABASE (decision #6) + Phase 2."""
    admin_dsn = f"postgresql://writable_user:writable_pass@{PG_HOST}:{PG_PORT}/postgres"
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(clone_executor.create_database_sql(dest_database))
    job = clone_executor.verify_and_create_schema(persistence, job_id)
    assert job["status"] == "SCHEMA_READY"
    assert clone_executor.start_phase2(persistence, dispatcher, None, job_id) is True
    job = _wait_for_terminal(persistence, job_id)
    assert job["status"] == "COMPLETED", job.get("error")
    return job


def _pg_connections(persistence: PgPersistence) -> tuple[dict, dict]:
    source_conn = persistence.save_connection(
        str(uuid.uuid4()),
        engine="postgres",
        host=PG_HOST,
        port=PG_PORT,
        username="readonly_user",
        password="readonly_pass",
    )
    dest_conn = persistence.save_connection(
        str(uuid.uuid4()),
        engine="postgres",
        host=PG_HOST,
        port=PG_PORT,
        username="writable_user",
        password="writable_pass",
    )
    return source_conn, dest_conn


@pytest.mark.integration
def test_typed_destination_columns_against_real_postgres(persistence: PgPersistence) -> None:
    """The typed-column DDL and the pre-insert cast had unit tests only.

    Everything they promise is a claim about a real database — that
    `NUMERIC(38,4)` is accepted DDL, that a Decimal reaches the column
    without going through a float, that an uncastable value becomes NULL
    instead of aborting the chunk. None of that can be proven with a mock.
    """
    dest_database = f"clone_typed_{uuid.uuid4().hex[:8]}"
    source_conn, dest_conn = _pg_connections(persistence)

    job = clone_executor.create_clone_job(
        persistence,
        request={
            "source_connection_id": source_conn["connection_id"],
            "source_database": "source_demo",
            "destination_connection_id": dest_conn["connection_id"],
            "destination_database": dest_database,
            "typed_destination_columns": True,
            "field_configs": {
                "typed_source": {"amount": "NUMERIC", "price": "MONEY", "active": "BOOLEAN"}
            },
        },
    )
    job_id = job["job_id"]
    job = _run_to_completion(persistence, _typed_dispatcher(), job_id, dest_database)

    dest_dsn = f"postgresql://writable_user:writable_pass@{PG_HOST}:{PG_PORT}/{dest_database}"
    with psycopg.connect(dest_dsn) as conn:
        columns = dict(
            conn.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = 'typed_source'"
            ).fetchall()
        )
        assert columns["amount"] == "numeric"
        assert columns["price"] == "numeric"
        assert columns["active"] == "boolean"
        # MONEY's currency would otherwise be dropped on the floor: the
        # amount is what the column can sum, the currency is what makes
        # the sum mean anything.
        assert columns["price_currency"] == "text"
        # The primary key is never typed (a ClickHouse sorting key cannot
        # be Nullable, and a NULL key is the least acceptable NULL there
        # is) — asserted here because it is the same code path on both.
        assert columns["id"] == "integer"

        rows = conn.execute(
            "SELECT id, amount, price, price_currency, active FROM typed_source ORDER BY id"
        ).fetchall()
        by_id = {r[0]: r[1:] for r in rows}

        # Both locales' separators reach the SAME native decimal, and it is
        # a Decimal, not a float — 1234.56 is not representable in binary
        # floating point, so a float round-trip here would not compare
        # equal.
        assert by_id[1][0] == decimal.Decimal("1234.56")
        assert by_id[2][0] == decimal.Decimal("1234.56")
        assert isinstance(by_id[1][0], decimal.Decimal)

        # "€1.234,56" and "1234.56 USD" agree on the amount and differ
        # only in the companion column.
        assert by_id[1][1] == decimal.Decimal("1234.5600")
        assert by_id[1][2] == "EUR"
        assert by_id[2][1] == decimal.Decimal("1234.5600")
        assert by_id[2][2] == "USD"

        assert by_id[1][3] is True  # "yes"
        assert by_id[2][3] is False  # "NO"

        # Row 3: nothing castable. The whole point is that the chunk still
        # inserted — the old behaviour was the database rejecting it and
        # taking the job (and the error rows explaining why) down with it.
        assert by_id[3] == (None, None, None, None)

        # And the column really is arithmetic now, which is the feature.
        total = conn.execute("SELECT sum(price) FROM typed_source").fetchone()[0]
        assert total == decimal.Decimal("2469.1200")

    errors = persistence.load_clone_job_errors_page(job_id, limit=100, offset=0)
    reported = {(e["field"], e["original"]): e["error"] for e in errors}
    assert "not a number" in reported[("amount", "not-a-number")]
    # "free" fails in MoneyNormalizer, so it arrives as its own raw string
    # and then fails the cast as well; either message is a true report.
    assert ("price", "free") in reported
    # The regression this test exists for: "maybe" is not a failure — it
    # normalizes to NORMALIZED with MissingKind.UNKNOWN_VALUE and a None
    # display — so neither decision #8 nor the cast said anything, and a
    # BOOLEAN column of "maybe"/"N/A" arrived 100% NULL looking like a
    # column that was simply empty at source.
    assert "means missing" in reported[("active", "maybe")]


@pytest.mark.integration
def test_in_place_normalization_swaps_the_real_table(persistence: PgPersistence) -> None:
    """In-place mode writes a staging table beside the original and swaps.

    Unit tests could only check the generated SQL strings. Whether Postgres
    actually accepts the rename pair, whether the swapped-in table keeps
    its primary key, and whether the original is really gone afterwards are
    facts about a live server.
    """
    database = f"inplace_{uuid.uuid4().hex[:8]}"
    admin_dsn = f"postgresql://writable_user:writable_pass@{PG_HOST}:{PG_PORT}/postgres"
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(clone_executor.create_database_sql(database))

    dsn = f"postgresql://writable_user:writable_pass@{PG_HOST}:{PG_PORT}/{database}"
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("CREATE TABLE amounts (id SERIAL PRIMARY KEY, amount TEXT)")
        conn.execute("INSERT INTO amounts (amount) VALUES ('1,234.56'), ('7.890,12')")

    # Same connection for source and destination: that IS in-place mode.
    conn_row = persistence.save_connection(
        str(uuid.uuid4()),
        engine="postgres",
        host=PG_HOST,
        port=PG_PORT,
        username="writable_user",
        password="writable_pass",
    )
    job = clone_executor.create_clone_job(
        persistence,
        request={
            "source_connection_id": conn_row["connection_id"],
            "source_database": database,
            "in_place": True,
            "field_configs": {"amounts": {"amount": "NUMERIC"}},
        },
    )
    job_id = job["job_id"]
    # No CREATE DATABASE step: in-place normalizes the database it read.
    job = clone_executor.verify_and_create_schema(persistence, job_id)
    assert job["status"] == "SCHEMA_READY"

    staging = clone_executor.staging_name("amounts")
    with psycopg.connect(dsn) as conn:
        present = {
            r[0]
            for r in conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            ).fetchall()
        }
        assert staging in present, "Phase 1 must create the staging table beside the original"
        assert "amounts" in present

    assert clone_executor.start_phase2(persistence, _typed_dispatcher(), None, job_id) is True
    job = _wait_for_terminal(persistence, job_id)
    assert job["status"] == "COMPLETED", job.get("error")

    with psycopg.connect(dsn) as conn:
        present = {
            r[0]
            for r in conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            ).fetchall()
        }
        assert "amounts" in present
        assert staging not in present, "the staging table must not survive the swap"

        rows = conn.execute("SELECT id, amount FROM amounts ORDER BY id").fetchall()
        assert [r[1] for r in rows] == ["1234.56", "7890.12"]

        pk_cols = conn.execute(
            "SELECT a.attname FROM pg_index i "
            "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
            "WHERE i.indrelid = 'amounts'::regclass AND i.indisprimary"
        ).fetchall()
        assert [c[0] for c in pk_cols] == ["id"], "the swapped-in table must keep its primary key"

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
from pathlib import Path

import clickhouse_connect
import psycopg
import pytest
from cryptography.fernet import Fernet
from normalizers.boolean import BooleanNormalizer
from normalizers.company import CompanyNormalizer
from normalizers.country import CountryNormalizer
from normalizers.date import DateNormalizer
from normalizers.email import EmailNormalizer
from normalizers.money import MoneyNormalizer
from normalizers.numeric import NumericNormalizer
from normalizers.passthrough import PassthroughNormalizer
from normalizers.phone import PhoneNormalizer
from normalizers.postcode import PostcodeNormalizer
from normapi.pg_persistence import PgPersistence
from normdict.loader import DictionaryLoader

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
    # 3 customers + 2 clone_source + 3 typed_source + 4 context_source
    # + 6 entity_country + 5 entity_phone + 25 mistyped_source
    # + 3 signal_phone + 3 signal_zip + 3 keyed_email + 4 quality_source:
    # a clone copies EVERY table in the source database, so adding a
    # fixture table moves this.
    assert job["progress"]["rows_done"] == 61
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
    assert job["progress"]["rows_done"] == 61  # unchanged — nothing re-inserted

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

        # Typed columns are the default, and in-place mode therefore
        # changes the SOURCE column's type when it swaps: a TEXT column of
        # "1,234.56" comes back as a real NUMERIC that SUM works on. That
        # is the loudest consequence of the default, so it is asserted
        # rather than left implicit.
        native = conn.execute(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'amounts' AND column_name = 'amount'"
        ).fetchone()[0]
        assert native == "numeric"

        rows = conn.execute("SELECT id, amount FROM amounts ORDER BY id").fetchall()
        assert [r[1] for r in rows] == [decimal.Decimal("1234.56"), decimal.Decimal("7890.12")]
        assert conn.execute("SELECT sum(amount) FROM amounts").fetchone()[0] == decimal.Decimal(
            "9124.68"
        )

        pk_cols = conn.execute(
            "SELECT a.attname FROM pg_index i "
            "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
            "WHERE i.indrelid = 'amounts'::regclass AND i.indisprimary"
        ).fetchall()
        assert [c[0] for c in pk_cols] == ["id"], "the swapped-in table must keep its primary key"


def _context_dispatcher() -> Dispatcher:
    registry = NormalizerRegistry()
    registry.register(PassthroughNormalizer())
    registry.register(CountryNormalizer())
    registry.register(PostcodeNormalizer())
    registry.register(BooleanNormalizer())
    return Dispatcher(registry, env_id="test-context-clone")


@pytest.mark.integration
def test_row_country_reaches_the_rest_of_its_row(persistence: PgPersistence) -> None:
    """Three things at once, because they are one pipeline pass.

    A COUNTRY column's answer now reaches the other columns of its own row
    as `ctx.country`, which is what POSTCODE was refusing to validate
    without: the only way `zip` can be reported INVALID here is if the
    country propagated. `comparison` — the ISO alpha-2 — gets a column of
    its own instead of being computed and discarded. And a column that
    normalization emptied is reported at the column level, which nothing
    said before: measured on a real source, typing one column NULLed 38.5%
    of it and the clone looked like a column that was merely sparse.

    No job-level country is set deliberately. Everything asserted here
    comes from the rows themselves.
    """
    dest_database = f"clone_ctx_{uuid.uuid4().hex[:8]}"
    source_conn, dest_conn = _pg_connections(persistence)

    job = clone_executor.create_clone_job(
        persistence,
        request={
            "source_connection_id": source_conn["connection_id"],
            "source_database": "source_demo",
            "destination_connection_id": dest_conn["connection_id"],
            "destination_database": dest_database,
            # Only what this test configures, so the assertions are about
            # propagation and not about what inference happened to guess.
            "autodetect_field_types": False,
            "field_configs": {
                "context_source": {
                    "country": "COUNTRY",
                    "other_country": "COUNTRY",
                    "zip": "POSTCODE",
                    "active": "BOOLEAN",
                }
            },
        },
    )
    job_id = job["job_id"]
    # Typed columns are the default now; `active` proves it without the
    # request having to ask.
    assert job["typed_destination_columns"] is True
    job = _run_to_completion(persistence, _context_dispatcher(), job_id, dest_database)

    dest_dsn = f"postgresql://writable_user:writable_pass@{PG_HOST}:{PG_PORT}/{dest_database}"
    with psycopg.connect(dest_dsn) as conn:
        columns = dict(
            conn.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = 'context_source'"
            ).fetchall()
        )
        assert columns["country_code"] == "text"
        assert columns["other_country_code"] == "text"
        assert columns["active"] == "boolean"
        # POSTCODE has no machine key distinct from its display form, so
        # it earns no companion — the rule is about `comparison`, not a
        # column for every semantic type.
        assert "zip_code" not in columns

        rows = conn.execute(
            "SELECT id, country, country_code, other_country_code, zip, active "
            "FROM context_source ORDER BY id"
        ).fetchall()
        by_id = {r[0]: r[1:] for r in rows}

        # The original column keeps `display`; the code goes beside it.
        # Before this, a column named CountryCode held "United States" and
        # joined against nothing.
        assert by_id[1][0] == "United States"
        assert by_id[1][1] == "US"
        # "US" and "United States" are the same country by different
        # names, and both land as the same code.
        assert by_id[1][2] == "US"
        assert by_id[3][1] == "GB"
        assert by_id[3][2] == "DE"
        assert by_id[4][:3] == (None, None, None)

        assert by_id[1][4] is True
        assert by_id[2][4] is False
        # "maybe" and "n/a" mean missing, not false.
        assert by_id[3][4] is None
        assert by_id[4][4] is None

    errors = persistence.load_clone_job_errors_page(job_id, limit=200, offset=0)
    ctx_errors = [e for e in errors if e["table_name"] == "context_source"]
    by_row: dict[int, dict[str, str]] = {}
    for e in ctx_errors:
        by_row.setdefault(e["row_index"], {})[e["field"]] = e["error"]

    # Row 2 (offset 1): the propagation this test exists for. A GB
    # postcode in a US row is INVALID — and POSTCODE can only say that if
    # it was told US, which only the row's own country column could do.
    assert "does not match the expected postcode format for US" in by_row[1]["zip"]

    # Row 3 (offset 2): two country columns that disagree. Both are
    # reported and NEITHER is used, so this row's `zip` is left alone even
    # though it is a valid GB postcode and one of the two columns said GB.
    assert "country conflict" in by_row[2]["other_country"]
    assert "GB" in by_row[2]["other_country"]
    assert "DE" in by_row[2]["other_country"]
    assert "zip" not in by_row[2]

    # Row 1 and row 4: a postcode with a country that fits, and a postcode
    # with no country at all. Neither is an error.
    assert 0 not in by_row
    assert "zip" not in by_row.get(3, {})

    # The column-level report, on the one offset no real row can occupy.
    column_report = by_row[-1]
    assert "50.0%" in column_report["active"]
    assert "2/4 values" in column_report["active"]
    # Columns that lost nothing are not reported — one row per gutted
    # column, not one per column.
    assert set(column_report) == {"active"}


def _entity_dispatcher() -> Dispatcher:
    registry = NormalizerRegistry()
    registry.register(PassthroughNormalizer())
    registry.register(CountryNormalizer())
    registry.register(PhoneNormalizer())
    return Dispatcher(registry, env_id="test-entity-clone")


@pytest.mark.integration
def test_a_siblings_country_reaches_a_phone_in_another_table(
    persistence: PgPersistence,
) -> None:
    """The cross-table half of country propagation, and the column-level
    wrong-semantic-type finding, in one pass because they are one pass.

    A company's country lives in its location rows; the phone that needs a
    country to parse lives in its company row. Phase 2 streams one table at
    a time and never holds two, so nothing could connect them — a UK
    landline stayed AMBIGUOUS next to a column that knew it was in the UK.
    Measured on a real source, this reaches 339,596 phone numbers across
    357 countries.

    Every guard is exercised: an entity whose rows disagree is dropped
    rather than resolved, an entity whose country column never resolved
    contributes nothing, a self-describing value is unaffected, and the
    entity id being TEXT in one table and INTEGER in the other still joins.
    """
    dest_database = f"clone_xtab_{uuid.uuid4().hex[:8]}"
    source_conn, dest_conn = _pg_connections(persistence)

    job = clone_executor.create_clone_job(
        persistence,
        request={
            "source_connection_id": source_conn["connection_id"],
            "source_database": "source_demo",
            "destination_connection_id": dest_conn["connection_id"],
            "destination_database": dest_database,
            "autodetect_field_types": False,
            "cross_table_entity_key": "company_key",
            "field_configs": {
                "entity_country": {"country_name": "COUNTRY"},
                "entity_phone": {"tel": "PHONE"},
            },
        },
    )
    job_id = job["job_id"]
    job = _run_to_completion(persistence, _entity_dispatcher(), job_id, dest_database)

    dest_dsn = f"postgresql://writable_user:writable_pass@{PG_HOST}:{PG_PORT}/{dest_database}"
    with psycopg.connect(dest_dsn) as conn:
        phones = dict(conn.execute("SELECT tel, tel_code FROM entity_phone ORDER BY id").fetchall())

    # Entity 11: only the map knows this is a UK number. A London landline
    # is not parseable at all without a region, and this is the assertion
    # the whole feature exists for.
    assert phones["+44 20 7930 4832"] == "+442079304832"
    # Entity 22: same, for a Berlin number — so it is the row's OWN entity
    # being looked up, not one country leaking across all rows.
    assert phones["+49 30 26431234"] == "+493026431234"

    # Entity 33's two location rows disagree (France vs Italy). Neither is
    # used, so its phone is untouched — picking one is the guess this
    # codebase does not make, even though guessing would have "worked"
    # here (the number is French).
    assert "01 42 60 30 30" in phones
    assert phones["01 42 60 30 30"] is None
    # Entity 44's country column held a description, not a country, so it
    # never entered the map.
    assert phones["0118 496 0000"] is None
    # A number that carries its own country code is unaffected by any of
    # this.
    assert phones["+1 650-253-0000"] == "+16502530000"

    errors = persistence.load_clone_job_errors_page(job_id, limit=200, offset=0)
    column_level = {
        (e["table_name"], e["field"]): e["error"] for e in errors if e["row_index"] == -1
    }

    # The map reports what it found, even when nothing went wrong: a map
    # that silently supplied nothing and a map that worked look identical
    # from the destination.
    summary = column_level[("", "")]
    assert "cross-table entity map on 'company_key'" in summary
    assert "2 entities with one country" in summary  # 11 and 22
    assert "1 dropped for disagreeing" in summary  # 33

    # The wrong-semantic-type finding: 1 of 6 values is not a country here,
    # which is under the reporting threshold, so `country_name` must NOT be
    # accused. The threshold is the whole point — a merely messy column is
    # not a mis-mapped one.
    assert ("entity_country", "country_name") not in column_level

    # And a signal-precedence assertion, because this table exercises it:
    # entity 11's second phone carries +1, which as an IMPLIED country
    # contradicts the GB its country column STATES. Stated wins, so entity
    # 11 keeps GB rather than being dropped as contradictory — which is what
    # happened the moment PHONE became a signal source, silently, because a
    # company legitimately has numbers in more than one country.
    assert phones["+44 20 7930 4832"] == "+442079304832"


@pytest.mark.integration
def test_a_column_that_is_not_its_semantic_type_is_reported_once(
    persistence: PgPersistence,
) -> None:
    """Mapping the SAME column to a type it mostly is not produces one
    column-level finding instead of a per-row finding nobody aggregates.

    `mistyped_source.looks_like_a_country` holds Wikidata-style
    descriptions, reproducing the real source where a COUNTRY-mapped column
    came back 99.2% INVALID.
    """
    dest_database = f"clone_mistyped_{uuid.uuid4().hex[:8]}"
    source_conn, dest_conn = _pg_connections(persistence)

    job = clone_executor.create_clone_job(
        persistence,
        request={
            "source_connection_id": source_conn["connection_id"],
            "source_database": "source_demo",
            "destination_connection_id": dest_conn["connection_id"],
            "destination_database": dest_database,
            "autodetect_field_types": False,
            "field_configs": {"mistyped_source": {"looks_like_a_country": "COUNTRY"}},
        },
    )
    job_id = job["job_id"]
    _run_to_completion(persistence, _entity_dispatcher(), job_id, dest_database)

    errors = persistence.load_clone_job_errors_page(job_id, limit=200, offset=0)
    column_level = [
        e for e in errors if e["row_index"] == -1 and e["field"] == "looks_like_a_country"
    ]
    assert len(column_level) == 1
    error = column_level[0]["error"]
    assert "100.0% of this column is not a COUNTRY" in error
    assert "wrong semantic type" in error
    # Real examples, because "100% is not a COUNTRY" is a number and
    # "Country located primarily in North America" is the answer.
    assert "Country located primarily in North America" in error

    # One row for 25 bad values, not 25 rows. Reading it per row means
    # reading every row to learn one fact about the column.
    per_row = [e for e in errors if e["row_index"] >= 0]
    assert len(per_row) == 25


def _signal_dispatcher() -> Dispatcher:
    registry = NormalizerRegistry()
    registry.register(PassthroughNormalizer())
    registry.register(PhoneNormalizer())
    registry.register(PostcodeNormalizer())
    return Dispatcher(registry, env_id="test-signal-clone")


@pytest.mark.integration
def test_a_phone_and_a_postcode_can_name_the_country_too(persistence: PgPersistence) -> None:
    """Neither table here has a COUNTRY column, and both still get a
    country — from a phone that carries its own +CC (247,469 values on a
    real source) and from a postcode only one country's format accepts
    (18.9% of 20,000 real distinct postcodes).

    Each signal reaches the OTHER table through the entity id, which is the
    point: a phone's +44 is useless to the phone itself and decisive for
    the postcode two tables over.
    """
    dest_database = f"clone_sig_{uuid.uuid4().hex[:8]}"
    source_conn, dest_conn = _pg_connections(persistence)

    job = clone_executor.create_clone_job(
        persistence,
        request={
            "source_connection_id": source_conn["connection_id"],
            "source_database": "source_demo",
            "destination_connection_id": dest_conn["connection_id"],
            "destination_database": dest_database,
            "autodetect_field_types": False,
            "cross_table_entity_key": "entity_key",
            "field_configs": {
                "signal_phone": {"tel": "PHONE"},
                "signal_zip": {"zip": "POSTCODE"},
            },
        },
    )
    job_id = job["job_id"]
    job = _run_to_completion(persistence, _signal_dispatcher(), job_id, dest_database)

    errors = persistence.load_clone_job_errors_page(job_id, limit=200, offset=0)
    column_level = {
        (e["table_name"], e["field"]): e["error"] for e in errors if e["row_index"] == -1
    }
    summary = column_level[("", "")]
    # Entity 1 from the phone's +44, entity 2 from the Canadian postcode.
    # Entity 3 has neither: a phone with no country code and a five-digit
    # postcode valid in 56 countries.
    assert "2 entities with one country" in summary
    assert "0 dropped for disagreeing" in summary

    dest_dsn = f"postgresql://writable_user:writable_pass@{PG_HOST}:{PG_PORT}/{dest_database}"
    with psycopg.connect(dest_dsn) as conn:
        phones = dict(
            conn.execute("SELECT entity_key, tel_code FROM signal_phone ORDER BY id").fetchall()
        )

    # Entity 2's phone is a bare Toronto local number. Nothing in its own
    # table could parse it; the POSTCODE in the other table could.
    assert phones[2] == "+14163922489"
    # Entity 1 carried its own +44 and is unaffected by any of this.
    assert phones[1] == "+442079304832"
    # Entity 3 had no signal anywhere, so it stays unparsed rather than
    # being given the most popular country in the map.
    assert phones[3] is None


def _quality_dispatcher() -> Dispatcher:
    registry = NormalizerRegistry()
    registry.register(PassthroughNormalizer())
    registry.register(PostcodeNormalizer())
    registry.register(CountryNormalizer())
    registry.register(EmailNormalizer())
    registry.register(
        CompanyNormalizer(DictionaryLoader(Path(__file__).parents[2] / "data" / "dictionaries"))
    )
    return Dispatcher(registry, env_id="test-quality-clone")


@pytest.mark.integration
def test_a_key_column_is_never_given_an_inferred_semantic_type(
    persistence: PgPersistence,
) -> None:
    """`keyed_email.contact_email` is the table's PRIMARY KEY and looks
    exactly like an email column, because it is one.

    Normalization is many-to-one: `ada@EXAMPLE.COM` and `ada@example.com`
    differ only in the domain's case, which EMAIL normalization folds, so
    they are two distinct keys with ONE normalized form. Inferring EMAIL
    here merges them — silently, and on a ReplacingMergeTree permanently.
    `work_email` holds the same data in a non-key column and IS detected,
    which is what makes this an exclusion rather than a gap in detection.
    """
    dest_database = f"clone_keyed_{uuid.uuid4().hex[:8]}"
    source_conn, dest_conn = _pg_connections(persistence)

    job = clone_executor.create_clone_job(
        persistence,
        request={
            "source_connection_id": source_conn["connection_id"],
            "source_database": "source_demo",
            "destination_connection_id": dest_conn["connection_id"],
            "destination_database": dest_database,
            "autodetect_field_types": True,
            "field_configs": {},
        },
        registry=_quality_dispatcher().registry,
    )
    configs = job["field_configs"].get("keyed_email", {})
    assert "contact_email" not in configs
    assert configs.get("work_email") == "EMAIL"

    _run_to_completion(persistence, _quality_dispatcher(), job["job_id"], dest_database)

    dest_dsn = f"postgresql://writable_user:writable_pass@{PG_HOST}:{PG_PORT}/{dest_database}"
    with psycopg.connect(dest_dsn) as conn:
        rows = conn.execute(
            "SELECT contact_email, work_email FROM keyed_email ORDER BY contact_email"
        ).fetchall()
    # All three keys survive as they arrived; the two that differ only in
    # case are still two rows.
    assert [r[0] for r in rows] == ["ada@EXAMPLE.COM", "ada@example.com", "grace@Example.com"]
    # The non-key copy of the same data WAS normalized — and the first two
    # collapsed to the same value there, which is what would have happened
    # to the key.
    assert sorted(r[1] for r in rows) == [
        "ada@example.com",
        "ada@example.com",
        "grace@example.com",
    ]


@pytest.mark.integration
def test_the_job_reports_what_each_column_achieved(persistence: PgPersistence) -> None:
    """Three columns, three different outcomes, one report.

    `zip_no_country` is 100% AMBIGUOUS and perfectly well typed — the
    normalizer refused to guess a country, which is not a failure and must
    not read as one. `bad_country` is mostly INVALID. `messy_company`
    normalizes cleanly. Reconstructing this previously meant querying the
    destination column by column after the fact.
    """
    dest_database = f"clone_qual_{uuid.uuid4().hex[:8]}"
    source_conn, dest_conn = _pg_connections(persistence)

    job = clone_executor.create_clone_job(
        persistence,
        request={
            "source_connection_id": source_conn["connection_id"],
            "source_database": "source_demo",
            "destination_connection_id": dest_conn["connection_id"],
            "destination_database": dest_database,
            "autodetect_field_types": False,
            "field_configs": {
                "quality_source": {
                    "zip_no_country": "POSTCODE",
                    "bad_country": "COUNTRY",
                    "messy_company": "COMPANY_NAME",
                }
            },
        },
    )
    job_id = job["job_id"]
    job = _run_to_completion(persistence, _quality_dispatcher(), job_id, dest_database)

    quality = job["quality"]["quality_source"]
    # 3 of 4 postcodes had no country to validate against, so the
    # normalizer refused to guess. The fourth is the row whose own
    # `bad_country` column says "United States" — within-row country
    # propagation handed it over, and `10115` validated. The report
    # distinguishes those two outcomes; the destination column cannot.
    assert quality["zip_no_country"]["statuses"] == {"AMBIGUOUS": 3, "NORMALIZED": 1}
    assert quality["bad_country"]["statuses"] == {"INVALID": 3, "NORMALIZED": 1}
    assert quality["messy_company"]["statuses"] == {"NORMALIZED": 4}
    # Whatever the mix, the categories sum to the column's own value count.
    for column in quality.values():
        assert sum(column["statuses"].values()) == column["values"]
    # Nothing in this column changed, so nothing needed re-checking; the
    # one column normalization did rewrite was checked in full.
    assert quality["zip_no_country"]["checked_idempotent"] == 0
    assert quality["messy_company"]["checked_idempotent"] == 4

    # A column that refused to guess produces no finding at all.
    errors = persistence.load_clone_job_errors_page(job_id, limit=200, offset=0)
    column_level = {e["field"] for e in errors if e["row_index"] == -1}
    assert "zip_no_country" not in column_level

    assert all(c["not_idempotent"] == 0 for c in quality.values())
    assert persistence.count_clone_job_errors(job_id) == len(errors)


def _country_dispatcher() -> Dispatcher:
    registry = NormalizerRegistry()
    registry.register(PassthroughNormalizer())
    registry.register(CountryNormalizer())
    return Dispatcher(registry, env_id="test-schema-clone")


@pytest.mark.integration
def test_a_table_in_a_named_schema_can_be_cloned(persistence: PgPersistence) -> None:
    """Every Postgres lookup is relative to a schema, and the default is
    `public`.

    Measured on a real 13-table source that keeps all of them in a named
    schema: `list_tables()` returned `[]`, the job was created with no
    tables, and Phase 2 reported COMPLETED having copied nothing. All four
    lookups have to honour the schema or none of them can — with it applied
    to `list_tables` alone the table is discovered and then has no columns,
    no key and no rows.
    """
    dest_database = f"clone_schema_{uuid.uuid4().hex[:8]}"
    source_conn, dest_conn = _pg_connections(persistence)

    job = clone_executor.create_clone_job(
        persistence,
        request={
            "source_connection_id": source_conn["connection_id"],
            "source_database": "source_demo",
            "source_schema": "tenant_b",
            "destination_connection_id": dest_conn["connection_id"],
            "destination_database": dest_database,
            "autodetect_field_types": False,
            "field_configs": {"scoped_source": {"country": "COUNTRY"}},
        },
    )
    # ONLY that schema's tables, and named without the schema — the bare
    # name is what the destination DDL and field_configs both use.
    assert job["tables"] == ["scoped_source"]

    job = _run_to_completion(persistence, _country_dispatcher(), job["job_id"], dest_database)
    assert job["progress"]["rows_done"] == 3

    dest_dsn = f"postgresql://writable_user:writable_pass@{PG_HOST}:{PG_PORT}/{dest_database}"
    with psycopg.connect(dest_dsn) as conn:
        # In `public` of the destination, not in a replicated `tenant_b`.
        rows = conn.execute("SELECT country FROM public.scoped_source ORDER BY id").fetchall()
    assert [r[0] for r in rows] == ["United Kingdom", "Germany", "United States"]


@pytest.mark.integration
def test_a_clone_with_nothing_to_clone_fails_instead_of_completing(
    persistence: PgPersistence,
) -> None:
    """The silent half of the same bug, and the worse half.

    With no tables the whole pipeline ran to COMPLETED having created an
    empty database. One guard at job creation covers every cause — wrong
    database, no SELECT grants, an empty source, or a schema nobody named —
    and the message has to say where the tables actually are, or it is true
    and useless.
    """
    source_conn, dest_conn = _pg_connections(persistence)
    request = {
        "source_connection_id": source_conn["connection_id"],
        "source_database": "source_demo",
        "source_schema": "tenant_b",
        "destination_connection_id": dest_conn["connection_id"],
        "destination_database": f"clone_empty_{uuid.uuid4().hex[:8]}",
        "autodetect_field_types": False,
        "field_configs": {},
    }

    with pytest.raises(clone_executor.CloneJobStateError) as exc:
        clone_executor.create_clone_job(
            persistence, request={**request, "source_schema": "tenant_empty"}
        )
    message = str(exc.value)
    assert "No tables to clone" in message
    assert "schema 'tenant_empty'" in message

    # This source's DEFAULT schema does hold tables, so reaching the guard
    # at all proves the named schema is really what was looked in — and the
    # same request with a populated schema succeeds.
    job = clone_executor.create_clone_job(persistence, request=request)
    assert job["tables"] == ["scoped_source"]

"""Route-level tests for the DB-clone-and-normalize feature's new §4
endpoints — request validation, 404s, and status transitions, same style
as the existing run-lifecycle route tests (test_normapi.py). No real
Postgres/ClickHouse: `get_connections` is overridden with a small
in-memory fake implementing exactly the `PgPersistence` methods the
routes/`clone_executor` call (real DB behavior is proven separately by
`tests/integration/test_clone_pipeline.py` against real containers).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from normapi.app import create_app
from normapi.dependencies import get_connections
from normapi.schemas import CloneJobCreateRequest
from normio.connector import ColumnInfo

from normapi import clone_executor, secrets


class _FakePersistence:
    """In-memory stand-in for the connections/clone-job slice of
    PgPersistence's real SQL-backed behavior — same method shapes, no
    database. `claim_clone_job`'s SCHEMA_READY|RUNNING -> RUNNING
    transition mirrors the real conditional-UPDATE semantics."""

    def __init__(self) -> None:
        self._connections: dict[str, dict] = {}
        self._jobs: dict[str, dict] = {}
        self._errors: dict[str, list[dict]] = {}

    def save_connection(self, connection_id, *, engine, host, port, username, password):
        row = {
            "connection_id": connection_id,
            "engine": engine,
            "host": host,
            "port": port,
            "username": username,
            "encrypted_password": secrets.encrypt(password),
            "created_at": "2026-01-01T00:00:00Z",
        }
        self._connections[connection_id] = row
        return row

    def get_connection(self, connection_id):
        return self._connections.get(connection_id)

    def list_connections(self):
        return list(self._connections.values())

    def delete_connection(self, connection_id):
        self._connections.pop(connection_id, None)

    def create_clone_job(self, job_id, data):
        self._jobs[job_id] = data

    def save_clone_job(self, job_id, data):
        self._jobs[job_id] = data

    def get_clone_job(self, job_id):
        return self._jobs.get(job_id)

    def list_clone_jobs(self):
        return list(self._jobs.values())

    def claim_clone_job(self, job_id):
        job = self._jobs.get(job_id)
        if job is None or job["status"] not in ("SCHEMA_READY", "RUNNING"):
            return False
        job["status"] = "RUNNING"
        return True

    def save_clone_job_errors(self, job_id, errors):
        self._errors.setdefault(job_id, []).extend(errors)

    def load_clone_job_errors_page(self, job_id, *, limit, offset):
        return self._errors.get(job_id, [])[offset : offset + limit]

    def count_clone_job_errors(self, job_id):
        return len(self._errors.get(job_id, []))


@pytest.fixture(autouse=True)
def _secret_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NORM_SECRET_KEY", Fernet.generate_key().decode())


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    dict_dir = tmp_path / "dictionaries"
    dict_dir.mkdir()
    custom_dict_dir = tmp_path / "custom-dictionaries"
    app = create_app(dictionaries_dir=dict_dir, custom_dictionaries_dir=custom_dict_dir)
    # One fake instance shared across every request in this test — a
    # fresh instance per call (e.g. `lambda: _FakePersistence()`) would
    # silently discard writes between requests, since FastAPI invokes a
    # plain-function dependency override fresh each call.
    fake = _FakePersistence()
    app.dependency_overrides[get_connections] = lambda: fake
    return TestClient(app)


@pytest.mark.unit
def test_clone_routes_published_in_openapi_schema() -> None:
    client = TestClient(create_app())
    schema = client.get("/openapi.json").json()
    for expected in (
        "/normalization/connections",
        "/normalization/connections/{connection_id}/databases",
        "/normalization/connections/{connection_id}/databases/{database}/tables",
        "/normalization/connections/{connection_id}/databases/{database}/tables/{table}/columns",
        "/normalization/clone-jobs",
        "/normalization/clone-jobs/{job_id}",
        "/normalization/clone-jobs/{job_id}/plan",
        "/normalization/clone-jobs/{job_id}/verify-database",
        "/normalization/clone-jobs/{job_id}/start",
        "/normalization/clone-jobs/{job_id}/errors",
    ):
        assert expected in schema["paths"], f"{expected} missing from OpenAPI schema"


@pytest.mark.unit
def test_connections_require_pg_dsn_configured(tmp_path: Path) -> None:
    """No dependency override here — a real (persistence=None) app, same
    as every other unit test's default, must reject clone-feature routes
    with a clean 503, not a crash (normapi.dependencies.get_connections)."""
    dict_dir = tmp_path / "dictionaries"
    dict_dir.mkdir()
    app = create_app(dictionaries_dir=dict_dir, custom_dictionaries_dir=tmp_path / "custom")
    client = TestClient(app)
    resp = client.get("/normalization/connections")
    assert resp.status_code == 503


@pytest.mark.unit
def test_create_list_delete_connection_round_trip(client: TestClient) -> None:
    resp = client.post(
        "/normalization/connections",
        json={
            "engine": "postgres",
            "host": "localhost",
            "port": 5432,
            "username": "demo",
            "password": "super-secret",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "password" not in body
    assert "encrypted_password" not in body
    connection_id = body["connection_id"]

    listed = client.get("/normalization/connections").json()
    assert any(c["connection_id"] == connection_id for c in listed)
    assert all("password" not in c and "encrypted_password" not in c for c in listed)

    resp = client.delete(f"/normalization/connections/{connection_id}")
    assert resp.status_code == 204
    assert connection_id not in [
        c["connection_id"] for c in client.get("/normalization/connections").json()
    ]


@pytest.mark.unit
def test_create_connection_rejects_unknown_engine(client: TestClient) -> None:
    resp = client.post(
        "/normalization/connections",
        json={"engine": "mysql", "host": "h", "port": 1, "username": "u", "password": "p"},
    )
    assert resp.status_code == 422


@pytest.mark.unit
def test_create_clone_job_404s_on_unknown_source_connection(client: TestClient) -> None:
    resp = client.post(
        "/normalization/clone-jobs",
        json={
            "source_connection_id": "does-not-exist",
            "source_database": "db",
            "destination_connection_id": "also-missing",
            "destination_database": "db_clone",
            "field_configs": {},
        },
    )
    assert resp.status_code == 404


@pytest.mark.unit
def test_get_clone_job_404s_on_unknown_job(client: TestClient) -> None:
    assert client.get("/normalization/clone-jobs/no-such-job").status_code == 404
    assert client.post("/normalization/clone-jobs/no-such-job/verify-database").status_code == 404
    assert client.post("/normalization/clone-jobs/no-such-job/start").status_code == 404
    assert client.get("/normalization/clone-jobs/no-such-job/errors").status_code == 404


@pytest.mark.unit
def test_start_rejects_job_not_yet_schema_ready(client: TestClient) -> None:
    fake = _FakePersistence()
    fake.create_clone_job(
        "job-1",
        {
            "job_id": "job-1",
            "status": "PENDING_DB_CREATE",
            "source_connection_id": "a",
            "source_database": "db",
            "destination_connection_id": "b",
            "destination_database": "db_clone",
            "tables": [],
            "field_configs": {},
            "progress": {
                "current_table": None,
                "tables_completed": [],
                "rows_done": 0,
                "checkpoints": {},
            },
            "error": None,
        },
    )
    client.app.dependency_overrides[get_connections] = lambda: fake
    resp = client.post("/normalization/clone-jobs/job-1/start")
    assert resp.status_code == 409
    assert client.get("/normalization/clone-jobs/job-1").json()["status"] == "PENDING_DB_CREATE"


# Request fields that deliberately do NOT appear verbatim on the job, each
# with the reason it cannot:
_NOT_STORED = frozenset(
    {
        # Creation-time switches: they decide what `field_configs` ends up
        # containing and mean nothing afterwards.
        "autodetect_field_types",
        "normalize_unconfigured_text",
        # Stored MERGED with what detection inferred, so it is not the
        # value that was sent.
        "field_configs",
    }
)


@pytest.mark.unit
def test_every_request_field_reaches_the_stored_job(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression, twice over: the route used to hand-copy 8 of the
    request's fields into the executor's dict, so
    `typed_destination_columns` was unreachable over HTTP
    however they were sent. Then `source_schema` was added and reached the
    discovery read but not the SAVED job, so Phase 1 reopened the source
    without it and raised `NoSuchTableError` on a table the job had just
    listed.

    So the expectation is derived from `CloneJobCreateRequest` rather than
    written out: a field added to the model and never stored fails here
    until someone either stores it or says in `_NOT_STORED` why not. A
    hand-written list of assertions has the same failure mode as the
    hand-written dict it is guarding.
    """

    class _Source:
        def list_tables(self):
            return ["Company"]

        def get_columns(self, table):
            return []

        def get_primary_key(self, table):
            # Every real source reports its key, and detection now REFUSES
            # to infer a semantic type for a key column — so a fake without
            # this is a fake that cannot exercise the exclusion.
            return ["companyID"]

        def close(self):
            pass

    monkeypatch.setattr(
        clone_executor, "build_source_connector", lambda conn, db, schema=None: _Source()
    )
    client.post(
        "/normalization/connections",
        json={
            "engine": "postgres",
            "host": "localhost",
            "port": 5432,
            "username": "u",
            "password": "p",
        },
    )
    connection_id = client.get("/normalization/connections").json()[0]["connection_id"]

    sent = {
        "source_connection_id": connection_id,
        "source_database": "src",
        "source_schema": "diffbot",
        "destination_connection_id": connection_id,
        "destination_database": "dst",
        "tables": ["Company"],
        "country": "GB",
        "locale": "en-GB",
        "typed_destination_columns": False,
        "max_new_null_rate": 0.25,
        "cross_table_entity_key": "companyID",
        "field_configs": {"Company": {"revenue": "MONEY"}},
        "confirmed_missing": {"Company": {"revenue": ["tbd"]}},
        "calibrated_abstention": True,
    }
    resp = client.post("/normalization/clone-jobs", json=sent)
    assert resp.status_code == 201, resp.text

    job = client.get(f"/normalization/clone-jobs/{resp.json()['job_id']}").json()
    for field, value in sent.items():
        if field in _NOT_STORED:
            continue
        assert job[field] == value, f"{field} did not reach the stored job"

    # Every field on the model is either sent above or deliberately not
    # stored — so adding one cannot quietly skip this test either.
    unchecked = set(CloneJobCreateRequest.model_fields) - set(sent) - _NOT_STORED
    assert unchecked == set(), f"new request field(s) not covered here: {sorted(unchecked)}"


class _PlanSource:
    """A source with just enough shape for the plan preview: columns, a
    primary key, and nothing writable."""

    def __init__(self) -> None:
        self._columns = [
            ColumnInfo(name="companyID", native_type="text"),
            ColumnInfo(name="revenue", native_type="text"),
            ColumnInfo(name="CountryCode", native_type="text"),
            ColumnInfo(name="created_at", native_type="timestamp"),
        ]

    def list_tables(self):
        return ["Company"]

    def get_columns(self, table):
        return self._columns

    def get_primary_key(self, table):
        return ["companyID"]

    def close(self):
        pass


def _plan_job(client: TestClient, monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> str:
    monkeypatch.setattr(
        clone_executor, "build_source_connector", lambda conn, db, schema=None: _PlanSource()
    )
    client.post(
        "/normalization/connections",
        json={
            "engine": "postgres",
            "host": "localhost",
            "port": 5432,
            "username": "u",
            "password": "p",
        },
    )
    connection_id = client.get("/normalization/connections").json()[0]["connection_id"]
    body = {
        "source_connection_id": connection_id,
        "source_database": "src",
        "destination_connection_id": connection_id,
        "destination_database": "dst",
        "field_configs": {"Company": {"revenue": "MONEY", "CountryCode": "COUNTRY"}},
        **overrides,
    }
    resp = client.post("/normalization/clone-jobs", json=body)
    assert resp.status_code == 201, resp.text
    return str(resp.json()["job_id"])


@pytest.mark.unit
def test_the_plan_shows_what_phase_1_will_do_before_it_does_it(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Detection is the part of a clone nobody could see: on a real
    13-table source it claimed 8 columns of 114 and the only trace was a
    JSON blob on the job."""
    job_id = _plan_job(client, monkeypatch)
    plan = client.get(f"/normalization/clone-jobs/{job_id}/plan").json()

    assert plan["amendable"] is True
    assert plan["typed_destination_columns"] is True
    table = plan["tables"][0]
    assert table["table"] == "Company"
    assert table["key_columns"] == ["companyID"]
    by_column = {c["column"]: c for c in table["columns"]}

    # A MONEY column: native type so it can be summed, plus the companion
    # that stops its currency being dropped on the floor.
    assert by_column["revenue"]["semantic_type"] == "MONEY"
    assert by_column["revenue"]["decided_by"] == "EXPLICIT"
    assert by_column["revenue"]["destination_type"] is not None
    assert by_column["revenue"]["companion_column"] == "revenue_currency"

    # A COUNTRY column keeps TEXT and gains the ISO code column.
    assert by_column["CountryCode"]["companion_column"] == "CountryCode_code"
    assert by_column["CountryCode"]["destination_type"] is None

    # The key column is never given a native type, and an unconfigured
    # column is visible as unconfigured rather than absent — "what is NOT
    # being normalized" is half of what a review is for.
    assert by_column["companyID"]["destination_type"] is None
    assert by_column["created_at"]["semantic_type"] is None
    assert by_column["created_at"]["decided_by"] is None
    assert by_column["created_at"]["source_type"] == "timestamp"

    assert table["extra_columns"] == {
        "revenue_currency": "TEXT",
        "CountryCode_code": "TEXT",
    }


@pytest.mark.unit
def test_a_review_can_amend_one_column_without_restating_the_rest(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id = _plan_job(client, monkeypatch)
    resp = client.patch(
        f"/normalization/clone-jobs/{job_id}/plan",
        json={"field_configs": {"Company": {"revenue": "NUMERIC"}}, "locale": "en-US"},
    )
    assert resp.status_code == 200, resp.text

    plan = client.get(f"/normalization/clone-jobs/{job_id}/plan").json()
    by_column = {c["column"]: c for c in plan["tables"][0]["columns"]}
    assert by_column["revenue"]["semantic_type"] == "NUMERIC"
    # The column the review did not mention is untouched, and so is every
    # setting it did not send.
    assert by_column["CountryCode"]["semantic_type"] == "COUNTRY"
    assert plan["locale"] == "en-US"
    assert plan["country"] is None
    assert plan["typed_destination_columns"] is True
    # MONEY's companion goes when MONEY does.
    assert by_column["revenue"]["companion_column"] is None


@pytest.mark.unit
def test_a_review_can_turn_a_column_off_entirely(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An explicit null is the only way to say "do not normalize this
    one" — omitting a column means "leave it as planned"."""
    job_id = _plan_job(client, monkeypatch)
    client.patch(
        f"/normalization/clone-jobs/{job_id}/plan",
        json={"field_configs": {"Company": {"revenue": None}}},
    )
    plan = client.get(f"/normalization/clone-jobs/{job_id}/plan").json()
    by_column = {c["column"]: c for c in plan["tables"][0]["columns"]}
    assert by_column["revenue"]["semantic_type"] is None
    assert by_column["revenue"]["companion_column"] is None
    assert plan["tables"][0]["extra_columns"] == {"CountryCode_code": "TEXT"}


@pytest.mark.unit
def test_the_plan_cannot_be_amended_once_tables_exist(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After Phase 1 the destination's columns are what they are, so
    amending the plan would make the job disagree with its own tables."""
    job_id = _plan_job(client, monkeypatch)
    # Phase 1 has run: the job is past the one status a plan may change in.
    persistence = client.app.dependency_overrides[get_connections]()
    job = persistence.get_clone_job(job_id)
    job["status"] = "SCHEMA_READY"
    persistence.save_clone_job(job_id, job)

    resp = client.patch(
        f"/normalization/clone-jobs/{job_id}/plan",
        json={"locale": "en-US"},
    )
    assert resp.status_code == 409
    assert "PENDING_DB_CREATE" in resp.json()["detail"]
    assert client.get(f"/normalization/clone-jobs/{job_id}/plan").json()["amendable"] is False


@pytest.mark.unit
def test_plan_routes_404_on_unknown_job(client: TestClient) -> None:
    assert client.get("/normalization/clone-jobs/nope/plan").status_code == 404
    assert client.patch("/normalization/clone-jobs/nope/plan", json={}).status_code == 404


def _error_row(index: int) -> dict[str, Any]:
    return {
        "row_index": index,
        "table_name": "Company",
        "field": "revenue",
        "original": "$1,234.56",
        "error": "could not parse",
    }


@pytest.mark.unit
class TestTheReportSaysHowMuchOfItIsThisJobs:
    def test_the_total_is_scoped_to_the_job_not_the_table(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One page cannot say how many rows there are, and the table holds
        every job's: 4.3M rows from an earlier run were once read as one
        run's output. Both jobs' rows are stored here on purpose."""
        persistence = client.app.dependency_overrides[get_connections]()
        mine = _plan_job(client, monkeypatch)
        someone_else = _plan_job(client, monkeypatch)
        persistence.save_clone_job_errors(mine, [_error_row(i) for i in range(3)])
        persistence.save_clone_job_errors(someone_else, [_error_row(i) for i in range(40)])

        response = client.get(f"/normalization/clone-jobs/{mine}/errors", params={"limit": 2})
        assert response.status_code == 200
        assert len(response.json()) == 2
        assert response.headers["X-Total-Count"] == "3"

    def test_a_job_with_no_errors_says_zero_rather_than_nothing(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        job_id = _plan_job(client, monkeypatch)
        response = client.get(f"/normalization/clone-jobs/{job_id}/errors")
        assert response.json() == []
        assert response.headers["X-Total-Count"] == "0"


@pytest.mark.unit
class TestQualityReport:
    def test_it_is_empty_before_any_table_finishes(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        job_id = _plan_job(client, monkeypatch)
        body = client.get(f"/normalization/clone-jobs/{job_id}/quality").json()
        assert body["tables"] == {}
        assert body["status"] == "PENDING_DB_CREATE"

    def test_it_reports_what_each_column_achieved(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        persistence = client.app.dependency_overrides[get_connections]()
        job_id = _plan_job(client, monkeypatch)
        job = persistence.get_clone_job(job_id)
        job["quality"] = {
            "Company": {
                "revenue": {
                    "values": 46956,
                    "statuses": {"NORMALIZED": 30756, "INVALID": 16200},
                    "emptied": 16200,
                    "checked_idempotent": 50,
                    "not_idempotent": 0,
                }
            }
        }
        persistence.save_clone_job(job_id, job)
        body = client.get(f"/normalization/clone-jobs/{job_id}/quality").json()
        column = body["tables"]["Company"]["revenue"]
        assert column["emptied"] == 16200
        assert column["not_idempotent"] == 0

    def test_an_unknown_job_is_404(self, client: TestClient) -> None:
        assert client.get("/normalization/clone-jobs/nope/quality").status_code == 404

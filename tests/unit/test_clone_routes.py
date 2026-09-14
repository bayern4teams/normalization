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

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from normapi.app import create_app
from normapi.dependencies import get_connections


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
        from normapi import secrets

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
    assert connection_id not in [c["connection_id"] for c in client.get("/normalization/connections").json()]


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
            "progress": {"current_table": None, "tables_completed": [], "rows_done": 0, "checkpoints": {}},
            "error": None,
        },
    )
    client.app.dependency_overrides[get_connections] = lambda: fake
    resp = client.post("/normalization/clone-jobs/job-1/start")
    assert resp.status_code == 409
    assert client.get("/normalization/clone-jobs/job-1").json()["status"] == "PENDING_DB_CREATE"

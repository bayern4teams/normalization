"""GET /clone-jobs lists every job with its id (ADR-023, the Jobs screen)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from normapi.app import create_app
from normapi.dependencies import get_connections
from normapi.pg_persistence import PgPersistence


@pytest.mark.unit
def test_clone_jobs_list_returns_every_job_with_its_id(tmp_path: Path) -> None:
    persistence = PgPersistence(f"sqlite:///{tmp_path}/m.db")
    persistence.ensure_schema()
    for job_id, status in (("job-a", "COMPLETED"), ("job-b", "RUNNING")):
        persistence.create_clone_job(job_id, {"status": status, "quality": {"t": "03/04/2020"}})
    app = create_app(dictionaries_dir=tmp_path / "d", custom_dictionaries_dir=tmp_path / "c")
    app.dependency_overrides[get_connections] = lambda: persistence
    client = TestClient(app, client=("127.0.0.1", 50000), base_url="http://localhost")
    body = client.get("/normalization/clone-jobs").json()
    assert {j["job_id"]: j["status"] for j in body} == {"job-a": "COMPLETED", "job-b": "RUNNING"}
    assert all("quality" not in j and "03/04/2020" not in str(j) for j in body)

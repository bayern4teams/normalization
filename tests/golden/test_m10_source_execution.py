"""M10 golden corpus — running a normalization against real values read
from a connected source, not pasted (Source.txt §105), proven over the
live API with a real local FileConnector (no docker needed for this
file; live Postgres/MySQL/Mongo/ClickHouse wiring is proven separately
in tests/integration/test_run_execution_from_source.py against the real
demo-* containers).
"""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.csv as pa_csv
import pytest
from fastapi.testclient import TestClient
from normapi.app import create_app

_DICT_ROOT = Path(__file__).parents[2] / "data" / "dictionaries"


@pytest.fixture
def source_dir(tmp_path: Path) -> Path:
    files_dir = tmp_path / "files"
    files_dir.mkdir()
    table = pa.table({"name": ["  Anna Muller  ", "Bob", "Anna Muller"]})
    pa_csv.write_csv(table, files_dir / "customers.csv")
    return files_dir


@pytest.fixture
def client(tmp_path: Path, source_dir: Path) -> TestClient:
    sources_config = tmp_path / "sources.json"
    sources_config.write_text(
        json.dumps({"demo_files": {"type": "file", "base_dir": str(source_dir)}}),
        encoding="utf-8",
    )
    app = create_app(
        dictionaries_dir=_DICT_ROOT,
        custom_dictionaries_dir=tmp_path / "custom-dictionaries",
        sources_config_path=sources_config,
    )
    return TestClient(app)


def _create_profile(client: TestClient) -> str:
    resp = client.post(
        "/normalization/profiles",
        json={"name": "p", "field_configs": [], "created_by": "tester"},
    )
    assert resp.status_code == 201
    result: str = resp.json()["id"]
    return result


@pytest.mark.golden
def test_sources_route_lists_configured_sources(client: TestClient) -> None:
    resp = client.get("/normalization/sources")
    assert resp.status_code == 200
    assert resp.json() == ["demo_files"]


@pytest.mark.golden
def test_source_tables_route_lists_real_tables(client: TestClient) -> None:
    resp = client.get("/normalization/sources/demo_files/tables")
    assert resp.status_code == 200
    assert resp.json() == ["customers.csv"]


@pytest.mark.golden
def test_source_tables_route_404s_for_unknown_source(client: TestClient) -> None:
    resp = client.get("/normalization/sources/nope/tables")
    assert resp.status_code == 404


@pytest.mark.golden
def test_run_executes_against_real_values_read_from_a_source(client: TestClient) -> None:
    """The core M10 proof: a run created with `source` instead of
    `values` normalizes real rows read live from the connector — the
    same collision (two "Anna Muller" rows) real pasted-values execution
    would find, but the values themselves came from a real CSV file, not
    the request body."""
    profile_id = _create_profile(client)
    resp = client.post(
        f"/normalization/runs?profile_id={profile_id}&source_snapshot=snap",
        json={
            "field_name": "name",
            "semantic_type": "FREE_TEXT",
            "source": {"source_id": "demo_files", "table": "customers.csv", "column": "name"},
        },
    )
    assert resp.status_code == 201
    run = resp.json()
    assert run["status"] == "COMPLETED"
    assert run["metrics"]["records_processed"] == 3

    values_resp = client.get(f"/normalization/runs/{run['id']}/values")
    assert values_resp.status_code == 200
    originals = [row["original"] for row in values_resp.json()]
    assert originals == ["  Anna Muller  ", "Bob", "Anna Muller"]


@pytest.mark.golden
def test_run_source_row_limit_truncates_real_read(client: TestClient) -> None:
    profile_id = _create_profile(client)
    resp = client.post(
        f"/normalization/runs?profile_id={profile_id}&source_snapshot=snap",
        json={
            "field_name": "name",
            "semantic_type": "FREE_TEXT",
            "source": {
                "source_id": "demo_files",
                "table": "customers.csv",
                "column": "name",
                "row_limit": 2,
            },
        },
    )
    assert resp.status_code == 201
    assert resp.json()["metrics"]["records_processed"] == 2


@pytest.mark.golden
def test_run_execution_rejects_both_values_and_source(client: TestClient) -> None:
    profile_id = _create_profile(client)
    resp = client.post(
        f"/normalization/runs?profile_id={profile_id}&source_snapshot=snap",
        json={
            "field_name": "name",
            "semantic_type": "FREE_TEXT",
            "values": ["a"],
            "source": {"source_id": "demo_files", "table": "customers.csv", "column": "name"},
        },
    )
    assert resp.status_code == 422


@pytest.mark.golden
def test_run_execution_rejects_neither_values_nor_source(client: TestClient) -> None:
    profile_id = _create_profile(client)
    resp = client.post(
        f"/normalization/runs?profile_id={profile_id}&source_snapshot=snap",
        json={"field_name": "name", "semantic_type": "FREE_TEXT"},
    )
    assert resp.status_code == 422


@pytest.mark.golden
def test_run_source_unknown_source_id_is_404(client: TestClient) -> None:
    profile_id = _create_profile(client)
    resp = client.post(
        f"/normalization/runs?profile_id={profile_id}&source_snapshot=snap",
        json={
            "field_name": "name",
            "semantic_type": "FREE_TEXT",
            "source": {"source_id": "nope", "table": "customers.csv", "column": "name"},
        },
    )
    assert resp.status_code == 404


@pytest.mark.golden
def test_run_source_unknown_table_is_400(client: TestClient) -> None:
    profile_id = _create_profile(client)
    resp = client.post(
        f"/normalization/runs?profile_id={profile_id}&source_snapshot=snap",
        json={
            "field_name": "name",
            "semantic_type": "FREE_TEXT",
            "source": {"source_id": "demo_files", "table": "nope.csv", "column": "name"},
        },
    )
    assert resp.status_code == 400

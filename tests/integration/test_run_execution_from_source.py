"""Integration tests against REAL running database containers (see
compose.yaml's demo-* services and tests/integration/fixtures/) — proves
M10's DB-connector wiring end-to-end through the live API, not just that
SourceRegistry/connectors work in isolation.

Each seeded `customers` table has 3 rows (see
tests/integration/fixtures/*-init/), matching
tests/integration/test_readonly_connectors.py's own expectations.

Requires: docker compose up -d demo-postgres demo-mysql demo-mongo demo-clickhouse
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from normapi.app import create_app

_DICT_ROOT = Path(__file__).parents[2] / "data" / "dictionaries"

POSTGRES_DSN = os.environ.get(
    "TEST_PG_DSN", "postgresql://readonly_user:readonly_pass@localhost:5434/source_demo"
)
MYSQL_DSN = os.environ.get(
    "TEST_MYSQL_DSN", "mysql://readonly_user:readonly_pass@localhost:3307/source_demo"
)
MONGO_URI = os.environ.get(
    "TEST_MONGO_URI", "mongodb://readonly_user:readonly_pass@localhost:27018/source_demo"
)
CLICKHOUSE_HOST = os.environ.get("TEST_CLICKHOUSE_HOST", "localhost")

_SOURCES_CONFIG = {
    "demo_pg": {"type": "postgres", "dsn": POSTGRES_DSN},
    "demo_mysql": {"type": "mysql", "dsn": MYSQL_DSN},
    "demo_mongo": {"type": "mongo", "uri": MONGO_URI, "database": "source_demo"},
    "demo_clickhouse": {
        "type": "clickhouse",
        "host": CLICKHOUSE_HOST,
        "port": 8124,
        "username": "readonly_user",
        "password": "readonly_pass",
        "database": "default",
    },
}


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    try:
        psycopg.connect(POSTGRES_DSN, connect_timeout=2).close()
    except psycopg.OperationalError as exc:
        pytest.skip(f"demo-postgres not reachable at {POSTGRES_DSN}: {exc}")

    sources_config = tmp_path / "sources.json"
    sources_config.write_text(json.dumps(_SOURCES_CONFIG), encoding="utf-8")
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


def _execute_from_source(client: TestClient, source_id: str, table: str) -> dict[str, object]:
    profile_id = _create_profile(client)
    resp = client.post(
        f"/normalization/runs?profile_id={profile_id}&source_snapshot=snap",
        json={
            "field_name": "first_name",
            "semantic_type": "FREE_TEXT",
            "source": {"source_id": source_id, "table": table, "column": "first_name"},
        },
    )
    assert resp.status_code == 201, resp.text
    result: dict[str, object] = resp.json()
    return result


@pytest.mark.integration
class TestRunExecutionFromRealSources:
    """Same real seeded `customers` table (3 rows, real whitespace/accent
    variation in first_name — see fixtures) read through the live API's
    execution path for every one of the 4 real DB connector types."""

    def test_postgres_source(self, client: TestClient) -> None:
        run = _execute_from_source(client, "demo_pg", "customers")
        assert run["status"] == "COMPLETED"
        metrics = run["metrics"]
        assert isinstance(metrics, dict)
        assert metrics["records_processed"] == 3

    def test_mysql_source(self, client: TestClient) -> None:
        run = _execute_from_source(client, "demo_mysql", "customers")
        assert run["status"] == "COMPLETED"
        metrics = run["metrics"]
        assert isinstance(metrics, dict)
        assert metrics["records_processed"] == 3

    def test_mongo_source(self, client: TestClient) -> None:
        run = _execute_from_source(client, "demo_mongo", "customers")
        assert run["status"] == "COMPLETED"
        metrics = run["metrics"]
        assert isinstance(metrics, dict)
        assert metrics["records_processed"] == 3

    def test_clickhouse_source(self, client: TestClient) -> None:
        run = _execute_from_source(client, "demo_clickhouse", "customers")
        assert run["status"] == "COMPLETED"
        metrics = run["metrics"]
        assert isinstance(metrics, dict)
        assert metrics["records_processed"] == 3

    def test_values_survive_the_round_trip_with_real_whitespace_preserved(
        self, client: TestClient
    ) -> None:
        """Proves it's real data, not a stub: the seeded row's original
        "  John  " whitespace (see tests/integration/fixtures/postgres-init)
        is present verbatim in the run's real per-value results."""
        run = _execute_from_source(client, "demo_pg", "customers")
        values_resp = client.get(f"/normalization/runs/{run['id']}/values")
        assert values_resp.status_code == 200
        originals = {row["original"] for row in values_resp.json()}
        assert "  John  " in originals

    def test_sources_route_lists_all_four_real_registered_sources(self, client: TestClient) -> None:
        resp = client.get("/normalization/sources")
        assert resp.status_code == 200
        assert set(resp.json()) == {"demo_pg", "demo_mysql", "demo_mongo", "demo_clickhouse"}

    def test_source_tables_route_reflects_real_schema(self, client: TestClient) -> None:
        resp = client.get("/normalization/sources/demo_pg/tables")
        assert resp.status_code == 200
        assert "customers" in resp.json()

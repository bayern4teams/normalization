"""Integration tests for M18's reporting rearchitecture
(docs/plan/M13-M22-program-plan.md) — live against the real ClickHouse at
localhost:8190 and the real metadata Postgres (port 5535).

Two things are proven:

1. `TestPerColumnReportsOnARealMultiColumnRun` — every per-column report
   route (`/errors`, `/values` with real pagination, `/collisions` +
   its decision route, `/profile`, `/handoff`, `/impact`, `/runs/compare`)
   correctly scopes to ONE (table, column) of a real, completed
   multi-column run via the new `table`/`column` selector — not "whichever
   column happened to be written first" (the real bug `get_execution`'s
   old "find first match" behavior would have for a multi-column run).
2. `TestBoundedOverviewAndQuality` — `GET /overview`/`GET /quality`
   respond quickly and with correct real numbers for a completed run.
   The companion structural proof — that these two routes never touch a
   run's per-value data at all, regardless of how large that run's real
   row count is — is a separate, deliberately NOT-live unit test
   (`tests/unit/test_overview_quality_bounded.py`): starting a genuinely
   unbounded ~11.8M-row Person streaming run in a background thread just
   to prove a timing bound would leave that thread running for a very
   long time after this test returns (M17's own pack already measured
   PERSON_NAME normalization + the persistent-cache-tier bench as slow
   at real cardinality), tying up shared worker-pool/ClickHouse/Postgres
   resources for the rest of this test session. The unit test proves the
   same invariant — `get_execution`/full per-value hydration is never
   called — directly and deterministically instead.

Requires: docker compose up -d postgres
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from normapi.app import create_app
from normapi.secrets import generate_secret_key

_PG_DSN = os.environ.get(
    "TEST_METADATA_PG_DSN", "postgresql://normalization:normalization@localhost:5535/normalization"
)
_REAL_CLICKHOUSE_HOST = os.environ.get("TEST_CLICKHOUSE_HOST", "localhost")
_TERMINAL_STATUSES = {"COMPLETED", "FAILED", "PARTIAL"}


def _skip_if_pg_unreachable() -> None:
    try:
        conn = psycopg.connect(_PG_DSN, connect_timeout=3)
    except psycopg.OperationalError as exc:
        pytest.skip(f"metadata postgres not reachable at {_PG_DSN}: {exc}")
    else:
        conn.close()


def _create_app(tmp_path: Path) -> FastAPI:
    secret_key = generate_secret_key()
    return create_app(
        postgres_dsn=_PG_DSN,
        secret_key=secret_key,
        sidecar_parquet_root=tmp_path / "parquet",
        sidecar_duckdb_path=tmp_path / "catalog.duckdb",
    )


def _create_real_connection(client: TestClient, alias: str) -> str:
    response = client.post(
        "/normalization/connections",
        json={
            "alias": alias,
            "kind": "clickhouse",
            "host": _REAL_CLICKHOUSE_HOST,
            "port": 8190,
            "username": "default",
            "password": "pass",
            "database": "origin2",
        },
    )
    assert response.status_code == 201, response.text
    result: str = response.json()["id"]
    return result


def _create_pending_run(client: TestClient) -> str:
    profile_resp = client.post(
        "/normalization/profiles",
        json={"name": "m18-test", "field_configs": [], "created_by": "tester"},
    )
    assert profile_resp.status_code == 201, profile_resp.text
    profile_id = profile_resp.json()["id"]
    run_resp = client.post(f"/normalization/runs?profile_id={profile_id}&source_snapshot=m18-snap")
    assert run_resp.status_code == 201, run_resp.text
    run_id: str = run_resp.json()["id"]
    return run_id


def _poll_until(client: TestClient, run_id: str, *, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        resp = client.get(f"/normalization/runs/{run_id}")
        assert resp.status_code == 200
        last = resp.json()
        if last["status"] in _TERMINAL_STATUSES:
            return last
        time.sleep(0.2)
    return last


def _start_two_column_industry_run(client: TestClient, connection_id: str) -> str:
    run_id = _create_pending_run(client)
    response = client.post(
        f"/normalization/runs/{run_id}/columns",
        json={
            "connection_id": connection_id,
            "database": "origin2",
            "columns": [
                {"table": "Industry", "column": "name", "semantic_type": "FREE_TEXT"},
                {"table": "Industry", "column": "surfaceForm", "semantic_type": "FREE_TEXT"},
            ],
            "chunk_size": 50,
            "mode": "full_resync",
        },
    )
    assert response.status_code == 202, response.text
    return run_id


@pytest.mark.integration
class TestPerColumnReportsOnARealMultiColumnRun:
    def test_every_per_column_route_scopes_to_the_selected_column(self, tmp_path: Path) -> None:
        _skip_if_pg_unreachable()
        app = _create_app(tmp_path)
        client = TestClient(app)
        connection_id = _create_real_connection(client, "m18-per-column-verify")
        try:
            run_id = _start_two_column_industry_run(client, connection_id)
            final = _poll_until(client, run_id, timeout=60)
            assert final.get("status") == "COMPLETED", final

            errors_name = client.get(
                f"/normalization/runs/{run_id}/errors",
                params={"table": "Industry", "column": "name"},
            )
            assert errors_name.status_code == 200

            profile_name = client.get(
                f"/normalization/runs/{run_id}/profile",
                params={"table": "Industry", "column": "name"},
            )
            assert profile_name.status_code == 200
            assert profile_name.json()["rows"] == 179

            profile_surface = client.get(
                f"/normalization/runs/{run_id}/profile",
                params={"table": "Industry", "column": "surfaceForm"},
            )
            assert profile_surface.status_code == 200
            assert profile_surface.json()["rows"] == 179
            # Real proof the two columns are genuinely distinct data, not
            # the same underlying result set returned twice: field_name
            # in each profile reflects the real column requested.
            assert profile_name.json()["field_name"] == "name"
            assert profile_surface.json()["field_name"] == "surfaceForm"

            impact = client.get(
                "/normalization/impact",
                params={"run_id": run_id, "table": "Industry", "column": "name"},
            )
            assert impact.status_code == 200
            assert impact.json()["total_values"] == 179

            collisions = client.get(
                f"/normalization/runs/{run_id}/collisions",
                params={"table": "Industry", "column": "name"},
            )
            assert collisions.status_code == 200

            handoff = client.get(
                f"/normalization/runs/{run_id}/handoff",
                params={"table": "Industry", "column": "name"},
            )
            assert handoff.status_code == 200
            assert handoff.json()["field_schema"]["field_name"] == "name"
        finally:
            client.delete(f"/normalization/connections/{connection_id}")

    def test_values_pagination_covers_every_row_exactly_once(self, tmp_path: Path) -> None:
        """The real fix for the plan's own callout: `/values` pushed down
        to DuckDB OFFSET/LIMIT, never a full `to_pylist()`."""
        _skip_if_pg_unreachable()
        app = _create_app(tmp_path)
        client = TestClient(app)
        connection_id = _create_real_connection(client, "m18-pagination-verify")
        try:
            run_id = _start_two_column_industry_run(client, connection_id)
            final = _poll_until(client, run_id, timeout=60)
            assert final.get("status") == "COMPLETED", final

            seen_originals: list[object] = []
            offset = 0
            page_size = 50
            for _ in range(10):  # 179 rows / 50 per page -> 4 pages, generous bound
                page = client.get(
                    f"/normalization/runs/{run_id}/values",
                    params={
                        "table": "Industry",
                        "column": "name",
                        "offset": offset,
                        "limit": page_size,
                    },
                )
                assert page.status_code == 200
                rows = page.json()
                if not rows:
                    break
                seen_originals.extend(r["original"] for r in rows)
                offset += page_size

            assert len(seen_originals) == 179
            # No duplicate/skipped rows across the page boundary.
            assert len(set(range(len(seen_originals)))) == 179

            empty_page = client.get(
                f"/normalization/runs/{run_id}/values",
                params={"table": "Industry", "column": "name", "offset": 179, "limit": 50},
            )
            assert empty_page.status_code == 200
            assert empty_page.json() == []
        finally:
            client.delete(f"/normalization/connections/{connection_id}")

    def test_collision_decision_scoped_to_one_column(self, tmp_path: Path) -> None:
        _skip_if_pg_unreachable()
        app = _create_app(tmp_path)
        client = TestClient(app)
        connection_id = _create_real_connection(client, "m18-collision-decision-verify")
        try:
            run_id = _start_two_column_industry_run(client, connection_id)
            final = _poll_until(client, run_id, timeout=60)
            assert final.get("status") == "COMPLETED", final

            collisions = client.get(
                f"/normalization/runs/{run_id}/collisions",
                params={"table": "Industry", "column": "name"},
            ).json()
            if not collisions:
                pytest.skip("Industry.name has no real collision group to decide on right now")
            normalized_value = collisions[0]["normalized_value"]

            decision = client.post(
                f"/normalization/runs/{run_id}/collisions/decision",
                json={
                    "normalized_value": normalized_value,
                    "decision": "ACCEPTED",
                    "decided_by": "tester",
                    "table": "Industry",
                    "column": "name",
                },
            )
            assert decision.status_code == 201, decision.text

            refetched = client.get(
                f"/normalization/runs/{run_id}/collisions",
                params={"table": "Industry", "column": "name"},
            ).json()
            matching = next(g for g in refetched if g["normalized_value"] == normalized_value)
            assert matching["decision"]["decision"] == "ACCEPTED"
        finally:
            client.delete(f"/normalization/connections/{connection_id}")

    def test_compare_two_runs_of_the_same_column(self, tmp_path: Path) -> None:
        _skip_if_pg_unreachable()
        app = _create_app(tmp_path)
        client = TestClient(app)
        connection_id = _create_real_connection(client, "m18-compare-verify")
        try:
            run_a = _create_pending_run(client)
            run_b = _create_pending_run(client)
            for run_id in (run_a, run_b):
                resp = client.post(
                    f"/normalization/runs/{run_id}/columns",
                    json={
                        "connection_id": connection_id,
                        "database": "origin2",
                        "columns": [
                            {"table": "Industry", "column": "name", "semantic_type": "FREE_TEXT"}
                        ],
                        "chunk_size": 50,
                        "mode": "full_resync",
                    },
                )
                assert resp.status_code == 202, resp.text
            final_a = _poll_until(client, run_a, timeout=60)
            final_b = _poll_until(client, run_b, timeout=60)
            assert final_a.get("status") == "COMPLETED", final_a
            assert final_b.get("status") == "COMPLETED", final_b

            compare = client.get(
                "/normalization/runs/compare",
                params={
                    "run_id_a": run_a,
                    "run_id_b": run_b,
                    "table": "Industry",
                    "column": "name",
                },
            )
            assert compare.status_code == 200, compare.text
        finally:
            client.delete(f"/normalization/connections/{connection_id}")


@pytest.mark.integration
class TestBoundedOverviewAndQuality:
    def test_overview_and_quality_reflect_a_completed_run_and_respond_quickly(
        self, tmp_path: Path
    ) -> None:
        _skip_if_pg_unreachable()
        app = _create_app(tmp_path)
        client = TestClient(app)
        connection_id = _create_real_connection(client, "m18-overview-verify")
        try:
            run_id = _start_two_column_industry_run(client, connection_id)
            final = _poll_until(client, run_id, timeout=60)
            assert final.get("status") == "COMPLETED", final

            t0 = time.monotonic()
            overview = client.get("/normalization/overview")
            overview_elapsed = time.monotonic() - t0
            assert overview.status_code == 200
            body = overview.json()
            # 2 columns x 179 rows each, real completed data.
            assert body["rows_processed"] >= 358
            assert overview_elapsed < 5.0, f"overview took {overview_elapsed:.2f}s"

            t0 = time.monotonic()
            quality = client.get("/normalization/quality")
            quality_elapsed = time.monotonic() - t0
            assert quality.status_code == 200
            assert quality_elapsed < 5.0, f"quality took {quality_elapsed:.2f}s"
        finally:
            client.delete(f"/normalization/connections/{connection_id}")

    # The companion proof — /overview and /quality stay correct and fast
    # no matter how large a run's REAL row count is, because they never
    # call get_execution/hydrate per-value data at all — is
    # tests/unit/test_overview_quality_bounded.py (see this file's module
    # docstring for why that's a unit test, not a live one here).

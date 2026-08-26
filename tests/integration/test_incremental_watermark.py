"""Integration tests for M20's incremental watermark + full resync
(docs/plan/M13-M22-program-plan.md) — live against the real ClickHouse
source at localhost:8190 (origin2, read-only) and the real metadata
Postgres (port 5535). The NULL-watermark-skip proof additionally uses a
small real table created on `demo-clickhouse` (port 8124) specifically
to contain a genuine NULL `created_at` row — `origin2`'s own real
`Person`/`Company` tables currently have ZERO such rows (a live,
previously-disclosed finding from M14/M17's own packs), so proving the
counter actually fires needs a table that really has one.

Two things are proven, matching the plan's own verify-live bullet:

1. `TestIndustryIncrementalAndFullResync` — `Industry` (179 real rows,
   non-nullable `created_at`): a first run sets a real watermark; a
   second run with the SAME mapping (`mode: "incremental"`, the default)
   processes 0 new rows since the watermark already covers every real
   row; `mode: "full_resync"` resets the watermark and processes all 179
   again.
2. `TestNullWatermarkSkipCounter` — a real, deliberately-constructed
   table with one genuine NULL `created_at` row proves
   `rows_skipped_null_watermark` actually increments, not just that the
   mechanism compiles.

Requires: docker compose up -d postgres demo-clickhouse
"""

from __future__ import annotations

import os
import time
import uuid
from pathlib import Path
from typing import Any

import clickhouse_connect
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
_REAL_SOURCE_PORT = 8190
_SAFE_DEMO_PORT = 8124  # demo-clickhouse
_TERMINAL_STATUSES = {"COMPLETED", "FAILED", "PARTIAL"}


def _skip_if_pg_unreachable() -> None:
    try:
        conn = psycopg.connect(_PG_DSN, connect_timeout=3)
    except psycopg.OperationalError as exc:
        pytest.skip(f"metadata postgres not reachable at {_PG_DSN}: {exc}")
    else:
        conn.close()


def _skip_if_demo_clickhouse_unreachable() -> None:
    try:
        client = clickhouse_connect.get_client(
            host=_REAL_CLICKHOUSE_HOST, port=_SAFE_DEMO_PORT, username="default", password=""
        )
        client.ping()
        client.close()
    except Exception as exc:  # any connectivity failure means skip
        pytest.skip(f"demo-clickhouse not reachable at port {_SAFE_DEMO_PORT}: {exc}")


def _create_app(tmp_path: Path) -> FastAPI:
    secret_key = generate_secret_key()
    return create_app(
        postgres_dsn=_PG_DSN,
        secret_key=secret_key,
        sidecar_parquet_root=tmp_path / "parquet",
        sidecar_duckdb_path=tmp_path / "catalog.duckdb",
    )


def _create_source_connection(client: TestClient, alias: str, *, database: str = "origin2") -> str:
    response = client.post(
        "/normalization/connections",
        json={
            "alias": alias,
            "kind": "clickhouse",
            "host": _REAL_CLICKHOUSE_HOST,
            "port": _REAL_SOURCE_PORT,
            "username": "default",
            "password": "pass",
            "database": database,
        },
    )
    assert response.status_code == 201, response.text
    result: str = response.json()["id"]
    return result


def _create_demo_connection(client: TestClient, alias: str, *, database: str) -> str:
    response = client.post(
        "/normalization/connections",
        json={
            "alias": alias,
            "kind": "clickhouse",
            "host": _REAL_CLICKHOUSE_HOST,
            "port": _SAFE_DEMO_PORT,
            "username": "default",
            "password": "",
            "database": database,
        },
    )
    assert response.status_code == 201, response.text
    result: str = response.json()["id"]
    return result


def _create_pending_run(client: TestClient) -> str:
    profile_resp = client.post(
        "/normalization/profiles",
        json={"name": "m20-test", "field_configs": [], "created_by": "tester"},
    )
    assert profile_resp.status_code == 201, profile_resp.text
    profile_id = profile_resp.json()["id"]
    run_resp = client.post(f"/normalization/runs?profile_id={profile_id}&source_snapshot=m20-snap")
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


@pytest.mark.integration
class TestIndustryIncrementalAndFullResync:
    def test_second_incremental_run_processes_zero_new_rows_then_full_resync_processes_all(
        self, tmp_path: Path
    ) -> None:
        _skip_if_pg_unreachable()
        app = _create_app(tmp_path)
        client = TestClient(app)
        connection_id = _create_source_connection(client, "m20-watermark-verify")
        body_base = {
            "connection_id": connection_id,
            "database": "origin2",
            "columns": [{"table": "Industry", "column": "name", "semantic_type": "FREE_TEXT"}],
            "chunk_size": 50,
        }
        try:
            # Run 1: full_resync — deliberately, not incremental. The
            # real Postgres this project uses is genuinely persistent
            # across the whole test session (and across every session
            # ever run against this same real database), so a PRIOR run
            # of this very test (or any other test against Industry with
            # this same real connection identity) may already have set a
            # real watermark — "first run, no watermark yet" is never a
            # safe assumption to make about real, shared state. Starting
            # from an explicit full_resync is what actually guarantees a
            # clean, deterministic starting point: all 179 real rows.
            run_a = _create_pending_run(client)
            resp_a = client.post(
                f"/normalization/runs/{run_a}/columns", json={**body_base, "mode": "full_resync"}
            )
            assert resp_a.status_code == 202, resp_a.text
            final_a = _poll_until(client, run_a, timeout=60)
            assert final_a.get("status") == "COMPLETED", final_a
            assert final_a["metrics"]["records_processed"] == 179

            # Run 2: incremental, same mapping — the watermark set by
            # run 1 already covers every real row's created_at, so this
            # processes 0 new rows.
            run_b = _create_pending_run(client)
            resp_b = client.post(f"/normalization/runs/{run_b}/columns", json=body_base)
            assert resp_b.status_code == 202, resp_b.text
            final_b = _poll_until(client, run_b, timeout=60)
            assert final_b.get("status") == "COMPLETED", final_b
            assert final_b["metrics"]["records_processed"] == 0

            # Run 3: full_resync — resets the watermark, processes all
            # 179 real rows again.
            run_c = _create_pending_run(client)
            resp_c = client.post(
                f"/normalization/runs/{run_c}/columns", json={**body_base, "mode": "full_resync"}
            )
            assert resp_c.status_code == 202, resp_c.text
            final_c = _poll_until(client, run_c, timeout=60)
            assert final_c.get("status") == "COMPLETED", final_c
            assert final_c["metrics"]["records_processed"] == 179
        finally:
            client.delete(f"/normalization/connections/{connection_id}")


@pytest.mark.integration
class TestNullWatermarkSkipCounter:
    def test_a_real_null_created_at_row_is_counted_and_excluded(self, tmp_path: Path) -> None:
        """origin2's real Person/Company tables currently have ZERO NULL
        created_at rows (a live finding already disclosed in M14/M17's
        own packs) — proving this counter actually fires needs a table
        that genuinely has one, built here on the safe demo-clickhouse
        server."""
        _skip_if_pg_unreachable()
        _skip_if_demo_clickhouse_unreachable()
        app = _create_app(tmp_path)
        client = TestClient(app)

        database = f"m20_null_test_{uuid.uuid4().hex[:8]}"
        admin_client = clickhouse_connect.get_client(
            host=_REAL_CLICKHOUSE_HOST, port=_SAFE_DEMO_PORT, username="default", password=""
        )
        connection_id = None
        try:
            admin_client.command(f"CREATE DATABASE IF NOT EXISTS {database}")
            admin_client.command(
                f"CREATE TABLE {database}.watermark_null_test "
                "(id String, val String, created_at Nullable(DateTime)) "
                "ENGINE = MergeTree ORDER BY id"
            )
            admin_client.command(
                f"INSERT INTO {database}.watermark_null_test (id, val, created_at) VALUES "
                "('1', 'alpha', '2024-01-01 00:00:00'), "
                "('2', 'beta', '2024-01-02 00:00:00'), "
                "('3', 'gamma', NULL)"
            )

            connection_id = _create_demo_connection(client, "m20-null-verify", database=database)
            run_id = _create_pending_run(client)
            resp = client.post(
                f"/normalization/runs/{run_id}/columns",
                json={
                    "connection_id": connection_id,
                    "database": database,
                    "columns": [
                        {
                            "table": "watermark_null_test",
                            "column": "val",
                            "semantic_type": "FREE_TEXT",
                        }
                    ],
                    "chunk_size": 50,
                },
            )
            assert resp.status_code == 202, resp.text
            final = _poll_until(client, run_id, timeout=30)
            assert final.get("status") == "COMPLETED", final

            # All 3 real rows still get NORMALIZED (the watermark only
            # gates which rows are read on a REPEAT run — a first,
            # never-watermarked run always reads everything).
            assert final["metrics"]["records_processed"] == 3
            # But the real NULL-created_at row is correctly surfaced as
            # a structural blind spot for FUTURE incremental runs.
            assert final["progress"]["rows_skipped_null_watermark"] == 1
        finally:
            if connection_id is not None:
                client.delete(f"/normalization/connections/{connection_id}")
            admin_client.command(f"DROP DATABASE IF EXISTS {database}")
            admin_client.close()

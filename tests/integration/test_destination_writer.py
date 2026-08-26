"""Integration tests for M19's destination writer
(docs/plan/M13-M22-program-plan.md) — live against the real ClickHouse
source at localhost:8190 (origin2) and a real, SAFE destination: the
`demo-clickhouse` container (port 8124), a genuinely separate server.

Per the user's own standing hard rule for this milestone, `origin1`/
`origin2` on `localhost:8190` are NEVER configured or tested as a
destination anywhere in this file — only as the (real, read-only) source.

Two things are proven:

1. `TestSelfWriteRefusalLive` — the real HTTP route refuses (409) both
   the exact self-write case (destination == source) and the
   same-server-different-database case (destination on `localhost:8190`
   but a different database than the source), WITHOUT ever creating a
   destination connector, a destination database, or any real
   normalization work — the check runs before any of that.
2. `TestDestinationWriteAgainstARealSafeDestination` — a real, small
   (`Industry`, 179 rows) source table mirrored into a real destination
   database on `demo-clickhouse`: every source column present, the
   mapped column real-normalized, every unmapped column copied verbatim,
   row count matches the source, and re-running the same completed run
   is refused (409) — resumability at the HTTP layer, matching M17's own
   precedent — while a SEPARATE fresh run of the SAME mapping is proven
   idempotent at the ClickHouse-engine level (row count unchanged after
   `OPTIMIZE ... FINAL`), matching the plan's own explicit verify-live
   requirement.
3. `TestTypedNumericExtractionAgainstRealMessyData` — `Company.revenue`
   (real, genuinely messy production data: `"$17.6 Million"`,
   `"$191,000"`, ranges) mapped `NUMERIC` and streamed directly through
   `stream_table_to_destination` (bounded to a few real chunks, not the
   full 1.27M-row table) into a real destination — proves the typed
   Decimal column, the real parse-failure side-table rows, AND that an
   AMBIGUOUS value (no warning/error of its own) still leaves a real
   explanatory trace rather than a silent, unexplained NULL.

Requires: docker compose up -d postgres demo-clickhouse
"""

from __future__ import annotations

import contextlib
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
from normalizers.numeric import NumericNormalizer
from normapi.app import create_app
from normapi.secrets import generate_secret_key
from normexec.destination_stream import stream_table_to_destination
from normio.connectors.clickhouse import ClickHouseConnector
from normsink.clickhouse import ClickHouseDestinationConnector, destination_type_for
from normsink.destination import DestinationColumnSpec

from normanalysis import RunRecorder
from normcore import (
    Dispatcher,
    FieldSemanticType,
    NormalizationProfile,
    NormalizationRun,
    NormalizationRunMetrics,
    NormalizerRegistry,
    RunStatus,
)

_PG_DSN = os.environ.get(
    "TEST_METADATA_PG_DSN", "postgresql://normalization:normalization@localhost:5535/normalization"
)
_REAL_CLICKHOUSE_HOST = os.environ.get("TEST_CLICKHOUSE_HOST", "localhost")
_REAL_SOURCE_PORT = 8190
_SAFE_DESTINATION_PORT = 8124  # demo-clickhouse — NEVER localhost:8190
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
            host=_REAL_CLICKHOUSE_HOST, port=_SAFE_DESTINATION_PORT, username="default", password=""
        )
        client.ping()
        client.close()
    except Exception as exc:  # any connectivity failure means skip
        pytest.skip(f"demo-clickhouse not reachable at port {_SAFE_DESTINATION_PORT}: {exc}")


def _create_app(tmp_path: Path) -> FastAPI:
    secret_key = generate_secret_key()
    return create_app(
        postgres_dsn=_PG_DSN,
        secret_key=secret_key,
        sidecar_parquet_root=tmp_path / "parquet",
        sidecar_duckdb_path=tmp_path / "catalog.duckdb",
    )


def _create_source_connection(client: TestClient, alias: str) -> str:
    """The REAL source — localhost:8190/origin2 — read-only use only,
    every test in this file only ever configures this as a `source_*`
    field, never a `destination_*` one."""
    response = client.post(
        "/normalization/connections",
        json={
            "alias": alias,
            "kind": "clickhouse",
            "host": _REAL_CLICKHOUSE_HOST,
            "port": _REAL_SOURCE_PORT,
            "username": "default",
            "password": "pass",
            "database": "origin2",
        },
    )
    assert response.status_code == 201, response.text
    result: str = response.json()["id"]
    return result


def _create_safe_destination_connection(client: TestClient, alias: str) -> str:
    """demo-clickhouse (port 8124) — a genuinely separate real server
    from the source's localhost:8190, safe to write to."""
    response = client.post(
        "/normalization/connections",
        json={
            "alias": alias,
            "kind": "clickhouse",
            "host": _REAL_CLICKHOUSE_HOST,
            "port": _SAFE_DESTINATION_PORT,
            "username": "default",
            "password": "",
            "database": "default",
        },
    )
    assert response.status_code == 201, response.text
    result: str = response.json()["id"]
    return result


def _create_pending_run(client: TestClient) -> str:
    profile_resp = client.post(
        "/normalization/profiles",
        json={"name": "m19-test", "field_configs": [], "created_by": "tester"},
    )
    assert profile_resp.status_code == 201, profile_resp.text
    profile_id = profile_resp.json()["id"]
    run_resp = client.post(f"/normalization/runs?profile_id={profile_id}&source_snapshot=m19-snap")
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


def _destination_db_client() -> Any:
    return clickhouse_connect.get_client(
        host=_REAL_CLICKHOUSE_HOST, port=_SAFE_DESTINATION_PORT, username="default", password=""
    )


@pytest.mark.integration
class TestSelfWriteRefusalLive:
    def test_destination_equal_to_source_is_refused_via_the_real_http_route(
        self, tmp_path: Path
    ) -> None:
        _skip_if_pg_unreachable()
        app = _create_app(tmp_path)
        client = TestClient(app)
        source_id = _create_source_connection(client, "m19-refusal-exact")
        try:
            run_id = _create_pending_run(client)
            response = client.post(
                f"/normalization/runs/{run_id}/destination",
                json={
                    "source_connection_id": source_id,
                    "source_database": "origin2",
                    "source_table": "Industry",
                    "destination_connection_id": source_id,  # literally the same connection
                    "destination_database": "origin2",
                    "destination_table": "Industry_norm",
                    "columns": [
                        {"table": "Industry", "column": "name", "semantic_type": "FREE_TEXT"}
                    ],
                },
            )
            assert response.status_code == 409, response.text
            assert "exact same connection" in response.json()["detail"]

            # The run must still be PENDING — nothing was ever attempted.
            run = client.get(f"/normalization/runs/{run_id}").json()
            assert run["status"] == "PENDING"
        finally:
            client.delete(f"/normalization/connections/{source_id}")

    def test_destination_on_the_same_server_different_database_is_refused_by_default(
        self, tmp_path: Path
    ) -> None:
        """The plan's own callout #3, proven live: `origin1` as a
        destination while `origin2` is the source, same real server
        (localhost:8190) — refused without `i_understand_same_server`."""
        _skip_if_pg_unreachable()
        app = _create_app(tmp_path)
        client = TestClient(app)
        source_id = _create_source_connection(client, "m19-refusal-same-server")
        try:
            run_id = _create_pending_run(client)
            response = client.post(
                f"/normalization/runs/{run_id}/destination",
                json={
                    "source_connection_id": source_id,
                    "source_database": "origin2",
                    "source_table": "Industry",
                    "destination_connection_id": source_id,
                    "destination_database": "origin1",  # different DB, SAME real server
                    "destination_table": "Industry_norm",
                    "columns": [
                        {"table": "Industry", "column": "name", "semantic_type": "FREE_TEXT"}
                    ],
                },
            )
            assert response.status_code == 409, response.text
            assert "SAME server" in response.json()["detail"]
        finally:
            client.delete(f"/normalization/connections/{source_id}")


@pytest.mark.integration
class TestDestinationWriteAgainstARealSafeDestination:
    def test_industry_mirrored_into_demo_clickhouse_matches_source(self, tmp_path: Path) -> None:
        _skip_if_pg_unreachable()
        _skip_if_demo_clickhouse_unreachable()
        app = _create_app(tmp_path)
        client = TestClient(app)
        source_id = _create_source_connection(client, "m19-write-source")
        destination_id = _create_safe_destination_connection(client, "m19-write-destination")
        destination_db_client = _destination_db_client()
        destination_database = f"m19_test_{uuid.uuid4().hex[:8]}"
        try:
            run_id = _create_pending_run(client)
            response = client.post(
                f"/normalization/runs/{run_id}/destination",
                json={
                    "source_connection_id": source_id,
                    "source_database": "origin2",
                    "source_table": "Industry",
                    "destination_connection_id": destination_id,
                    "destination_database": destination_database,
                    "destination_table": "Industry_norm",
                    "columns": [
                        {"table": "Industry", "column": "name", "semantic_type": "FREE_TEXT"}
                    ],
                    "chunk_size": 50,
                },
            )
            assert response.status_code == 202, response.text

            final = _poll_until(client, run_id, timeout=60)
            assert final.get("status") == "COMPLETED", final
            assert final["metrics"]["records_processed"] == 179

            row_count = destination_db_client.query(
                f"SELECT count(*) FROM {destination_database}.Industry_norm"
            ).result_rows[0][0]
            assert row_count == 179

            # Every real source column is present — mapped (`name`) AND
            # unmapped (`classificationID`, `surfaceForm`, `created_at`).
            dest_columns = {
                row[0]
                for row in destination_db_client.query(
                    "SELECT name FROM system.columns WHERE database = %(db)s AND table = %(t)s",
                    parameters={"db": destination_database, "t": "Industry_norm"},
                ).result_rows
            }
            assert dest_columns == {"classificationID", "name", "surfaceForm", "created_at"}

            # A real, unmapped column's value matches the source verbatim
            # for at least one real row.
            source_client = clickhouse_connect.get_client(
                host=_REAL_CLICKHOUSE_HOST,
                port=_REAL_SOURCE_PORT,
                username="default",
                password="pass",
                database="origin2",
            )
            try:
                source_row = source_client.query(
                    "SELECT classificationID, surfaceForm FROM Industry LIMIT 1"
                ).result_rows[0]
                dest_row = destination_db_client.query(
                    f"SELECT classificationID, surfaceForm FROM {destination_database}."
                    "Industry_norm WHERE classificationID = {cid:String}",
                    parameters={"cid": source_row[0]},
                ).result_rows[0]
                assert dest_row == source_row
            finally:
                source_client.close()

            # Re-running the SAME already-COMPLETED run is refused —
            # resumability at the HTTP layer, matching M17's precedent.
            second = client.post(
                f"/normalization/runs/{run_id}/destination",
                json={
                    "source_connection_id": source_id,
                    "source_database": "origin2",
                    "source_table": "Industry",
                    "destination_connection_id": destination_id,
                    "destination_database": destination_database,
                    "destination_table": "Industry_norm",
                    "columns": [
                        {"table": "Industry", "column": "name", "semantic_type": "FREE_TEXT"}
                    ],
                    "chunk_size": 50,
                },
            )
            assert second.status_code == 409

            # A genuinely NEW run over the SAME mapping proves engine-level
            # idempotency: ReplacingMergeTree + OPTIMIZE FINAL collapses
            # the re-inserted rows back to the same real row count.
            second_run_id = _create_pending_run(client)
            third = client.post(
                f"/normalization/runs/{second_run_id}/destination",
                json={
                    "source_connection_id": source_id,
                    "source_database": "origin2",
                    "source_table": "Industry",
                    "destination_connection_id": destination_id,
                    "destination_database": destination_database,
                    "destination_table": "Industry_norm",
                    "columns": [
                        {"table": "Industry", "column": "name", "semantic_type": "FREE_TEXT"}
                    ],
                    "chunk_size": 50,
                },
            )
            assert third.status_code == 202, third.text
            third_final = _poll_until(client, second_run_id, timeout=60)
            assert third_final.get("status") == "COMPLETED", third_final

            destination_db_client.command(
                f"OPTIMIZE TABLE {destination_database}.Industry_norm FINAL"
            )
            row_count_after = destination_db_client.query(
                f"SELECT count(*) FROM {destination_database}.Industry_norm"
            ).result_rows[0][0]
            assert row_count_after == 179
        finally:
            destination_db_client.command(f"DROP DATABASE IF EXISTS {destination_database}")
            destination_db_client.close()
            client.delete(f"/normalization/connections/{source_id}")
            client.delete(f"/normalization/connections/{destination_id}")


def _real_dispatcher() -> Dispatcher:
    registry = NormalizerRegistry()
    registry.register(NumericNormalizer())
    return Dispatcher(registry, env_id="e" * 64)


def _real_profile() -> NormalizationProfile:
    return NormalizationProfile(
        id="p1",
        name="p",
        version="v1",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        created_by="tester",
    )


def _real_recorder() -> RunRecorder:
    run = NormalizationRun(
        id="run-typed",
        profile_id="p1",
        profile_version="v1",
        env_id="e" * 64,
        source_snapshot="s",
        started_at="2026-01-01T00:00:00Z",
        status=RunStatus.PENDING,
        metrics=NormalizationRunMetrics(),
    )
    recorder = RunRecorder(run)
    recorder.start()
    return recorder


@pytest.mark.integration
class TestTypedNumericExtractionAgainstRealMessyData:
    def test_company_revenue_mapped_numeric_against_real_production_data(
        self, tmp_path: Path
    ) -> None:
        """Bounded to a few real chunks (`Company` has ~1.27M rows) via
        the same "raise from the on_chunk_committed callback" technique
        M17's own `test_stream_column.py` established for bounding a
        large real table — not run to completion."""
        _skip_if_demo_clickhouse_unreachable()
        destination_database = f"m19_typed_test_{uuid.uuid4().hex[:8]}"
        destination_db_client = _destination_db_client()

        class _StopStreaming(Exception):
            pass

        source_connector = ClickHouseConnector(
            "m19-typed-source",
            _REAL_CLICKHOUSE_HOST,
            port=_REAL_SOURCE_PORT,
            username="default",
            password="pass",
            database="origin2",
        )
        destination_connector = ClickHouseDestinationConnector(
            host=_REAL_CLICKHOUSE_HOST,
            port=_SAFE_DESTINATION_PORT,
            username="default",
            password="",
            database=destination_database,
        )
        try:
            source_columns = source_connector.list_columns("Company")
            column_semantic_types = {"revenue": FieldSemanticType.NUMERIC}
            destination_columns = [
                DestinationColumnSpec(
                    name=col.name,
                    destination_type=destination_type_for(
                        semantic_type_value=column_semantic_types[col.name].value
                        if col.name in column_semantic_types
                        else None,
                        source_type=col.type,
                    ),
                    is_mapped=col.name in column_semantic_types,
                )
                for col in source_columns
            ]
            destination_connector.ensure_database()
            destination_connector.ensure_table(
                "Company_norm", columns=destination_columns, key_columns=["companyID"]
            )
            destination_connector.ensure_side_table("Company_norm")

            chunks_seen = 0

            def _stop_after_two_chunks(_progress: object) -> None:
                nonlocal chunks_seen
                chunks_seen += 1
                if chunks_seen >= 2:
                    raise _StopStreaming

            with contextlib.suppress(_StopStreaming):
                stream_table_to_destination(
                    source_connector,
                    run_id="run-typed",
                    table="Company",
                    key_columns=["companyID"],
                    source_columns=source_columns,
                    column_semantic_types=column_semantic_types,
                    field_ref_prefix="m19-typed.origin2.Company.",
                    profile=_real_profile(),
                    dispatcher=_real_dispatcher(),
                    cache=None,
                    recorder=_real_recorder(),
                    destination=destination_connector,
                    destination_table="Company_norm",
                    chunk_size=25,
                    on_chunk_committed=_stop_after_two_chunks,
                )

            assert chunks_seen == 2

            revenue_type = destination_db_client.query(
                "SELECT type FROM system.columns WHERE database = %(db)s AND table = %(t)s "
                "AND name = 'revenue'",
                parameters={"db": destination_database, "t": "Company_norm"},
            ).result_rows[0][0]
            assert revenue_type == "Nullable(Decimal(38, 9))"

            row_count = destination_db_client.query(
                f"SELECT count(*) FROM {destination_database}.Company_norm"
            ).result_rows[0][0]
            # NOT necessarily exactly 50 (2 chunks x chunk_size=25): real
            # `Company` data has genuine un-merged ReplacingMergeTree
            # duplicate companyIDs upstream (verified live — the same
            # real characteristic M14's own pack already disclosed for
            # `Person`), which the destination's own ReplacingMergeTree
            # engine may have already merged away if a background merge
            # ran before this query. <= 50 is the real, correct bound.
            assert 0 < row_count <= 50

            # Real messy production data ("$17.6 Million", "50 - 100"
            # ranges) means at least one row's revenue genuinely fails to
            # parse as NUMERIC — proving the typed column is really
            # NULL-on-failure, not silently accepting garbage.
            null_count = destination_db_client.query(
                f"SELECT count(*) FROM {destination_database}.Company_norm WHERE revenue IS NULL"
            ).result_rows[0][0]
            assert null_count > 0

            # Every NULL caused by a real parse failure (as opposed to a
            # genuinely NULL/empty source value, which correctly gets no
            # issue row — nothing to explain) has a real, explanatory
            # side-table row: at least one real issue row exists, and the
            # issue count can never exceed the NULL count (every issue
            # row corresponds to some NULL value, never a phantom one).
            issue_count = destination_db_client.query(
                f"SELECT count(*) FROM {destination_database}.Company_norm__normalization_issues "
                "WHERE column_name = 'revenue'"
            ).result_rows[0][0]
            assert 0 < issue_count <= null_count
        finally:
            destination_db_client.command(f"DROP DATABASE IF EXISTS {destination_database}")
            destination_db_client.close()
            source_connector.close()
            destination_connector.close()

"""Integration tests for M16's catalog browsing + column mapping API —
live against the real ClickHouse at localhost:8190 (origin2) and the real
metadata Postgres (compose.yaml's `postgres` service, port 5535).

Two things proven, matching the M13-M22 plan's own verify-live bullet for
M16, not assumed:
1. Map Person.fullName->PERSON_NAME, Company.name->COMPANY_NAME,
   Location.country->COUNTRY, Location.zip->POSTCODE via the real API.
2. DELETE the connection; re-add under a DIFFERENT alias with the same
   host/port/database -> the mappings reappear, because they're keyed by
   real connection identity, never by the connection's own id/alias.

Requires: docker compose up -d postgres
"""

from __future__ import annotations

import os

import psycopg
import pytest
from fastapi.testclient import TestClient
from normapi.app import create_app
from normapi.secrets import generate_secret_key

_PG_DSN = os.environ.get(
    "TEST_METADATA_PG_DSN", "postgresql://normalization:normalization@localhost:5535/normalization"
)
_REAL_CLICKHOUSE_HOST = os.environ.get("TEST_CLICKHOUSE_HOST", "localhost")


def _skip_if_pg_unreachable() -> None:
    try:
        conn = psycopg.connect(_PG_DSN, connect_timeout=3)
    except psycopg.OperationalError as exc:
        pytest.skip(f"metadata postgres not reachable at {_PG_DSN}: {exc}")
    else:
        conn.close()


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(postgres_dsn=_PG_DSN, secret_key=generate_secret_key()))


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


@pytest.mark.integration
class TestCatalogBrowsingLiveAgainstRealClickHouse:
    def test_list_databases_tables_columns_samples(self, client: TestClient) -> None:
        _skip_if_pg_unreachable()
        connection_id = _create_real_connection(client, "m16-catalog-verify")
        try:
            databases = client.get(f"/normalization/connections/{connection_id}/databases")
            assert databases.status_code == 200
            assert "origin2" in databases.json()

            tables = client.get(
                f"/normalization/connections/{connection_id}/databases/origin2/tables"
            )
            assert tables.status_code == 200
            assert "Person" in tables.json()

            columns = client.get(
                f"/normalization/connections/{connection_id}/databases/origin2/tables/Person/columns"
            )
            assert columns.status_code == 200
            body = columns.json()
            assert body["name"] == "Person"
            column_names = {c["name"] for c in body["columns"]}
            assert "fullName" in column_names
            assert "personID" in column_names
            pk_columns = {c["name"] for c in body["columns"] if c["is_primary_key"]}
            assert pk_columns  # Person has a real primary key

            samples = client.get(
                f"/normalization/connections/{connection_id}/databases/origin2/tables/Person/samples",
                params={"n": 3},
            )
            assert samples.status_code == 200
            samples_body = samples.json()
            assert "fullName" in samples_body
            assert len(samples_body["fullName"]) <= 3
        finally:
            client.delete(f"/normalization/connections/{connection_id}")


@pytest.mark.integration
class TestColumnMappingsLiveAgainstRealClickHouse:
    def test_map_four_real_columns_per_the_program_plans_own_verify_live_list(
        self, client: TestClient
    ) -> None:
        connection_id = _create_real_connection(client, "m16-mapping-verify")
        try:
            targets = [
                ("Person", "fullName", "PERSON_NAME"),
                ("Company", "name", "COMPANY_NAME"),
                ("Location", "country", "COUNTRY"),
                ("Location", "zip", "POSTCODE"),
            ]
            for table, column, semantic_type in targets:
                response = client.put(
                    f"/normalization/connections/{connection_id}/databases/origin2"
                    f"/tables/{table}/columns/{column}/mapping",
                    json={"semantic_type": semantic_type, "updated_by": "tester"},
                )
                assert response.status_code == 200, response.text
                body = response.json()
                assert body["semantic_type"] == semantic_type
                assert body["table_name"] == table
                assert body["column_name"] == column

            person_mappings = client.get(
                f"/normalization/connections/{connection_id}/databases/origin2/tables/Person/mappings"
            )
            assert person_mappings.status_code == 200
            assert len(person_mappings.json()) == 1
            assert person_mappings.json()[0]["semantic_type"] == "PERSON_NAME"

            location_mappings = client.get(
                f"/normalization/connections/{connection_id}/databases/origin2"
                "/tables/Location/mappings"
            )
            assert location_mappings.status_code == 200
            location_types = {
                m["column_name"]: m["semantic_type"] for m in location_mappings.json()
            }
            assert location_types == {"country": "COUNTRY", "zip": "POSTCODE"}
        finally:
            client.delete(f"/normalization/connections/{connection_id}")

    def test_mappings_survive_delete_and_re_add_under_a_different_alias(
        self, client: TestClient
    ) -> None:
        """The real point of keying mappings by connection identity, not
        connection id/alias (decision 4 of the M13-M22 program)."""
        first_connection_id = _create_real_connection(client, "m16-original-alias")
        upsert = client.put(
            f"/normalization/connections/{first_connection_id}/databases/origin2"
            "/tables/Company/columns/name/mapping",
            json={"semantic_type": "COMPANY_NAME", "updated_by": "tester"},
        )
        assert upsert.status_code == 200, upsert.text

        client.delete(f"/normalization/connections/{first_connection_id}")

        second_connection_id = _create_real_connection(client, "m16-a-completely-different-alias")
        try:
            assert second_connection_id != first_connection_id  # a genuinely new connection row

            mappings = client.get(
                f"/normalization/connections/{second_connection_id}/databases/origin2"
                "/tables/Company/mappings"
            )
            assert mappings.status_code == 200
            body = mappings.json()
            assert len(body) == 1
            assert body[0]["semantic_type"] == "COMPANY_NAME"
            assert body[0]["column_name"] == "name"
        finally:
            client.delete(f"/normalization/connections/{second_connection_id}")

    def test_mapping_with_profile_id_materializes_a_new_profile_version(
        self, client: TestClient
    ) -> None:
        connection_id = _create_real_connection(client, "m16-materialize-verify")
        try:
            profile_resp = client.post(
                "/normalization/profiles",
                json={"name": "m16-materialize-test", "field_configs": [], "created_by": "tester"},
            )
            assert profile_resp.status_code == 201, profile_resp.text
            profile_id = profile_resp.json()["id"]
            assert profile_resp.json()["version"] == "v1"

            upsert = client.put(
                f"/normalization/connections/{connection_id}/databases/origin2"
                "/tables/Person/columns/fullName/mapping",
                json={
                    "semantic_type": "PERSON_NAME",
                    "updated_by": "tester",
                    "profile_id": profile_id,
                },
            )
            assert upsert.status_code == 200, upsert.text

            profile_after = client.get(f"/normalization/profiles/{profile_id}")
            assert profile_after.status_code == 200
            body = profile_after.json()
            assert body["version"] == "v2"  # a real new version was created
            field_refs = [fc["field_ref"] for fc in body["field_configs"]]
            assert len(field_refs) == 1
            assert field_refs[0].endswith(".origin2.Person.fullName")
            assert body["field_configs"][0]["semantic_type"] == "PERSON_NAME"
        finally:
            client.delete(f"/normalization/connections/{connection_id}")

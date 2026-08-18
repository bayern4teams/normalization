"""Exercises every Source.txt §98 route against a real running FastAPI app
(via TestClient — an actual ASGI request/response cycle, not a mocked
router) and asserts each returns a schema-valid response, per M1's Gate G1
requirement.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from normapi.app import create_app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    dict_dir = tmp_path / "dictionaries"
    dict_dir.mkdir()
    custom_dict_dir = tmp_path / "custom-dictionaries"
    app = create_app(dictionaries_dir=dict_dir, custom_dictionaries_dir=custom_dict_dir)
    return TestClient(app)


@pytest.mark.unit
def test_health() -> None:
    client = TestClient(create_app())
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.unit
def test_openapi_schema_is_published() -> None:
    client = TestClient(create_app())
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    schema = resp.json()
    paths = schema["paths"]
    for expected in (
        "/normalization/profiles",
        "/normalization/fields",
        "/normalization/preview",
        "/normalization/runs",
        "/normalization/runs/{run_id}",
        "/normalization/runs/{run_id}/errors",
        "/normalization/runs/{run_id}/collisions",
        "/normalization/profiles/{profile_id}/versions",
        "/normalization/dictionaries",
        "/normalization/field-test",
        "/normalization/impact",
    ):
        assert expected in paths, f"{expected} missing from OpenAPI schema"


@pytest.mark.unit
def test_create_and_list_profiles(client: TestClient) -> None:
    resp = client.post(
        "/normalization/profiles",
        json={
            "name": "customer-fields",
            "description": "test profile",
            "field_configs": [
                {"field_ref": "customers.first_name", "semantic_type": "PERSON_NAME"}
            ],
            "created_by": "tester",
        },
    )
    assert resp.status_code == 201
    profile = resp.json()
    assert profile["name"] == "customer-fields"
    assert profile["version"] == "v1"
    assert profile["status"] == "ACTIVE"

    list_resp = client.get("/normalization/profiles")
    assert list_resp.status_code == 200
    assert any(p["id"] == profile["id"] for p in list_resp.json())


@pytest.mark.unit
def test_profile_versioning_deprecates_previous_version(client: TestClient) -> None:
    created = client.post(
        "/normalization/profiles",
        json={"name": "p", "field_configs": [], "created_by": "tester"},
    ).json()

    versioned = client.post(
        f"/normalization/profiles/{created['id']}/versions",
        json={"description": "v2 update", "created_by": "tester"},
    )
    assert versioned.status_code == 201
    v2 = versioned.json()
    assert v2["version"] == "v2"
    assert v2["parent_version"] == "v1"
    assert v2["status"] == "ACTIVE"

    # The active listing shows only the new version, not both
    profiles = client.get("/normalization/profiles").json()
    matching = [p for p in profiles if p["id"] == created["id"]]
    assert len(matching) == 1
    assert matching[0]["version"] == "v2"


@pytest.mark.unit
def test_create_version_for_unknown_profile_404s(client: TestClient) -> None:
    resp = client.post(
        "/normalization/profiles/does-not-exist/versions",
        json={"created_by": "tester"},
    )
    assert resp.status_code == 404


@pytest.mark.unit
def test_fields_derived_from_profiles(client: TestClient) -> None:
    client.post(
        "/normalization/profiles",
        json={
            "name": "p",
            "field_configs": [{"field_ref": "customers.email", "semantic_type": "EMAIL"}],
            "created_by": "tester",
        },
    )
    resp = client.get("/normalization/fields")
    assert resp.status_code == 200
    fields = resp.json()
    assert any(
        f["field_ref"] == "customers.email" and f["semantic_type"] == "EMAIL" for f in fields
    )


@pytest.mark.unit
def test_preview_runs_real_dispatcher(client: TestClient) -> None:
    resp = client.post(
        "/normalization/preview",
        json={
            "field_name": "first_name",
            "semantic_type": "PERSON_NAME",
            "values": ["  John  ", None],
        },
    )
    assert resp.status_code == 200
    results = resp.json()
    assert len(results) == 2
    assert results[0]["original"] == "  John  "
    # NameNormalizer (M3) is the real adapter for PERSON_NAME now — it
    # trims whitespace via the shared UnicodeNormalizer pre-processing
    # stage, unlike M1's PassthroughNormalizer placeholder this test
    # originally exercised.
    assert results[0]["display"] == "John"
    assert results[1]["original"] is None


@pytest.mark.unit
def test_field_test_runs_real_dispatcher(client: TestClient) -> None:
    resp = client.post(
        "/normalization/field-test",
        json={"field_name": "email", "semantic_type": "EMAIL", "value": "x@example.com"},
    )
    assert resp.status_code == 200
    result = resp.json()
    assert result["original"] == "x@example.com"
    assert result["comparison"] == "x@example.com"


@pytest.mark.unit
def test_run_lifecycle(client: TestClient) -> None:
    profile = client.post(
        "/normalization/profiles",
        json={"name": "p", "field_configs": [], "created_by": "tester"},
    ).json()

    run_resp = client.post(
        "/normalization/runs",
        params={"profile_id": profile["id"], "source_snapshot": "snap-1"},
    )
    assert run_resp.status_code == 201
    run = run_resp.json()
    assert run["profile_id"] == profile["id"]
    assert run["status"] == "PENDING"
    assert run["env_id"]

    get_resp = client.get(f"/normalization/runs/{run['id']}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == run["id"]

    errors_resp = client.get(f"/normalization/runs/{run['id']}/errors")
    assert errors_resp.status_code == 200
    assert errors_resp.json() == []

    collisions_resp = client.get(f"/normalization/runs/{run['id']}/collisions")
    assert collisions_resp.status_code == 200
    assert collisions_resp.json() == []


@pytest.mark.unit
def test_run_for_unknown_profile_404s(client: TestClient) -> None:
    resp = client.post("/normalization/runs", params={"profile_id": "nope", "source_snapshot": "s"})
    assert resp.status_code == 404


@pytest.mark.unit
def test_unknown_run_id_404s(client: TestClient) -> None:
    assert client.get("/normalization/runs/nope").status_code == 404
    assert client.get("/normalization/runs/nope/errors").status_code == 404
    assert client.get("/normalization/runs/nope/collisions").status_code == 404


@pytest.mark.unit
def test_dictionaries_list_reflects_real_seeded_dictionary() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    app = create_app(dictionaries_dir=repo_root / "data" / "dictionaries")
    client = TestClient(app)

    resp = client.get("/normalization/dictionaries")
    assert resp.status_code == 200
    dictionaries = resp.json()
    assert any(d["id"] == "honorifics.common" and d["version"] == "2026.08" for d in dictionaries)


@pytest.mark.unit
def test_dictionary_create_and_impact_are_real_as_of_m6(client: TestClient) -> None:
    """M1's honest-501 scaffold for these two routes is gone as of M6 —
    both are now wired to real logic (normdict.CustomDictionaryStore,
    normanalysis.compute_impact). A malformed/incomplete request now 404s
    or 422s on real validation instead of always 501ing."""
    dict_resp = client.post(
        "/normalization/dictionaries",
        json={"id": "m6-scaffold-test", "source": "test", "license": "CC0", "created_by": "tester"},
    )
    assert dict_resp.status_code == 201
    assert dict_resp.json()["is_custom"] is True

    impact_resp = client.get("/normalization/impact", params={"run_id": "nonexistent"})
    assert impact_resp.status_code == 404

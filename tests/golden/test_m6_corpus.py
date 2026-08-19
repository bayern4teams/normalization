"""M6 golden corpus — Source.txt Gate G6's explicit requirements:
impact analysis (§78) matching the spec's own worked-example shape,
collision analysis (§79/§92) reproducing the José/Jose example, A/B
comparison (§96), and dictionary versioning/rollback (§59) round-tripping
through the live API surface.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from normapi.app import create_app

_DICT_ROOT = Path(__file__).parents[2] / "data" / "dictionaries"


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    app = create_app(
        dictionaries_dir=_DICT_ROOT, custom_dictionaries_dir=tmp_path / "custom-dictionaries"
    )
    return TestClient(app)


def _create_profile(client: TestClient) -> str:
    resp = client.post(
        "/normalization/profiles",
        json={"name": "p", "field_configs": [], "created_by": "tester"},
    )
    result: str = resp.json()["id"]
    return result


def _execute_run(
    client: TestClient, profile_id: str, values: list[str | None]
) -> dict[str, object]:
    resp = client.post(
        f"/normalization/runs?profile_id={profile_id}&source_snapshot=snap",
        json={"field_name": "name", "semantic_type": "FREE_TEXT", "values": values},
    )
    assert resp.status_code == 201
    result: dict[str, object] = resp.json()
    return result


@pytest.mark.golden
def test_source_txt_78_worked_example_shape_over_live_api(client: TestClient) -> None:
    """§78's own worked example: unique_before, unique_after, and "New
    collisions" — reproduced through the real running API, not a bare
    function call."""
    profile_id = _create_profile(client)
    run = _execute_run(
        client,
        profile_id,
        ["Jose Garcia", "José García", "JOSÉ GARCÍA", "Anna", "Bob"],
    )
    impact = client.get("/normalization/impact", params={"run_id": run["id"]})
    assert impact.status_code == 200
    body = impact.json()
    assert body["unique_before"] == 5
    assert body["unique_after"] == 4
    assert body["new_collisions"] == 1


@pytest.mark.golden
def test_source_txt_79_collision_dashboard_example_over_live_api(client: TestClient) -> None:
    """§79/§92's own worked example format: normalized value + the
    original variants that collapsed into it + count."""
    profile_id = _create_profile(client)
    run = _execute_run(client, profile_id, ["José García", "Jose Garcia", "JOSÉ GARCÍA"])
    collisions = client.get(f"/normalization/runs/{run['id']}/collisions")
    assert collisions.status_code == 200
    groups = collisions.json()
    assert len(groups) == 1
    assert set(groups[0]["original_values"]) == {"José García", "JOSÉ GARCÍA"}
    assert groups[0]["total_occurrences"] == 2


@pytest.mark.golden
def test_source_txt_77_profiling_preview_over_live_api(client: TestClient) -> None:
    """§77's own worked example shape: rows/changed/unchanged/warnings/
    errors/potentially-lossy plus top transformation patterns."""
    profile_id = _create_profile(client)
    run = _execute_run(client, profile_id, ["  Anna  ", "Bob", "Anna"])
    profile_resp = client.get(f"/normalization/runs/{run['id']}/profile")
    assert profile_resp.status_code == 200
    body = profile_resp.json()
    assert body["rows"] == 3
    assert body["changed"] == 1
    assert body["unchanged"] == 2
    assert isinstance(body["top_transformation_patterns"], list)


@pytest.mark.golden
def test_dictionary_full_lifecycle_over_live_api(client: TestClient) -> None:
    """§59: Import(create)/Edit(version)/Version/Rollback/Delete, all
    through the live API, and a builtin collision refused at the HTTP
    boundary."""
    create = client.post(
        "/normalization/dictionaries",
        json={
            "id": "golden-aliases",
            "entries": {"foo": "bar"},
            "source": "test",
            "license": "CC0",
            "created_by": "alice",
        },
    )
    assert create.status_code == 201
    assert create.json()["version"] == "v1"

    builtin_collision = client.post(
        "/normalization/dictionaries",
        json={
            "id": "honorifics.common",
            "entries": {},
            "source": "x",
            "license": "x",
            "created_by": "alice",
        },
    )
    assert builtin_collision.status_code == 409

    versioned = client.post(
        "/normalization/dictionaries/golden-aliases/versions",
        json={"entries": {"baz": "qux"}, "created_by": "alice", "merge": True},
    )
    assert versioned.status_code == 201
    assert versioned.json()["version"] == "v2"
    assert versioned.json()["entry_count"] == 2

    rolled_back = client.post(
        "/normalization/dictionaries/golden-aliases/rollback",
        json={"target_version": "v1", "by": "bob"},
    )
    assert rolled_back.status_code == 200
    assert rolled_back.json()["active_version"] == "v1"

    listing = client.get("/normalization/dictionaries")
    custom_rows = [row for row in listing.json() if row["is_custom"]]
    assert {row["id"] for row in custom_rows} == {"golden-aliases"}

    deleted = client.delete("/normalization/dictionaries/golden-aliases", params={"by": "bob"})
    assert deleted.status_code == 204


@pytest.mark.golden
def test_ab_comparison_over_live_api(client: TestClient) -> None:
    """§96 A/B normalization — two runs over the same aligned values,
    compared through the live `/runs/compare` route."""
    profile_id = _create_profile(client)
    values: list[str | None] = ["Jose Garcia", "José García", "Anna"]
    run_a = _execute_run(client, profile_id, values)
    run_b = _execute_run(client, profile_id, values)

    compare = client.get(
        "/normalization/runs/compare",
        params={"run_id_a": run_a["id"], "run_id_b": run_b["id"]},
    )
    assert compare.status_code == 200
    body = compare.json()
    assert body["changed_between_a_and_b"] == 0
    assert body["a"]["unique_values"] == body["b"]["unique_values"]


@pytest.mark.golden
def test_profile_rollback_over_live_api(client: TestClient) -> None:
    """§59/§94: rolling a profile back reactivates a prior version without
    deleting the version rolled back from."""
    profile_id = _create_profile(client)
    client.post(
        f"/normalization/profiles/{profile_id}/versions",
        json={"description": "v2", "created_by": "tester"},
    )
    rolled_back = client.post(
        f"/normalization/profiles/{profile_id}/rollback", json={"target_version": "v1"}
    )
    assert rolled_back.status_code == 200
    assert rolled_back.json()["version"] == "v1"
    assert rolled_back.json()["status"] == "ACTIVE"

    # rolling forward again must still work — v2 was never deleted
    forward = client.post(
        f"/normalization/profiles/{profile_id}/rollback", json={"target_version": "v2"}
    )
    assert forward.status_code == 200
    assert forward.json()["version"] == "v2"

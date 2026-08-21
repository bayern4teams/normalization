"""M11 golden corpus — the Collision Dashboard's real action buttons
(Source.txt §92: Accept rule / Reject rule / Inspect / Whitelist
collision), proven over the live API. "Inspect" already existed
(GET .../collisions); this is what makes Accept/Reject/Whitelist real
persisted decisions instead of dead buttons.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from normapi.app import create_app

_DICT_ROOT = Path(__file__).parents[2] / "data" / "dictionaries"
_TERMINAL_STATUSES = {"COMPLETED", "FAILED", "PARTIAL"}


def _wait_for_terminal(
    client: TestClient, run_id: str, *, timeout: float = 5.0
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = client.get(f"/normalization/runs/{run_id}")
        assert resp.status_code == 200
        run: dict[str, object] = resp.json()
        if run["status"] in _TERMINAL_STATUSES:
            return run
        time.sleep(0.02)
    pytest.fail(f"Run {run_id} did not reach a terminal status within {timeout}s")


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    app = create_app(
        dictionaries_dir=_DICT_ROOT, custom_dictionaries_dir=tmp_path / "custom-dictionaries"
    )
    return TestClient(app)


def _run_with_collision(client: TestClient) -> str:
    profile_resp = client.post(
        "/normalization/profiles",
        json={"name": "p", "field_configs": [], "created_by": "tester"},
    )
    profile_id = profile_resp.json()["id"]
    run_resp = client.post(
        f"/normalization/runs?profile_id={profile_id}&source_snapshot=snap",
        json={
            "field_name": "name",
            "semantic_type": "FREE_TEXT",
            "values": ["José García", "Jose Garcia", "JOSÉ GARCÍA"],
        },
    )
    assert run_resp.status_code == 201
    run = _wait_for_terminal(client, run_resp.json()["id"])
    run_id = run["id"]
    assert isinstance(run_id, str)
    return run_id


@pytest.mark.golden
def test_whitelist_collision_is_recorded_and_reflected_in_the_dashboard(
    client: TestClient,
) -> None:
    run_id = _run_with_collision(client)
    collisions = client.get(f"/normalization/runs/{run_id}/collisions").json()
    assert len(collisions) == 1
    normalized_value = collisions[0]["normalized_value"]
    assert collisions[0]["decision"] is None  # nobody has reviewed it yet

    decide = client.post(
        f"/normalization/runs/{run_id}/collisions/decision",
        json={
            "normalized_value": normalized_value,
            "decision": "WHITELISTED",
            "decided_by": "alice",
            "note": "intentional accent variants, both correct",
        },
    )
    assert decide.status_code == 201
    body = decide.json()
    assert body["decision"] == "WHITELISTED"
    assert body["decided_by"] == "alice"
    assert body["run_id"] == run_id
    assert body["normalized_value"] == normalized_value

    collisions_after = client.get(f"/normalization/runs/{run_id}/collisions").json()
    assert collisions_after[0]["decision"]["decision"] == "WHITELISTED"
    assert collisions_after[0]["decision"]["decided_by"] == "alice"


@pytest.mark.golden
@pytest.mark.parametrize("decision", ["ACCEPTED", "REJECTED", "WHITELISTED"])
def test_all_three_decision_types_are_accepted(client: TestClient, decision: str) -> None:
    run_id = _run_with_collision(client)
    normalized_value = client.get(f"/normalization/runs/{run_id}/collisions").json()[0][
        "normalized_value"
    ]
    resp = client.post(
        f"/normalization/runs/{run_id}/collisions/decision",
        json={"normalized_value": normalized_value, "decision": decision, "decided_by": "bob"},
    )
    assert resp.status_code == 201
    assert resp.json()["decision"] == decision


@pytest.mark.golden
def test_re_deciding_the_same_collision_overwrites_the_prior_decision(
    client: TestClient,
) -> None:
    run_id = _run_with_collision(client)
    normalized_value = client.get(f"/normalization/runs/{run_id}/collisions").json()[0][
        "normalized_value"
    ]
    client.post(
        f"/normalization/runs/{run_id}/collisions/decision",
        json={"normalized_value": normalized_value, "decision": "REJECTED", "decided_by": "bob"},
    )
    second = client.post(
        f"/normalization/runs/{run_id}/collisions/decision",
        json={
            "normalized_value": normalized_value,
            "decision": "ACCEPTED",
            "decided_by": "carol",
        },
    )
    assert second.status_code == 201

    collisions = client.get(f"/normalization/runs/{run_id}/collisions").json()
    assert collisions[0]["decision"]["decision"] == "ACCEPTED"
    assert collisions[0]["decision"]["decided_by"] == "carol"


@pytest.mark.golden
def test_deciding_a_fabricated_normalized_value_is_404(client: TestClient) -> None:
    run_id = _run_with_collision(client)
    resp = client.post(
        f"/normalization/runs/{run_id}/collisions/decision",
        json={
            "normalized_value": "this was never a real collision group",
            "decision": "ACCEPTED",
            "decided_by": "bob",
        },
    )
    assert resp.status_code == 404


@pytest.mark.golden
def test_deciding_on_an_unknown_run_is_404(client: TestClient) -> None:
    resp = client.post(
        "/normalization/runs/does-not-exist/collisions/decision",
        json={"normalized_value": "x", "decision": "ACCEPTED", "decided_by": "bob"},
    )
    assert resp.status_code == 404

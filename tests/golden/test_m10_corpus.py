"""M10 golden corpus — profile-driven config actually changing live
normalizer behavior (Source.txt §60-62, §101), not just being stored and
ignored. Proven over the real running API, not a bare function call:
the exact same ambiguous input value produces different real
`NormalizedValue.display` output depending purely on the executing
run's profile `locale_policy`/field-level `locale_overrides`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from normapi.app import create_app
from normapi.schemas import ProfileCreateRequest

_DICT_ROOT = Path(__file__).parents[2] / "data" / "dictionaries"


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    app = create_app(
        dictionaries_dir=_DICT_ROOT, custom_dictionaries_dir=tmp_path / "custom-dictionaries"
    )
    return TestClient(app)


def _create_profile(client: TestClient, **kwargs: object) -> str:
    resp = client.post(
        "/normalization/profiles",
        json={"name": "p", "field_configs": [], "created_by": "tester", **kwargs},
    )
    assert resp.status_code == 201
    result: str = resp.json()["id"]
    return result


def _execute_run(
    client: TestClient, profile_id: str, field_name: str, semantic_type: str, values: list[str]
) -> dict[str, object]:
    resp = client.post(
        f"/normalization/runs?profile_id={profile_id}&source_snapshot=snap",
        json={"field_name": field_name, "semantic_type": semantic_type, "values": values},
    )
    assert resp.status_code == 201
    result: dict[str, object] = resp.json()
    return result


def _run_values(client: TestClient, run_id: str) -> list[dict[str, object]]:
    resp = client.get(f"/normalization/runs/{run_id}/values")
    assert resp.status_code == 200
    result: list[dict[str, object]] = resp.json()
    return result


@pytest.mark.golden
def test_profile_locale_policy_resolves_ambiguous_date_order(client: TestClient) -> None:
    """ "03/04/2024" is genuinely ambiguous (day or month first?) — a US
    profile (MDY) and a GB profile (DMY) must produce different real ISO
    dates for the exact same input, driven purely by profile config with
    zero DateNormalizer code changes."""
    us_profile = _create_profile(client, locale_policy={"country": "US"})
    gb_profile = _create_profile(client, locale_policy={"country": "GB"})

    us_run = _execute_run(client, us_profile, "event_date", "DATE", ["03/04/2024"])
    gb_run = _execute_run(client, gb_profile, "event_date", "DATE", ["03/04/2024"])

    us_result = _run_values(client, str(us_run["id"]))[0]["result"]
    gb_result = _run_values(client, str(gb_run["id"]))[0]["result"]
    assert isinstance(us_result, dict)
    assert isinstance(gb_result, dict)
    us_display = us_result["display"]
    gb_display = gb_result["display"]

    assert us_display == "2024-03-04"  # US: MDY -> March 4th
    assert gb_display == "2024-04-03"  # GB: DMY -> April 3rd
    assert us_display != gb_display


@pytest.mark.golden
def test_field_level_locale_override_wins_over_profile_locale_policy(client: TestClient) -> None:
    """A field's own `locale_overrides` must win over the profile-wide
    `locale_policy` for the same field — proven with the same ambiguous
    date, this time both profiles start at "US" and only the field
    config differs."""
    body = ProfileCreateRequest(
        name="p",
        locale_policy={"country": "US"},
        field_configs=(
            {
                "field_ref": "event_date",
                "semantic_type": "DATE",
                "locale_overrides": {"country": "GB"},
            },
        ),
        created_by="tester",
    )
    resp = client.post("/normalization/profiles", json=body.model_dump(mode="json"))
    assert resp.status_code == 201
    profile_id = resp.json()["id"]

    run = _execute_run(client, profile_id, "event_date", "DATE", ["03/04/2024"])
    result = _run_values(client, str(run["id"]))[0]["result"]
    assert isinstance(result, dict)
    assert result["display"] == "2024-04-03"  # field override (GB) wins over profile-wide US


@pytest.mark.golden
def test_run_without_locale_policy_keeps_prior_ambiguous_date_fallback(
    client: TestClient,
) -> None:
    """No regression for existing behavior: a profile with no
    locale_policy at all must produce the same result M6-M9 always did
    (DateNormalizer's own ISO-first-then-ambiguity-flagged fallback),
    since `build_context` leaves `ctx.country`/`ctx.locale` as None."""
    profile_id = _create_profile(client)
    run = _execute_run(client, profile_id, "event_date", "DATE", ["03/04/2024"])
    result = _run_values(client, str(run["id"]))[0]["result"]
    assert isinstance(result, dict)
    assert result["validation_status"] == "AMBIGUOUS"
    assert "AMBIGUOUS_DATE" in result["flags"]

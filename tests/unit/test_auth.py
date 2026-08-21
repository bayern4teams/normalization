"""Lightweight API-key auth (M11, normapi.auth) — over the live API,
not the bare function, since the whole point is a router-level
dependency actually gating real requests.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from normapi.app import create_app

_DICT_ROOT = Path(__file__).parents[2] / "data" / "dictionaries"


def _client(tmp_path: Path, *, api_key: str | None) -> TestClient:
    app = create_app(
        dictionaries_dir=_DICT_ROOT,
        custom_dictionaries_dir=tmp_path / "custom-dictionaries",
        api_key=api_key,
    )
    return TestClient(app)


@pytest.mark.unit
class TestAuthDisabledByDefault:
    def test_no_api_key_configured_mutations_work_without_any_header(self, tmp_path: Path) -> None:
        client = _client(tmp_path, api_key=None)
        resp = client.post(
            "/normalization/profiles",
            json={"name": "p", "field_configs": [], "created_by": "u"},
        )
        assert resp.status_code == 201


@pytest.mark.unit
class TestAuthEnforced:
    def test_post_without_authorization_header_is_401(self, tmp_path: Path) -> None:
        client = _client(tmp_path, api_key="secret123")
        resp = client.post(
            "/normalization/profiles",
            json={"name": "p", "field_configs": [], "created_by": "u"},
        )
        assert resp.status_code == 401

    def test_post_with_wrong_key_is_401(self, tmp_path: Path) -> None:
        client = _client(tmp_path, api_key="secret123")
        resp = client.post(
            "/normalization/profiles",
            json={"name": "p", "field_configs": [], "created_by": "u"},
            headers={"Authorization": "Bearer wrong-key"},
        )
        assert resp.status_code == 401

    def test_post_with_malformed_authorization_header_is_401(self, tmp_path: Path) -> None:
        client = _client(tmp_path, api_key="secret123")
        resp = client.post(
            "/normalization/profiles",
            json={"name": "p", "field_configs": [], "created_by": "u"},
            headers={"Authorization": "secret123"},  # missing "Bearer " prefix
        )
        assert resp.status_code == 401

    def test_post_with_correct_key_succeeds(self, tmp_path: Path) -> None:
        client = _client(tmp_path, api_key="secret123")
        resp = client.post(
            "/normalization/profiles",
            json={"name": "p", "field_configs": [], "created_by": "u"},
            headers={"Authorization": "Bearer secret123"},
        )
        assert resp.status_code == 201

    def test_delete_without_key_is_401(self, tmp_path: Path) -> None:
        client = _client(tmp_path, api_key="secret123")
        create = client.post(
            "/normalization/dictionaries",
            json={
                "id": "auth-test-dict",
                "entries": {"foo": "bar"},
                "source": "test",
                "license": "CC0",
                "created_by": "u",
            },
            headers={"Authorization": "Bearer secret123"},
        )
        assert create.status_code == 201

        delete_resp = client.delete(
            "/normalization/dictionaries/auth-test-dict", params={"by": "u"}
        )
        assert delete_resp.status_code == 401

    def test_get_requests_stay_open_even_with_a_key_configured(self, tmp_path: Path) -> None:
        """Read access is never gated — no Authorization header needed
        for GET even when NORM_API_KEY is set."""
        client = _client(tmp_path, api_key="secret123")
        resp = client.get("/normalization/profiles")
        assert resp.status_code == 200

    def test_health_check_stays_open(self, tmp_path: Path) -> None:
        client = _client(tmp_path, api_key="secret123")
        resp = client.get("/health")
        assert resp.status_code == 200

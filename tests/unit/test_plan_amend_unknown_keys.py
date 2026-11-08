"""D19: PATCH /clone-jobs/{id}/plan refused nothing it did not know, while
POST forbids unknown keys: a misspelt option was dropped silently."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from normapi.app import create_app
from normapi.dependencies import get_connections
from normapi.pg_persistence import PgPersistence

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("NORM_SECRET_KEY", Fernet.generate_key().decode())
    store = PgPersistence(f"sqlite:///{tmp_path}/m.db")
    store.ensure_schema()
    app = create_app()
    app.dependency_overrides[get_connections] = lambda: store
    return TestClient(app, client=("127.0.0.1", 50000))


def test_an_unknown_key_is_refused(client: TestClient) -> None:
    response = client.patch("/normalization/clone-jobs/any/plan", json={"field_confgs": {}})
    assert response.status_code == 422
    assert "field_confgs" in response.text


def test_a_known_key_reaches_the_route(client: TestClient) -> None:
    response = client.patch("/normalization/clone-jobs/any/plan", json={"field_configs": {}})
    assert response.status_code == 404

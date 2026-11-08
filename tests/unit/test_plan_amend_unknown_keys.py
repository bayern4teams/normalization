"""D19: PATCH /clone-jobs/{id}/plan refused nothing it did not know, while
POST forbids unknown keys: a misspelt option was dropped silently."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from normapi.app import create_app

pytestmark = pytest.mark.unit


def test_an_unknown_key_is_refused() -> None:
    client = TestClient(create_app(), client=("127.0.0.1", 50000))
    response = client.patch("/normalization/clone-jobs/any/plan", json={"field_confgs": {}})
    assert response.status_code == 422
    assert "field_confgs" in response.text

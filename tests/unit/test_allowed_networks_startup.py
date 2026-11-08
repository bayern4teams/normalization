"""D18: a bad NORM_ALLOWED_NETWORKS stops the API at start-up, with a message
naming the entry and the fix, instead of a 500 on every request."""

from __future__ import annotations

import pytest
from normapi.app import create_app

pytestmark = pytest.mark.unit


def test_a_bad_entry_stops_the_api_and_names_the_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NORM_ALLOWED_NETWORKS", "100.64.0.0/10, 10.0.0.1/8")
    with pytest.raises(ValueError, match=r"NORM_ALLOWED_NETWORKS.*'10\.0\.0\.1/8'.*Fix:"):
        create_app()


def test_good_entries_start(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NORM_ALLOWED_NETWORKS", "100.64.0.0/10")
    assert create_app() is not None

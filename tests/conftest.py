"""Test-client defaults for the local-network policy (ADR-022).

Starlette's `TestClient` reports its peer as the string `testclient` and sends
`Host: testserver`; the app refuses both. This gives the client a loopback peer
and the `localhost` host unless a test passes its own. It changes how a test
reaches the app, not what the app does: the policy itself is never replaced.
"""

from typing import Any

import pytest
from starlette.testclient import TestClient


@pytest.fixture(autouse=True)
def _local_test_client(monkeypatch: pytest.MonkeyPatch) -> None:
    original: Any = TestClient.__init__

    def init(self: Any, app: Any, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("client", ("127.0.0.1", 50000))
        kwargs.setdefault("base_url", "http://localhost")
        original(self, app, *args, **kwargs)

    monkeypatch.setattr(TestClient, "__init__", init)

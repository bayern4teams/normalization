"""D17: a Host header must be a host and an optional port. Starlette 1.6.0's
TrustedHostMiddleware read `localhost:80@evil.com` as the host `localhost`."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from normapi.app import create_app

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app(), client=("127.0.0.1", 50000))


@pytest.mark.parametrize(
    "host",
    [
        "localhost:80@evil.com",
        "user@localhost",
        "localhost/path",
        "localhost:80:80",
        "localhost:port",
        "localhost?x",
        "local host",
    ],
)
def test_a_malformed_host_is_refused(client: TestClient, host: str) -> None:
    assert client.get("/health", headers={"Host": host}).status_code == 400


@pytest.mark.parametrize("host", ["localhost", "localhost:8080", "127.0.0.1:8080"])
def test_a_host_and_optional_port_pass(client: TestClient, host: str) -> None:
    assert client.get("/health", headers={"Host": host}).status_code == 200

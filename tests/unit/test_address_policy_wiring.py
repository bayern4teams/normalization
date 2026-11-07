"""D15: every path to a database address goes through the policy (ADR-022).

The attack verifier removed each call in turn and no test noticed; these pin them.
Only the network (socket.getaddrinfo) and the driver classes are replaced.
"""

from typing import Any

import pytest
from normapi.address_policy import AddressPolicyError
from normapi.app import create_app
from normapi.dependencies import get_connections
from normio.connectors.postgres_destination import build_postgres_dsn, engine_from_dsn
from starlette.testclient import TestClient

from normapi import clone_executor

PUBLIC = "8.8.8.8"  # public DNS resolver, outside every allowed network (RFC 1918 et al.)


def _conn(engine: str, host: str) -> dict[str, Any]:
    return {
        "engine": engine,
        "connection_id": "c1",
        "username": "u",
        "host": host,
        "port": 5432,
        "encrypted_password": "x",
    }


@pytest.fixture(autouse=True)
def _decrypt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clone_executor.secrets, "decrypt", lambda _: "pw")


@pytest.mark.parametrize("engine", ["postgres", "clickhouse"])
def test_source_builder_refuses_a_public_host(engine: str) -> None:
    with pytest.raises(AddressPolicyError):
        clone_executor.build_source_connector(_conn(engine, PUBLIC), "db")


@pytest.mark.parametrize("engine", ["postgres", "clickhouse"])
def test_destination_builder_refuses_a_public_host(engine: str) -> None:
    with pytest.raises(AddressPolicyError):
        clone_executor.build_destination_writer(_conn(engine, PUBLIC))


def test_saving_a_connection_to_a_public_host_is_refused() -> None:
    app = create_app()
    app.dependency_overrides[get_connections] = object  # never reached: the check comes first
    resp = TestClient(app).post(
        "/normalization/connections",
        json={"engine": "postgres", "host": PUBLIC, "port": 5432, "username": "u", "password": "p"},
    )
    assert resp.status_code == 422
    assert "outside the allowed local network" in resp.json()["detail"]


def test_clickhouse_connects_to_the_checked_address(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    class _Spy:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            seen.update(kwargs)

    monkeypatch.setattr(clone_executor, "ClickHouseConnector", _Spy)
    clone_executor.build_source_connector(_conn("clickhouse", "127.0.0.1"), "db")
    assert seen["hostaddr"] == "127.0.0.1"


def test_postgres_connects_to_the_checked_address(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    class _Spy:
        def __init__(self, source_id: str, dsn: str, schema: str | None = None) -> None:
            seen.append(dsn)

    monkeypatch.setattr(clone_executor, "PostgresConnector", _Spy)
    clone_executor.build_source_connector(_conn("postgres", "127.0.0.1"), "db")
    assert "hostaddr=127.0.0.1" in seen[0]


@pytest.mark.parametrize("secret", ["p://w", "x://y@z/db?host=8.8.8.8", "postgresql://a"])
def test_a_url_lookalike_in_a_password_is_not_read_as_a_url(secret: str) -> None:
    dsn = build_postgres_dsn("10.0.0.5", 5432, "u", secret, "d", hostaddr="10.0.0.5")
    engine = engine_from_dsn(dsn)
    assert engine.dialect.name == "postgresql"

"""D14: a job whose destination is its origin never starts, whatever created it (ADR-013)."""

from typing import Any

import pytest
from normapi.clone_executor import CloneJobStateError

from normapi import clone_executor


def _conn(connection_id: str, host: str = "10.0.0.5", port: int = 5432) -> dict[str, Any]:
    return {"connection_id": connection_id, "engine": "postgres", "host": host, "port": port}


def _job(source_database: str, destination_database: str) -> dict[str, Any]:
    return {
        "job_id": "j1",
        "source_database": source_database,
        "destination_database": destination_database,
    }


def test_same_connection_and_database_is_refused() -> None:
    with pytest.raises(CloneJobStateError, match="origin"):
        clone_executor._require_separate_copy(_job("shop", "shop"), _conn("a"), _conn("a"))


def test_two_saved_connections_to_one_server_are_the_same_origin() -> None:
    with pytest.raises(CloneJobStateError, match="origin"):
        clone_executor._require_separate_copy(
            _job("shop", "shop"), _conn("a"), _conn("b", host="10.0.0.5")
        )


def test_another_database_on_the_same_server_is_a_separate_copy() -> None:
    # no refusal: the call returns instead of raising CloneJobStateError
    assert (
        clone_executor._require_separate_copy(_job("shop", "shop_clone"), _conn("a"), _conn("a"))
        is None
    )


def test_the_same_name_on_another_server_is_not_guessed_to_be_the_origin() -> None:
    # Two host names may or may not be one server; only provable identity is refused.
    assert (
        clone_executor._require_separate_copy(
            _job("shop", "shop"), _conn("a"), _conn("b", host="10.0.0.6")
        )
        is None
    )


class _Store:
    def __init__(self, job: dict[str, Any]) -> None:
        self.job = job
        self.claimed = False

    def get_clone_job(self, _job_id: str) -> dict[str, Any]:
        return self.job

    def get_connection(self, _connection_id: str) -> dict[str, Any]:
        return _conn("a")

    def claim_clone_job(self, _job_id: str) -> bool:
        self.claimed = True
        return True


def test_a_stored_job_pointing_at_its_origin_is_not_claimed() -> None:
    legacy = {
        **_job("shop", "shop"),
        "source_connection_id": "a",
        "destination_connection_id": "a",
        "status": "RUNNING",
    }
    store: Any = _Store(legacy)
    with pytest.raises(CloneJobStateError, match="origin"):
        clone_executor.start_phase2(store, None, None, "j1")
    assert not store.claimed


def _resolves(monkeypatch: pytest.MonkeyPatch, **names: list[str]) -> None:
    def getaddrinfo(host: str, *_: Any, **__: Any) -> list[tuple[Any, ...]]:
        return [(0, 0, 0, "", (address, 0)) for address in names[host.replace("-", "_")]]

    monkeypatch.setattr("socket.getaddrinfo", getaddrinfo)


def test_two_host_names_for_one_address_are_the_same_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _resolves(monkeypatch, db_a=["10.0.0.5"], db_b=["10.0.0.5"])
    with pytest.raises(CloneJobStateError, match="origin"):
        clone_executor._require_separate_copy(
            _job("shop", "shop"), _conn("a", host="db-a"), _conn("b", host="db-b")
        )


def test_a_host_name_and_its_ip_literal_are_the_same_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _resolves(monkeypatch, db_a=["10.0.0.5"])
    with pytest.raises(CloneJobStateError, match="origin"):
        clone_executor._require_separate_copy(
            _job("shop", "shop"), _conn("a", host="db-a"), _conn("b", host="10.0.0.5")
        )


def test_names_that_share_any_address_are_the_same_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _resolves(monkeypatch, db_a=["10.0.0.9", "10.0.0.5"], db_b=["10.0.0.5"])
    with pytest.raises(CloneJobStateError, match="origin"):
        clone_executor._require_separate_copy(
            _job("shop", "shop"), _conn("a", host="db-a"), _conn("b", host="db-b")
        )


def test_two_names_for_two_addresses_are_separate(monkeypatch: pytest.MonkeyPatch) -> None:
    _resolves(monkeypatch, db_a=["10.0.0.5"], db_b=["10.0.0.6"])
    assert (
        clone_executor._require_separate_copy(
            _job("shop", "shop"), _conn("a", host="db-a"), _conn("b", host="db-b")
        )
        is None
    )


def test_one_address_on_another_port_is_separate(monkeypatch: pytest.MonkeyPatch) -> None:
    _resolves(monkeypatch, db_a=["10.0.0.5"], db_b=["10.0.0.5"])
    assert (
        clone_executor._require_separate_copy(
            _job("shop", "shop"), _conn("a", host="db-a"), _conn("b", host="db-b", port=5433)
        )
        is None
    )


class _Connections:
    def get_connection(self, connection_id: str) -> dict[str, Any]:
        return _conn(connection_id, host=f"db-{connection_id}")


def test_create_refuses_two_names_for_one_address(monkeypatch: pytest.MonkeyPatch) -> None:
    _resolves(monkeypatch, db_a=["10.0.0.5"], db_b=["10.0.0.5"])
    request = {
        "source_connection_id": "a",
        "source_database": "shop",
        "destination_connection_id": "b",
        "destination_database": "shop",
        "field_configs": {},
    }
    with pytest.raises(CloneJobStateError, match="origin"):
        clone_executor.create_clone_job(_Connections(), request=request)

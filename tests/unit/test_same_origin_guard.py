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

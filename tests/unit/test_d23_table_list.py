"""D23: a clone job can name its tables; each is checked against the origin."""

from __future__ import annotations

from typing import Any

import pytest
from normapi.schemas import CloneJobCreateRequest
from pydantic import ValidationError

from normapi import clone_executor

pytestmark = pytest.mark.unit


class _Source:
    def list_tables(self) -> list[str]:
        return ["a", "b", "c"]

    def close(self) -> None:
        pass


class _Store:
    def __init__(self) -> None:
        self.job: dict[str, Any] | None = None

    def get_connection(self, connection_id: str) -> dict[str, Any]:
        return {"connection_id": connection_id, "engine": "postgres", "host": "h", "port": 1}

    def create_clone_job(self, _job_id: str, job: dict[str, Any]) -> None:
        self.job = job


def _create(monkeypatch: pytest.MonkeyPatch, **fields: Any) -> _Store:
    monkeypatch.setattr(
        clone_executor, "build_source_connector", lambda conn, db, schema=None: _Source()
    )
    store = _Store()
    request = {
        "source_connection_id": "s",
        "source_database": "src",
        "destination_connection_id": "d",
        "destination_database": "dst",
        "field_configs": {},
        **fields,
    }
    clone_executor.create_clone_job(store, request=request)  # type: ignore[arg-type]
    return store


def test_one_table_of_three_is_the_only_one_cloned(monkeypatch: pytest.MonkeyPatch) -> None:
    job = _create(monkeypatch, tables=["b"]).job
    assert job is not None
    assert job["tables"] == ["b"]


def test_without_a_list_every_table_is_cloned(monkeypatch: pytest.MonkeyPatch) -> None:
    job = _create(monkeypatch).job
    assert job is not None
    assert job["tables"] == ["a", "b", "c"]


def test_a_table_the_origin_does_not_have_is_refused_by_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(clone_executor.CloneJobStateError, match="nope"):
        _create(monkeypatch, tables=["a", "nope"])


def test_an_empty_list_is_refused_not_read_as_all() -> None:
    with pytest.raises(ValidationError):
        CloneJobCreateRequest(
            source_connection_id="s",
            source_database="src",
            destination_connection_id="d",
            destination_database="dst",
            field_configs={},
            tables=[],
        )

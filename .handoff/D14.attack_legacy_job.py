"""D14 attack probe: a job stored before D14 (destination == origin) is not refused by Phase 2.

Run (importlib mode, the file name has a dot):
    ( ulimit -v 16777216; uv run pytest -p no:cacheprovider --import-mode=importlib -q \
        .handoff/D14.attack_legacy_job.py )

Both tests PASS today, and each pass is the defect: they assert what the code does.
"""

from __future__ import annotations

from typing import Any

import pytest

from normapi import clone_executor

CONN = {
    "connection_id": "c1",
    "engine": "clickhouse",
    "host": "127.0.0.1",
    "port": 8123,
    "username": "u",
    "encrypted_password": "x",
}
LEGACY_JOB: dict[str, Any] = {
    "job_id": "j1",
    "status": "RUNNING",
    "source_connection_id": "c1",
    "source_database": "shop",
    "destination_connection_id": "c1",
    "destination_database": "shop",
    "tables": ["orders"],
    "in_place": True,
    "progress": {"checkpoints": {"orders": 41}, "rows_done": 42},
}


class _Stop(Exception):
    pass


class _Persistence:
    def get_clone_job(self, job_id: str) -> dict[str, Any]:
        return dict(LEGACY_JOB, progress={"checkpoints": {"orders": 41}, "rows_done": 42})

    def get_connection(self, connection_id: str) -> dict[str, Any]:
        return CONN

    def delete_clone_job_errors(self, job_id: str, table: str) -> None:
        return None

    def reset_queue_counts(self, job_id: str, table: str) -> None:
        return None


def test_legacy_job_phase2_builds_a_writer_on_the_origin_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    def writer(conn: dict[str, Any]) -> Any:
        seen.append(conn["connection_id"])
        raise _Stop

    monkeypatch.setattr(clone_executor, "build_source_connector", lambda *a, **k: object())
    monkeypatch.setattr(clone_executor, "source_identity", lambda *a, **k: "id")
    monkeypatch.setattr(clone_executor, "build_destination_writer", writer)
    with pytest.raises(_Stop):
        clone_executor._run_phase2(_Persistence(), object(), None, "j1")  # type: ignore[arg-type]
    # The writer is built from the SOURCE connection: nothing refused the job.
    assert seen == ["c1"]


def test_legacy_clickhouse_job_resume_truncates_the_original_table() -> None:
    calls: list[tuple[str, str]] = []

    class Dest:
        def truncate_table(self, database: str, table: str) -> None:
            calls.append((database, table))

    job = dict(LEGACY_JOB)
    progress = {"checkpoints": {"orders": 41}, "rows_done": 42}
    clone_executor._resume_point(
        "orders",
        source_engine="clickhouse",
        progress=progress,
        dest=Dest(),
        job=job,
        persistence=_Persistence(),  # type: ignore[arg-type]
        job_id="j1",
    )
    # Before D14 the target was the staging table; now it is the origin's own table.
    assert calls == [("shop", "orders")]

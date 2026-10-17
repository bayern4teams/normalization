"""PART1 D4.1/D4.2: the disguised-missing detector was a library function
nothing called, and no cell ever got a MissingKind from it. A clone now
reports, per column, the values that are disguised nulls with their exact
counts (`quality[...]["disguised_missing"]`), and a value a person confirms
(`confirmed_missing`) is written as NULL with an error row keeping the
original. Nothing is applied unconfirmed. Fails on main.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from tests.unit.test_adjudication_acceptance import TABLE, _Env, _rows

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

# 97 real dates, `empty` twice (no date, not in the missing-value table), and
# `-` twice and `N/A` once, which the table names and are already MISSING.
_VALID = [f"2024-01-{d:02d}" for d in range(1, 29)] * 3 + [f"2023-05-{d:02d}" for d in range(1, 14)]
_COLUMN = [*_VALID, "empty", "empty", "-", "-", "N/A"]


@pytest.fixture
def env(tmp_path: Path) -> _Env:
    return _Env(tmp_path)


def _run(env: _Env, **job: object) -> tuple[list[dict], dict]:
    _, rows, done = env.run(
        [_rows([{"d": v} for v in _COLUMN])], {"d": "DATE"}, job_extra=dict(job)
    )
    return rows, done


def test_a_clone_reports_its_disguised_nulls_with_exact_counts(env: _Env) -> None:
    rows, job = _run(env)
    report = job["quality"][TABLE]["d"]["disguised_missing"]
    assert {(r["value"], r["count"]) for r in report} == {("empty", 2)}
    # reported, not applied
    assert sum(r["d"] == "empty" for r in rows) == 2


def test_a_confirmed_value_is_written_as_null_with_its_original_kept(env: _Env) -> None:
    job_id = "confirmed"
    _, rows, _ = env.run(
        [_rows([{"d": v} for v in _COLUMN])],
        {"d": "DATE"},
        job_id=job_id,
        job_extra={"confirmed_missing": {TABLE: {"d": ["empty"]}}},
    )
    assert [r["d"] for r in rows if r["d"] is None or r["d"] == "empty"].count("empty") == 0
    # two `empty` (confirmed); `-` twice and `N/A` are in the missing-value table
    assert sum(r["d"] is None for r in rows) == 5
    errors = env.errors(job_id)
    assert sum(e["original"] == "empty" for e in errors) == 2
    # everything else is exactly what an unconfirmed run writes
    plain, _ = _run(env)
    assert [r["d"] for r in rows if r["d"] is not None] == [
        r["d"] for r in plain if r["d"] not in (None, "empty")
    ]


def test_a_confirmed_value_in_another_column_changes_nothing_here(env: _Env) -> None:
    rows, _ = _run(env, confirmed_missing={TABLE: {"other": ["empty"]}})
    assert sum(r["d"] == "empty" for r in rows) == 2

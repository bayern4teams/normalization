"""PART1 D5.3 / ADR-020 (amended 2026-10-14): DATE and DATETIME keep their
TEXT column, as stated, and gain typed `<col>__from` / `<col>__to`: the first
and last day of the stated period. Precision is preserved (a year is a range,
not an invented day); a refusal has no bounds; a bound the column cannot hold
is NULL plus an error row. Fails on main (no bounds exist there).
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, Any

import pytest
from normapi.clone_executor import _destination_plan
from tests.unit.test_adjudication_acceptance import RAW_DATE, TABLE, _Env, _rows

from normio import storage_types

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


@pytest.fixture
def env(tmp_path: Path) -> _Env:
    return _Env(tmp_path)


class TestBoundsOfAStatedPeriod:
    @pytest.mark.parametrize(
        ("structured", "expected"),
        [
            ({"parsed_date": "1990", "precision": "year"}, ("1990-01-01", "1990-12-31")),
            ({"parsed_date": "2024-02", "precision": "month"}, ("2024-02-01", "2024-02-29")),
            ({"parsed_date": "2023-02", "precision": "month"}, ("2023-02-01", "2023-02-28")),
            ({"parsed_date": "2024-03-15", "precision": "day"}, ("2024-03-15", "2024-03-15")),
            (
                {"parsed_date": "2024-03-15T15:00:00", "precision": "time"},
                ("2024-03-15", "2024-03-15"),
            ),
            ({"earliest": "1990-01-01", "latest": "1999-12-31"}, ("1990-01-01", "1999-12-31")),
            ({"earliest": "1990-01-01", "latest": None}, ("1990-01-01", None)),
            ({"candidates": []}, (None, None)),
            ({"parsed_date": "199X", "precision": "decade"}, (None, None)),
        ],
    )
    def test_first_and_last_day(self, structured: dict[str, Any], expected: tuple) -> None:
        assert storage_types.date_bounds(structured) == expected

    def test_a_bound_outside_clickhouse_date32_is_refused_not_clamped(self) -> None:
        value, error = storage_types.coerce_bound("1850-01-01", "clickhouse")
        assert value is None
        assert error is not None
        assert storage_types.coerce_bound("1850-01-01", "postgres") == (dt.date(1850, 1, 1), None)


class TestDestinationPlan:
    @pytest.mark.parametrize(("engine", "sql"), [("postgres", "DATE"), ("clickhouse", "Date32")])
    def test_date_and_datetime_get_two_typed_companions(self, engine: str, sql: str) -> None:
        _, extras, typed = _destination_plan(
            {"born": "DATE", "seen": "DATETIME"}, engine, [], typed=True
        )
        assert extras == {"born__from": sql, "born__to": sql, "seen__from": sql, "seen__to": sql}
        assert "born" not in typed  # the value itself stays TEXT

    def test_no_bounds_on_a_key_or_when_untyped(self) -> None:
        assert _destination_plan({"born": "DATE"}, "postgres", ["born"], typed=True)[1] == {}
        assert _destination_plan({"born": "DATE"}, "postgres", [], typed=False)[1] == {}


class TestBoundsInAClone:
    def test_cells_get_the_bounds_of_what_they_state(self, env: _Env) -> None:
        values = ["1990", "1990-03", "2024-03-15", RAW_DATE, "not a date"]
        plan = {TABLE: {"bounds_columns": {"d": ["d__from", "d__to"]}}}
        _, rows, _ = env.run(
            [_rows([{"d": v} for v in values])],
            {"d": "DATE"},
            job_extra={"destination_plan": plan},
        )
        got = [(r["d"], r["d__from"], r["d__to"]) for r in rows]
        assert got == [
            ("1990", dt.date(1990, 1, 1), dt.date(1990, 12, 31)),
            ("1990-03", dt.date(1990, 3, 1), dt.date(1990, 3, 31)),
            ("2024-03-15", dt.date(2024, 3, 15), dt.date(2024, 3, 15)),
            (RAW_DATE, None, None),  # AMBIGUOUS: no period is stated
            ("not a date", None, None),
        ]

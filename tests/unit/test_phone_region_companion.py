"""PART1 D10.2: "store E.164 together with the region" (libphonenumber's
FALSEHOODS: E.164 alone does not re-render or re-parse a number; +1 is the US,
Canada and 22 more). A clone stored display and E.164 only; a PHONE column now
gets `<col>_region`, the region libphonenumber reads from the number. Example
numbers come from libphonenumber itself. Fails on main.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import phonenumbers
import pytest
from normapi.clone_executor import _destination_plan
from tests.unit.test_adjudication_acceptance import TABLE, _Env, _rows

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def _example(region: str) -> str:
    number = phonenumbers.example_number(region)
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.INTERNATIONAL)


@pytest.fixture
def env(tmp_path: Path) -> _Env:
    return _Env(tmp_path)


def test_the_plan_gives_a_phone_column_a_region_companion() -> None:
    _, extras, _ = _destination_plan({"p": "PHONE"}, "postgres", [], typed=True)
    assert extras["p_region"] == "TEXT"


def test_two_numbers_of_one_country_code_keep_their_regions(env: _Env) -> None:
    plan = {TABLE: {"code_columns": {"p": "p_code"}, "region_columns": {"p": "p_region"}}}
    values = [_example("US"), _example("CA"), "(201) 555-0123"]
    _, rows, _ = env.run(
        [_rows([{"p": v} for v in values])], {"p": "PHONE"}, job_extra={"destination_plan": plan}
    )
    assert [r["p_region"] for r in rows] == ["US", "CA", None]  # the last: no region stated
    assert all(r["p_code"].startswith("+1") for r in rows[:2])

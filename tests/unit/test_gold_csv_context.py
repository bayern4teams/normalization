"""PART1 D6.5: the dirty/clean CSV loader took no context, so on real data
PHONE and POSTCODE abstained on every cell and the D6 command could not
score them. A CSV may carry `country`/`locale` columns per row, or the
caller states them (`--country`/`--locale`). Fails on main.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from normanalysis.gold import load_cases
from normcli.cli import main as normcli_main

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def _csv(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "c.csv"
    path.write_text(text, encoding="utf-8")
    return path


def test_context_columns_reach_each_case(tmp_path: Path) -> None:
    path = _csv(tmp_path, "dirty,clean,country\n(201) 555-0123,+12015550123,US\n")
    (case,) = load_cases(path, semantic_type="PHONE")
    assert case.context == {"country": "US"}


def test_a_stated_context_applies_to_rows_without_one(tmp_path: Path) -> None:
    path = _csv(tmp_path, "dirty,clean,country\n12345,12345,\n12345,12345,DE\n")
    cases = load_cases(path, semantic_type="POSTCODE", context={"country": "US"})
    assert [c.context for c in cases] == [{"country": "US"}, {"country": "DE"}]


def test_the_cli_takes_country_and_locale(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    path = _csv(tmp_path, "dirty,clean\n(201) 555-0123,+1 201-555-0123\n")
    args = ["gold", "score", str(path), "--semantic-type", "PHONE", "--country", "US"]
    assert normcli_main(args) == 0
    assert "correct-abstain: 0" in capsys.readouterr().out

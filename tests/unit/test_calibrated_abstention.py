"""PART1 D2.2/D2.5 (ADR-019 amended): every clone reports, per column, the
answers below the type's calibrated threshold; a job with
`calibrated_abstention` turns them into AMBIGUOUS, original kept, queued.
Fails on main (no table, no report, no flag).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from normcli.cli import main as normcli_main
from tests.unit.test_adjudication_acceptance import TABLE, _Env, _rows

from normapi import clone_executor

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

_TABLE = {
    "NUMERIC": {
        "n": 1000,
        "threshold": None,
        "abstain_on_everything": True,
        "bins": [{"lo": 0.9, "hi": 1.0, "count": 1000, "mean_confidence": 1.0, "accuracy": 0.75}],
    }
}


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Env:
    monkeypatch.setattr(clone_executor, "_calibration_table", lambda: _TABLE)
    return _Env(tmp_path)


def test_every_clone_reports_the_answers_below_the_threshold(env: _Env) -> None:
    _, rows, job = env.run([_rows([{"n": "12"}, {"n": "13"}])], {"n": "NUMERIC"})
    report = job["quality"][TABLE]["n"]["calibration"]
    assert report["below_threshold"] == 2
    assert report["expected_wrong"] == pytest.approx(0.5)
    assert [r["n"] for r in rows] == ["12", "13"]  # reported, not applied
    assert env.queue() == []


def test_an_opted_in_job_keeps_them_for_review(env: _Env) -> None:
    _, rows, _ = env.run(
        [_rows([{"n": "12"}])], {"n": "NUMERIC"}, job_extra={"calibrated_abstention": True}
    )
    assert rows[0]["n"] == "12"  # the original, as for any AMBIGUOUS cell
    (entry,) = env.queue()
    assert entry["original"] == "12"


def test_a_type_without_a_table_entry_is_untouched(env: _Env) -> None:
    _, _, job = env.run([_rows([{"d": "2024-01-02"}])], {"d": "DATE"})
    assert job["quality"][TABLE]["d"]["calibration"] is None


def test_the_cli_writes_the_table(tmp_path: Path) -> None:
    corpus = tmp_path / "c.csv"
    corpus.write_text("dirty,clean\n12,12\n13,13\n", encoding="utf-8")
    out = tmp_path / "t.json"
    args = ["calibrate", str(corpus), "--semantic-type", "NUMERIC", "--cost-ratio", "20"]
    assert normcli_main([*args, "--out-table", str(out)]) == 0
    table = json.loads(out.read_text())
    assert table["cost_ratio"] == 20
    assert "NUMERIC" in table["types"]

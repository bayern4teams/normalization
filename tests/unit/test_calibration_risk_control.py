"""PART1 D2.2/D2.3 (ADR-019 amended): a risk-controlled threshold (Learn-then-
Test, fixed-sequence Hoeffding) and a per-type table. The guarantee is checked
by simulation: on data whose true error rate above every threshold is known,
the chosen threshold's true risk exceeds alpha in at most delta of the runs.
Fails on main (the functions do not exist).
"""

from __future__ import annotations

import math
import random

import pytest
from normanalysis.calibration import _DELTA, calibration_table, risk_controlled_threshold

pytestmark = pytest.mark.unit


def test_nothing_passes_when_every_answer_is_often_wrong() -> None:
    pairs = [(1.0, i % 5 != 0) for i in range(1000)]  # 80% right at a stated 1.0
    assert risk_controlled_threshold(pairs, cost_ratio=20) is math.inf


def test_a_clean_high_band_passes_and_a_dirty_low_band_does_not() -> None:
    pairs = [(0.99, True)] * 2000 + [(0.5, i % 2 == 0) for i in range(2000)]
    assert risk_controlled_threshold(pairs, cost_ratio=20) == 0.99


def test_no_pairs_no_threshold() -> None:
    assert risk_controlled_threshold([], cost_ratio=20) is None


def test_the_risk_bound_holds_under_simulation() -> None:
    """Confidence c is right with probability c (calibrated). True risk above t
    is the mean of 1 - c over c >= t, computed exactly from the grid."""
    rng = random.Random(7)
    grid = [0.80 + 0.002 * i for i in range(101)]
    alpha = 1 / 21

    def true_risk(t: float) -> float:
        kept = [c for c in grid if c >= t]
        return sum(1 - c for c in kept) / len(kept)

    runs, violations = 300, 0
    for _ in range(runs):
        pairs = [(c, rng.random() < c) for c in rng.choices(grid, k=3000)]
        t = risk_controlled_threshold(pairs, cost_ratio=20)
        if t is not None and not math.isinf(t) and true_risk(t) > alpha:
            violations += 1
    assert violations / runs <= _DELTA


def test_the_table_is_per_type_with_its_evidence() -> None:
    pairs = [(1.0, True)] * 500 + [(1.0, i % 4 != 0) for i in range(500)]
    types = ["NUMERIC"] * 500 + ["PHONE"] * 500
    table = calibration_table(pairs, types, cost_ratio=20)
    assert table["NUMERIC"]["threshold"] == 1.0
    assert table["PHONE"]["threshold"] is None
    assert table["PHONE"]["abstain_on_everything"] is True
    assert table["PHONE"]["n"] == 500
    assert table["PHONE"]["bins"][-1]["accuracy"] == pytest.approx(0.75)

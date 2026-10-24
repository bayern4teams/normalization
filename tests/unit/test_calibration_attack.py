"""D2 attack tests: independent brute force, exact permutation averages, boundary pins, edge input.

Heavy Monte Carlo (seeds x n x skewed confidence laws) lives in the D2 verdict
(docs/archive/plans/defects/FINAL_REPORT.md appendix), not here.
xfail(strict) marks a confirmed defect: it flips to a failure when the defect is fixed.
"""

from __future__ import annotations

import itertools
import json
import math
import random
import time
from fractions import Fraction
from pathlib import Path

import pytest
from normanalysis.calibration import (
    chow_threshold,
    ece_tolerance,
    reliability,
    report,
    risk_coverage,
)
from normanalysis.gold import default_engine, dump_cases, generate_corpus, score
from normcli.cli import main as normcli_main

pytestmark = pytest.mark.unit

P4 = [(0.9, True), (0.9, True), (0.8, True), (0.6, False)]


def _cost(pairs, t, ratio):
    return sum((0 if ok else ratio) if c >= t else 1 for c, ok in pairs)


def _brute(pairs, ratio):
    cands = [*sorted({c for c, _ in pairs}), math.inf]
    costs = {t: _cost(pairs, t, ratio) for t in cands}
    best = min(costs.values())
    return best, max(t for t in cands if costs[t] == best)


# --- chow_threshold against an independent exact-arithmetic brute force ---


def test_chow_matches_exact_brute_force_ties_and_extreme_ratios():
    rng = random.Random(7)
    ratios = [Fraction(1, 10), Fraction(1, 2), 1, Fraction(3, 2), 2, 7, 100, 10**9]
    for _ in range(1500):
        n = rng.choice([1, 2, 3, 5, 10, 30])
        levels = (
            [i / 4 for i in range(5)] if rng.random() < 0.5 else [rng.random() for _ in range(6)]
        )
        kind = rng.choice(["rand", "allok", "allwrong", "calib"])
        pairs = []
        for _ in range(n):
            c = rng.choice(levels)
            ok = {"allok": True, "allwrong": False}.get(
                kind, rng.random() < (c if kind == "calib" else 0.5)
            )
            pairs.append((c, ok))
        ratio = rng.choice(ratios)
        t = chow_threshold(pairs, float(ratio))
        best, best_t = _brute(pairs, ratio)
        assert _cost(pairs, t, ratio) == best, (pairs, ratio, t)
        assert t == best_t, (pairs, ratio, t, best_t)  # equal cost: the highest threshold wins


def test_chow_tie_goes_to_highest_and_abstain_wins_a_tie_with_emitting():
    assert chow_threshold([(0.9, True), (0.5, False)], 1) == 0.9  # costs: t=.9 -> 1, t=.5 -> 1
    assert chow_threshold([(0.5, False)], 1) == math.inf  # emit costs 1, abstain costs 1


def test_chow_degenerate_optima():
    pairs = [(0.3, True), (0.6, True), (0.6, True)]
    assert chow_threshold(pairs, 1000) == 0.3  # all right: emit everything
    assert chow_threshold([(0.5, False)] * 3, 2) == math.inf  # all wrong: abstain on everything
    assert chow_threshold(P4, 0.5) == 0.6  # ratio < 1: a wrong value is cheaper than abstaining
    assert chow_threshold([(0.7, False)], 1e308) == math.inf


def test_chow_threshold_monotone_in_ratio_with_ties():
    rng = random.Random(3)
    for _ in range(300):
        pairs = [
            (rng.choice([0.1, 0.3, 0.5, 0.7, 0.9, 1.0]), rng.random() < 0.6)
            for _ in range(rng.randint(1, 40))
        ]
        ts = [chow_threshold(pairs, r) for r in (0.2, 1, 2, 5, 50, 1e9)]
        assert ts == sorted(ts)


def test_report_turns_infinite_threshold_into_json_safe_flag():
    data, md = report([(0.5, False)] * 3, cost_ratio=2)
    json.dumps(data, allow_nan=False)
    assert data["threshold"] is None and data["abstain_on_everything"] is True
    assert "abstain on everything" in md


def test_infinite_cost_ratio_is_rejected_or_answered_correctly():
    try:
        t = chow_threshold(P4, math.inf)
    except ValueError:
        return
    assert t == 0.8  # with an infinite price on errors: emit down to the last error-free level


def test_cli_infinite_ratio_does_not_write_invalid_json(tmp_path):
    corpus = tmp_path / "c.jsonl"
    corpus.write_text(dump_cases(generate_corpus(0, 3)))
    out = tmp_path / "r.json"
    rc = normcli_main(["calibrate", str(corpus), "--cost-ratio", "inf", "--out-json", str(out)])
    assert rc != 0 or json.loads(out.read_text(), parse_constant=_no_const)


def _no_const(tok):
    raise ValueError(tok)


@pytest.mark.parametrize("ratio", [math.nan, 0, -1, "3", None])
def test_chow_rejects_bad_ratio(ratio):
    with pytest.raises((ValueError, TypeError)):
        chow_threshold(P4, ratio)


# --- risk_coverage against the exact average over every tie order ---


def test_aurc_equals_exact_average_over_all_tie_orders():
    rng = random.Random(5)
    for _ in range(120):
        n = rng.randint(1, 6)
        pairs = [(rng.choice([0.2, 0.5, 0.8, 1.0]), rng.random() < 0.5) for _ in range(n)]
        total = 0.0
        perms = list(itertools.permutations(range(n)))
        for perm in perms:
            order = sorted(
                (pairs[i] for i in perm), key=lambda p: -p[0]
            )  # stable: ties in perm order
            errors = 0
            acc = 0.0
            for k, (_, ok) in enumerate(order, 1):
                errors += not ok
                acc += errors / k
            total += acc / n
        _, aurc = risk_coverage(pairs)
        assert aurc == pytest.approx(total / len(perms), abs=1e-12), pairs


def test_risk_coverage_small_inputs():
    assert risk_coverage([]) == ([], None)
    assert risk_coverage([(0.5, True)]) == ([(1.0, 0.0)], 0.0)
    assert risk_coverage([(0.5, False)]) == ([(1.0, 1.0)], 1.0)


# --- the noise bounds: pins that distinguish delta and delta/bins ---


def test_ece_tolerance_value_is_the_documented_formula():
    assert ece_tolerance(1000, 10) == pytest.approx(
        math.sqrt(10 / 1000) / 2 + math.sqrt(2 * math.log(20) / 1000)
    )
    assert ece_tolerance(1000, 10) == pytest.approx(0.1274, abs=1e-4)


def test_overconfident_threshold_is_hoeffding_over_bins():
    # n=100 stated 0.95: flagged iff gap > sqrt(ln(bins/delta) / (2n)) = sqrt(ln 200 / 200) = 0.1628
    def flagged(correct: int) -> bool:
        pairs = [(0.95, i < correct) for i in range(100)]
        return bool(reliability(pairs).overconfident_bins)

    assert flagged(78)  # gap .17
    assert not flagged(80)  # gap .15
    # fewer bins -> a looser Bonferroni share -> a smaller gap suffices (delta/bins is in use)
    pairs = [
        (0.95, i < 79) for i in range(100)
    ]  # gap .16: between ln(2/.05)/200 and ln(10/.05)/200
    assert reliability(pairs, bins=1).overconfident_bins
    assert not reliability(pairs, bins=10).overconfident_bins


def test_power_a_real_gap_is_flagged_when_n_pays_for_it():
    for n, gap in [(500, 0.10), (1000, 0.07), (5000, 0.03)]:
        k = round(n * (0.95 - gap))
        pairs = [(0.95, i < k) for i in range(n)]
        assert reliability(pairs).overconfident_bins, (n, gap)


@pytest.mark.parametrize("law", ["spike99", "two_spikes", "uniform", "mix"])
@pytest.mark.parametrize("n", [20, 50, 200])
def test_calibrated_predictor_rarely_exceeds_tolerance_or_is_flagged(law, n):
    laws = {
        "spike99": lambda r: 0.99,
        "two_spikes": lambda r: r.choice([0.5, 0.99]),
        "uniform": lambda r: r.random(),
        "mix": lambda r: 1.0 if r.random() < 0.7 else r.random(),
    }
    rng = random.Random(f"{law}{n}")
    runs, over_tol, flagged = 80, 0, 0
    for _ in range(runs):
        pairs = []
        for _ in range(n):
            c = laws[law](rng)
            pairs.append((c, rng.random() < c))
        rel = reliability(pairs)
        over_tol += rel.ece > ece_tolerance(n, 10)
        flagged += bool(rel.overconfident_bins)
    assert over_tol / runs <= 0.05 and flagged / runs <= 0.05


# --- input edges ---


def test_confidence_edges():
    for bad in (math.nan, math.inf, -0.1, 1.0000000000000002):
        with pytest.raises(ValueError, match=r"outside \[0, 1\]"):
            reliability([(bad, True)])
        with pytest.raises(ValueError, match=r"outside \[0, 1\]"):
            chow_threshold([(bad, True)], 2)
        with pytest.raises(ValueError, match=r"outside \[0, 1\]"):
            risk_coverage([(bad, True)])
    assert reliability([(-0.0, False)]).bins[0].count == 1


def test_bool_confidence_is_rejected():
    with pytest.raises(ValueError, match=r"outside \[0, 1\]"):
        reliability([(True, 0.8)])


def test_nan_bin_edge_is_rejected():
    with pytest.raises(ValueError, match=r"bin edges must span"):
        reliability(P4, bins=(0, math.nan, 1))


def test_groups_single_case_and_alignment():
    pairs = [(0.9, True), (0.6, False), (0.9, False), (0.6, True), (0.3, True)]
    labels = ["b", "a", "b", "a", "solo"]
    rel = reliability(pairs, groups=labels)
    assert sorted(rel.groups) == ["a", "b", "solo"]
    assert sum(b.count for b in rel.groups["solo"].bins) == 1
    assert rel.groups["solo"].ece == pytest.approx(0.7)
    for label in rel.groups:
        sub = [p for p, g in zip(pairs, labels, strict=True) if g == label]
        assert rel.groups[label].ece == reliability(sub).ece
    assert rel.ece == reliability(pairs).ece  # grouping does not change the pooled number
    with pytest.raises(ValueError, match=r"group labels for"):
        reliability(pairs, groups=labels[:-1])
    with pytest.raises(ValueError, match=r"group labels for"):
        reliability(pairs, groups=[*labels, "x"])


def test_groups_cost_is_linear_in_pairs():
    n = 8000
    pairs = [(0.5, True)] * n
    t = time.perf_counter()
    reliability(pairs, groups=[str(i) for i in range(n)])
    assert time.perf_counter() - t < 0.5


# --- pair_types alignment in gold.score, with clean answers that carry no confidence ---


def test_pair_types_stay_aligned_with_pairs_when_confidence_is_missing_or_abstaining():
    cases = generate_corpus(1, 4)
    random.Random(2).shuffle(cases)
    answers = {}
    for i, c in enumerate(cases):
        status = ("NORMALIZED", "AMBIGUOUS", "PARSED", "NORMALIZED")[i % 4]
        conf = None if i % 5 == 0 else round(0.05 + (i % 19) / 20, 2)
        answers[id(c)] = (status, c.expected_value or "x", conf)
    scored = score(cases, lambda c: answers[id(c)])
    expect = [
        (answers[id(c)][2], c.semantic_type)
        for c in cases
        if answers[id(c)][0] != "AMBIGUOUS" and answers[id(c)][2] is not None
    ]
    assert len(scored.pairs) == len(scored.pair_types) == len(expect) > 10
    assert [(p[0], t) for p, t in zip(scored.pairs, scored.pair_types, strict=True)] == expect
    # and the grouped report equals the report of each type's own pairs
    rel = reliability(scored.pairs, groups=scored.pair_types)
    for label, g in rel.groups.items():
        own = [p for p, t in zip(scored.pairs, scored.pair_types, strict=True) if t == label]
        assert g.ece == reliability(own).ece


# --- CLI ---


def _corpus(tmp_path: Path) -> Path:
    p = tmp_path / "c.jsonl"
    p.write_text(dump_cases(generate_corpus(0, 3)))
    return p


@pytest.mark.parametrize(
    "ratio", [[], ["--cost-ratio", "nan"], ["--cost-ratio", "-1"], ["--cost-ratio", "x"]]
)
def test_cli_bad_ratio_writes_nothing(tmp_path, ratio, capsys):
    out_json, out_md = tmp_path / "r.json", tmp_path / "r.md"
    argv = [
        "calibrate",
        str(_corpus(tmp_path)),
        "--out-json",
        str(out_json),
        "--out-md",
        str(out_md),
        *ratio,
    ]
    try:
        rc = normcli_main(argv)
    except SystemExit as exc:  # argparse exits for a missing/unparseable value
        rc = exc.code
    assert rc not in (0, None)
    assert not out_json.exists() and not out_md.exists()


def test_cli_unwritable_out_is_an_error_not_a_traceback(tmp_path, capsys):
    corpus = _corpus(tmp_path)
    assert (
        normcli_main(["calibrate", str(corpus), "--cost-ratio", "3", "--out-json", str(tmp_path)])
        == 2
    )
    assert (
        normcli_main(
            [
                "calibrate",
                str(corpus),
                "--cost-ratio",
                "3",
                "--out-md",
                str(tmp_path / "no" / "x.md"),
            ]
        )
        == 2
    )
    assert normcli_main(["calibrate", str(tmp_path / "missing.jsonl"), "--cost-ratio", "3"]) == 2


def test_cli_csv_corpus_and_default_bins_equal_the_library(tmp_path):
    csv = tmp_path / "d.csv"
    csv.write_text(
        "dirty,clean\n  FOO@Example.COM ,foo@example.com\nBar@Example.org,bar@example.org\n"
    )
    out = tmp_path / "r.json"
    assert (
        normcli_main(
            [
                "calibrate",
                str(csv),
                "--semantic-type",
                "EMAIL",
                "--cost-ratio",
                "3",
                "--out-json",
                str(out),
            ]
        )
        == 0
    )
    data = json.loads(out.read_text())
    assert data["n"] == sum(b["count"] for b in data["bins"])
    assert [(b["lo"], b["hi"]) for b in data["bins"]] == [
        (b.lo, b.hi) for b in reliability([(0.5, True)]).bins
    ]
    assert data["cost_ratio"] == 3.0
    assert normcli_main(["calibrate", str(csv), "--cost-ratio", "3"]) == 2  # no type anywhere


def test_cli_seed0_report_claims_hold():
    """`gold generate --seed 0 --n 30` used to flag [0.8, 0.9): the bare-host URLs (https
    guessed at 0.8) and one ee-GH date (hand M/d/y table). With both fixed (PART1 N3, N4)
    no answer is confident and wrong, so no bin is flagged."""
    cases = generate_corpus(0, 30)
    scored = score(cases, default_engine)
    clean = {"NORMALIZED", "UNCHANGED", "REPAIRED", "PARSED"}
    kept = [
        c
        for c, (st, _, conf) in zip(cases, scored.answers, strict=True)
        if st in clean and conf is not None
    ]
    assert len(kept) == len(scored.pairs)
    rel = reliability(scored.pairs, groups=scored.pair_types)
    assert rel.overconfident_bins == []
    assert all(ok for _, ok in scored.pairs)

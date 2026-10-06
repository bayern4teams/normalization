"""D2 acceptance (derive mode): measure confidence, then threshold it.

Written from improvement-report D2 (Evidence/Fix), plan 2.4 and 9 "D2" and the lead's fixed API,
before any implementation exists. These tests MUST fail today: the import below is the negative
case (`normanalysis.calibration` does not exist).

Everything is checked against numbers computed independently in this file (hand arithmetic, a
brute-force search, a seeded Bernoulli predictor), never against the implementation's own output,
except where a CLI report must agree with the library on the same pairs.
"""

from __future__ import annotations

import ast
import inspect
import json
import math
import random
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
from normanalysis.calibration import (
    chow_threshold,
    ece_tolerance,
    reliability,
    report,
    risk_coverage,
)
from normanalysis.gold import (
    GoldCase,
    default_engine,
    dump_cases,
    generate_corpus,
    load_cases,
    score,
)
from normcli.cli import main as normcli_main

ROOT = Path(__file__).resolve().parents[2]
CAL = ROOT / "packages" / "normanalysis" / "src" / "normanalysis" / "calibration.py"
Pairs = list[tuple[float, bool]]


# --- helpers that fix the vocabulary, not the implementation ---


def _g(obj: Any, name: str) -> Any:
    """Attribute or key: a Bin/Reliability may be a dataclass or a dict."""
    return obj[name] if isinstance(obj, dict) else getattr(obj, name)


def _block(conf: float, n: int, right: int) -> Pairs:
    """n answers all stating `conf`, exactly `right` of them correct (no sampling noise)."""
    return [(conf, True)] * right + [(conf, False)] * (n - right)


def _bernoulli(seed: int, n: int) -> Pairs:
    """A perfectly calibrated predictor: stated ~ U(0,1), correct ~ Bernoulli(stated)."""
    rng = random.Random(seed)
    out: Pairs = []
    for _ in range(n):
        c = rng.random()
        out.append((c, rng.random() < c))
    return out


def _flagged(rel: Any) -> list[tuple[float, float]]:
    """(lo, hi) of each overconfident bin; the list may hold bins or bin indexes."""
    out = []
    for item in _g(rel, "overconfident_bins"):
        b = _g(rel, "bins")[item] if isinstance(item, int) else item
        out.append((float(_g(b, "lo")), float(_g(b, "hi"))))
    return out


def _pt(p: Any) -> tuple[float, float]:
    if isinstance(p, (tuple, list)):
        return float(p[0]), float(p[1])
    return float(_g(p, "coverage")), float(_g(p, "risk"))


def _cost(pairs: Pairs, t: float, ratio: float) -> float:
    """Expected total cost of threshold t: emit iff confidence >= t. A wrong emitted value costs
    `ratio`, an abstention costs 1, a right emitted value costs 0."""
    return sum((0.0 if ok else ratio) if c >= t else 1.0 for c, ok in pairs)


def _brute_min_cost(pairs: Pairs, ratio: float) -> float:
    # Candidate thresholds: every observed confidence (emit from there up) and "abstain on all".
    candidates = {c for c, _ in pairs} | {math.inf}
    return min(_cost(pairs, t, ratio) for t in candidates)


def _numbers(obj: Any) -> list[float]:
    """Every number anywhere in a JSON document (structure-agnostic)."""
    if isinstance(obj, bool):
        return []
    if isinstance(obj, (int, float)):
        return [float(obj)]
    if isinstance(obj, dict):
        return [x for v in obj.values() for x in _numbers(v)]
    if isinstance(obj, list):
        return [x for v in obj for x in _numbers(v)]
    return []


def _threshold_values(obj: Any) -> list[Any]:
    """Values of every key that mentions 'threshold', at any depth."""
    out: list[Any] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if "threshold" in str(k).lower():
                out.append(v)
            out += _threshold_values(v)
    elif isinstance(obj, list):
        for v in obj:
            out += _threshold_values(v)
    return out


def _has(numbers: list[float], x: float) -> bool:
    return any(math.isclose(n, x, rel_tol=1e-6, abs_tol=1e-9) for n in numbers)


# --- 1. reliability: bins, ECE, overconfident bins ---


@pytest.mark.unit
class TestReliability:
    def test_hand_computed_ece_uses_mean_confidence_not_the_bin_midpoint(self) -> None:
        # bins=2 -> [0,.5) and [.5,1]. Low bin: stated .1/.3 (mean .2), 0 of 2 right -> gap .2.
        # High bin: stated .55/.65 (mean .6), 1 of 2 right -> gap .1. ECE = .5*.2 + .5*.1 = .15.
        # With bin midpoints (.25/.75) the gaps would be .25/.25 -> ECE .25: that is the wrong one.
        pairs: Pairs = [(0.1, False), (0.3, False), (0.55, True), (0.65, False)]
        rel = reliability(pairs, bins=2)
        assert rel.ece == pytest.approx(0.15)
        lo, hi = _g(rel, "bins")
        assert (_g(lo, "count"), _g(hi, "count")) == (2, 2)
        assert _g(lo, "mean_confidence") == pytest.approx(0.2)
        assert _g(hi, "mean_confidence") == pytest.approx(0.6)
        assert _g(lo, "accuracy") == pytest.approx(0.0)
        assert _g(hi, "accuracy") == pytest.approx(0.5)
        assert (float(_g(lo, "lo")), float(_g(lo, "hi"))) == pytest.approx((0.0, 0.5))
        assert (float(_g(hi, "lo")), float(_g(hi, "hi"))) == pytest.approx((0.5, 1.0))

    def test_explicit_edges_equal_the_int_form_and_counts_cover_every_pair(self) -> None:
        pairs = _bernoulli(1, 500)
        a = reliability(pairs, bins=4)
        b = reliability(pairs, bins=[0.0, 0.25, 0.5, 0.75, 1.0])
        assert a.ece == pytest.approx(b.ece)
        assert [_g(x, "count") for x in _g(a, "bins")] == [_g(x, "count") for x in _g(b, "bins")]
        assert sum(_g(x, "count") for x in _g(a, "bins")) == 500
        assert len(_g(a, "bins")) == 4

    def test_a_stated_one_and_a_stated_zero_land_in_a_bin(self) -> None:
        # The top edge is closed: confidence 1.0 (28 of the 61 normalizer sites) must not fall off.
        rel = reliability([(1.0, True), (1.0, False), (0.0, False)], bins=10)
        counts = [_g(b, "count") for b in _g(rel, "bins")]
        assert sum(counts) == 3
        assert counts[-1] == 2
        assert counts[0] == 1

    def test_empty_bins_report_no_accuracy_not_zero(self) -> None:
        # never-guess: a bin that saw no case has no accuracy; 0.0 would claim "always wrong".
        rel = reliability(_block(0.95, 40, 38), bins=10)
        bins = _g(rel, "bins")
        assert len(bins) == 10
        empty = [b for b in bins if _g(b, "count") == 0]
        assert len(empty) == 9
        assert all(_g(b, "accuracy") is None for b in empty)
        full = [b for b in bins if _g(b, "count") > 0]
        assert len(full) == 1 and _g(full[0], "accuracy") == pytest.approx(0.95)
        assert rel.ece == pytest.approx(0.0)  # only the populated bin contributes
        assert _flagged(rel) == []  # an empty bin is never "overconfident"

    def test_empty_input_claims_nothing(self) -> None:
        # never-guess: no pairs -> no ECE (None) or a loud ValueError; never a 0.0 "perfect".
        try:
            rel = reliability([])
        except ValueError:
            return
        assert rel.ece is None
        assert _flagged(rel) == []

    @pytest.mark.parametrize("bad", [0, -3, [0.5, 0.2, 1.0], [0.2, 0.5], [0.0, 0.5]])
    def test_bad_bins_are_rejected(self, bad: Any) -> None:
        # edges must increase and span [0, 1]; a bin count must be positive.
        with pytest.raises(ValueError):
            reliability([(0.5, True)], bins=bad)

    @pytest.mark.parametrize("bad", [1.2, -0.1])
    def test_a_confidence_outside_unit_interval_is_an_error_not_clamped(self, bad: float) -> None:
        with pytest.raises(ValueError):
            reliability([(bad, True)])

    def test_overconfident_predictor_is_flagged_and_the_bin_is_named(self) -> None:
        # The report's headline: stated 1.0, observed 0.8. n >= 200 so it is not sampling noise.
        for n in (200, 500, 5000):
            rel = reliability(_block(1.0, n, n * 4 // 5), bins=10)
            flagged = _flagged(rel)
            assert len(flagged) == 1, n
            lo, hi = flagged[0]
            assert lo == pytest.approx(0.9) and hi == pytest.approx(1.0), n
            top = _g(rel, "bins")[-1]
            assert _g(top, "count") == n
            assert _g(top, "mean_confidence") == pytest.approx(1.0)
            assert _g(top, "accuracy") == pytest.approx(0.8)
            assert rel.ece == pytest.approx(0.2)

    def test_calibrated_and_underconfident_bins_are_not_flagged(self) -> None:
        pairs = (
            _block(0.55, 200, 110)  # exactly calibrated
            + _block(0.25, 200, 50)  # exactly calibrated
            + _block(0.35, 300, 270)  # stated .35, observed .9: UNDER-confident, not flagged
            + _block(0.8, 50, 39)  # stated .8, observed .78 on n=50: inside sampling noise
        )
        assert _flagged(reliability(pairs, bins=10)) == []

    def test_only_the_bad_bin_is_flagged_among_good_ones(self) -> None:
        pairs = _block(0.55, 200, 110) + _block(0.25, 200, 50) + _block(1.0, 400, 320)
        flagged = _flagged(reliability(pairs, bins=10))
        assert len(flagged) == 1 and flagged[0][1] == pytest.approx(1.0)

    def test_per_group_results_are_separate_and_the_pool_is_unchanged(self) -> None:
        a = _block(1.0, 300, 240)  # source "bad": overconfident
        b = _block(0.55, 300, 165)  # source "good": calibrated
        pairs = a + b
        labels = ["bad"] * len(a) + ["good"] * len(b)
        rel = reliability(pairs, groups=labels)
        groups = _g(rel, "groups")
        assert set(groups) == {"bad", "good"}
        assert _flagged(groups["bad"]) != [] and _flagged(groups["good"]) == []
        assert groups["bad"].ece == pytest.approx(0.2)
        assert groups["good"].ece == pytest.approx(0.0)
        assert sum(_g(x, "count") for x in _g(groups["bad"], "bins")) == 300
        assert rel.ece == pytest.approx(reliability(pairs).ece)  # pooled result unaffected

    def test_groups_must_have_one_label_per_pair(self) -> None:
        with pytest.raises(ValueError):
            reliability([(0.5, True), (0.6, False)], groups=["a"])


# --- 2. ECE tolerance from the sample size ---


@pytest.mark.unit
class TestEceTolerance:
    def test_tolerance_shrinks_as_n_grows(self) -> None:
        tols = [ece_tolerance(n, 10) for n in (100, 400, 1600, 6400, 25600)]
        assert all(t > 0 for t in tols)
        assert tols == sorted(tols, reverse=True) and len(set(tols)) == len(tols)
        # sampling noise falls like 1/sqrt(n): 100x the data buys well over 5x the precision.
        assert ece_tolerance(10_000, 10) < ece_tolerance(100, 10) / 5

    def test_more_bins_never_tighten_the_tolerance(self) -> None:
        # each extra bin adds noise at fixed n.
        assert ece_tolerance(2000, 20) >= ece_tolerance(2000, 10) >= ece_tolerance(2000, 5)

    @pytest.mark.parametrize("n", [300, 1000, 5000, 20000])
    def test_a_perfectly_calibrated_predictor_is_within_tolerance(self, n: int) -> None:
        tol = ece_tolerance(n, 10)
        for seed in (0, 1, 2):  # the tolerance is an upper confidence bound, not the mean
            ece = reliability(_bernoulli(seed, n), bins=10).ece
            assert ece <= tol, (n, seed, ece, tol)

    def test_the_tolerance_is_not_vacuous(self) -> None:
        # a tolerance that passes anything would pass the 0.2-off predictor too.
        n = 1000
        overconfident = reliability(_block(1.0, n, 800), bins=10).ece
        assert overconfident > ece_tolerance(n, 10)
        assert ece_tolerance(n, 10) < 0.15

    def test_tolerance_has_no_tuning_default(self) -> None:
        params = inspect.signature(ece_tolerance).parameters
        assert [p.default for p in list(params.values())[:2]] == [inspect.Parameter.empty] * 2


# --- 3. Chow's rule ---


@pytest.mark.unit
class TestChowThreshold:
    TOY: Pairs = _block(0.9, 10, 9) + _block(0.7, 10, 6) + _block(0.5, 10, 3)

    def test_toy_case_equals_the_hand_computed_minimum_cost_threshold(self) -> None:
        # ratio 3 (a wrong value costs 3 abstentions):
        #   t=0.9: emit 10 (1 wrong -> 3) + abstain 20 -> 23     <- minimum
        #   t=0.7: emit 20 (5 wrong -> 15) + abstain 10 -> 25
        #   t=0.5: emit 30 (12 wrong -> 36)                      -> 36
        #   abstain all                                          -> 30
        assert _cost(self.TOY, 0.9, 3.0) == 23
        assert _cost(self.TOY, 0.7, 3.0) == 25
        assert _cost(self.TOY, 0.5, 3.0) == 36
        assert _cost(self.TOY, math.inf, 3.0) == 30
        assert _brute_min_cost(self.TOY, 3.0) == 23
        t = chow_threshold(self.TOY, 3.0)
        assert t is not None and 0.7 < t <= 0.9
        assert _cost(self.TOY, t, 3.0) == 23

    @pytest.mark.parametrize("ratio", [1.0, 1.5, 2.0, 5.0, 10.0, 100.0])
    def test_random_case_matches_brute_force(self, ratio: float) -> None:
        rng = random.Random(7)
        pairs: Pairs = []
        for _ in range(300):
            c = round(rng.random(), 2)  # rounding makes confidence ties, as real data has
            pairs.append((c, rng.random() < c))
        t = chow_threshold(pairs, ratio)
        assert t is not None
        assert _cost(pairs, t, ratio) == _brute_min_cost(pairs, ratio)

    def test_larger_ratio_never_lowers_the_threshold(self) -> None:
        rng = random.Random(11)
        pairs = [(c := round(rng.random(), 2), rng.random() < c) for _ in range(400)]
        ts = [chow_threshold(pairs, r) for r in (1.0, 1.5, 2.0, 3.0, 5.0, 10.0, 50.0, 1000.0)]
        assert None not in ts
        assert ts == sorted(ts)

    def test_a_cost_ratio_is_required_with_no_default(self) -> None:
        with pytest.raises(TypeError):
            chow_threshold(self.TOY)
        assert inspect.signature(chow_threshold).parameters["cost_ratio"].default is (
            inspect.Parameter.empty
        )

    @pytest.mark.parametrize("bad", [0, 0.0, -1.0, -5])
    def test_non_positive_ratio_is_an_error(self, bad: float) -> None:
        with pytest.raises(ValueError):
            chow_threshold(self.TOY, bad)

    def test_no_data_means_no_threshold_claimed(self) -> None:
        # never-guess: with no pairs there is nothing to optimise; a 0.5 would be invented.
        try:
            t = chow_threshold([], 2.0)
        except ValueError:
            return
        assert t is None


# --- 4. risk-coverage ---


@pytest.mark.unit
class TestRiskCoverage:
    def test_toy_case_points_and_aurc_by_hand(self) -> None:
        # Ranked by confidence: .9 T, .8 T, .7 F, .6 T. Keeping the top k:
        #   k=4 cov 1.00 risk 1/4;  k=3 cov .75 risk 1/3;  k=2 cov .5 risk 0;  k=1 cov .25 risk 0.
        # AURC = mean selective risk over k = (1/4 + 1/3 + 0 + 0) / 4 = 7/48.
        pairs: Pairs = [(0.6, True), (0.9, True), (0.7, False), (0.8, True)]  # unsorted on purpose
        points, aurc = risk_coverage(pairs)
        got = [_pt(p) for p in points]
        assert got == pytest.approx([(1.0, 0.25), (0.75, 1 / 3), (0.5, 0.0), (0.25, 0.0)])
        assert aurc == pytest.approx(7 / 48)

    def test_coverage_descends_from_one_and_first_risk_is_the_error_rate(self) -> None:
        pairs = _bernoulli(5, 400)
        points, _ = risk_coverage(pairs)
        cov = [_pt(p)[0] for p in points]
        assert cov[0] == pytest.approx(1.0)
        assert cov == sorted(cov, reverse=True)
        assert all(0.0 <= _pt(p)[1] <= 1.0 for p in points)
        assert _pt(points[0])[1] == pytest.approx(sum(not ok for _, ok in pairs) / 400)

    def test_perfect_ranker_beats_a_reversed_one(self) -> None:
        n = 100
        right = [True] * 80 + [False] * 20
        perfect = [(1.0 - i / 1000, ok) for i, ok in enumerate(right)]  # right answers most sure
        reverse = [(1.0 - i / 1000, ok) for i, ok in enumerate(reversed(right))]
        _, a_perfect = risk_coverage(perfect)
        _, a_reverse = risk_coverage(reverse)
        assert 0.0 <= a_perfect < a_reverse <= 1.0
        # a ranker cannot beat "all right" or lose to "all wrong"
        assert risk_coverage([(0.5 + i / 1000, True) for i in range(n)])[1] == pytest.approx(0.0)
        assert risk_coverage([(0.5 + i / 1000, False) for i in range(n)])[1] == pytest.approx(1.0)

    def test_input_order_never_matters_even_among_tied_confidences(self) -> None:
        # never-guess: ties must not be broken by whichever case came first.
        pairs: Pairs = _block(0.9, 6, 3) + _block(0.8, 4, 4) + _block(0.5, 5, 1)
        base = risk_coverage(pairs)
        for seed in range(5):
            shuffled = pairs[:]
            random.Random(seed).shuffle(shuffled)
            points, aurc = risk_coverage(shuffled)
            assert [_pt(p) for p in points] == pytest.approx([_pt(p) for p in base[0]])
            assert aurc == pytest.approx(base[1])

    def test_empty_input_claims_nothing(self) -> None:
        try:
            points, aurc = risk_coverage([])
        except ValueError:
            return
        assert list(points) == [] and aurc is None


# --- 5. the report (library and CLI) ---


def _report(pairs: Pairs, ratio: float) -> tuple[dict[str, Any], str]:
    # ponytail-free adapter: report(pairs, *, cost_ratio, ...) -> (json-able dict, markdown str).
    out = report(pairs, cost_ratio=ratio)
    return out[0], out[1]


@pytest.mark.unit
class TestReport:
    PAIRS: Pairs = _block(0.55, 200, 110) + _block(1.0, 400, 320)

    def test_json_is_serialisable_and_agrees_with_the_library(self) -> None:
        data, md = _report(self.PAIRS, 4.0)
        text = json.dumps(data)  # raises if anything non-JSON leaks (numpy, dataclass, inf)
        assert isinstance(md, str) and md.strip()
        nums = _numbers(json.loads(text))
        assert _has(nums, reliability(self.PAIRS).ece)
        assert _has(nums, chow_threshold(self.PAIRS, 4.0))
        assert _has(nums, risk_coverage(self.PAIRS)[1])
        assert _has(nums, 4.0)  # the stated cost ratio is echoed: the report says what it assumed
        assert _has(nums, len(self.PAIRS))

    def test_markdown_names_the_overconfident_bin(self) -> None:
        _, md = _report(self.PAIRS, 4.0)
        low = md.lower()
        assert "overconfident" in low or "over-confident" in low
        assert "0.9" in md and "1.0" in md  # the [0.9, 1.0] bin edges
        assert "ece" in low and "aurc" in low
        assert re.search(r"cost[ _-]?ratio", low)

    def test_empty_pairs_report_no_threshold(self) -> None:
        try:
            data, _ = _report([], 4.0)
        except ValueError:
            return
        assert all(v is None for v in _threshold_values(data))


def _corpus(tmp_path: Path, cases: list[GoldCase] | None = None) -> Path:
    p = tmp_path / "corpus.jsonl"
    p.write_text(
        dump_cases(cases if cases is not None else generate_corpus(0, 10)), encoding="utf-8"
    )
    return p


def _run(argv: list[str]) -> int:
    try:
        return normcli_main(argv)
    except SystemExit as e:  # argparse errors exit 2
        return e.code if isinstance(e.code, int) else 1


@pytest.mark.unit
class TestCli:
    def test_refuses_without_a_cost_ratio(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        p = _corpus(tmp_path)
        out_json, out_md = tmp_path / "r.json", tmp_path / "r.md"
        capsys.readouterr()
        rc = _run(["calibrate", str(p), "--out-json", str(out_json), "--out-md", str(out_md)])
        err = capsys.readouterr()
        assert rc != 0
        assert re.search(r"cost[ _-]?ratio", (err.err + err.out).lower())  # says what is missing
        assert not out_json.exists() and not out_md.exists()  # and writes nothing

    @pytest.mark.parametrize("bad", ["0", "-2", "abc"])
    def test_refuses_a_bad_cost_ratio(self, tmp_path: Path, bad: str) -> None:
        p = _corpus(tmp_path)
        assert _run(["calibrate", str(p), "--cost-ratio", bad]) != 0

    def test_report_agrees_with_the_library_on_the_same_corpus(self, tmp_path: Path) -> None:
        p = _corpus(tmp_path)
        out_json, out_md = tmp_path / "r.json", tmp_path / "r.md"
        rc = _run(
            [
                "calibrate",
                str(p),
                "--cost-ratio",
                "5",
                "--out-json",
                str(out_json),
                "--out-md",
                str(out_md),
            ]
        )
        assert rc == 0
        pairs = score(load_cases(p), default_engine).pairs  # the real engine, scored by D6
        assert pairs, "corpus must give the engine something to be confident about"
        nums = _numbers(json.loads(out_json.read_text(encoding="utf-8")))
        assert _has(nums, reliability(pairs).ece)
        assert _has(nums, chow_threshold(pairs, 5.0))
        assert _has(nums, risk_coverage(pairs)[1])
        assert _has(nums, 5.0) and _has(nums, len(pairs))
        md = out_md.read_text(encoding="utf-8")
        assert md.strip() and "ece" in md.lower()

    def test_a_corpus_the_engine_always_abstains_on_claims_no_threshold(
        self, tmp_path: Path
    ) -> None:
        # never-guess: 03/04/2024 is AMBIGUOUS; the engine abstains; there are no confident
        # answers, so there is nothing to calibrate and no threshold may be invented.
        case = GoldCase(
            "DATE", {}, "03/04/2024", "AMBIGUOUS", None, ("2024-03-04", "2024-04-03"), "t"
        )
        p = _corpus(tmp_path, [case, case])
        out_json = tmp_path / "r.json"
        rc = _run(["calibrate", str(p), "--cost-ratio", "5", "--out-json", str(out_json)])
        if rc != 0:
            return
        data = json.loads(out_json.read_text(encoding="utf-8"))
        assert all(v is None for v in _threshold_values(data))

    def test_missing_corpus_is_an_error(self, tmp_path: Path) -> None:
        try:
            rc = _run(["calibrate", str(tmp_path / "nope.jsonl"), "--cost-ratio", "5"])
        except (OSError, ValueError):
            return
        assert rc != 0


# --- plan 2.4 / 2.5: general, never guessed, and nothing else touched ---

_NORMALIZER_CONFIDENCE_SITES = {
    # `git grep -c "confidence=" packages/normalizers` at derivation time; total 61 = the report
    "address.py": 3,
    "boolean.py": 3,
    "company.py": 2,
    "country.py": 3,
    "currency.py": 3,
    "date.py": 8,
    "email.py": 3,
    "generic_text.py": 2,
    "identifier.py": 4,
    "language.py": 3,
    "money.py": 3,
    "name.py": 3,
    "numeric.py": 4,
    "passthrough.py": 1,
    "phone.py": 4,
    "postcode.py": 4,
    "script.py": 2,
    "unit.py": 3,
    "url.py": 3,
}


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout


def _magic_numbers(src: str) -> list[tuple[int, str]]:
    """Numeric literals other than 0, 1, 2 (and their float forms) with no derivation or
    `ponytail:` note on the same line or in the comment block directly above."""
    lines = src.splitlines()
    out: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Constant) or isinstance(node.value, (bool, str, bytes)):
            continue
        if not isinstance(node.value, (int, float)) or node.value in {0, 1, 2}:
            continue
        ctx = [lines[node.lineno - 1]]
        i = node.lineno - 2
        while i >= 0 and lines[i].lstrip().startswith("#"):
            ctx.append(lines[i])
            i -= 1
        if not re.search(r"ponytail:|deriv", " ".join(ctx), re.IGNORECASE):
            out.append((node.lineno, lines[node.lineno - 1].strip()))
    return out


@pytest.mark.unit
class TestSection24Grep:
    def test_the_scan_catches_planted_threshold_literals(self) -> None:
        planted = [
            "z = 1.96\n",
            "def f(bins=10): ...\n",
            "t = 0.5\n",
            "cut = 0.95\n",
            "tol = 0.05\n",
        ]
        for src in planted:
            assert _magic_numbers(src), src

    def test_the_scan_passes_derived_or_noted_or_trivial_numbers(self) -> None:
        clean = [
            "t = 1 - 1 / ratio\n",
            "x = n * 2\n",
            "hi = 1.0\n",
            "def f(bins=10): ...  # ponytail: convention, per-type n is small\n",
            "# ponytail: ten equal-width bins is the textbook default\ndef f(bins=10): ...\n",
            "# derived: Hoeffding, 3 sigma of the bin mean\nk = 3\n",
            '"""a docstring with 0.95 and 10 in it"""\n',
        ]
        for src in clean:
            assert _magic_numbers(src) == [], src

    def test_calibration_py_has_no_unexplained_threshold_literal(self) -> None:
        # Scans the WHOLE file: a new file is invisible to `git diff`, and CI is a shallow clone.
        assert CAL.exists()
        assert _magic_numbers(CAL.read_text(encoding="utf-8")) == []

    def test_calibration_py_is_pure_and_records_its_ceiling_and_deferral(self) -> None:
        src = CAL.read_text(encoding="utf-8")
        imported: set[str] = set()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert not imported & {"normapi", "normalizers", "normexec", "normio"}
        # the report's deferred alternative (step 3) is named where the next person will look
        lines = src.splitlines()
        near = " ".join(
            " ".join(lines[i : i + 4]) for i, ln in enumerate(lines) if "ponytail:" in ln
        )
        assert "conformal" in near.lower()

    def test_adr_019_exists_and_states_the_cost_ratio_decision(self) -> None:
        adr = ROOT / "docs" / "adr" / "ADR-019-confidence-calibration.md"
        assert adr.exists()
        text = adr.read_text(encoding="utf-8").lower()
        assert "cost ratio" in text and "conformal" in text


@pytest.mark.unit
class TestMeasuringComesBeforeTuning:
    def test_no_normalizer_changed(self) -> None:
        assert _git("diff", "HEAD", "--stat", "--", "packages/normalizers") == ""
        assert _git("status", "--porcelain", "--", "packages/normalizers").strip() == ""

    def test_no_confidence_literal_added_or_removed(self) -> None:
        counts = {
            Path(ln.rsplit(":", 1)[0]).name: int(ln.rsplit(":", 1)[1])
            for ln in _git("grep", "-c", "confidence=", "--", "packages/normalizers").splitlines()
        }
        assert counts == _NORMALIZER_CONFIDENCE_SITES
        assert sum(counts.values()) == 61  # the report's "Verified state"

    def test_calibration_is_not_wired_into_dispatch(self) -> None:
        for pkg in ("normcore", "normapi", "normexec", "normio", "normalizers"):
            assert _git("diff", "HEAD", "--stat", "--", f"packages/{pkg}") == "", pkg
        users = _git(
            "grep",
            "-lE",
            r"normanalysis\.calibration|import calibration|chow_threshold|risk_coverage",
            "--",
            "packages/normcore",
            "packages/normapi",
            "packages/normexec",
            "packages/normio",
            "packages/normalizers",
        )
        assert users.strip() == ""

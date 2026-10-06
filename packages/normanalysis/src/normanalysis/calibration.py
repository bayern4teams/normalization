"""Measure stated confidence against correctness, then threshold it (improvement-report D2).

The normalizers' `confidence=` values are numbers a developer typed. This module answers "when the
engine says 0.85, how often is it right?" from `(stated confidence, correct)` pairs (D6's
`GoldReport.pairs`), and nothing else: it is not wired into dispatch and changes no normalizer.
Measuring comes before tuning.

* `reliability`: confidence bins against observed accuracy, the expected calibration error (ECE)
  and the bins whose stated confidence is above the observed accuracy beyond sampling noise.
* `ece_tolerance`: how large the ECE of a perfectly calibrated predictor can be at this sample size.
* `chow_threshold`: the abstain/emit threshold from a cost ratio the caller must state.
* `risk_coverage`: error rate among the answers kept, as the threshold rises, and its area (AURC).

ponytail: conformal prediction (the report's step 3: candidate sets with a coverage guarantee,
MAPIE) and per-source `calibration_bins` persisted for dispatch are deferred to Part 3; the trigger
is a labelled corpus large enough per semantic type that these bins are not mostly noise.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import groupby, pairwise
from typing import Any

Pairs = Sequence[tuple[float, bool]]

# ponytail: 5% is the conventional significance level; every noise bound below is derived from it
# (Hoeffding / McDiarmid), so changing the level is this one line.
_DELTA = 0.05
# ponytail: ten equal-width bins is the textbook reliability-diagram default (Guo et al. 2017);
# with little data per semantic type, pass fewer bins (ece_tolerance shows the noise either way).
_BINS = 10


@dataclass(frozen=True)
class Bin:
    lo: float
    hi: float
    count: int
    mean_confidence: float | None  # None for an empty bin: it saw nothing, so it claims nothing
    accuracy: float | None


@dataclass(frozen=True)
class Reliability:
    bins: list[Bin]
    ece: float | None  # None without pairs
    overconfident_bins: list[Bin]
    groups: dict[str, Reliability] = field(default_factory=dict)


def _edges(bins: int | Sequence[float]) -> list[float]:
    if isinstance(bins, int):
        if bins < 1:
            raise ValueError(f"bins must be positive, got {bins}")
        return [i / bins for i in range(bins + 1)]
    edges = [float(e) for e in bins]
    if len(edges) < 2 or edges[0] != 0 or edges[-1] != 1 or any(map(math.isnan, edges)):
        raise ValueError(f"bin edges must span [0, 1], got {edges}")
    if any(a >= b for a, b in pairwise(edges)):
        raise ValueError(f"bin edges must increase, got {edges}")
    return edges


def _check(pairs: Pairs) -> None:
    for conf, _ in pairs:
        # also rejects NaN and a bool (True is not a stated confidence); never clamped
        if isinstance(conf, bool) or not 0 <= conf <= 1:
            raise ValueError(f"confidence {conf!r} is outside [0, 1]")


def reliability(
    pairs: Pairs,
    *,
    bins: int | Sequence[float] = _BINS,
    groups: Sequence[str] | None = None,
) -> Reliability:
    """Bins `[lo, hi)`, the last one closed so a stated 1.0 is counted. ECE weights each bin's
    |accuracy - mean stated confidence| by its share of the pairs. A bin is overconfident when a
    one-sided Hoeffding test rejects "accuracy >= stated" at `_DELTA` split over the bins
    (Bonferroni): exp(-2 n gap^2) < delta / bins."""
    edges = _edges(bins)
    _check(pairs)
    if groups is not None and len(groups) != len(pairs):
        raise ValueError(f"{len(groups)} group labels for {len(pairs)} pairs")
    k = len(edges) - 1
    members: list[list[tuple[float, bool]]] = [[] for _ in range(k)]
    for conf, ok in pairs:
        members[min(bisect_right(edges, conf) - 1, k - 1)].append((conf, ok))
    out: list[Bin] = []
    over: list[Bin] = []
    gaps = 0.0
    for (lo, hi), m in zip(pairwise(edges), members, strict=True):
        if not m:
            out.append(Bin(lo, hi, 0, None, None))
            continue
        mean = math.fsum(c for c, _ in m) / len(m)
        acc = sum(ok for _, ok in m) / len(m)
        out.append(Bin(lo, hi, len(m), mean, acc))
        gaps += len(m) * abs(acc - mean)
        if mean > acc and math.exp(-2 * len(m) * (mean - acc) ** 2) < _DELTA / k:
            over.append(out[-1])
    ece = gaps / len(pairs) if pairs else None
    by_group: dict[str, Reliability] = {}
    if groups is not None:
        split: dict[str, list[tuple[float, bool]]] = {}
        for p, g in zip(pairs, groups, strict=True):
            split.setdefault(g, []).append(p)
        for label in sorted(split):
            by_group[label] = reliability(split[label], bins=edges)
    return Reliability(out, ece, over, by_group)


def ece_tolerance(n: int, bins: int) -> float:
    """An upper `1 - _DELTA` bound on the ECE of a perfectly calibrated predictor over `n` pairs.

    Derivation: ECE = (1/n) sum_b |S_b| with S_b = sum over bin b of (correct - stated), a sum of
    independent zero-mean terms under calibration, so E|S_b| <= sqrt(n_b) / 2 and, by
    Cauchy-Schwarz over the bins, E[ECE] <= sqrt(bins / n) / 2. Changing one pair moves at most
    two S_b by at most 1, so ECE has bounded differences 2/n, and McDiarmid adds
    sqrt(2 ln(1/delta) / n)."""
    if n < 1 or bins < 1:
        raise ValueError(f"need n >= 1 and bins >= 1, got n={n}, bins={bins}")
    return math.sqrt(bins / n) / 2 + math.sqrt(2 * math.log(1 / _DELTA) / n)


def chow_threshold(pairs: Pairs, cost_ratio: float) -> float | None:
    """Chow's rule, measured: the threshold t (emit iff confidence >= t) of least total cost, where
    a wrong emitted value costs `cost_ratio` abstentions and a right one costs nothing.

    For calibrated confidences this is Chow's 1 - 1/cost_ratio; here it is the empirical optimum
    over the observed confidences, so a miscalibrated engine gets the threshold its real accuracy
    earns. `math.inf` means abstaining on everything is cheapest; `None` means no pairs, so
    nothing to optimise. Among equal-cost thresholds the highest wins (abstain when in doubt),
    which also keeps the threshold monotone in the ratio."""
    if not 0 < cost_ratio < math.inf:  # also rejects NaN; inf * 0 wrong answers would be NaN
        raise ValueError(f"cost_ratio must be positive and finite, got {cost_ratio!r}")
    _check(pairs)
    if not pairs:
        return None
    best_t, best_cost = math.inf, float(len(pairs))  # abstain on everything
    wrong = emitted = 0
    for conf, group in groupby(sorted(pairs, key=lambda p: -p[0]), key=lambda p: p[0]):
        oks = [ok for _, ok in group]
        emitted += len(oks)
        wrong += len(oks) - sum(oks)
        cost = cost_ratio * wrong + (len(pairs) - emitted)
        if cost < best_cost:
            best_t, best_cost = conf, cost
    return best_t


def risk_coverage(pairs: Pairs) -> tuple[list[tuple[float, float]], float | None]:
    """`(coverage, risk)` points from full coverage down, one per distinct confidence (tied
    answers are kept or dropped together), and AURC: the selective risk averaged over keeping the
    top k answers for every k, with a tie group's errors spread evenly (the expected risk over
    every order of the tie, so the input order never matters)."""
    _check(pairs)
    if not pairs:
        return [], None
    n = len(pairs)
    points: list[tuple[float, float]] = []
    area = 0.0
    kept = errors = 0
    for _, group in groupby(sorted(pairs, key=lambda p: -p[0]), key=lambda p: p[0]):
        oks = [ok for _, ok in group]
        rate = (len(oks) - sum(oks)) / len(oks)
        for j in range(1, len(oks) + 1):
            area += (errors + j * rate) / (kept + j)
        kept += len(oks)
        errors += len(oks) - sum(oks)
        points.append((kept / n, errors / kept))
    return points[::-1], area / n


def _bin_json(b: Bin) -> dict[str, Any]:
    return {
        "lo": b.lo,
        "hi": b.hi,
        "count": b.count,
        "mean_confidence": b.mean_confidence,
        "accuracy": b.accuracy,
    }


def report(
    pairs: Pairs,
    *,
    cost_ratio: float,
    groups: Sequence[str] | None = None,
    bins: int | Sequence[float] = _BINS,
) -> tuple[dict[str, Any], str]:
    """The JSON-serialisable report and its Markdown rendering."""
    rel = reliability(pairs, bins=bins, groups=groups)
    t = chow_threshold(pairs, cost_ratio)
    points, aurc = risk_coverage(pairs)
    k = len(rel.bins)
    data: dict[str, Any] = {
        "n": len(pairs),
        "cost_ratio": cost_ratio,
        "ece": rel.ece,
        "ece_tolerance": ece_tolerance(len(pairs), k) if pairs else None,
        "bins": [_bin_json(b) for b in rel.bins],
        "overconfident_bins": [_bin_json(b) for b in rel.overconfident_bins],
        # JSON has no infinity: abstain-on-everything is a flag, not a number
        "threshold": None if t is None or math.isinf(t) else t,
        "abstain_on_everything": t is not None and math.isinf(t),
        "aurc": aurc,
        "risk_coverage": [{"coverage": c, "risk": r} for c, r in points],
        "groups": {
            label: {
                "n": sum(b.count for b in g.bins),
                "ece": g.ece,
                "overconfident_bins": [_bin_json(b) for b in g.overconfident_bins],
            }
            for label, g in rel.groups.items()
        },
    }
    return data, _markdown(data)


def _fmt(x: float | None) -> str:
    return "-" if x is None else f"{x:.3f}"


def _span(b: dict[str, Any]) -> str:
    return f"[{b['lo']}, {b['hi']}{']' if b['hi'] == 1 else ')'}"


def _markdown(d: dict[str, Any]) -> str:
    lines = [
        "# Confidence calibration",
        "",
        f"{d['n']} confident answers; stated cost ratio (wrong value : abstention) "
        f"= {d['cost_ratio']}.",
        "",
        f"- ECE: {_fmt(d['ece'])} (a calibrated engine stays under {_fmt(d['ece_tolerance'])})",
        f"- AURC: {_fmt(d['aurc'])}",
        "- Chow threshold (emit iff confidence >= t): "
        + (
            "abstain on everything"
            if d["abstain_on_everything"]
            else "none (no confident answers)"
            if d["threshold"] is None
            else str(d["threshold"])
        ),
        "",
        "| bin | count | mean stated | observed |",
        "|---|---|---|---|",
    ]
    lines += [
        f"| {_span(b)} | {b['count']} | {_fmt(b['mean_confidence'])} | {_fmt(b['accuracy'])} |"
        for b in d["bins"]
    ]
    over = d["overconfident_bins"]
    lines += ["", "Overconfident bins (stated above observed beyond sampling noise): "]
    lines[-1] += ", ".join(_span(b) for b in over) if over else "none"
    for label, g in d["groups"].items():
        flagged = ", ".join(_span(b) for b in g["overconfident_bins"]) or "none"
        lines.append(f"- {label}: n {g['n']}, ECE {_fmt(g['ece'])}, overconfident {flagged}")
    return "\n".join(lines) + "\n"

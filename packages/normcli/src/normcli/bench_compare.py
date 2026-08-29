"""`normcli bench-compare` — the performance regression gate `gate.yml`'s
`benchmarks` job has invoked (`--max-throughput-regression 0.10
--max-p95-regression 0.15`) since M13-M22 was drafted, but which never
existed as real code: `normcli/cli.py` registered no such subcommand,
so every gate run since would have failed at argparse before comparing
a single number. Real implementation, found missing during the
2026-08-29 throughput R&D pass (see docs/plan history — the
`tests/bench/baseline.json` this compares against was also never
committed, only ever written as a release artifact by `release.yml`).

Compares two `pytest-benchmark --benchmark-json` files by benchmark
`fullname` (unique across a run, unlike `name` which repeats for
parametrized cases). Two independent signals per benchmark:

- **Throughput** — `stats.ops` (operations/second, i.e. 1/mean). A
  regression is `ops` dropping by more than `--max-throughput-regression`.
- **p95 latency** — computed from `stats.data` (the raw per-round timings
  pytest-benchmark records), not from `stats.mean`/`stats.median`, since
  neither of those is a tail-latency measure. A regression is p95 rising
  by more than `--max-p95-regression`.

Benchmarks present only in `--current` (new benchmarks, not yet in the
baseline) are reported, never failed on — this is deliberate: it's the
only way a baseline can ever grow without a chicken-and-egg failure the
first time a new bench lands. Benchmarks present only in `--baseline`
(removed or renamed) are reported the same way, not failed on, since a
rename is a normal refactor, not a regression.
"""

from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO


class BenchmarkFileNotFoundError(FileNotFoundError):
    pass


class BenchmarkFileFormatError(ValueError):
    pass


@dataclass(frozen=True)
class BenchmarkComparison:
    fullname: str
    baseline_ops: float
    current_ops: float
    baseline_p95: float
    current_p95: float
    max_throughput_regression: float
    max_p95_regression: float

    @property
    def throughput_regression(self) -> float:
        """Fractional drop in ops/sec; positive = slower, negative = faster."""
        if self.baseline_ops == 0:
            return 0.0
        return (self.baseline_ops - self.current_ops) / self.baseline_ops

    @property
    def p95_regression(self) -> float:
        """Fractional rise in p95 latency; positive = slower, negative = faster."""
        if self.baseline_p95 == 0:
            return 0.0
        return (self.current_p95 - self.baseline_p95) / self.baseline_p95

    @property
    def passed(self) -> bool:
        return (
            self.throughput_regression <= self.max_throughput_regression
            and self.p95_regression <= self.max_p95_regression
        )


@dataclass(frozen=True)
class BenchCompareResult:
    comparisons: tuple[BenchmarkComparison, ...]
    new_in_current: tuple[str, ...]  # fullnames only in --current
    missing_from_current: tuple[str, ...]  # fullnames only in --baseline

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.comparisons)


def _percentile(data: list[float], pct: float) -> float:
    """Nearest-rank percentile over raw round timings. `pct` in [0, 1]."""
    if not data:
        raise BenchmarkFileFormatError("cannot compute a percentile of an empty data series")
    ordered = sorted(data)
    rank = max(1, min(len(ordered), math.ceil(pct * len(ordered))))
    return ordered[rank - 1]


def _load_benchmarks(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        msg = f"No benchmark JSON file at {path}"
        raise BenchmarkFileNotFoundError(msg)

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        msg = f"{path} is not valid JSON: {exc}"
        raise BenchmarkFileFormatError(msg) from exc

    if "benchmarks" not in raw:
        msg = f"{path} has no top-level 'benchmarks' key — not a pytest-benchmark JSON report"
        raise BenchmarkFileFormatError(msg)

    by_fullname: dict[str, dict[str, Any]] = {}
    for entry in raw["benchmarks"]:
        fullname = entry.get("fullname") or entry.get("name")
        if not fullname:
            msg = f"{path} contains a benchmark entry with no 'fullname' or 'name': {entry}"
            raise BenchmarkFileFormatError(msg)
        by_fullname[fullname] = entry
    return by_fullname


def compare_benchmarks(
    *,
    current_path: Path,
    baseline_path: Path,
    max_throughput_regression: float,
    max_p95_regression: float,
) -> BenchCompareResult:
    current = _load_benchmarks(current_path)
    baseline = _load_benchmarks(baseline_path)

    shared_fullnames = sorted(set(current) & set(baseline))
    new_in_current = tuple(sorted(set(current) - set(baseline)))
    missing_from_current = tuple(sorted(set(baseline) - set(current)))

    comparisons = []
    for fullname in shared_fullnames:
        current_stats = current[fullname]["stats"]
        baseline_stats = baseline[fullname]["stats"]
        comparisons.append(
            BenchmarkComparison(
                fullname=fullname,
                baseline_ops=float(baseline_stats["ops"]),
                current_ops=float(current_stats["ops"]),
                baseline_p95=_percentile(baseline_stats["data"], 0.95),
                current_p95=_percentile(current_stats["data"], 0.95),
                max_throughput_regression=max_throughput_regression,
                max_p95_regression=max_p95_regression,
            )
        )

    return BenchCompareResult(
        comparisons=tuple(comparisons),
        new_in_current=new_in_current,
        missing_from_current=missing_from_current,
    )


def run_bench_compare(
    *,
    current_path: Path,
    baseline_path: Path,
    max_throughput_regression: float,
    max_p95_regression: float,
    stream: TextIO | None = None,
) -> int:
    """Returns a process exit code (0 = pass), matching
    `run_mutation_score_gate`'s shape so both gates are independently
    testable without subprocess machinery."""
    out = stream if stream is not None else sys.stdout

    try:
        result = compare_benchmarks(
            current_path=current_path,
            baseline_path=baseline_path,
            max_throughput_regression=max_throughput_regression,
            max_p95_regression=max_p95_regression,
        )
    except (BenchmarkFileNotFoundError, BenchmarkFileFormatError) as exc:
        out.write(f"bench-compare: ERROR: {exc}\n")
        return 2

    for comparison in result.comparisons:
        status = "OK" if comparison.passed else "REGRESSION"
        out.write(
            f"bench-compare: {status} {comparison.fullname} — "
            f"throughput {comparison.baseline_ops:.1f} -> {comparison.current_ops:.1f} ops/s "
            f"({comparison.throughput_regression:+.1%}, "
            f"limit {comparison.max_throughput_regression:.0%}), "
            f"p95 {comparison.baseline_p95 * 1000:.3f}ms -> {comparison.current_p95 * 1000:.3f}ms "
            f"({comparison.p95_regression:+.1%}, limit {comparison.max_p95_regression:.0%})\n"
        )

    for fullname in result.new_in_current:
        out.write(f"bench-compare: NEW (not in baseline, not gated) {fullname}\n")
    for fullname in result.missing_from_current:
        out.write(f"bench-compare: MISSING (in baseline, not in this run) {fullname}\n")

    status = "PASSED" if result.passed else "FAILED"
    out.write(
        f"bench-compare: {status} — {sum(c.passed for c in result.comparisons)}/"
        f"{len(result.comparisons)} benchmarks within regression limits\n"
    )
    return 0 if result.passed else 1

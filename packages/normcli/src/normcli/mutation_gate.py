"""`normcli mutation-score-gate` — gates CI on a minimum mutmut mutation
score.

Reads the real stats file `mutmut export-cicd-stats` (mutmut 3.x)
produces at `mutants/mutmut-cicd-stats.json` (keys: killed, survived,
total, no_tests, skipped, suspicious, timeout,
check_was_interrupted_by_user, segfault — verified against the actual
installed `mutmut` package source, `mutmut/__main__.py`'s
`save_cicd_stats()`, not guessed from documentation).

Mutation score is defined as `killed / (killed + survived)` — the
standard definition, counting only mutants that were actually evaluated
to a clean kill-or-survive verdict; `no_tests`/`skipped`/`suspicious`/
`timeout` mutants are excluded from the denominator since neither
outcome reflects real test-suite strength for that mutant.

Running `mutmut run` itself is out of this module's scope (mutmut
explicitly does not support native Windows — WSL/Linux only — while this
gate command's own logic must run and be tested anywhere per this
project's cross-platform CI). This module only consumes mutmut's output;
producing it is `.github/workflows/gate.yml`'s `mutation-testing` job's
job, running on `ubuntu-latest`.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO


class MutationStatsNotFoundError(FileNotFoundError):
    pass


class MutationStatsFormatError(ValueError):
    pass


@dataclass(frozen=True)
class MutationScoreResult:
    killed: int
    survived: int
    evaluated: int
    score: float | None  # None when zero mutants were evaluated
    min_score: float

    @property
    def passed(self) -> bool:
        return self.score is not None and self.score >= self.min_score


_REQUIRED_KEYS = ("killed", "survived")


def compute_mutation_score(stats_path: Path, *, min_score: float) -> MutationScoreResult:
    if not stats_path.exists():
        msg = (
            f"No mutmut CI/CD stats file at {stats_path} — run "
            "`mutmut run` then `mutmut export-cicd-stats` first."
        )
        raise MutationStatsNotFoundError(msg)

    try:
        raw = json.loads(stats_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        msg = f"{stats_path} is not valid JSON: {exc}"
        raise MutationStatsFormatError(msg) from exc

    missing_keys = [key for key in _REQUIRED_KEYS if key not in raw]
    if missing_keys:
        msg = f"{stats_path} is missing expected key(s) {missing_keys}: {raw}"
        raise MutationStatsFormatError(msg)

    killed = int(raw["killed"])
    survived = int(raw["survived"])
    evaluated = killed + survived
    score = (killed / evaluated) if evaluated > 0 else None

    return MutationScoreResult(
        killed=killed, survived=survived, evaluated=evaluated, score=score, min_score=min_score
    )


def run_mutation_score_gate(
    *, stats_path: Path, min_score: float, stream: TextIO | None = None
) -> int:
    """Returns a process exit code (0 = pass) rather than calling
    `sys.exit()` directly, so this is independently testable without
    subprocess machinery."""
    out = stream if stream is not None else sys.stdout

    try:
        result = compute_mutation_score(stats_path, min_score=min_score)
    except (MutationStatsNotFoundError, MutationStatsFormatError) as exc:
        out.write(f"mutation-score-gate: ERROR: {exc}\n")
        return 2

    if result.score is None:
        out.write("mutation-score-gate: ERROR: zero mutants evaluated (killed=0, survived=0)\n")
        return 2

    status = "PASSED" if result.passed else "FAILED"
    out.write(
        f"mutation-score-gate: {status} — score={result.score:.1%} "
        f"(killed={result.killed}, survived={result.survived}) "
        f"required >= {result.min_score:.1%}\n"
    )
    return 0 if result.passed else 1

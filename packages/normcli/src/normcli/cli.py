"""normcli — the gate/tooling CLI referenced by `.github/workflows/gate.yml`
and `docs/traceability-matrix.md`. Was an empty package (no `__main__`,
no commands at all) until the M7 follow-up self-audit — CI's
`mutation-testing` job invoking `python -m normcli mutation-score-gate`
would have crashed with `ModuleNotFoundError` the first time it actually
ran.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from normcli.mutation_gate import run_mutation_score_gate
from normcli.traceability import check_traceability

_REPO_ROOT = Path(__file__).resolve().parents[4]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="normcli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_traceability_parser = subparsers.add_parser(
        "check-traceability",
        help="Assert every Source.txt §N section header appears in docs/traceability-matrix.md",
    )
    check_traceability_parser.add_argument("--source", type=Path, default=_REPO_ROOT / "Source.txt")
    check_traceability_parser.add_argument(
        "--matrix", type=Path, default=_REPO_ROOT / "docs" / "traceability-matrix.md"
    )

    mutation_gate_parser = subparsers.add_parser(
        "mutation-score-gate",
        help="Fail if mutmut's exported CI/CD stats show a mutation score below --min-score",
    )
    mutation_gate_parser.add_argument("--min-score", type=float, required=True)
    mutation_gate_parser.add_argument(
        "--stats-file", type=Path, default=_REPO_ROOT / "mutants" / "mutmut-cicd-stats.json"
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "check-traceability":
        result = check_traceability(source_path=args.source, matrix_path=args.matrix)
        if result.is_complete:
            print(
                f"check-traceability: PASSED — all {len(result.source_section_numbers)} "
                "Source.txt sections are present in the traceability matrix"
            )
            return 0
        if result.missing_from_matrix:
            print(
                "check-traceability: FAILED — sections missing from the matrix: "
                f"{sorted(result.missing_from_matrix)}"
            )
        if result.extra_in_matrix:
            print(
                "check-traceability: FAILED — matrix references sections Source.txt "
                f"doesn't have: {sorted(result.extra_in_matrix)}"
            )
        return 1

    if args.command == "mutation-score-gate":
        return run_mutation_score_gate(stats_path=args.stats_file, min_score=args.min_score)

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())

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

    gold_parser = subparsers.add_parser(
        "gold", help="Generate or score a gold corpus (does the engine give the RIGHT answer?)"
    )
    gold_sub = gold_parser.add_subparsers(dest="gold_command", required=True)
    generate_parser = gold_sub.add_parser("generate", help="Write a seeded injector corpus (JSONL)")
    generate_parser.add_argument("--seed", type=int, default=0)
    generate_parser.add_argument("--n", type=int, default=30, help="cases per injector family")
    generate_parser.add_argument("--out", type=Path, required=True)
    score_parser = gold_sub.add_parser("score", help="Score the real engine on a JSONL/CSV corpus")
    score_parser.add_argument("path", type=Path)
    score_parser.add_argument("--semantic-type", help="for a dirty/clean CSV without a type column")

    return parser


def _run_gold(args: argparse.Namespace) -> int:
    # Imported here, not at module top: gold pulls in babel, phonenumbers and the whole engine,
    # which the other (gate) subcommands must not need.
    from normanalysis.gold import (  # noqa: PLC0415
        default_engine,
        dump_cases,
        generate_corpus,
        load_cases,
        score,
    )

    if args.gold_command == "generate":
        args.out.write_bytes(dump_cases(generate_corpus(args.seed, args.n)).encode("utf-8"))
        return 0
    try:
        cases = load_cases(args.path, semantic_type=args.semantic_type)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"gold score: cannot read {args.path}: {exc!r}", file=sys.stderr)
        return 2
    report = score(cases, default_engine)
    print(f"gold score: {len(cases)} cases from {args.path}")
    for outcome, count in report.counts.items():
        print(f"  {outcome}: {count}")
    for case, outcome, (status, value, _) in zip(
        cases, report.outcomes, report.answers, strict=True
    ):
        if outcome in {"wrong-confident", "over-abstain"}:
            print(
                f"  {outcome}: {case.semantic_type} {case.input!r} {case.context or ''} "
                f"expected {case.expected_status} {case.expected_value!r}, got {status} {value!r}"
            )
    return 0


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

    if args.command == "gold":
        return _run_gold(args)

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())

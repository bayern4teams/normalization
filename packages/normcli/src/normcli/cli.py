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

from normcli.bench_compare import run_bench_compare
from normcli.diff_cmd import run_diff_cli
from normcli.mutation_gate import run_mutation_score_gate
from normcli.run_cmd import run_normalization_cli
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

    bench_compare_parser = subparsers.add_parser(
        "bench-compare",
        help="Fail if any benchmark in --current regressed vs --baseline beyond the thresholds",
    )
    bench_compare_parser.add_argument("--current", type=Path, required=True)
    bench_compare_parser.add_argument("--baseline", type=Path, required=True)
    bench_compare_parser.add_argument("--max-throughput-regression", type=float, required=True)
    bench_compare_parser.add_argument("--max-p95-regression", type=float, required=True)

    run_parser = subparsers.add_parser(
        "run",
        help="Run a normalization profile against a source end to end, writing sidecar output",
    )
    run_parser.add_argument("--profile", required=True, help="Only 'demo' is defined today")
    run_parser.add_argument("--source", required=True, help="Only 'demo_pg' is defined today")
    run_parser.add_argument("--out", type=Path, required=True)
    run_parser.add_argument("--run-id", default="normcli-run")
    run_parser.add_argument(
        "--dsn", default=None, help="Overrides the source's resolved DSN (mainly for testing)"
    )
    run_parser.add_argument("--chunk-size", type=int, default=100_000)
    run_parser.add_argument(
        "--parallel-workers",
        type=int,
        default=0,
        help=(
            "0 (default) disables the process pool. A positive value builds a real "
            "DistinctValueWorkerPool — see normexec.parallel for what it means."
        ),
    )

    diff_parser = subparsers.add_parser(
        "diff",
        help="Compare two `normcli run` output directories for content-identical results",
    )
    diff_parser.add_argument("left_dir", type=Path)
    diff_parser.add_argument("right_dir", type=Path)
    diff_parser.add_argument("--require-identical", action="store_true")

    return parser


def _run_check_traceability(args: argparse.Namespace) -> int:
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


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "check-traceability":
        return _run_check_traceability(args)

    if args.command == "mutation-score-gate":
        return run_mutation_score_gate(stats_path=args.stats_file, min_score=args.min_score)

    if args.command == "bench-compare":
        return run_bench_compare(
            current_path=args.current,
            baseline_path=args.baseline,
            max_throughput_regression=args.max_throughput_regression,
            max_p95_regression=args.max_p95_regression,
        )

    if args.command == "run":
        return run_normalization_cli(
            profile_name=args.profile,
            source_name=args.source,
            out_dir=args.out,
            run_id=args.run_id,
            dsn=args.dsn,
            chunk_size=args.chunk_size,
            parallel_workers=args.parallel_workers,
        )

    if args.command == "diff":
        return run_diff_cli(
            left_dir=args.left_dir,
            right_dir=args.right_dir,
            require_identical=args.require_identical,
        )

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())

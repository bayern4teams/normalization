"""normcli diff — compares two `normcli run` output directories for
content-identical normalization results, the other half of the
ADR-014 byte-identical-replay determinism gate
(`.github/workflows/gate.yml`'s `determinism-replay` job:
`normcli diff ./out/run1 ./out/run2 --require-identical`).

Deliberately compares DECODED Arrow/Parquet content, never raw file
bytes — two independent, correct runs are not guaranteed to produce
byte-identical Parquet files (writer version, compression, and row-group
boundaries can differ), and `catalog.duckdb`'s own `written_at` column is
real wall-clock time by construction
(`packages/normio/src/normio/sidecar_store.py:60`), so that file can
never byte-compare equal between two runs even given identical content.
Two independent comparisons instead:

1. Every `(source_id, table, column)` partition's Parquet rows, matched
   between the two runs regardless of run_id (a partition's *directory
   name* embeds run_id — `sidecar_store.py:86-90` — but this tool doesn't
   require the two runs to share one), sorted by `source_row_key`.
   `NORMALIZED_VALUE_ARROW_SCHEMA` carries no run-identity or wall-clock
   field at the per-row level (confirmed during the 2026-08-29 R&D pass:
   the only place `TraceStep.duration_us` could introduce one is never
   actually set by any normalizer today), so every field is compared —
   no exclusion list needed for the Parquet side.
2. `run_report.json`'s fields, excluding the ones that ARE inherently
   time-varying by name: `id` (the run_id), `started_at`, `finished_at`,
   and every `metrics.*` latency/duration/throughput field (all real
   `time.perf_counter()` wall-clock — see
   `packages/normanalysis/src/normanalysis/run_recorder.py` — never
   reproducible and never claimed to be).
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

# Import order guard — MUST run before `pyarrow` is imported anywhere in
# this process, or PyICU's and PyArrow's bundled native DLLs conflict on
# Windows (segfault). See ADR-001's DLL-load-order addendum and
# run_cmd.py's identical comment — this module imports `pyarrow.parquet`
# directly, so it needs its own guard rather than relying on import order
# across normcli's other submodules.
import icu  # noqa: F401
import pyarrow.parquet as pa_parquet

_EXCLUDED_TOP_LEVEL_FIELDS = frozenset({"id", "started_at", "finished_at"})
_EXCLUDED_METRICS_FIELDS = frozenset(
    {"duration_seconds", "rows_per_second", "avg_latency_ms", "p95_latency_ms", "p99_latency_ms"}
)


class RunReportNotFoundError(FileNotFoundError):
    pass


@dataclass(frozen=True)
class DiffResult:
    parquet_mismatches: tuple[str, ...]
    report_mismatches: tuple[str, ...]
    left_only_partitions: tuple[str, ...]
    right_only_partitions: tuple[str, ...]

    @property
    def identical(self) -> bool:
        return not (
            self.parquet_mismatches
            or self.report_mismatches
            or self.left_only_partitions
            or self.right_only_partitions
        )


def _discover_partitions(parquet_root: Path) -> dict[tuple[str, str, str], list[Path]]:
    """Maps (source_id, table, column) -> sorted part files, across
    whatever run_id directory they landed under (`{source_id}/{table}/
    {column}/{run_id}/part-N.parquet`, `sidecar_store.py:86-90`) — this
    tool does not require the two runs being compared to share a run_id."""
    partitions: dict[tuple[str, str, str], list[Path]] = {}
    if not parquet_root.exists():
        return partitions
    for part_path in parquet_root.glob("*/*/*/*/part-*.parquet"):
        source_id, table, column, _run_id = part_path.parts[-5:-1]
        partitions.setdefault((source_id, table, column), []).append(part_path)
    for paths in partitions.values():
        paths.sort()
    return partitions


def _read_partition_rows(paths: list[Path]) -> list[dict[str, Any]]:
    table = pa_parquet.read_table([str(p) for p in paths])
    rows: list[dict[str, Any]] = table.to_pylist()
    return sorted(rows, key=lambda row: row["source_row_key"])


def _diff_parquet(
    left_root: Path, right_root: Path
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    left_partitions = _discover_partitions(left_root)
    right_partitions = _discover_partitions(right_root)

    left_keys = set(left_partitions)
    right_keys = set(right_partitions)
    left_only = tuple(sorted(".".join(k) for k in left_keys - right_keys))
    right_only = tuple(sorted(".".join(k) for k in right_keys - left_keys))

    mismatches: list[str] = []
    for key in sorted(left_keys & right_keys):
        left_rows = _read_partition_rows(left_partitions[key])
        right_rows = _read_partition_rows(right_partitions[key])
        partition_label = ".".join(key)
        if len(left_rows) != len(right_rows):
            mismatches.append(
                f"{partition_label}: row count differs ({len(left_rows)} vs {len(right_rows)})"
            )
            continue
        for left_row, right_row in zip(left_rows, right_rows, strict=True):
            if left_row != right_row:
                mismatches.append(
                    f"{partition_label}: row {left_row.get('source_row_key')!r} differs"
                )
    return tuple(mismatches), left_only, right_only


def _load_run_report(out_dir: Path) -> dict[str, Any]:
    report_path = out_dir / "run_report.json"
    if not report_path.exists():
        msg = f"No run_report.json under {out_dir} — was this produced by `normcli run`?"
        raise RunReportNotFoundError(msg)
    result: dict[str, Any] = json.loads(report_path.read_text(encoding="utf-8"))
    return result


def _diff_run_report(left: dict[str, Any], right: dict[str, Any]) -> tuple[str, ...]:
    mismatches: list[str] = []
    for key in sorted((set(left) | set(right)) - _EXCLUDED_TOP_LEVEL_FIELDS):
        if key == "metrics":
            left_metrics = left.get("metrics") or {}
            right_metrics = right.get("metrics") or {}
            for metrics_key in sorted(
                (set(left_metrics) | set(right_metrics)) - _EXCLUDED_METRICS_FIELDS
            ):
                if left_metrics.get(metrics_key) != right_metrics.get(metrics_key):
                    mismatches.append(
                        f"metrics.{metrics_key}: {left_metrics.get(metrics_key)!r} != "
                        f"{right_metrics.get(metrics_key)!r}"
                    )
            continue
        if left.get(key) != right.get(key):
            mismatches.append(f"{key}: {left.get(key)!r} != {right.get(key)!r}")
    return tuple(mismatches)


def diff_runs(left_dir: Path, right_dir: Path) -> DiffResult:
    parquet_mismatches, left_only, right_only = _diff_parquet(
        left_dir / "parquet", right_dir / "parquet"
    )
    left_report = _load_run_report(left_dir)
    right_report = _load_run_report(right_dir)
    report_mismatches = _diff_run_report(left_report, right_report)
    return DiffResult(
        parquet_mismatches=parquet_mismatches,
        report_mismatches=report_mismatches,
        left_only_partitions=left_only,
        right_only_partitions=right_only,
    )


def run_diff_cli(
    *, left_dir: Path, right_dir: Path, require_identical: bool, stream: TextIO | None = None
) -> int:
    out = stream if stream is not None else sys.stdout
    try:
        result = diff_runs(left_dir, right_dir)
    except RunReportNotFoundError as exc:
        out.write(f"diff: ERROR: {exc}\n")
        return 2

    for partition in result.left_only_partitions:
        out.write(f"diff: LEFT-ONLY partition {partition}\n")
    for partition in result.right_only_partitions:
        out.write(f"diff: RIGHT-ONLY partition {partition}\n")
    for mismatch in result.parquet_mismatches:
        out.write(f"diff: MISMATCH {mismatch}\n")
    for mismatch in result.report_mismatches:
        out.write(f"diff: REPORT MISMATCH {mismatch}\n")

    out.write(f"diff: {'IDENTICAL' if result.identical else 'DIFFERENT'}\n")

    if require_identical and not result.identical:
        return 1
    return 0

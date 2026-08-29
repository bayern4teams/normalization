"""Unit tests for normcli — the CLI package that was completely empty
until this M7-follow-up self-audit (found: gate.yml's mutation-testing
job calls `python -m normcli mutation-score-gate` against a module with
no commands at all; the traceability matrix separately claimed
`normcli gate --check-traceability` was "built in M1", which was false).
"""

from __future__ import annotations

import io
import json
from pathlib import Path

# Import order guard — see normcli/run_cmd.py's identical comment: MUST
# run before `pyarrow` is imported anywhere in this process, or PyICU's
# and PyArrow's bundled native DLLs conflict on Windows (segfault). This
# file imports pyarrow directly (to build synthetic sidecar rows for the
# diff_cmd tests below), so it needs its own guard.
import icu  # noqa: F401
import pyarrow as pa
import pytest
from normcli.bench_compare import (
    BenchmarkFileFormatError,
    BenchmarkFileNotFoundError,
    compare_benchmarks,
    run_bench_compare,
)
from normcli.demo_fixture import (
    DEMO_PROFILE,
    UnknownProfileError,
    UnknownSourceError,
    resolve_profile,
    resolve_source_dsn,
)
from normcli.diff_cmd import RunReportNotFoundError, diff_runs, run_diff_cli
from normcli.mutation_gate import (
    MutationStatsFormatError,
    MutationStatsNotFoundError,
    compute_mutation_score,
    run_mutation_score_gate,
)
from normcli.run_cmd import UnknownFieldRefError, _parse_field_ref
from normcli.traceability import (
    check_traceability,
    extract_matrix_section_numbers,
    extract_source_section_numbers,
)
from normio.sidecar_store import SidecarStore

from normcore import NORMALIZED_VALUE_ARROW_SCHEMA, FieldSemanticType

_REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.unit
class TestTraceabilityExtraction:
    def test_extracts_a_real_section_header(self) -> None:
        text = "58. DICTIONARY FRAMEWORK\n" + "=" * 60 + "\n"
        assert extract_source_section_numbers(text) == frozenset({58})

    def test_does_not_match_a_numbered_list_item_in_body_text(self) -> None:
        text = "1. Raw value\n2. Repaired value\nsome prose, no underline follows\n"
        assert extract_source_section_numbers(text) == frozenset()

    def test_matrix_row_with_bare_number(self) -> None:
        text = "| 58 | Dictionary framework | M1 | 2 | `normdict` | `tests/x.py` |\n"
        assert extract_matrix_section_numbers(text) == frozenset({58})

    def test_matrix_row_with_sub_range_annotation(self) -> None:
        text = "| 4 (4.1-4.8) | Mandatory research phase | M0 | 1 | - | docs/x |\n"
        assert extract_matrix_section_numbers(text) == frozenset({4})

    def test_real_repo_files_are_fully_cross_referenced(self) -> None:
        """The real check, against the real files in this repo — not a
        fixture. Source.txt has exactly 138 sections (§0-§137)."""
        result = check_traceability(
            source_path=_REPO_ROOT / "Source.txt",
            matrix_path=_REPO_ROOT / "docs" / "traceability-matrix.md",
        )
        assert result.source_section_numbers == frozenset(range(138))
        assert result.is_complete, (
            f"missing={sorted(result.missing_from_matrix)} extra={sorted(result.extra_in_matrix)}"
        )


@pytest.mark.unit
class TestMutationScoreComputation:
    def test_computes_score_from_a_real_shaped_stats_file(self, tmp_path: Path) -> None:
        stats_path = tmp_path / "mutmut-cicd-stats.json"
        stats_path.write_text(json.dumps({"killed": 90, "survived": 10}), encoding="utf-8")

        result = compute_mutation_score(stats_path, min_score=0.75)
        assert result.score == pytest.approx(0.9)
        assert result.passed is True

    def test_below_threshold_fails(self, tmp_path: Path) -> None:
        stats_path = tmp_path / "mutmut-cicd-stats.json"
        stats_path.write_text(json.dumps({"killed": 50, "survived": 50}), encoding="utf-8")

        result = compute_mutation_score(stats_path, min_score=0.75)
        assert result.score == pytest.approx(0.5)
        assert result.passed is False

    def test_missing_file_raises_a_clear_error(self, tmp_path: Path) -> None:
        with pytest.raises(MutationStatsNotFoundError):
            compute_mutation_score(tmp_path / "does-not-exist.json", min_score=0.75)

    def test_malformed_json_raises_a_clear_error(self, tmp_path: Path) -> None:
        stats_path = tmp_path / "mutmut-cicd-stats.json"
        stats_path.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(MutationStatsFormatError):
            compute_mutation_score(stats_path, min_score=0.75)

    def test_missing_required_keys_raises_a_clear_error(self, tmp_path: Path) -> None:
        stats_path = tmp_path / "mutmut-cicd-stats.json"
        stats_path.write_text(json.dumps({"total": 100}), encoding="utf-8")
        with pytest.raises(MutationStatsFormatError):
            compute_mutation_score(stats_path, min_score=0.75)

    def test_zero_evaluated_mutants_gives_no_score_not_a_false_pass(self, tmp_path: Path) -> None:
        stats_path = tmp_path / "mutmut-cicd-stats.json"
        stats_path.write_text(json.dumps({"killed": 0, "survived": 0}), encoding="utf-8")

        result = compute_mutation_score(stats_path, min_score=0.0)
        assert result.score is None
        assert result.passed is False


@pytest.mark.unit
class TestRunMutationScoreGateExitCodes:
    def test_pass_returns_zero(self, tmp_path: Path) -> None:
        stats_path = tmp_path / "stats.json"
        stats_path.write_text(json.dumps({"killed": 90, "survived": 10}), encoding="utf-8")
        buffer = io.StringIO()
        assert run_mutation_score_gate(stats_path=stats_path, min_score=0.75, stream=buffer) == 0
        assert "PASSED" in buffer.getvalue()

    def test_fail_returns_one(self, tmp_path: Path) -> None:
        stats_path = tmp_path / "stats.json"
        stats_path.write_text(json.dumps({"killed": 10, "survived": 90}), encoding="utf-8")
        buffer = io.StringIO()
        assert run_mutation_score_gate(stats_path=stats_path, min_score=0.75, stream=buffer) == 1
        assert "FAILED" in buffer.getvalue()

    def test_missing_stats_file_returns_two(self, tmp_path: Path) -> None:
        buffer = io.StringIO()
        exit_code = run_mutation_score_gate(
            stats_path=tmp_path / "nope.json", min_score=0.75, stream=buffer
        )
        assert exit_code == 2
        assert "ERROR" in buffer.getvalue()


def _bench_json(entries: dict[str, dict[str, float | list[float]]]) -> dict[str, object]:
    """Builds a minimal but real-shaped pytest-benchmark `--benchmark-json`
    document: only the fields `bench_compare.py` actually reads
    (`fullname`, `stats.ops`, `stats.data`), matching the real schema
    verified by running `pytest --benchmark-json` against this repo's own
    benchmarks during the 2026-08-29 throughput R&D pass."""
    return {
        "benchmarks": [
            {"fullname": fullname, "name": fullname, "stats": stats}
            for fullname, stats in entries.items()
        ]
    }


@pytest.mark.unit
class TestBenchCompare:
    def test_no_regression_passes(self, tmp_path: Path) -> None:
        baseline_path = tmp_path / "baseline.json"
        current_path = tmp_path / "current.json"
        baseline_path.write_text(
            json.dumps(_bench_json({"t::a": {"ops": 1000.0, "data": [0.001] * 10}})),
            encoding="utf-8",
        )
        current_path.write_text(
            json.dumps(_bench_json({"t::a": {"ops": 1000.0, "data": [0.001] * 10}})),
            encoding="utf-8",
        )

        result = compare_benchmarks(
            current_path=current_path,
            baseline_path=baseline_path,
            max_throughput_regression=0.10,
            max_p95_regression=0.15,
        )
        assert result.passed is True
        assert len(result.comparisons) == 1
        assert result.comparisons[0].throughput_regression == pytest.approx(0.0)

    def test_throughput_regression_beyond_threshold_fails(self, tmp_path: Path) -> None:
        baseline_path = tmp_path / "baseline.json"
        current_path = tmp_path / "current.json"
        baseline_path.write_text(
            json.dumps(_bench_json({"t::a": {"ops": 1000.0, "data": [0.001] * 10}})),
            encoding="utf-8",
        )
        # 20% slower — beyond the 10% limit.
        current_path.write_text(
            json.dumps(_bench_json({"t::a": {"ops": 800.0, "data": [0.00125] * 10}})),
            encoding="utf-8",
        )

        result = compare_benchmarks(
            current_path=current_path,
            baseline_path=baseline_path,
            max_throughput_regression=0.10,
            max_p95_regression=0.15,
        )
        assert result.passed is False
        assert result.comparisons[0].throughput_regression == pytest.approx(0.2)

    def test_p95_regression_beyond_threshold_fails(self, tmp_path: Path) -> None:
        baseline_path = tmp_path / "baseline.json"
        current_path = tmp_path / "current.json"
        baseline_data = [0.001] * 19 + [0.002]  # p95 (rank 19 of 20) == 0.001
        baseline_path.write_text(
            json.dumps(_bench_json({"t::a": {"ops": 1000.0, "data": baseline_data}})),
            encoding="utf-8",
        )
        # Same throughput, but the whole distribution shifted up 30% — p95
        # clearly regresses beyond the 15% limit even though ops didn't move.
        shifted_data = [d * 1.3 for d in baseline_data]
        current_path.write_text(
            json.dumps(_bench_json({"t::a": {"ops": 1000.0, "data": shifted_data}})),
            encoding="utf-8",
        )

        result = compare_benchmarks(
            current_path=current_path,
            baseline_path=baseline_path,
            max_throughput_regression=0.10,
            max_p95_regression=0.15,
        )
        assert result.passed is False
        assert result.comparisons[0].p95_regression == pytest.approx(0.3, abs=1e-6)

    def test_benchmark_only_in_current_is_reported_not_failed(self, tmp_path: Path) -> None:
        baseline_path = tmp_path / "baseline.json"
        current_path = tmp_path / "current.json"
        baseline_path.write_text(json.dumps(_bench_json({})), encoding="utf-8")
        current_path.write_text(
            json.dumps(_bench_json({"t::new": {"ops": 500.0, "data": [0.002] * 5}})),
            encoding="utf-8",
        )

        result = compare_benchmarks(
            current_path=current_path,
            baseline_path=baseline_path,
            max_throughput_regression=0.10,
            max_p95_regression=0.15,
        )
        assert result.passed is True  # nothing to compare, so nothing can fail
        assert result.new_in_current == ("t::new",)

    def test_benchmark_only_in_baseline_is_reported_not_failed(self, tmp_path: Path) -> None:
        baseline_path = tmp_path / "baseline.json"
        current_path = tmp_path / "current.json"
        baseline_path.write_text(
            json.dumps(_bench_json({"t::removed": {"ops": 500.0, "data": [0.002] * 5}})),
            encoding="utf-8",
        )
        current_path.write_text(json.dumps(_bench_json({})), encoding="utf-8")

        result = compare_benchmarks(
            current_path=current_path,
            baseline_path=baseline_path,
            max_throughput_regression=0.10,
            max_p95_regression=0.15,
        )
        assert result.passed is True
        assert result.missing_from_current == ("t::removed",)

    def test_missing_file_raises_a_clear_error(self, tmp_path: Path) -> None:
        with pytest.raises(BenchmarkFileNotFoundError):
            compare_benchmarks(
                current_path=tmp_path / "does-not-exist.json",
                baseline_path=tmp_path / "also-missing.json",
                max_throughput_regression=0.10,
                max_p95_regression=0.15,
            )

    def test_malformed_json_raises_a_clear_error(self, tmp_path: Path) -> None:
        current_path = tmp_path / "current.json"
        baseline_path = tmp_path / "baseline.json"
        current_path.write_text("{not valid json", encoding="utf-8")
        baseline_path.write_text(json.dumps(_bench_json({})), encoding="utf-8")
        with pytest.raises(BenchmarkFileFormatError):
            compare_benchmarks(
                current_path=current_path,
                baseline_path=baseline_path,
                max_throughput_regression=0.10,
                max_p95_regression=0.15,
            )

    def test_missing_benchmarks_key_raises_a_clear_error(self, tmp_path: Path) -> None:
        current_path = tmp_path / "current.json"
        baseline_path = tmp_path / "baseline.json"
        current_path.write_text(json.dumps({"not_benchmarks": []}), encoding="utf-8")
        baseline_path.write_text(json.dumps(_bench_json({})), encoding="utf-8")
        with pytest.raises(BenchmarkFileFormatError):
            compare_benchmarks(
                current_path=current_path,
                baseline_path=baseline_path,
                max_throughput_regression=0.10,
                max_p95_regression=0.15,
            )


@pytest.mark.unit
class TestRunBenchCompareExitCodes:
    def test_pass_returns_zero(self, tmp_path: Path) -> None:
        baseline_path = tmp_path / "baseline.json"
        current_path = tmp_path / "current.json"
        baseline_path.write_text(
            json.dumps(_bench_json({"t::a": {"ops": 1000.0, "data": [0.001] * 10}})),
            encoding="utf-8",
        )
        current_path.write_text(
            json.dumps(_bench_json({"t::a": {"ops": 1000.0, "data": [0.001] * 10}})),
            encoding="utf-8",
        )
        buffer = io.StringIO()
        exit_code = run_bench_compare(
            current_path=current_path,
            baseline_path=baseline_path,
            max_throughput_regression=0.10,
            max_p95_regression=0.15,
            stream=buffer,
        )
        assert exit_code == 0
        assert "PASSED" in buffer.getvalue()

    def test_regression_returns_one(self, tmp_path: Path) -> None:
        baseline_path = tmp_path / "baseline.json"
        current_path = tmp_path / "current.json"
        baseline_path.write_text(
            json.dumps(_bench_json({"t::a": {"ops": 1000.0, "data": [0.001] * 10}})),
            encoding="utf-8",
        )
        current_path.write_text(
            json.dumps(_bench_json({"t::a": {"ops": 500.0, "data": [0.002] * 10}})),
            encoding="utf-8",
        )
        buffer = io.StringIO()
        exit_code = run_bench_compare(
            current_path=current_path,
            baseline_path=baseline_path,
            max_throughput_regression=0.10,
            max_p95_regression=0.15,
            stream=buffer,
        )
        assert exit_code == 1
        assert "FAILED" in buffer.getvalue()
        assert "REGRESSION" in buffer.getvalue()

    def test_missing_file_returns_two(self, tmp_path: Path) -> None:
        buffer = io.StringIO()
        exit_code = run_bench_compare(
            current_path=tmp_path / "nope.json",
            baseline_path=tmp_path / "also-nope.json",
            max_throughput_regression=0.10,
            max_p95_regression=0.15,
            stream=buffer,
        )
        assert exit_code == 2
        assert "ERROR" in buffer.getvalue()


@pytest.mark.unit
class TestParseFieldRef:
    def test_parses_three_part_ref(self) -> None:
        assert _parse_field_ref("demo_pg.customers.first_name") == (
            "demo_pg",
            "customers",
            "first_name",
        )

    def test_malformed_ref_raises(self) -> None:
        with pytest.raises(UnknownFieldRefError):
            _parse_field_ref("not.enough")

    def test_too_many_parts_raises(self) -> None:
        with pytest.raises(UnknownFieldRefError):
            _parse_field_ref("a.b.c.d")


@pytest.mark.unit
class TestDemoFixture:
    def test_resolve_profile_returns_demo_profile(self) -> None:
        assert resolve_profile("demo") is DEMO_PROFILE
        assert len(DEMO_PROFILE.field_configs) == 3

    def test_resolve_unknown_profile_raises(self) -> None:
        with pytest.raises(UnknownProfileError):
            resolve_profile("nope")

    def test_resolve_source_dsn_for_demo_pg_matches_compose_yaml(self) -> None:
        """5434 / source_demo — must match compose.yaml's demo-postgres
        service (port 5434, POSTGRES_DB=source_demo) or this resolves to
        a database that doesn't exist."""
        dsn = resolve_source_dsn("demo_pg")
        assert "5434" in dsn
        assert "source_demo" in dsn

    def test_resolve_unknown_source_raises(self) -> None:
        with pytest.raises(UnknownSourceError):
            resolve_source_dsn("nope")

    def test_resolve_profile_returns_origin1_companies_profile(self) -> None:
        profile = resolve_profile("origin1-companies")
        assert len(profile.field_configs) == 2
        semantic_types = {fc.semantic_type for fc in profile.field_configs}
        assert semantic_types == {FieldSemanticType.COMPANY_NAME, FieldSemanticType.PERSON_NAME}

    def test_resolve_source_dsn_for_origin1_pg(self) -> None:
        dsn = resolve_source_dsn("origin1_pg")
        assert "55201" in dsn
        assert "testorigin1" in dsn

    def test_demo_and_origin1_pg_are_both_still_resolvable(self) -> None:
        """Adding the second named pair (Phase 3 item 4) must not have
        broken resolution of the original pair."""
        assert resolve_profile("demo") is DEMO_PROFILE
        assert resolve_source_dsn("demo_pg")
        assert resolve_profile("origin1-companies") is not None
        assert resolve_source_dsn("origin1_pg")


def _fake_arrow_row(*, source_row_key: str, display: str) -> dict[str, object]:
    """A row matching `NORMALIZED_VALUE_ARROW_SCHEMA` plus the
    `source_row_key` column `stream.py`'s real sidecar rows carry —
    hand-built rather than going through a real `NormalizedValue` +
    `normalize_value_to_arrow_row`, since these tests exercise
    `diff_cmd.py`'s comparison logic against known content, not the
    normalizers themselves."""
    return {
        "source_row_key": source_row_key,
        "original": display,
        "original_kind": None,
        "repaired": display,
        "display": display,
        "comparison": display.lower(),
        "search": display.lower(),
        "ascii": display,
        "structured_json": None,
        "validation_status": "VALID",
        "normalization_status": "UNCHANGED",
        "confidence": 1.0,
        "flags": [],
        "warnings": [],
        "errors": [],
        "trace_json": "[]",
        "lossiness": "LOSSLESS",
        "profile_version": "v1",
        "env_id": "e" * 64,
        "semantic_type": "FREE_TEXT",
        "context_hash": "c" * 16,
    }


def _write_fake_run(
    out_dir: Path,
    *,
    display: str,
    run_id: str = "run",
    started_at: str = "2026-01-01T00:00:00Z",
    finished_at: str = "2026-01-01T00:00:01Z",
    duration_seconds: float = 1.0,
) -> Path:
    """Writes a real sidecar Parquet partition + a run_report.json, in
    the exact shape `run_cmd.py` produces, without needing a live
    Postgres — for testing `diff_cmd.py`'s comparison logic in
    isolation. The live end-to-end path (both commands, against a real
    demo-postgres) is covered separately by
    tests/integration/test_normcli_run_diff.py."""
    out_dir.mkdir(parents=True, exist_ok=True)
    schema = pa.schema(
        [pa.field("source_row_key", pa.large_string()), *NORMALIZED_VALUE_ARROW_SCHEMA]
    )
    table = pa.Table.from_pylist(
        [_fake_arrow_row(source_row_key="1", display=display)], schema=schema
    )
    with SidecarStore(out_dir / "parquet", out_dir / "catalog.duckdb") as sidecar:
        sidecar.write_batch(
            source_id="demo_pg",
            table="customers",
            column="first_name",
            run_id=run_id,
            batch=table.to_batches()[0],
            part_index=0,
        )
    report = {
        "id": run_id,
        "profile_id": "demo",
        "profile_version": "v1",
        "env_id": "e" * 64,
        "source_snapshot": "demo_pg",
        "started_at": started_at,
        "finished_at": finished_at,
        "status": "COMPLETED",
        "failure_reason": None,
        "metrics": {
            "records_processed": 1,
            "duration_seconds": duration_seconds,
            "rows_per_second": 1.0 / duration_seconds,
            "avg_latency_ms": 1.0,
            "p95_latency_ms": 1.0,
            "p99_latency_ms": 1.0,
        },
    }
    (out_dir / "run_report.json").write_text(json.dumps(report), encoding="utf-8")
    return out_dir


@pytest.mark.unit
class TestDiffCmd:
    def test_identical_content_is_identical_despite_different_run_id_and_timing(
        self, tmp_path: Path
    ) -> None:
        """The whole point of excluding run_id/timestamps/latency from
        the comparison — two runs with genuinely identical normalization
        output but different run_id/wall-clock timing must still report
        IDENTICAL, or the gate would never pass twice in a row."""
        _write_fake_run(tmp_path / "run1", display="John")
        _write_fake_run(
            tmp_path / "run2",
            display="John",
            run_id="a-totally-different-run-id",
            started_at="2026-02-02T00:00:00Z",
            finished_at="2026-02-02T00:00:05Z",
            duration_seconds=5.0,
        )
        result = diff_runs(tmp_path / "run1", tmp_path / "run2")
        assert result.identical is True
        assert result.parquet_mismatches == ()
        assert result.report_mismatches == ()

    def test_parquet_content_mismatch_is_detected(self, tmp_path: Path) -> None:
        _write_fake_run(tmp_path / "run1", display="John")
        _write_fake_run(tmp_path / "run2", display="Jane")
        result = diff_runs(tmp_path / "run1", tmp_path / "run2")
        assert result.identical is False
        assert len(result.parquet_mismatches) == 1

    def test_report_field_mismatch_outside_excluded_set_is_detected(self, tmp_path: Path) -> None:
        _write_fake_run(tmp_path / "run1", display="John")
        run2 = _write_fake_run(tmp_path / "run2", display="John")
        # Corrupt a non-excluded field directly (profile_version isn't
        # inherently time-varying, unlike started_at/duration_seconds).
        report_path = run2 / "run_report.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["profile_version"] = "v2-mismatched"
        report_path.write_text(json.dumps(report), encoding="utf-8")

        result = diff_runs(tmp_path / "run1", tmp_path / "run2")
        assert result.identical is False
        assert any("profile_version" in m for m in result.report_mismatches)

    def test_partition_only_on_one_side_is_reported(self, tmp_path: Path) -> None:
        run1 = _write_fake_run(tmp_path / "run1", display="John")
        run2 = _write_fake_run(tmp_path / "run2", display="John", run_id="other")
        # Add a second, distinct partition only to run1.
        with SidecarStore(run1 / "parquet", run1 / "catalog.duckdb") as sidecar:
            schema = pa.schema(
                [pa.field("source_row_key", pa.large_string()), *NORMALIZED_VALUE_ARROW_SCHEMA]
            )
            table = pa.Table.from_pylist(
                [_fake_arrow_row(source_row_key="1", display="Smith")], schema=schema
            )
            sidecar.write_batch(
                source_id="demo_pg",
                table="customers",
                column="last_name",
                run_id="run",
                batch=table.to_batches()[0],
                part_index=0,
            )

        result = diff_runs(run1, run2)
        assert result.identical is False
        assert result.left_only_partitions == ("demo_pg.customers.last_name",)
        assert result.right_only_partitions == ()

    def test_missing_run_report_raises(self, tmp_path: Path) -> None:
        _write_fake_run(tmp_path / "run1", display="John")
        (tmp_path / "run2").mkdir()
        with pytest.raises(RunReportNotFoundError):
            diff_runs(tmp_path / "run1", tmp_path / "run2")


@pytest.mark.unit
class TestRunDiffCliExitCodes:
    def test_identical_returns_zero(self, tmp_path: Path) -> None:
        _write_fake_run(tmp_path / "run1", display="John")
        _write_fake_run(tmp_path / "run2", display="John", run_id="other")
        buffer = io.StringIO()
        exit_code = run_diff_cli(
            left_dir=tmp_path / "run1",
            right_dir=tmp_path / "run2",
            require_identical=True,
            stream=buffer,
        )
        assert exit_code == 0
        assert "IDENTICAL" in buffer.getvalue()

    def test_different_with_require_identical_returns_one(self, tmp_path: Path) -> None:
        _write_fake_run(tmp_path / "run1", display="John")
        _write_fake_run(tmp_path / "run2", display="Jane")
        buffer = io.StringIO()
        exit_code = run_diff_cli(
            left_dir=tmp_path / "run1",
            right_dir=tmp_path / "run2",
            require_identical=True,
            stream=buffer,
        )
        assert exit_code == 1
        assert "MISMATCH" in buffer.getvalue()

    def test_different_without_require_identical_still_returns_zero(self, tmp_path: Path) -> None:
        _write_fake_run(tmp_path / "run1", display="John")
        _write_fake_run(tmp_path / "run2", display="Jane")
        buffer = io.StringIO()
        exit_code = run_diff_cli(
            left_dir=tmp_path / "run1",
            right_dir=tmp_path / "run2",
            require_identical=False,
            stream=buffer,
        )
        assert exit_code == 0

    def test_missing_report_returns_two(self, tmp_path: Path) -> None:
        _write_fake_run(tmp_path / "run1", display="John")
        (tmp_path / "run2").mkdir()
        buffer = io.StringIO()
        exit_code = run_diff_cli(
            left_dir=tmp_path / "run1",
            right_dir=tmp_path / "run2",
            require_identical=True,
            stream=buffer,
        )
        assert exit_code == 2
        assert "ERROR" in buffer.getvalue()

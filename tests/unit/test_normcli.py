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

import pytest
from normcli.mutation_gate import (
    MutationStatsFormatError,
    MutationStatsNotFoundError,
    compute_mutation_score,
    run_mutation_score_gate,
)
from normcli.traceability import (
    check_traceability,
    extract_matrix_section_numbers,
    extract_source_section_numbers,
)

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

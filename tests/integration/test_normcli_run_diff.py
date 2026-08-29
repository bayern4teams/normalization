"""Integration tests for `normcli run` / `normcli diff --require-identical`
against a REAL demo-postgres container — the exact scenario
`.github/workflows/gate.yml`'s `determinism-replay` job runs
(`normcli run --profile demo --source demo_pg --out ./out/run1`, twice,
then `normcli diff ./out/run1 ./out/run2 --require-identical`), which had
never actually executed since that job was written: neither command
existed until the 2026-08-29 throughput R&D pass (see
`packages/normcli/src/normcli/cli.py`'s history).

Requires: docker compose up -d demo-postgres (compose.yaml's
`profiles: ["integration"]` service — see tests/integration/test_readonly_connectors.py
for the same DSN default).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

# Import order guard — see normcli/run_cmd.py's identical comment: MUST
# run before `pyarrow` is imported anywhere in this process, or PyICU's
# and PyArrow's bundled native DLLs conflict on Windows (segfault). This
# file imports pyarrow directly to mutate a real output row.
import icu  # noqa: F401
import pyarrow as pa
import pyarrow.parquet as pa_parquet
import pytest
from normcli.demo_fixture import DEMO_PROFILE
from normcli.diff_cmd import diff_runs
from normcli.run_cmd import run_normalization

from normcore import FieldNormalizationConfig, FieldSemanticType, RunStatus

POSTGRES_DSN = os.environ.get(
    "TEST_PG_DSN", "postgresql://readonly_user:readonly_pass@localhost:5434/source_demo"
)


@pytest.mark.integration
class TestRunNormalizationLiveAgainstRealDemoPostgres:
    def test_two_independent_runs_are_content_identical(self, tmp_path: Path) -> None:
        """ADR-014's actual claim: same profile + same source + same
        env_id -> byte-identical (content-identical) output, proven
        across two genuinely independent `run_normalization` calls, not
        just two calls that happen to share warm in-process state."""
        result1 = run_normalization(
            profile_name="demo",
            source_name="demo_pg",
            out_dir=tmp_path / "run1",
            dsn=POSTGRES_DSN,
        )
        result2 = run_normalization(
            profile_name="demo",
            source_name="demo_pg",
            out_dir=tmp_path / "run2",
            run_id="a-different-run-id",  # deliberately different — diff must not require a match
            dsn=POSTGRES_DSN,
        )

        assert result1.run.status is RunStatus.COMPLETED
        assert result2.run.status is RunStatus.COMPLETED
        assert result1.rows_processed == 9  # 3 seeded customers x 3 profiled columns
        assert result1.rows_processed == result2.rows_processed

        diff = diff_runs(tmp_path / "run1", tmp_path / "run2")
        assert diff.identical, (
            f"parquet_mismatches={diff.parquet_mismatches} "
            f"report_mismatches={diff.report_mismatches}"
        )

    def test_a_real_content_mutation_is_detected(self, tmp_path: Path) -> None:
        """The negative case: diff must actually catch a difference, not
        just report IDENTICAL unconditionally. Mutates one real output
        row after a real run rather than hand-building two fixtures, so
        this proves the comparison against the real Parquet layout
        `run_normalization` produces."""
        run_normalization(
            profile_name="demo", source_name="demo_pg", out_dir=tmp_path / "run1", dsn=POSTGRES_DSN
        )
        run_normalization(
            profile_name="demo", source_name="demo_pg", out_dir=tmp_path / "run2", dsn=POSTGRES_DSN
        )

        part_path = next(
            (tmp_path / "run2" / "parquet").glob("*/*/first_name/*/part-000000.parquet")
        )
        table = pa_parquet.read_table(part_path)
        rows = table.to_pylist()
        rows[0]["display"] = "MUTATED-VALUE"
        pa_parquet.write_table(pa.Table.from_pylist(rows, schema=table.schema), part_path)

        diff = diff_runs(tmp_path / "run1", tmp_path / "run2")
        assert not diff.identical
        assert diff.parquet_mismatches

    def test_unknown_column_in_profile_fails_clearly(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The real "demo" profile only ever references real columns, so
        this proves the validation itself fires by substituting a
        profile shaped like DEMO_PROFILE but pointing at a column the
        live `customers` table doesn't have — a genuine live-connector
        check (`connector.list_columns`), not a hand-rolled assertion."""
        bad_profile = DEMO_PROFILE.model_copy(
            update={
                "field_configs": (
                    FieldNormalizationConfig(
                        field_ref="demo_pg.customers.not_a_real_column",
                        semantic_type=FieldSemanticType.FREE_TEXT,
                    ),
                )
            }
        )
        monkeypatch.setattr("normcli.run_cmd.resolve_profile", lambda _name: bad_profile)

        with pytest.raises(Exception, match="does not exist"):
            run_normalization(
                profile_name="demo",
                source_name="demo_pg",
                out_dir=tmp_path / "run_bad",
                dsn=POSTGRES_DSN,
            )

        # The failure is also recorded in the written report, not just
        # raised — a real reader inspecting a failed CLI run's output
        # directory needs this without re-running anything.
        report_path = tmp_path / "run_bad" / "run_report.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["status"] == "FAILED"
        assert "does not exist" in report["failure_reason"]


@pytest.mark.integration
class TestNormcliCliLiveAgainstRealDemoPostgres:
    def test_full_gate_yml_scenario_via_subprocess(self, tmp_path: Path) -> None:
        """Exercises the exact commands `.github/workflows/gate.yml`'s
        `determinism-replay` job runs, as real subprocesses (not direct
        function calls) — proves the argparse wiring in cli.py end to
        end, and proves two separate PROCESSES (not just two calls in
        one warm interpreter) produce identical output, the stronger
        claim ADR-014 actually makes."""
        env = {**os.environ, "NORM_DEMO_PG_DSN": POSTGRES_DSN}

        run1 = subprocess.run(
            [
                sys.executable,
                "-m",
                "normcli",
                "run",
                "--profile",
                "demo",
                "--source",
                "demo_pg",
                "--out",
                str(tmp_path / "run1"),
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert run1.returncode == 0, run1.stdout + run1.stderr

        run2 = subprocess.run(
            [
                sys.executable,
                "-m",
                "normcli",
                "run",
                "--profile",
                "demo",
                "--source",
                "demo_pg",
                "--out",
                str(tmp_path / "run2"),
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert run2.returncode == 0, run2.stdout + run2.stderr

        diff = subprocess.run(
            [
                sys.executable,
                "-m",
                "normcli",
                "diff",
                str(tmp_path / "run1"),
                str(tmp_path / "run2"),
                "--require-identical",
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert diff.returncode == 0, diff.stdout + diff.stderr
        assert "IDENTICAL" in diff.stdout

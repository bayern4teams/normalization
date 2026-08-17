"""The capstone M1 Gate G1 proof: a synthetic dataset flows end-to-end
(FileConnector -> DistinctValuePlanner -> PassthroughNormalizer ->
SidecarStore) through TWO SEPARATE PROCESSES (not two in-process calls —
genuinely independent Python interpreter invocations, via subprocess), and
the resulting sidecar Parquet output is byte-identical. This is
ADR-014's reproducibility guarantee, proven at the file level, not just
asserted for individual values.

Dataset size: 1,000,000 rows (Source.txt's plan explicitly calls for a
"1M-row synthetic dataset" at this gate) with bounded cardinality (1,000
distinct values), reflecting a realistic redundant column and exercising
the distinct-value-first execution path at scale.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

FIXTURE_SCRIPT = Path(__file__).parent / "fixtures" / "run_passthrough_demo.py"
N_ROWS = 1_000_000
N_DISTINCT = 1_000


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.integration
def test_1m_row_replay_is_byte_identical_across_two_processes(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    out1 = tmp_path / "out1"
    out2 = tmp_path / "out2"

    cities = [f"city_{i % N_DISTINCT}" for i in range(N_ROWS)]
    table = pa.table({"city": cities})
    pq.write_table(table, input_dir / "customers.parquet")

    for output_dir in (out1, out2):
        # Fixed, repo-local script + trusted args (not user input).
        args = [
            sys.executable,
            str(FIXTURE_SCRIPT),
            str(input_dir),
            "customers.parquet",
            str(output_dir),
        ]
        result = subprocess.run(args, capture_output=True, text=True, check=False, timeout=180)
        assert result.returncode == 0, (
            f"replay run failed for {output_dir}:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    part1 = out1 / "parquet" / "replay_demo" / "customers" / "run" / "part-000000.parquet"
    part2 = out2 / "parquet" / "replay_demo" / "customers" / "run" / "part-000000.parquet"
    assert part1.exists()
    assert part2.exists()

    hash1, hash2 = _sha256(part1), _sha256(part2)
    assert hash1 == hash2, (
        f"Two independent process runs of the SAME input+profile+env_id produced "
        f"different output bytes ({hash1} != {hash2}) — this breaks ADR-014's "
        f"reproducibility guarantee."
    )

    # Not just "the bytes match" — confirm the content is actually correct,
    # not two runs coincidentally producing the same (wrong) empty output.
    result_table = pq.read_table(part1)
    assert result_table.num_rows == N_ROWS
    distinct_displays = pa.compute.count_distinct(result_table.column("display"))
    assert distinct_displays.as_py() == N_DISTINCT

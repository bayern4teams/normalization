"""Standalone runner: reads a Parquet file via FileConnector, normalizes
one column via DistinctValuePlanner + PassthroughNormalizer with a FIXED
env_id, and writes the result to a SidecarStore. Invoked as a real
subprocess (not an in-process function call) by
tests/integration/test_byte_identical_replay.py so the two runs are
genuinely independent processes, proving ADR-014's reproducibility claim
end-to-end rather than just within a single Python session's warm state.

Usage:
    python run_passthrough_demo.py <input_parquet_dir> <input_filename> <output_dir>
"""

from __future__ import annotations

import sys
from pathlib import Path

import polars as pl
import pyarrow as pa
from normalizers.passthrough import PassthroughNormalizer
from normio.connectors.file import FileConnector
from normio.sidecar_store import SidecarStore

from normcore import (
    Dispatcher,
    FieldSemanticType,
    NormalizationContext,
    NormalizationProfile,
    NormalizerRegistry,
)
from normexec import DistinctValuePlanner

# Fixed, not recomputed per run — this is exactly what ADR-014 requires:
# same input + same profile + same env_id must produce the same output.
FIXED_ENV_ID = "f" * 64
FIXED_PROFILE = NormalizationProfile(
    id="replay-demo",
    name="replay-demo",
    version="v1",
    created_at="2026-01-01T00:00:00Z",
    updated_at="2026-01-01T00:00:00Z",
    created_by="replay-demo",
)


def main() -> int:
    input_dir, input_filename, output_dir = sys.argv[1], sys.argv[2], sys.argv[3]

    connector = FileConnector("replay_demo", input_dir)
    batches = list(connector.read_table(input_filename))
    arrow_table = pa.Table.from_batches(batches)
    df = pl.from_arrow(arrow_table)
    if not isinstance(df, pl.DataFrame):  # single-column input can return a Series
        df = df.to_frame()

    registry = NormalizerRegistry()
    registry.register(PassthroughNormalizer())
    dispatcher = Dispatcher(registry, env_id=FIXED_ENV_ID)
    planner = DistinctValuePlanner(dispatcher)

    ctx = NormalizationContext(field_name="city", semantic_type=FieldSemanticType.ADDRESS)
    struct_array = planner.normalize_column_to_arrow(
        df, "city", FieldSemanticType.ADDRESS, ctx, FIXED_PROFILE
    )
    record_batch = pa.RecordBatch.from_struct_array(struct_array)

    with SidecarStore(Path(output_dir) / "parquet", Path(output_dir) / "catalog.duckdb") as store:
        store.write_batch(
            source_id="replay_demo",
            table="customers",
            run_id="run",
            batch=record_batch,
            part_index=0,
        )

    print(f"OK: wrote {record_batch.num_rows} rows to {output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

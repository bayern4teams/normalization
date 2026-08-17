"""Spike: Polars <-> Arrow struct round-trip for distinct-value-first
execution (Source.txt §102-104; decision recorded in
docs/adr/ADR-016-performance-architecture.md).

Proves the core performance strategy actually works mechanically:
1. Extract the distinct value set from a (deliberately redundant) column.
2. "Normalize" only the distinct set (a trivial stand-in transform here —
   real normalizers land in M2+).
3. Join the small result back onto every original row via a join on the
   raw value, without ever calling the transform function on a
   non-distinct value.
4. Confirm the joined-back column is a valid Arrow StructArray, matching
   the NormalizedValue-shaped contract normcore.models defines.

Run: uv run python spikes/06_polars_arrow_distinct_value.py
"""

from __future__ import annotations

import sys

import polars as pl
import pyarrow as pa

sys.stdout.reconfigure(encoding="utf-8")


def make_redundant_dataset(n_rows: int, n_distinct: int) -> pl.DataFrame:
    """Simulates a real column: high redundancy (e.g. a `city` column)."""
    cities = [f"city_{i}" for i in range(n_distinct)]
    return pl.DataFrame(
        {"row_id": range(n_rows), "city": [cities[i % n_distinct] for i in range(n_rows)]}
    )


CALL_COUNT = 0


def fake_normalize(value: str) -> dict[str, object]:
    """Stand-in for a real Normalizer.normalize() call — counts invocations
    so we can prove the distinct-value planner actually reduces call volume.
    """
    global CALL_COUNT
    CALL_COUNT += 1
    return {
        "original": value,
        "display": value.replace("_", " ").title(),
        "comparison": value.lower(),
        "status": "NORMALIZED",
    }


def distinct_value_first_normalize(df: pl.DataFrame, column: str) -> pl.DataFrame:
    distinct_values = df.select(pl.col(column).unique()).to_series().to_list()
    print(f"  {len(df)} rows, {len(distinct_values)} distinct values in column {column!r}")

    results = {v: fake_normalize(v) for v in distinct_values}

    lookup = pl.DataFrame(
        {
            column: list(results.keys()),
            f"{column}__original": [r["original"] for r in results.values()],
            f"{column}__display": [r["display"] for r in results.values()],
            f"{column}__comparison": [r["comparison"] for r in results.values()],
            f"{column}__status": [r["status"] for r in results.values()],
        }
    )

    return df.join(lookup, on=column, how="left")


def to_arrow_struct(df: pl.DataFrame, column: str) -> pa.StructArray:
    """Reassemble the four flat lookup columns into one Arrow StructArray —
    the shape normcore.models.NormalizedValue is designed to mirror when
    written to the Parquet sidecar store (ADR-013).
    """
    arrow_table = df.select(
        [
            pl.col(f"{column}__original").alias("original"),
            pl.col(f"{column}__display").alias("display"),
            pl.col(f"{column}__comparison").alias("comparison"),
            pl.col(f"{column}__status").alias("status"),
        ]
    ).to_arrow()

    return pa.StructArray.from_arrays(
        [arrow_table.column(name).combine_chunks() for name in arrow_table.column_names],
        names=arrow_table.column_names,
    )


if __name__ == "__main__":
    n_rows, n_distinct = 100_000, 500
    print(f"=== Distinct-value-first execution: {n_rows:,} rows, {n_distinct} distinct values ===")
    df = make_redundant_dataset(n_rows, n_distinct)

    result_df = distinct_value_first_normalize(df, "city")
    print(
        f"  fake_normalize() was called {CALL_COUNT} times for {n_rows:,} rows "
        f"(reduction factor: {n_rows / CALL_COUNT:.0f}x)"
    )
    assert n_distinct == CALL_COUNT, (
        "normalize() must be called exactly once per distinct value, never per row"
    )

    struct_array = to_arrow_struct(result_df, "city")
    print(f"\n  Arrow StructArray type: {struct_array.type}")
    print(f"  length: {len(struct_array)} (== row count, joined back correctly)")
    assert len(struct_array) == n_rows

    print("\n  sample rows:")
    for i in (0, 1, n_rows - 1):
        row = struct_array[i].as_py()
        print(f"    row {i}: {row}")

    print(
        "\nConclusion: normalize() call volume is bounded by DISTINCT values, "
        "not row count — this is what makes even a network-hop normalizer "
        "(libpostal sidecar) practical at scale, and it produces a genuine "
        "Arrow StructArray matching the sidecar store's struct-column design."
    )

"""FileConnector (CSV/Parquet/Excel) and SidecarStore — no live database
needed, so these run as fast unit tests rather than integration tests.
"""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.csv as pa_csv
import pyarrow.parquet as pa_parquet
import pytest
from normio.connector import SourceConnector
from normio.connectors.file import FileConnector
from normio.sidecar_store import SidecarStore


@pytest.fixture
def sample_dir(tmp_path: Path) -> Path:
    table = pa.table(
        {
            "first_name": ["  John  ", "José", "JOHN"],
            "last_name": ["Smith", "García", "SMITH"],
        }
    )
    pa_parquet.write_table(table, tmp_path / "customers.parquet")
    pa_csv.write_csv(table, tmp_path / "customers.csv")
    return tmp_path


@pytest.mark.unit
def test_file_connector_satisfies_source_connector_protocol() -> None:
    connector = FileConnector("demo_files", ".")
    assert isinstance(connector, SourceConnector)
    # Structural proof there is no write path: the protocol itself defines
    # none, and this asserts the concrete class hasn't bolted one on.
    assert not any(name in dir(connector) for name in ("write_table", "insert", "update", "delete"))


@pytest.mark.unit
def test_file_connector_lists_and_reads_parquet(sample_dir: Path) -> None:
    connector = FileConnector("demo_files", sample_dir)
    tables = connector.list_tables()
    assert "customers.parquet" in tables
    assert "customers.csv" in tables

    batches = list(connector.read_table("customers.parquet"))
    assert sum(b.num_rows for b in batches) == 3
    assert "source_row_key" in batches[0].schema.names
    first_names = batches[0].column("first_name").to_pylist()
    assert "  John  " in first_names  # whitespace preserved, no silent trim


@pytest.mark.unit
def test_file_connector_reads_csv_with_column_selection(sample_dir: Path) -> None:
    connector = FileConnector("demo_files", sample_dir)
    batches = list(connector.read_table("customers.csv", columns=["first_name"]))
    assert "last_name" not in batches[0].schema.names
    assert "first_name" in batches[0].schema.names


@pytest.mark.unit
def test_file_connector_refuses_path_escape(sample_dir: Path) -> None:
    connector = FileConnector("demo_files", sample_dir)
    with pytest.raises(ValueError, match="outside base_dir"):
        list(connector.read_table("../../etc/passwd"))


@pytest.mark.unit
def test_file_connector_raises_on_missing_file(sample_dir: Path) -> None:
    connector = FileConnector("demo_files", sample_dir)
    with pytest.raises(FileNotFoundError):
        list(connector.read_table("does_not_exist.csv"))


@pytest.mark.unit
def test_sidecar_store_write_and_read_round_trip(tmp_path: Path) -> None:
    with SidecarStore(tmp_path / "parquet", tmp_path / "catalog.duckdb") as store:
        batch = pa.record_batch(
            {"original": ["a", "b"], "display": ["A", "B"]},
        )
        part_path = store.write_batch(
            source_id="demo_pg", table="customers", run_id="run1", batch=batch, part_index=0
        )
        assert part_path.exists()

        result = store.read_run(source_id="demo_pg", table="customers", run_id="run1")
        assert result.num_rows == 2
        assert result.column("display").to_pylist() == ["A", "B"]


@pytest.mark.unit
def test_sidecar_store_read_run_raises_for_unknown_run(tmp_path: Path) -> None:
    with (
        SidecarStore(tmp_path / "parquet", tmp_path / "catalog.duckdb") as store,
        pytest.raises(FileNotFoundError),
    ):
        store.read_run(source_id="x", table="y", run_id="does-not-exist")


@pytest.mark.unit
def test_sidecar_store_multiple_parts_concatenate(tmp_path: Path) -> None:
    with SidecarStore(tmp_path / "parquet", tmp_path / "catalog.duckdb") as store:
        for i in range(3):
            batch = pa.record_batch({"value": [i]})
            store.write_batch(source_id="s1", table="t1", run_id="run1", batch=batch, part_index=i)
        result = store.read_run(source_id="s1", table="t1", run_id="run1")
        assert result.num_rows == 3
        assert sorted(result.column("value").to_pylist()) == [0, 1, 2]


@pytest.mark.unit
def test_sidecar_store_find_run_table_returns_source_and_table(tmp_path: Path) -> None:
    with SidecarStore(tmp_path / "parquet", tmp_path / "catalog.duckdb") as store:
        batch = pa.record_batch({"value": [1]})
        store.write_batch(
            source_id="demo_pg", table="customers", run_id="run1", batch=batch, part_index=0
        )
        assert store.find_run_table("run1") == ("demo_pg", "customers")


@pytest.mark.unit
def test_sidecar_store_find_run_table_returns_none_for_unknown_run(tmp_path: Path) -> None:
    with SidecarStore(tmp_path / "parquet", tmp_path / "catalog.duckdb") as store:
        assert store.find_run_table("does-not-exist") is None

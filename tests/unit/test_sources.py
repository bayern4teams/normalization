"""SourceRegistry (Source.txt §105, M10) — no live database needed for
these: FileConnector wiring is real and local (a real CSV under
tmp_path), and config-parsing/error-path behavior needs no connector at
all. Live DB connector wiring (Postgres/MySQL/Mongo/ClickHouse) is
proven against the real demo-* containers in
tests/integration/test_run_execution_from_source.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.csv as pa_csv
import pyarrow.parquet as pa_parquet
import pytest
from normapi.sources import InvalidSourceConfigError, SourceRegistry, UnknownSourceError


@pytest.fixture
def customers_csv(tmp_path: Path) -> Path:
    source_dir = tmp_path / "files"
    source_dir.mkdir()
    table = pa.table({"first_name": ["  John  ", "José", None], "age": [30, 41, 22]})
    pa_csv.write_csv(table, source_dir / "customers.csv")
    return source_dir


@pytest.fixture
def customers_parquet(tmp_path: Path) -> Path:
    # Parquet, not CSV, for the null-preservation test below: CSV has no
    # distinct null encoding (write_csv serializes None as an empty
    # field, indistinguishable on read from a genuine empty string) —
    # Parquet's real null bitmap is what actually proves None survives.
    source_dir = tmp_path / "files"
    source_dir.mkdir()
    table = pa.table({"first_name": ["  John  ", "José", None], "age": [30, 41, 22]})
    pa_parquet.write_table(table, source_dir / "customers.parquet")
    return source_dir


@pytest.mark.unit
class TestSourceRegistryConfig:
    def test_file_source_registers_and_lists(self, customers_csv: Path) -> None:
        registry = SourceRegistry({"demo_files": {"type": "file", "base_dir": str(customers_csv)}})
        assert registry.list_source_ids() == ["demo_files"]
        assert registry.get("demo_files").list_tables() == ["customers.csv"]

    def test_empty_config_is_a_valid_empty_registry(self) -> None:
        registry = SourceRegistry({})
        assert registry.list_source_ids() == []

    def test_get_unknown_source_raises(self) -> None:
        registry = SourceRegistry({})
        with pytest.raises(UnknownSourceError):
            registry.get("nope")

    def test_unknown_connector_type_raises_at_construction(self) -> None:
        with pytest.raises(InvalidSourceConfigError, match="unknown or missing"):
            SourceRegistry({"s1": {"type": "oracle", "dsn": "x"}})

    def test_missing_type_key_raises_at_construction(self) -> None:
        with pytest.raises(InvalidSourceConfigError, match="unknown or missing"):
            SourceRegistry({"s1": {"base_dir": "x"}})

    def test_missing_required_key_for_type_raises_at_construction(self) -> None:
        with pytest.raises(InvalidSourceConfigError, match="missing required key"):
            SourceRegistry({"s1": {"type": "postgres"}})  # no 'dsn'

    def test_from_config_file_parses_real_json(self, tmp_path: Path, customers_csv: Path) -> None:
        config_path = tmp_path / "sources.json"
        config_path.write_text(
            json.dumps({"demo_files": {"type": "file", "base_dir": str(customers_csv)}}),
            encoding="utf-8",
        )
        registry = SourceRegistry.from_config_file(config_path)
        assert registry.list_source_ids() == ["demo_files"]

    def test_from_config_file_rejects_malformed_json(self, tmp_path: Path) -> None:
        config_path = tmp_path / "sources.json"
        config_path.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(InvalidSourceConfigError, match="not valid JSON"):
            SourceRegistry.from_config_file(config_path)

    def test_from_config_file_rejects_non_object_json(self, tmp_path: Path) -> None:
        config_path = tmp_path / "sources.json"
        config_path.write_text("[1, 2, 3]", encoding="utf-8")
        with pytest.raises(InvalidSourceConfigError, match="must be a JSON object"):
            SourceRegistry.from_config_file(config_path)


@pytest.mark.unit
class TestReadColumnValues:
    def test_reads_real_values_and_coerces_non_strings(self, customers_csv: Path) -> None:
        registry = SourceRegistry({"demo_files": {"type": "file", "base_dir": str(customers_csv)}})
        values = registry.read_column_values("demo_files", "customers.csv", "age", row_limit=10_000)
        assert values == ["30", "41", "22"]  # real int column, coerced to str

    def test_preserves_null_as_none_not_string(self, customers_parquet: Path) -> None:
        registry = SourceRegistry(
            {"demo_files": {"type": "file", "base_dir": str(customers_parquet)}}
        )
        values = registry.read_column_values(
            "demo_files", "customers.parquet", "first_name", row_limit=10_000
        )
        assert values == ["  John  ", "José", None]

    def test_row_limit_truncates(self, customers_csv: Path) -> None:
        registry = SourceRegistry({"demo_files": {"type": "file", "base_dir": str(customers_csv)}})
        values = registry.read_column_values("demo_files", "customers.csv", "age", row_limit=2)
        assert values == ["30", "41"]

    def test_unknown_source_id_raises(self, customers_csv: Path) -> None:
        registry = SourceRegistry({"demo_files": {"type": "file", "base_dir": str(customers_csv)}})
        with pytest.raises(UnknownSourceError):
            registry.read_column_values("nope", "customers.csv", "age", row_limit=10)

    def test_unknown_table_raises(self, customers_csv: Path) -> None:
        registry = SourceRegistry({"demo_files": {"type": "file", "base_dir": str(customers_csv)}})
        with pytest.raises(FileNotFoundError):
            registry.read_column_values("demo_files", "nope.csv", "age", row_limit=10)

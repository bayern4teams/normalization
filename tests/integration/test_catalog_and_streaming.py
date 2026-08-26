"""Live catalog introspection + keyset-paginated streaming (M14,
docs/plan/M13-M22-program-plan.md) against REAL running database
containers — see compose.yaml's demo-* services.

Companion to test_readonly_connectors.py: that file proves read/write
enforcement; this file proves the new `CatalogConnector`/
`StreamingSourceConnector` capabilities (normio.capabilities) actually
work against real catalogs, not just that they type-check.

Requires: docker compose up -d demo-postgres demo-mysql demo-clickhouse
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest
from normio.capabilities import CatalogConnector, StreamingSourceConnector
from normio.connectors import ClickHouseConnector, MySQLConnector, PostgresConnector

if TYPE_CHECKING:
    from collections.abc import Callable

    Connector = ClickHouseConnector | PostgresConnector | MySQLConnector
    MakeConnector = Callable[[], Connector]

POSTGRES_DSN = os.environ.get(
    "TEST_PG_DSN", "postgresql://readonly_user:readonly_pass@localhost:5434/source_demo"
)
MYSQL_DSN = os.environ.get(
    "TEST_MYSQL_DSN", "mysql://readonly_user:readonly_pass@localhost:3307/source_demo"
)
CLICKHOUSE_HOST = os.environ.get("TEST_CLICKHOUSE_HOST", "localhost")


def _clickhouse() -> ClickHouseConnector:
    return ClickHouseConnector(
        "demo_clickhouse",
        CLICKHOUSE_HOST,
        port=8124,
        username="readonly_user",
        password="readonly_pass",
        database="default",
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    "make_connector",
    [
        _clickhouse,
        lambda: PostgresConnector("demo_pg", POSTGRES_DSN),
        lambda: MySQLConnector("demo_mysql", MYSQL_DSN),
    ],
    ids=["clickhouse", "postgres", "mysql"],
)
class TestCatalogAndStreamingAcrossConnectors:
    def test_connector_satisfies_both_capability_protocols(
        self, make_connector: MakeConnector
    ) -> None:
        connector = make_connector()
        try:
            assert isinstance(connector, CatalogConnector)
            assert isinstance(connector, StreamingSourceConnector)
        finally:
            connector.close()

    def test_table_spec_reports_real_primary_key_and_columns(
        self, make_connector: MakeConnector
    ) -> None:
        connector = make_connector()
        try:
            spec = connector.table_spec("customers")
            assert spec.primary_key == ("id",)
            column_names = {c.name for c in spec.columns}
            assert column_names == {"id", "first_name", "last_name", "email"}
            email_column = next(c for c in spec.columns if c.name == "email")
            assert email_column.nullable is True
            id_column = next(c for c in spec.columns if c.name == "id")
            assert id_column.nullable is False
        finally:
            connector.close()

    def test_table_spec_rejects_unknown_table(self, make_connector: MakeConnector) -> None:
        connector = make_connector()
        try:
            with pytest.raises(ValueError, match="Unknown table"):
                connector.table_spec("no_such_table")
        finally:
            connector.close()

    def test_sample_rows_returns_real_seeded_data(self, make_connector: MakeConnector) -> None:
        connector = make_connector()
        try:
            table = connector.sample_rows("customers", limit=2)
            assert table.num_rows == 2
            assert "first_name" in table.schema.names
        finally:
            connector.close()

    def test_sample_values_is_distinct_and_excludes_null(
        self, make_connector: MakeConnector
    ) -> None:
        connector = make_connector()
        try:
            values = connector.sample_values("customers", "email", limit=10)
            assert None not in values
            assert len(values) == len(set(values))
            assert "john.smith@example.com" in values
        finally:
            connector.close()

    def test_read_chunk_keyset_pagination_has_no_overlap_and_uses_real_keys(
        self, make_connector: MakeConnector
    ) -> None:
        connector = make_connector()
        try:
            first = connector.read_chunk("customers", key_columns=["id"], limit=2)
            assert first is not None
            assert first.num_rows == 2
            first_keys = set(first.column("source_row_key").to_pylist())
            assert first_keys == {"1", "2"}  # real `id` values, not a positional index

            after = (first.column("id")[-1].as_py(),)
            second = connector.read_chunk("customers", key_columns=["id"], after_key=after, limit=2)
            assert second is not None
            assert second.num_rows == 1
            second_ids = set(second.column("id").to_pylist())
            first_ids = set(first.column("id").to_pylist())
            assert not (first_ids & second_ids)

            exhausted = connector.read_chunk(
                "customers",
                key_columns=["id"],
                after_key=(second.column("id")[-1].as_py(),),
                limit=2,
            )
            assert exhausted is None
        finally:
            connector.close()

    def test_read_chunk_rejects_unknown_key_column(self, make_connector: MakeConnector) -> None:
        connector = make_connector()
        try:
            with pytest.raises(ValueError, match="Unknown key columns"):
                connector.read_chunk("customers", key_columns=["not_a_real_column"])
        finally:
            connector.close()

    def test_read_table_now_uses_real_primary_key_not_a_positional_index(
        self, make_connector: MakeConnector
    ) -> None:
        connector = make_connector()
        try:
            batches = list(connector.read_table("customers"))
            keys = {key for batch in batches for key in batch.column("source_row_key").to_pylist()}
            assert keys == {"1", "2", "3"}
        finally:
            connector.close()

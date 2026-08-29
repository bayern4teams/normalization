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
import threading
from typing import TYPE_CHECKING

import pytest
from normio.capabilities import (
    CardinalitySamplingConnector,
    CatalogConnector,
    StreamingSourceConnector,
)
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
class TestCardinalitySamplingAcrossConnectors:
    """Throughput/memory program Phase 3 item 2's `CardinalitySamplingConnector`
    capability, now implemented by all three connector kinds (ClickHouse via
    `uniqExact`, Postgres/MySQL via standard `COUNT(DISTINCT ...)` on
    `SqlConnectorBase`) — proven here against real containers rather than
    the fake-connector doubles in tests/unit/test_stream_cache_policy.py."""

    def test_connector_satisfies_the_capability_protocol(
        self, make_connector: MakeConnector
    ) -> None:
        connector = make_connector()
        try:
            assert isinstance(connector, CardinalitySamplingConnector)
        finally:
            connector.close()

    def test_estimate_distinct_ratio_on_all_distinct_column(
        self, make_connector: MakeConnector
    ) -> None:
        connector = make_connector()
        try:
            # Every seeded first_name is distinct (see postgres-init/mysql-init/
            # clickhouse-init) — 3 non-null, 3 distinct.
            ratio = connector.estimate_distinct_ratio("customers", "first_name")
            assert ratio == pytest.approx(1.0)
        finally:
            connector.close()

    def test_estimate_distinct_ratio_excludes_nulls(self, make_connector: MakeConnector) -> None:
        connector = make_connector()
        try:
            # email has one NULL row (JOHN/SMITH) and 2 distinct non-null
            # values — a null-inflated denominator would report 2/3, not 1.0.
            ratio = connector.estimate_distinct_ratio("customers", "email")
            assert ratio == pytest.approx(1.0)
        finally:
            connector.close()

    def test_estimate_distinct_ratio_rejects_unknown_column(
        self, make_connector: MakeConnector
    ) -> None:
        connector = make_connector()
        try:
            with pytest.raises(ValueError, match="Unknown column"):
                connector.estimate_distinct_ratio("customers", "not_a_real_column")
        finally:
            connector.close()


@pytest.mark.integration
def test_clickhouse_connector_survives_real_concurrent_calls_from_multiple_threads() -> None:
    """M22 regression test for a real bug found via live testing: this
    project's own containerized deployment (docs/plan/M13-M22-program-
    plan.md's one-command-startup milestone). `normapi.sources.
    SourceRegistry.get_by_connection` caches ONE `ClickHouseConnector`
    per (connection_id, database) and reuses it across every subsequent
    request — including two real, genuinely concurrent HTTP requests
    (Explore's parallel `columns`/`samples` queries land on FastAPI's
    thread pool at the same time). `clickhouse_connect`'s client is not
    safe for that: a real `docker compose up` run against a real
    ClickHouse hit `ProgrammingError: Attempt to execute concurrent
    queries within the same session` — the same root cause M18 already
    found and fixed for DuckDB, applied here to `ClickHouseConnector`'s
    new `threading.Lock`. This drives the SAME connector instance from
    real threads, concurrently, many times over — flaky before the fix
    (raced within a handful of iterations in manual reproduction), always
    clean after."""
    connector = _clickhouse()
    errors: list[BaseException] = []

    def hit_it() -> None:
        try:
            connector.list_columns("customers")
            connector.sample_rows("customers", limit=3)
        except BaseException as exc:
            errors.append(exc)

    try:
        for _ in range(10):
            threads = [threading.Thread(target=hit_it) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        assert errors == []
    finally:
        connector.close()

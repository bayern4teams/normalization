"""`ClickHouseDestinationConnector` — real DDL mirroring + Arrow inserts
against a real destination ClickHouse. M19 of the M13-M22 program.

DDL mirroring rules (decision 7): every source column appears in the
destination, in the source's own order. A column with a semantic-type
mapping of `NUMERIC` gets `Nullable(Decimal(38,9))`; `DATE` gets
`Nullable(Date)`; `DATETIME` gets `Nullable(DateTime64(3))` — real typed
columns, per `normsink.typed_values`'s extraction contract. Every other
column — unmapped, or mapped to a semantic type other than those three —
keeps the source's own real type string verbatim (`ColumnSpec.type`, from
`system.columns.type`), holding either the source's untouched value
(unmapped) or the normalized string (`NormalizedValue.display`, mapped).
Same engine family as the source (`ReplacingMergeTree`) with `ORDER BY`
the same real key columns — what makes a repeated run idempotent by
construction, verified live in this milestone's own pack.

M19 callout #2 (the plan's own honest flag): "byte-identical verbatim"
copying of a ClickHouse `String` column is not literally achievable via
Arrow — ClickHouse `String` is a raw byte array with no UTF-8 guarantee,
while `normio.connectors.clickhouse.ClickHouseConnector.read_chunk`
(M14) already materializes `String` columns as Arrow `large_string`
(UTF-8-validated) when reading from the source, before this package ever
sees the data. This module inserts whatever Arrow array it is given
unchanged — it introduces no additional lossiness of its own — but the
end-to-end claim for a `String` source column is honestly
"value-identical for valid UTF-8", not byte-identical, a pre-existing
characteristic of the M14 read path this milestone does not change.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import clickhouse_connect
import pyarrow as pa

from normsink.destination import DestinationColumnSpec

if TYPE_CHECKING:
    from collections.abc import Sequence

_SIDE_TABLE_SUFFIX = "__normalization_issues"


def _quote_identifier(name: str) -> str:
    """Backtick-quotes a real catalog-derived identifier. `table`/
    `column` names in this codebase always come from a source's own real
    catalog (M14's `list_tables`/`list_columns`, or a saved column
    mapping keyed against them, M16) — never arbitrary free-text user
    input — but DDL statements have no parameter-binding form for
    identifiers the way `SELECT ... WHERE` values do, so quoting is the
    real, standard mitigation applied here regardless."""
    escaped = name.replace("`", "``")
    return f"`{escaped}`"


class ClickHouseDestinationConnector:
    def __init__(
        self, *, host: str, port: int, username: str, password: str, database: str
    ) -> None:
        self._client = clickhouse_connect.get_client(
            host=host, port=port, username=username, password=password
        )
        self._database = database

    def ensure_database(self) -> None:
        self._client.command(f"CREATE DATABASE IF NOT EXISTS {_quote_identifier(self._database)}")

    def ensure_table(
        self, table: str, *, columns: Sequence[DestinationColumnSpec], key_columns: Sequence[str]
    ) -> None:
        if not key_columns:
            msg = f"Cannot mirror table {table!r} with no real key columns to ORDER BY"
            raise ValueError(msg)
        column_defs = ", ".join(
            f"{_quote_identifier(c.name)} {c.destination_type}" for c in columns
        )
        order_by = ", ".join(_quote_identifier(k) for k in key_columns)
        self._client.command(
            f"CREATE TABLE IF NOT EXISTS "
            f"{_quote_identifier(self._database)}.{_quote_identifier(table)} "
            f"({column_defs}) ENGINE = ReplacingMergeTree ORDER BY ({order_by})"
        )

    def ensure_side_table(self, table: str) -> None:
        self._client.command(
            f"CREATE TABLE IF NOT EXISTS "
            f"{_quote_identifier(self._database)}.{_quote_identifier(table + _SIDE_TABLE_SUFFIX)} "
            "(table_name String, source_row_key String, column_name String, "
            "severity String, code String, message String, lossiness String, "
            "normalization_status String, run_id String) "
            "ENGINE = ReplacingMergeTree "
            "ORDER BY (table_name, source_row_key, column_name)"
        )

    def insert_batch(self, table: str, batch: pa.RecordBatch) -> None:
        self._client.insert_arrow(table, _as_table(batch), database=self._database)

    def insert_side_table_batch(self, table: str, batch: pa.RecordBatch) -> None:
        self._client.insert_arrow(
            table + _SIDE_TABLE_SUFFIX, _as_table(batch), database=self._database
        )

    def close(self) -> None:
        self._client.close()


def _as_table(batch: pa.RecordBatch) -> pa.Table:
    return pa.Table.from_batches([batch])


def destination_type_for(*, semantic_type_value: str | None, source_type: str) -> str:
    """`semantic_type_value` is `None` for an unmapped column. Only the
    three semantic types the plan names get a real typed column;
    everything else — unmapped, or mapped to any OTHER semantic type —
    keeps the source's own real type string verbatim."""
    if semantic_type_value == "NUMERIC":
        return "Nullable(Decimal(38,9))"
    if semantic_type_value == "DATE":
        return "Nullable(Date)"
    if semantic_type_value == "DATETIME":
        return "Nullable(DateTime64(3))"
    return source_type

"""Server-side source registry — Source.txt §105, M10.

Maps a `source_id` to a real, already-connected `SourceConnector`.
Configured from a JSON file (`NORM_SOURCES_CONFIG_PATH`), never from a
client-supplied DSN/URI/credentials in a request body: accepting
connection strings from a request would be both a credential-injection
risk and something that would end up in request logs/traces, the same
trust boundary `NORM_PG_DSN`/`NORM_SIDECAR_*` already draw for this
process's own metadata/sidecar storage (see normapi.app, M9/M9-followup).

Connectors are constructed eagerly, at registry-construction time (app
startup), not lazily on first use — a misconfigured source fails loudly
at startup rather than surfacing as a confusing 500 on whichever request
happens to touch it first.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from normio.connectors import (
    ClickHouseConnector,
    FileConnector,
    MongoConnector,
    MySQLConnector,
    PostgresConnector,
)

if TYPE_CHECKING:
    from normio.connector import SourceConnector

_CONNECTOR_TYPES = frozenset({"postgres", "mysql", "mongo", "clickhouse", "file"})


class UnknownSourceError(LookupError):
    """Raised when a request references a source_id the registry was
    never configured with — a client-facing 404, not a 500, since it's
    the caller referencing a name that doesn't exist, not a system fault.
    """


class InvalidSourceConfigError(ValueError):
    """Raised at registry-construction time for a malformed config entry
    — deliberately fails app startup rather than deferring to first use.
    """


class SourceRegistry:
    def __init__(self, config: dict[str, dict[str, Any]]) -> None:
        self._connectors: dict[str, SourceConnector] = {
            source_id: _build_connector(source_id, spec) for source_id, spec in config.items()
        }

    @classmethod
    def from_config_file(cls, path: str | Path) -> SourceRegistry:
        raw = Path(path).read_text(encoding="utf-8")
        try:
            config = json.loads(raw)
        except json.JSONDecodeError as exc:
            msg = f"Source config at {path!r} is not valid JSON: {exc}"
            raise InvalidSourceConfigError(msg) from exc
        if not isinstance(config, dict):
            msg = f"Source config at {path!r} must be a JSON object of source_id -> spec"
            raise InvalidSourceConfigError(msg)
        return cls(config)

    def get(self, source_id: str) -> SourceConnector:
        connector = self._connectors.get(source_id)
        if connector is None:
            raise UnknownSourceError(source_id)
        return connector

    def list_source_ids(self) -> list[str]:
        return sorted(self._connectors)

    def close(self) -> None:
        for connector in self._connectors.values():
            connector.close()

    def read_column_values(
        self, source_id: str, table: str, column: str, *, row_limit: int
    ) -> list[str | None]:
        """Reads up to `row_limit` values of one column from a real
        source table — the synchronous read path a run's execution uses
        (M10; a chunked/async equivalent is M11's job, not this one).
        Every value is coerced to `str` (or kept `None`) since real
        source columns can be numeric/timestamp/etc. and
        `InMemoryStore.execute_run` normalizes `str | None`, the same
        contract pasted `values` already use — the raw source value is
        never silently dropped, just stringified the same way any other
        text-ingestion boundary would."""
        connector = self.get(source_id)
        values: list[str | None] = []
        for batch in connector.read_table(table, columns=[column]):
            for value in batch.column(column).to_pylist():
                values.append(None if value is None else str(value))
                if len(values) >= row_limit:
                    return values
        return values


def _build_connector(source_id: str, spec: dict[str, Any]) -> SourceConnector:
    kind = spec.get("type")
    if kind not in _CONNECTOR_TYPES:
        msg = (
            f"Source {source_id!r}: unknown or missing 'type' {kind!r} "
            f"(expected one of {sorted(_CONNECTOR_TYPES)})"
        )
        raise InvalidSourceConfigError(msg)
    try:
        if kind == "postgres":
            return PostgresConnector(source_id, spec["dsn"])
        if kind == "mysql":
            return MySQLConnector(source_id, spec["dsn"])
        if kind == "mongo":
            return MongoConnector(source_id, spec["uri"], spec["database"])
        if kind == "file":
            return FileConnector(source_id, spec["base_dir"])
        return ClickHouseConnector(
            source_id,
            spec["host"],
            port=spec.get("port", 8123),
            username=spec["username"],
            password=spec["password"],
            database=spec["database"],
        )
    except KeyError as exc:
        msg = f"Source {source_id!r} (type={kind!r}) is missing required key {exc}"
        raise InvalidSourceConfigError(msg) from exc

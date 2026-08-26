"""Server-side source registry — Source.txt §105, M10; hybrid with
DB-configured connections as of M15 (docs/plan/M13-M22-program-plan.md).

Maps a `source_id` to a real, already-connected `SourceConnector`.
File-configured sources (`NORM_SOURCES_CONFIG_PATH`) stay eager —
constructed at registry-construction time (app startup), not lazily on
first use, so a misconfigured source fails loudly at startup rather than
surfacing as a confusing 500 on whichever request happens to touch it
first. That eager/fail-fast property is deliberately NOT extended to
DB-configured connections (M15's `POST /connections`): those are created
at runtime, long after app startup, so they build LAZILY into a bounded
pool keyed by `(connection_id, database)` on first access, with
`refresh()` dropping a connection's cached connectors after a
credential/host change (PATCH) or removal (DELETE) so the next access
rebuilds rather than reusing stale credentials.

Neither path ever accepts a client-supplied DSN/URI in a request body —
file-based sources are server-side JSON, DB-based connections resolve
through `ConnectionResolver` (Postgres + `CredentialCipher`), matching
the same trust boundary `NORM_PG_DSN`/`NORM_SIDECAR_*` already draw for
this process's own metadata/sidecar storage.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from normio.connectors import (
    ClickHouseConnector,
    FileConnector,
    MongoConnector,
    MySQLConnector,
    PostgresConnector,
)

if TYPE_CHECKING:
    from normio.connector import SourceConnector

    from normapi.connections import ConnectionResolver

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
    def __init__(
        self,
        config: dict[str, dict[str, Any]],
        *,
        connection_resolver: ConnectionResolver | None = None,
    ) -> None:
        self._connectors: dict[str, SourceConnector] = {
            source_id: _build_connector(source_id, spec) for source_id, spec in config.items()
        }
        self._connection_resolver = connection_resolver
        # Lazily-built pool for DB-configured connections, keyed by
        # (connection_id, database) — a connection's kind/host/port
        # allow reading multiple databases off one server, so the
        # database is part of the cache key, not just the connection id.
        self._connection_pool: dict[tuple[str, str], SourceConnector] = {}

    @classmethod
    def from_config_file(
        cls, path: str | Path, *, connection_resolver: ConnectionResolver | None = None
    ) -> SourceRegistry:
        raw = Path(path).read_text(encoding="utf-8")
        try:
            config = json.loads(raw)
        except json.JSONDecodeError as exc:
            msg = f"Source config at {path!r} is not valid JSON: {exc}"
            raise InvalidSourceConfigError(msg) from exc
        if not isinstance(config, dict):
            msg = f"Source config at {path!r} must be a JSON object of source_id -> spec"
            raise InvalidSourceConfigError(msg)
        return cls(config, connection_resolver=connection_resolver)

    def get(self, source_id: str) -> SourceConnector:
        connector = self._connectors.get(source_id)
        if connector is None:
            raise UnknownSourceError(source_id)
        return connector

    def list_source_ids(self) -> list[str]:
        return sorted(self._connectors)

    def get_by_connection(self, connection_id: str, database: str) -> SourceConnector:
        """Lazily builds (or returns the cached) connector for a
        DB-configured connection, targeting `database` — a connection's
        own `database` field is its *default* database, but a caller may
        target any database the same server exposes (M16's catalog
        routes let a user browse others after connecting)."""
        if self._connection_resolver is None:
            raise UnknownSourceError(connection_id)
        cache_key = (connection_id, database)
        cached = self._connection_pool.get(cache_key)
        if cached is not None:
            return cached
        resolved = self._connection_resolver.resolve(connection_id)
        connector = build_connector_from_parts(
            connection_id,
            kind=resolved.kind,
            host=resolved.host,
            port=resolved.port,
            username=resolved.username,
            password=resolved.password,
            database=database,
        )
        self._connection_pool[cache_key] = connector
        return connector

    def refresh(self, connection_id: str) -> None:
        """Drops every pooled connector for `connection_id` (any
        database), closing each first — called after a connection's
        credentials change (PATCH) or it's removed (DELETE), so the next
        access rebuilds rather than silently reusing stale credentials."""
        stale_keys = [key for key in self._connection_pool if key[0] == connection_id]
        for key in stale_keys:
            self._connection_pool.pop(key).close()

    def close(self) -> None:
        for connector in self._connectors.values():
            connector.close()
        for connector in self._connection_pool.values():
            connector.close()
        self._connection_pool.clear()

    def read_column_values(
        self,
        source_id: str,
        table: str,
        column: str,
        *,
        row_limit: int,
        database: str | None = None,
    ) -> list[str | None]:
        """Reads up to `row_limit` values of one column from a real
        source table — the synchronous read path a run's execution uses
        (M10; a chunked/async equivalent is M11's job, not this one).
        Every value is coerced to `str` (or kept `None`) since real
        source columns can be numeric/timestamp/etc. and
        `InMemoryStore.execute_run` normalizes `str | None`, the same
        contract pasted `values` already use — the raw source value is
        never silently dropped, just stringified the same way any other
        text-ingestion boundary would.

        `database` (M16): when given, `source_id` is treated as a
        connection id (M15) rather than a file-config source_id — see
        `get_by_connection`'s own docstring."""
        connector = (
            self.get_by_connection(source_id, database)
            if database is not None
            else self.get(source_id)
        )
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


def build_connector_from_parts(
    source_id: str,
    *,
    kind: str,
    host: str,
    port: int,
    username: str,
    password: str,
    database: str,
) -> SourceConnector:
    """Builds a connector from a `ConnectionRecord`'s uniform
    host/port/username/password/database shape (M15's connection
    registry) — a separate function from `_build_connector` (the
    JSON-file config path, which accepts a raw `dsn`/`uri` per source
    rather than decomposed parts) since the two configuration shapes
    genuinely differ, not a redundant duplicate."""
    if kind == "clickhouse":
        return ClickHouseConnector(
            source_id, host, port=port, username=username, password=password, database=database
        )
    # Postgres/MySQL/Mongo connectors take a DSN/URI, not decomposed
    # parts — username/password are percent-encoded before interpolation
    # so a credential containing "@", ":", "/", or "%" doesn't corrupt
    # the URL or get misparsed as a different URL component.
    user_enc = quote(username, safe="")
    pass_enc = quote(password, safe="")
    if kind == "postgres":
        return PostgresConnector(
            source_id, f"postgresql://{user_enc}:{pass_enc}@{host}:{port}/{database}"
        )
    if kind == "mysql":
        return MySQLConnector(source_id, f"mysql://{user_enc}:{pass_enc}@{host}:{port}/{database}")
    return MongoConnector(source_id, f"mongodb://{user_enc}:{pass_enc}@{host}:{port}", database)

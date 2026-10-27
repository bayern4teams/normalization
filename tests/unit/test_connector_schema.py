"""Postgres table lookups are relative to a SCHEMA.

The default one is `public`, and every lookup in `PostgresConnector` used
it implicitly. Measured on a real source that keeps all 13 of its tables in
a named schema: `list_tables()` returned `[]`, the clone job was created
with no tables, Phase 1 created nothing, and Phase 2 reported COMPLETED —
an empty database and no indication anywhere that anything was wrong.

Two things are being asserted here, and the second matters more than the
first: that a schema can be named, and that a clone of nothing FAILS.
"""

from __future__ import annotations

from typing import Any

import pytest
from normapi.clone_executor import CloneJobStateError, _require_tables

from normapi import clone_executor


class _NoTables:
    """A source whose default namespace is empty while another holds
    everything — the real shape."""

    def __init__(self, schemas: list[str] | None = None) -> None:
        self._schemas = schemas if schemas is not None else ["diffbot"]

    def list_tables(self) -> list[str]:
        return []

    def list_schemas(self) -> list[str]:
        return self._schemas


@pytest.mark.unit
class TestACloneOfNothingIsAFailure:
    def test_it_refuses_and_says_where_the_tables_are(self) -> None:
        with pytest.raises(CloneJobStateError) as exc:
            _require_tables(_NoTables(), [], {"source_database": "testdiffbot"})
        message = str(exc.value)
        assert "No tables to clone in database 'testdiffbot'" in message
        # The whole point: the error has to be actionable, not just true.
        assert "'diffbot'" in message
        assert "source_schema" in message

    def test_it_names_every_candidate_rather_than_choosing_one(self) -> None:
        """With two populated schemas, picking one would be a guess — and
        this project refuses plausible answers everywhere else."""
        with pytest.raises(CloneJobStateError) as exc:
            _require_tables(_NoTables(["diffbot", "zoominfo"]), [], {"source_database": "db"})
        assert "'diffbot'" in str(exc.value)
        assert "'zoominfo'" in str(exc.value)

    def test_an_explicitly_named_schema_that_is_empty_says_so(self) -> None:
        """No hint here: the operator already chose, so the answer is that
        their choice is empty — not a list that includes it."""
        with pytest.raises(CloneJobStateError) as exc:
            _require_tables(_NoTables(), [], {"source_database": "db", "source_schema": "public"})
        assert "schema 'public'" in str(exc.value)
        assert "source_schema" not in str(exc.value)

    def test_a_genuinely_empty_source_still_fails(self) -> None:
        """Every cause lands here — wrong database, no SELECT grants, an
        empty source — because all of them produce the same silent
        COMPLETED without this guard."""
        with pytest.raises(CloneJobStateError):
            _require_tables(_NoTables([]), [], {"source_database": "db"})

    def test_a_source_that_cannot_list_schemas_still_fails(self) -> None:
        """ClickHouse has no schemas; the guard must not depend on the
        hint being available."""

        class _Bare:
            def list_tables(self) -> list[str]:
                return []

        with pytest.raises(CloneJobStateError):
            _require_tables(_Bare(), [], {"source_database": "db"})

    def test_tables_present_is_simply_allowed(self) -> None:
        _require_tables(_NoTables(), ["company"], {"source_database": "db"})


@pytest.mark.unit
class TestTheSchemaReachesTheConnector:
    def test_build_source_connector_passes_it_through(self, monkeypatch) -> None:
        """Every lookup has to honour the schema or none of them can: with
        it applied to `list_tables` alone, a table would be discovered and
        then fail to have columns, a key, or rows."""
        seen: dict[str, Any] = {}

        class _Spy:
            def __init__(self, source_id: str, dsn: str, schema: str | None = None) -> None:
                seen["source_id"] = source_id
                seen["schema"] = schema

        monkeypatch.setattr(clone_executor, "PostgresConnector", _Spy)
        monkeypatch.setattr(clone_executor.secrets, "decrypt", lambda _: "pw")
        conn = {
            "engine": "postgres",
            "connection_id": "c1",
            "username": "u",
            "host": "127.0.0.1",
            "port": 5432,
            "encrypted_password": "x",
        }
        clone_executor.build_source_connector(conn, "db", "diffbot")
        assert seen == {"source_id": "c1", "schema": "diffbot"}

    def test_clickhouse_needs_no_schema(self, monkeypatch) -> None:
        """ClickHouse has no layer between database and table, so its
        `database` argument already is this — passing a schema to it would
        be inventing a concept the engine does not have."""
        seen: dict[str, Any] = {}

        class _Spy:
            def __init__(self, source_id: str, host: str, **kwargs: Any) -> None:
                seen.update(kwargs)

        monkeypatch.setattr(clone_executor, "ClickHouseConnector", _Spy)
        monkeypatch.setattr(clone_executor.secrets, "decrypt", lambda _: "pw")
        conn = {
            "engine": "clickhouse",
            "connection_id": "c1",
            "username": "u",
            "host": "127.0.0.1",
            "port": 8123,
            "encrypted_password": "x",
        }
        clone_executor.build_source_connector(conn, "db", "ignored")
        assert "schema" not in seen
        assert seen["database"] == "db"

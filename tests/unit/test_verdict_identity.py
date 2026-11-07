"""Reproducers for PART1 D1.3 and D1.5 (docs/archive/plans/defects/PART1_TRACEABILITY.md).

D1.3, F-VERDICT-SCOPE: a verdict's key held the saved connection id (as
`context.source`), so re-adding a connection, after a password rotation for
example, orphaned every verdict and the same ambiguity was asked again. Part 1
D1: "the same ambiguity is never asked twice".
D1.5: a ClickHouse table that starts over on resume counted its rows in the
queue's `occurrences` a second time.
Each failed on main (002eda0) before its fix.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from cryptography.fernet import Fernet
from normapi.adjudication import migrate_sources, source_identity, verdict_key
from normapi.clone_executor import _resume_point
from normapi.scaffold_profile import SCAFFOLD_PROFILE
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType
from tests.unit.test_adjudication_acceptance import DECIDE_DATE, RAW_DATE, TABLE, _Env, _rows

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

_SERVER = {"engine": "postgres", "host": "DB.example", "port": 5432, "username": "u"}
_IDENTITY = "postgres://db.example:5432/sales"


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Env:
    monkeypatch.setenv("NORM_SECRET_KEY", Fernet.generate_key().decode())
    return _Env(tmp_path)


def _job_on(connection_id: str) -> dict[str, Any]:
    return {"source_connection_id": connection_id, "source_identity": _IDENTITY}


class TestSourceIdentity:
    def test_names_the_server_and_database_never_the_credentials(self) -> None:
        conn = {**_SERVER, "username": "alice", "encrypted_password": "secret"}
        identity = source_identity(conn, "sales", None)
        assert identity == _IDENTITY
        assert "alice" not in identity
        assert "secret" not in identity

    def test_schema_is_part_of_it(self) -> None:
        assert source_identity(_SERVER, "sales", "eu") == f"{_IDENTITY}/eu"


class TestReAddedConnectionKeepsItsVerdicts:
    def test_verdict_survives_a_new_connection_id(self, env: _Env) -> None:
        batches = [_rows([{"d": RAW_DATE}])]
        env.run(batches, {"d": "DATE"}, job_extra=_job_on("conn-old"))
        assert env.post(env.key_of(RAW_DATE), DECIDE_DATE).status_code == 201

        # The same server, saved again: a new connection id.
        _, rows, _ = env.run(batches, {"d": "DATE"}, job_extra=_job_on("conn-new"))
        assert rows[0]["d"] == DECIDE_DATE
        assert len(env.queue()) == 1  # not asked a second time

    def test_another_database_is_another_source(self, env: _Env) -> None:
        batches = [_rows([{"d": RAW_DATE}])]
        env.run(batches, {"d": "DATE"}, job_extra=_job_on("c"))
        assert env.post(env.key_of(RAW_DATE), DECIDE_DATE).status_code == 201
        other = {"source_connection_id": "c", "source_identity": "postgres://db.example:5432/hr"}
        _, rows, _ = env.run(batches, {"d": "DATE"}, job_extra=other)
        assert rows[0]["d"] == RAW_DATE


class TestMigration:
    """Queue rows and verdicts stored under a connection id are re-keyed to
    the identity; the old verdict rows stay (append-only audit trail)."""

    def _legacy(self, env: _Env) -> tuple[str, str]:
        store = env.persistence
        conn_id = "conn-legacy"
        store.save_connection(
            conn_id, engine="postgres", host="DB.example", port=5432, username="u", password="p"
        )
        job = {"source_connection_id": conn_id, "source_database": "sales"}
        store.create_clone_job("old-job", job)
        ctx = NormalizationContext(
            field_name="d",
            semantic_type=FieldSemanticType.DATE,
            table=TABLE,
            source=conn_id,
            include_trace=False,
        )
        old_key = verdict_key(FieldSemanticType.DATE, RAW_DATE, ctx, SCAFFOLD_PROFILE.version)
        item = {
            "key": old_key,
            "semantic_type": "DATE",
            "context_hash": ctx.context_hash,
            "profile_version": SCAFFOLD_PROFILE.version,
            "context": ctx.model_dump_json(),
            "original": RAW_DATE,
            "detail": "{}",
            "occurrences": 3,
        }
        store.save_clone_job_and_enqueue("old-job", job, [item])
        store.add_verdict(
            {
                "key": old_key,
                "semantic_type": "DATE",
                "context_hash": ctx.context_hash,
                "profile_version": SCAFFOLD_PROFILE.version,
                "decided_value": DECIDE_DATE,
                "decided_display": DECIDE_DATE,
                "decided_by": "human:alice",
                "decided_at": "2026-10-01T00:00:00+00:00",
                "rationale": "checked",
                "confidence": None,
                "env_id": "env-0",
            }
        )
        return conn_id, old_key

    def test_legacy_rows_are_rekeyed_and_applied(self, env: _Env) -> None:
        _, old_key = self._legacy(env)
        report = migrate_sources(env.persistence)
        assert report == {"migrated": 1, "unmigrated": 0}

        (row,) = env.queue()
        assert row["key"] != old_key
        assert json.loads(row["context"])["source"] == _IDENTITY
        assert env.persistence.list_verdicts(old_key)  # the old row is kept
        assert env.persistence.list_verdicts(row["key"])[-1]["decided_value"] == DECIDE_DATE

        _, rows, _ = env.run(
            [_rows([{"d": RAW_DATE}])], {"d": "DATE"}, job_extra=_job_on("re-added")
        )
        assert rows[0]["d"] == DECIDE_DATE

    def test_running_it_twice_changes_nothing(self, env: _Env) -> None:
        self._legacy(env)
        migrate_sources(env.persistence)
        before = env.queue()
        assert migrate_sources(env.persistence) == {"migrated": 0, "unmigrated": 0}
        assert env.queue() == before

    def test_two_connection_ids_for_one_server_merge(self, env: _Env) -> None:
        """Found live: two legacy rows, one per connection id of the same
        server, re-key to the same key. One row stays, both verdicts apply."""
        self._legacy(env)
        store = env.persistence
        store.save_connection(
            "conn-again",
            engine="postgres",
            host="db.example",
            port=5432,
            username="u2",
            password="q",
        )
        job2 = {"source_connection_id": "conn-again", "source_database": "sales"}
        store.create_clone_job("old-job-2", job2)
        ctx = NormalizationContext(
            field_name="d",
            semantic_type=FieldSemanticType.DATE,
            table=TABLE,
            source="conn-again",
            include_trace=False,
        )
        key = verdict_key(FieldSemanticType.DATE, RAW_DATE, ctx, SCAFFOLD_PROFILE.version)
        store.save_clone_job_and_enqueue(
            "old-job-2",
            job2,
            [
                {
                    "key": key,
                    "semantic_type": "DATE",
                    "context_hash": ctx.context_hash,
                    "profile_version": SCAFFOLD_PROFILE.version,
                    "context": ctx.model_dump_json(),
                    "original": RAW_DATE,
                    "detail": "{}",
                    "occurrences": 2,
                }
            ],
        )
        assert migrate_sources(store) == {"migrated": 2, "unmigrated": 0}
        (row,) = env.queue()
        assert json.loads(row["context"])["source"] == _IDENTITY

    def test_a_row_whose_connection_is_gone_is_left_and_counted(self, env: _Env) -> None:
        conn_id, old_key = self._legacy(env)
        env.persistence.delete_connection(conn_id)
        assert migrate_sources(env.persistence) == {"migrated": 0, "unmigrated": 1}
        assert env.queue()[0]["key"] == old_key


class _TruncatingDest:
    def truncate_table(self, database: str, table: str) -> None:
        pass


class TestClickHouseRestartCountsOnce:
    def test_a_restarted_table_is_not_counted_twice(self, env: _Env) -> None:
        batches = [_rows([{"d": RAW_DATE}] * 5)]
        job_id, _, job = env.run(batches, {"d": "DATE"}, job_extra=_job_on("c"))
        assert env.queue()[0]["occurrences"] == 5
        # The executor restarts an unfinished ClickHouse table: here, this one.
        job["progress"]["checkpoints"][TABLE] = 4
        _resume_point(
            TABLE,
            source_engine="clickhouse",
            progress=job["progress"],
            dest=_TruncatingDest(),
            job=job,
            persistence=env.persistence,
            job_id=job_id,
        )
        env.persistence.save_clone_job(job_id, job)
        env.run(batches, {"d": "DATE"}, job_id=job_id, resume=True)
        assert env.queue()[0]["occurrences"] == 5

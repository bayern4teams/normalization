"""PostgreSQL-backed persistence for InMemoryStore — ADR-013.

Originally a write-through side channel only: InMemoryStore's in-process
dicts stayed the read path, this module just durably mirrored writes and
rehydrated once at startup. Live testing with a genuine second replica
found that design doesn't actually solve the problem it was built for —
a write on one replica was invisible to an already-running sibling until
that sibling itself restarted, and two replicas racing to version the
same profile could both get a 201 while one's write was silently
overwritten in Postgres with no error to either caller (the exact
before/after is in the audit report's §11).

Fixed by making Postgres the single source of truth whenever it's
configured, not just a durability backstop: every read in store.py
(`get_profile`, `list_profiles`, `get_run`, `list_runs`, ...) queries
Postgres directly when persistence is active, so a sibling replica's
write is visible on the very next request, not after a restart. The two
operations proven racy — profile versioning and run execution — use a
`SELECT ... FOR UPDATE` row lock (`create_version_atomic`,
`rollback_profile_atomic`) or an atomic conditional UPDATE
(`claim_run_for_execution`) so two replicas serialize on the same
Postgres row instead of computing the same "next version" independently
and clobbering each other.

Rows are stored as the same `model_dump_json()` strings the codebase
already uses for JSON persistence elsewhere (normexec.cache follows the
identical convention) rather than mapped onto a bespoke relational
schema — these are document-shaped values, not rows with independently
queried columns.

Execution rows (§ below) are the exception: a run's per-value results are
stored one row per value, not one JSON blob per run. A real 250,000-row
run OOM-killed the api container under the original one-blob-per-run
design — `[r.model_dump(...) for r in results]` built the whole run's
JSON in memory at once, on top of the live Python objects already held by
`execute_run`, right as the process's memory was already under the most
pressure it would ever be under for that run. Storing one row per value
means a write is O(chunk size) in peak memory, not O(run size), and reads
(`load_execution_rows_page`) can be paginated by SQL LIMIT/OFFSET instead
of reconstructing the whole run just to hand back a page of it.

Scope note: value-level output belongs in the Parquet/DuckDB sidecar per
ADR-013, not row-per-value Postgres text columns — this is a durability
and memory fix, not the sidecar migration, which is a materially larger
follow-up (Arrow schema export, Parquet writing, DuckDB cataloging).
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from normio.connectors._sql_base import (
    PERSISTENCE_PAGE_ROWS as _PAGE_ROWS,
)
from normio.connectors._sql_base import (
    PERSISTENCE_WRITE_CHUNK_ROWS as _WRITE_CHUNK_ROWS,
)

from normanalysis import InvariantSampleReport, InvariantViolation
from normapi import secrets
from normcore import (
    FieldSemanticType,
    NormalizationProfile,
    NormalizationRun,
    NormalizedValue,
    ProfileStatus,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

# _WRITE_CHUNK_ROWS bounds peak memory for save_execution's writes,
# load_execution's full-run reconstruction, and (DB-clone-and-normalize
# feature) save_clone_job_errors's writes — a shared constant
# (normio.connectors._sql_base) since it's used by both
# packages, not redefined here.

_SCHEMA = """
CREATE TABLE IF NOT EXISTS normalization_profiles (
    profile_id TEXT NOT NULL,
    version TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (profile_id, version)
);
CREATE TABLE IF NOT EXISTS normalization_active_versions (
    profile_id TEXT PRIMARY KEY,
    version TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS normalization_runs (
    run_id TEXT PRIMARY KEY,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS normalization_execution_meta (
    run_id TEXT PRIMARY KEY,
    field_name TEXT NOT NULL,
    semantic_type TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    invariant_report TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS normalization_execution_rows (
    run_id TEXT NOT NULL,
    row_index INTEGER NOT NULL,
    original TEXT,
    result TEXT NOT NULL,
    PRIMARY KEY (run_id, row_index)
);
DROP TABLE IF EXISTS normalization_executions;
CREATE TABLE IF NOT EXISTS normalization_connections (
    connection_id TEXT PRIMARY KEY,
    engine TEXT NOT NULL,
    host TEXT NOT NULL,
    port INTEGER NOT NULL,
    username TEXT NOT NULL,
    encrypted_password TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS normalization_clone_jobs (
    job_id TEXT PRIMARY KEY,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS normalization_clone_job_errors (
    job_id TEXT NOT NULL,
    row_index INTEGER NOT NULL,
    table_name TEXT NOT NULL,
    field TEXT NOT NULL,
    original TEXT,
    error TEXT NOT NULL,
    PRIMARY KEY (job_id, row_index, table_name, field)
);
"""
# The last statement retires the original one-blob-per-run table this
# schema replaces — safe on a table that only ever held this audit's own
# test data, never real user data (v1, first deployment).


class PgPersistence:
    """One instance per process, constructed from `NORM_PG_DSN`. All
    methods are synchronous, direct SQL — no ORM, matching normio's own
    connector style (see normio/connectors/postgres.py)."""

    def __init__(self, dsn: str) -> None:
        # postgresql+psycopg:// selects the psycopg3 driver explicitly,
        # same rationale as normio.connectors.postgres.PostgresConnector.
        normalized_dsn = dsn.replace("postgresql://", "postgresql+psycopg://", 1)
        self._engine = sa.create_engine(normalized_dsn)

    def ensure_schema(self) -> None:
        with self._engine.begin() as conn:
            for raw_statement in _SCHEMA.strip().split(";\n\n"):
                statement = raw_statement.strip()
                if statement:
                    conn.execute(sa.text(statement))

    # --- writes (called by InMemoryStore right after each in-memory mutation) ---

    def save_profile(self, profile: NormalizationProfile) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO normalization_profiles (profile_id, version, data) "
                    "VALUES (:pid, :version, :data) "
                    "ON CONFLICT (profile_id, version) DO UPDATE SET data = EXCLUDED.data"
                ),
                {"pid": profile.id, "version": profile.version, "data": profile.model_dump_json()},
            )

    def save_active_version(self, profile_id: str, version: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO normalization_active_versions (profile_id, version) "
                    "VALUES (:pid, :version) "
                    "ON CONFLICT (profile_id) DO UPDATE SET version = EXCLUDED.version"
                ),
                {"pid": profile_id, "version": version},
            )

    def save_run(self, run: NormalizationRun) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO normalization_runs (run_id, data) VALUES (:rid, :data) "
                    "ON CONFLICT (run_id) DO UPDATE SET data = EXCLUDED.data"
                ),
                {"rid": run.id, "data": run.model_dump_json()},
            )

    # --- authoritative reads (F10 fix — every read goes straight to
    # Postgres when persistence is configured, so a sibling replica's
    # write is visible on the next request instead of only after this
    # replica's own restart) ---

    def get_profile(
        self, profile_id: str, version: str | None = None
    ) -> NormalizationProfile | None:
        with self._engine.begin() as conn:
            resolved_version = version
            if resolved_version is None:
                row = conn.execute(
                    sa.text(
                        "SELECT version FROM normalization_active_versions WHERE profile_id = :pid"
                    ),
                    {"pid": profile_id},
                ).first()
                if row is None:
                    return None
                resolved_version = row[0]
            row = conn.execute(
                sa.text(
                    "SELECT data FROM normalization_profiles "
                    "WHERE profile_id = :pid AND version = :v"
                ),
                {"pid": profile_id, "v": resolved_version},
            ).first()
        return NormalizationProfile.model_validate_json(row[0]) if row is not None else None

    def list_profile_versions(self, profile_id: str) -> list[NormalizationProfile] | None:
        with self._engine.begin() as conn:
            exists = conn.execute(
                sa.text("SELECT 1 FROM normalization_active_versions WHERE profile_id = :pid"),
                {"pid": profile_id},
            ).first()
            if exists is None:
                return None
            rows = conn.execute(
                sa.text(
                    "SELECT data FROM normalization_profiles "
                    "WHERE profile_id = :pid ORDER BY version"
                ),
                {"pid": profile_id},
            ).all()
        return [NormalizationProfile.model_validate_json(r[0]) for r in rows]

    def list_profiles(self) -> list[NormalizationProfile]:
        with self._engine.begin() as conn:
            rows = conn.execute(
                sa.text(
                    "SELECT p.data FROM normalization_profiles p "
                    "JOIN normalization_active_versions a "
                    "ON a.profile_id = p.profile_id AND a.version = p.version"
                )
            ).all()
        return [NormalizationProfile.model_validate_json(r[0]) for r in rows]

    def get_run(self, run_id: str) -> NormalizationRun | None:
        with self._engine.begin() as conn:
            row = conn.execute(
                sa.text("SELECT data FROM normalization_runs WHERE run_id = :rid"), {"rid": run_id}
            ).first()
        return NormalizationRun.model_validate_json(row[0]) if row is not None else None

    def list_runs(self) -> list[NormalizationRun]:
        with self._engine.begin() as conn:
            rows = conn.execute(sa.text("SELECT data FROM normalization_runs")).all()
        return [NormalizationRun.model_validate_json(r[0]) for r in rows]

    # --- atomic writes (F9 fix — a Postgres row lock or conditional
    # UPDATE serializes two replicas racing on the same profile/run
    # instead of each computing the same "next version" independently and
    # one silently overwriting the other) ---

    def create_version_atomic(
        self,
        profile_id: str,
        build_next: Callable[[NormalizationProfile, str], NormalizationProfile],
    ) -> NormalizationProfile | None:
        """`build_next(current_profile, next_version) -> new_profile`
        supplies the field-merging logic store.py's persistence=None path
        already has (kept in one place, store.py, rather than duplicated
        here) — this method owns only the transactional mechanics: lock
        the profile's active-version pointer, so a concurrent call for
        the SAME profile_id from another replica blocks until this
        transaction commits rather than racing it. Returns None if the
        profile doesn't exist."""
        with self._engine.begin() as conn:
            row = conn.execute(
                sa.text(
                    "SELECT version FROM normalization_active_versions "
                    "WHERE profile_id = :pid FOR UPDATE"
                ),
                {"pid": profile_id},
            ).first()
            if row is None:
                return None
            current_version = row[0]
            current_data = conn.execute(
                sa.text(
                    "SELECT data FROM normalization_profiles "
                    "WHERE profile_id = :pid AND version = :v"
                ),
                {"pid": profile_id, "v": current_version},
            ).scalar_one()
            current = NormalizationProfile.model_validate_json(current_data)
            next_version = f"v{int(current_version.removeprefix('v')) + 1}"
            new_profile = build_next(current, next_version)
            deprecated = current.model_copy(update={"status": ProfileStatus.DEPRECATED})

            for profile in (deprecated, new_profile):
                conn.execute(
                    sa.text(
                        "INSERT INTO normalization_profiles (profile_id, version, data) "
                        "VALUES (:pid, :version, :data) "
                        "ON CONFLICT (profile_id, version) DO UPDATE SET data = EXCLUDED.data"
                    ),
                    {
                        "pid": profile_id,
                        "version": profile.version,
                        "data": profile.model_dump_json(),
                    },
                )
            conn.execute(
                sa.text(
                    "INSERT INTO normalization_active_versions (profile_id, version) "
                    "VALUES (:pid, :version) "
                    "ON CONFLICT (profile_id) DO UPDATE SET version = EXCLUDED.version"
                ),
                {"pid": profile_id, "version": next_version},
            )
        return new_profile

    def rollback_profile_atomic(
        self, profile_id: str, target_version: str
    ) -> NormalizationProfile | None:
        """Same locking strategy as `create_version_atomic`. Returns None
        if the profile or the target version doesn't exist — store.py
        distinguishes those cases the same way it already does for the
        persistence=None path (by message only), so one sentinel covers
        both here."""
        with self._engine.begin() as conn:
            row = conn.execute(
                sa.text(
                    "SELECT version FROM normalization_active_versions "
                    "WHERE profile_id = :pid FOR UPDATE"
                ),
                {"pid": profile_id},
            ).first()
            if row is None:
                return None
            current_version = row[0]

            target_row = conn.execute(
                sa.text(
                    "SELECT data FROM normalization_profiles "
                    "WHERE profile_id = :pid AND version = :v"
                ),
                {"pid": profile_id, "v": target_version},
            ).first()
            if target_row is None:
                return None
            target = NormalizationProfile.model_validate_json(target_row[0])

            if current_version != target_version:
                current_data = conn.execute(
                    sa.text(
                        "SELECT data FROM normalization_profiles "
                        "WHERE profile_id = :pid AND version = :v"
                    ),
                    {"pid": profile_id, "v": current_version},
                ).scalar_one()
                current = NormalizationProfile.model_validate_json(current_data)
                deprecated = current.model_copy(update={"status": ProfileStatus.DEPRECATED})
                conn.execute(
                    sa.text(
                        "UPDATE normalization_profiles SET data = :data "
                        "WHERE profile_id = :pid AND version = :v"
                    ),
                    {"data": deprecated.model_dump_json(), "pid": profile_id, "v": current_version},
                )

            reactivated = target.model_copy(update={"status": ProfileStatus.ACTIVE})
            conn.execute(
                sa.text(
                    "UPDATE normalization_profiles SET data = :data "
                    "WHERE profile_id = :pid AND version = :v"
                ),
                {"data": reactivated.model_dump_json(), "pid": profile_id, "v": target_version},
            )
            conn.execute(
                sa.text(
                    "INSERT INTO normalization_active_versions (profile_id, version) "
                    "VALUES (:pid, :version) "
                    "ON CONFLICT (profile_id) DO UPDATE SET version = EXCLUDED.version"
                ),
                {"pid": profile_id, "version": target_version},
            )
        return reactivated

    def claim_run_for_execution(self, run_id: str) -> bool:
        """Atomically transitions a run PENDING -> RUNNING and returns
        whether THIS call made the transition. False means either the
        run doesn't exist or something else (this process's earlier
        attempt, or another replica) already claimed it — the same
        silent-overwrite race as profile versioning, applied to run
        execution: without this, two replicas executing the same run_id
        concurrently would both compute full results and last-write-wins
        on save_run/save_execution. A single conditional UPDATE, not a
        lock held for the run's whole (potentially long) execution time,
        since only the PENDING->RUNNING transition itself needs to be
        atomic — once claimed, no other replica's conditional UPDATE can
        succeed against the same row."""
        with self._engine.begin() as conn:
            result = conn.execute(
                sa.text(
                    "UPDATE normalization_runs SET data = "
                    "jsonb_set(data::jsonb, '{status}', '\"RUNNING\"')::text "
                    "WHERE run_id = :rid AND (data::jsonb ->> 'status') = 'PENDING'"
                ),
                {"rid": run_id},
            )
        return result.rowcount > 0

    def save_execution(
        self,
        run_id: str,
        *,
        field_name: str,
        semantic_type: FieldSemanticType,
        originals: Sequence[str | None],
        results: Sequence[NormalizedValue],
        invariant_report: InvariantSampleReport,
    ) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO normalization_execution_meta "
                    "(run_id, field_name, semantic_type, row_count, invariant_report) "
                    "VALUES (:rid, :fn, :st, :rc, :ir) "
                    "ON CONFLICT (run_id) DO UPDATE SET "
                    "field_name = EXCLUDED.field_name, semantic_type = EXCLUDED.semantic_type, "
                    "row_count = EXCLUDED.row_count, invariant_report = EXCLUDED.invariant_report"
                ),
                {
                    "rid": run_id,
                    "fn": field_name,
                    "st": semantic_type.value,
                    "rc": len(originals),
                    "ir": json.dumps(dataclasses.asdict(invariant_report)),
                },
            )
            # A run executes at most once (RunNotExecutableError guards
            # re-execution — see store.py), but DELETE-then-insert is
            # cheap defensive idempotency against a retried save.
            conn.execute(
                sa.text("DELETE FROM normalization_execution_rows WHERE run_id = :rid"),
                {"rid": run_id},
            )

        for start in range(0, len(originals), _WRITE_CHUNK_ROWS):
            chunk = list(
                zip(
                    originals[start : start + _WRITE_CHUNK_ROWS],
                    results[start : start + _WRITE_CHUNK_ROWS],
                    strict=True,
                )
            )
            rows = [
                {"rid": run_id, "idx": start + i, "orig": original, "res": result.model_dump_json()}
                for i, (original, result) in enumerate(chunk)
            ]
            with self._engine.begin() as conn:
                conn.execute(
                    sa.text(
                        "INSERT INTO normalization_execution_rows "
                        "(run_id, row_index, original, result) VALUES (:rid, :idx, :orig, :res)"
                    ),
                    rows,
                )

    # --- startup hydration (profiles/runs only — executions load lazily, see store.py) ---

    def load_all(
        self,
    ) -> tuple[
        dict[str, dict[str, NormalizationProfile]],
        dict[str, str],
        dict[str, NormalizationRun],
    ]:
        """Raw materials for InMemoryStore.__init__ to rebuild its
        profile/run dicts from. Deliberately does NOT eagerly load every
        run's execution data — that was its own unbounded-memory risk
        (a process with many/large historical runs would reload all of
        them into memory on every restart, before serving a single
        request). Execution data loads lazily, on first access, via
        `load_execution`/`load_execution_rows_page` below."""
        with self._engine.begin() as conn:
            profile_rows = conn.execute(
                sa.text("SELECT profile_id, version, data FROM normalization_profiles")
            ).all()
            active_rows = conn.execute(
                sa.text("SELECT profile_id, version FROM normalization_active_versions")
            ).all()
            run_rows = conn.execute(sa.text("SELECT run_id, data FROM normalization_runs")).all()

        profiles: dict[str, dict[str, NormalizationProfile]] = {}
        for profile_id, version, data in profile_rows:
            profiles.setdefault(profile_id, {})[version] = NormalizationProfile.model_validate_json(
                data
            )

        active_versions: dict[str, str] = {row[0]: row[1] for row in active_rows}
        runs = {run_id: NormalizationRun.model_validate_json(data) for run_id, data in run_rows}

        return profiles, active_versions, runs

    # --- lazy execution access ---

    def load_execution_meta(self, run_id: str) -> dict[str, Any] | None:
        with self._engine.begin() as conn:
            row = conn.execute(
                sa.text(
                    "SELECT field_name, semantic_type, row_count, invariant_report "
                    "FROM normalization_execution_meta WHERE run_id = :rid"
                ),
                {"rid": run_id},
            ).first()
        if row is None:
            return None
        field_name, semantic_type, row_count, invariant_report = row
        return {
            "field_name": field_name,
            "semantic_type": semantic_type,
            "row_count": row_count,
            "invariant_report": json.loads(invariant_report),
        }

    def load_execution_rows_page(
        self, run_id: str, *, limit: int, offset: int
    ) -> list[tuple[str | None, str]]:
        """One page of (original, result_json) pairs, ordered by
        row_index — the only method the paginated GET /runs/{id}/values
        endpoint needs; it never touches the full run."""
        with self._engine.begin() as conn:
            rows = conn.execute(
                sa.text(
                    "SELECT original, result FROM normalization_execution_rows "
                    "WHERE run_id = :rid ORDER BY row_index LIMIT :limit OFFSET :offset"
                ),
                {"rid": run_id, "limit": limit, "offset": offset},
            ).all()
        return [(original, result) for original, result in rows]

    def load_execution_all_rows(self, run_id: str) -> list[tuple[str | None, str]]:
        """Every row for one run, still paginated internally in
        `_PAGE_ROWS` pages so a caller reconstructing a full
        `_RunExecution` (needed by collisions/impact/overview, which
        compute over the whole run, not a page of it) never asks
        Postgres for more than one chunk's worth at a time — bounds
        driver-side buffering the same way `save_execution`'s writes are
        bounded, even though the caller ultimately holds the full result
        in memory either way (that's this endpoint's inherent shape, not
        something a pagination fix at the storage layer can remove)."""
        rows: list[tuple[str | None, str]] = []
        offset = 0
        while True:
            page = self.load_execution_rows_page(run_id, limit=_PAGE_ROWS, offset=offset)
            if not page:
                break
            rows.extend(page)
            offset += _PAGE_ROWS
        return rows

    # --- DB-clone-and-normalize: saved connections (decisions #12, #13) ---
    # Server-level (host+port+username+password+engine) — the database is
    # picked fresh each use, not baked into the saved connection. No
    # per-user scoping (this app has no auth/session model). The password
    # is encrypted here, once, at the single write path — every read
    # returns the ciphertext; callers decrypt only at connect-time
    # (normapi.secrets), never storing the plaintext anywhere else.

    def save_connection(
        self, connection_id: str, *, engine: str, host: str, port: int, username: str, password: str
    ) -> dict[str, Any]:
        created_at = datetime.now(UTC).isoformat()
        encrypted_password = secrets.encrypt(password)
        with self._engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO normalization_connections "
                    "(connection_id, engine, host, port, username, encrypted_password, created_at) "
                    "VALUES (:cid, :engine, :host, :port, :username, :pw, :created_at)"
                ),
                {
                    "cid": connection_id,
                    "engine": engine,
                    "host": host,
                    "port": port,
                    "username": username,
                    "pw": encrypted_password,
                    "created_at": created_at,
                },
            )
        return {
            "connection_id": connection_id,
            "engine": engine,
            "host": host,
            "port": port,
            "username": username,
            "encrypted_password": encrypted_password,
            "created_at": created_at,
        }

    def get_connection(self, connection_id: str) -> dict[str, Any] | None:
        with self._engine.begin() as conn:
            row = conn.execute(
                sa.text(
                    "SELECT connection_id, engine, host, port, username, "
                    "encrypted_password, created_at "
                    "FROM normalization_connections WHERE connection_id = :cid"
                ),
                {"cid": connection_id},
            ).first()
        return _connection_row_to_dict(row) if row is not None else None

    def list_connections(self) -> list[dict[str, Any]]:
        with self._engine.begin() as conn:
            rows = conn.execute(
                sa.text(
                    "SELECT connection_id, engine, host, port, username, "
                    "encrypted_password, created_at "
                    "FROM normalization_connections ORDER BY created_at"
                )
            ).all()
        return [_connection_row_to_dict(row) for row in rows]

    def delete_connection(self, connection_id: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                sa.text("DELETE FROM normalization_connections WHERE connection_id = :cid"),
                {"cid": connection_id},
            )

    # --- DB-clone-and-normalize: clone jobs (decisions #4, #5, #10) ---
    # Same single-JSONB-status-blob shape as normalization_runs — status,
    # source/dest connection_id+database, per-table field_configs, and
    # progress counters (current table, last committed source_row_key per
    # table) all live in `data`.

    def create_clone_job(self, job_id: str, data: dict[str, Any]) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                sa.text("INSERT INTO normalization_clone_jobs (job_id, data) VALUES (:jid, :data)"),
                {"jid": job_id, "data": json.dumps(data)},
            )

    def save_clone_job(self, job_id: str, data: dict[str, Any]) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                sa.text("UPDATE normalization_clone_jobs SET data = :data WHERE job_id = :jid"),
                {"jid": job_id, "data": json.dumps(data)},
            )

    def get_clone_job(self, job_id: str) -> dict[str, Any] | None:
        with self._engine.begin() as conn:
            row = conn.execute(
                sa.text("SELECT data FROM normalization_clone_jobs WHERE job_id = :jid"),
                {"jid": job_id},
            ).first()
        return json.loads(row[0]) if row is not None else None

    def list_clone_jobs(self) -> list[dict[str, Any]]:
        with self._engine.begin() as conn:
            rows = conn.execute(sa.text("SELECT data FROM normalization_clone_jobs")).all()
        return [json.loads(r[0]) for r in rows]

    def claim_clone_job(self, job_id: str) -> bool:
        """Atomic SCHEMA_READY|RUNNING -> RUNNING transition, same
        conditional-UPDATE-with-rowcount pattern as `claim_run_for_execution`
        — RUNNING is an allowed source state too (not just SCHEMA_READY)
        so re-clicking start on an orphaned (crashed) job can resume it,
        per decision #10; the executor's own re-stream-and-skip logic is
        what makes that resume safe, not this claim."""
        with self._engine.begin() as conn:
            result = conn.execute(
                sa.text(
                    "UPDATE normalization_clone_jobs SET data = "
                    "jsonb_set(data::jsonb, '{status}', '\"RUNNING\"')::text "
                    "WHERE job_id = :jid "
                    "AND (data::jsonb ->> 'status') IN ('SCHEMA_READY', 'RUNNING')"
                ),
                {"jid": job_id},
            )
        return result.rowcount > 0

    def save_clone_job_errors(self, job_id: str, errors: Sequence[dict[str, Any]]) -> None:
        """Chunked insert, mirroring `save_execution`'s row-per-value
        writes — bounds peak memory the same way."""
        for start in range(0, len(errors), _WRITE_CHUNK_ROWS):
            chunk = errors[start : start + _WRITE_CHUNK_ROWS]
            rows = [
                {
                    "jid": job_id,
                    "idx": e["row_index"],
                    "table": e["table_name"],
                    "field": e["field"],
                    "orig": e["original"],
                    "err": e["error"],
                }
                for e in chunk
            ]
            with self._engine.begin() as conn:
                conn.execute(
                    sa.text(
                        "INSERT INTO normalization_clone_job_errors "
                        "(job_id, row_index, table_name, field, original, error) "
                        "VALUES (:jid, :idx, :table, :field, :orig, :err) "
                        "ON CONFLICT (job_id, row_index, table_name, field) DO NOTHING"
                    ),
                    rows,
                )

    def count_clone_job_errors(self, job_id: str) -> int:
        """How many report rows belong to THIS job.

        A page of results cannot answer that, and the table holds every
        job's rows: 4.3M rows from an earlier run were read as one run's
        output before anyone checked the `job_id`. The listing was always
        correctly scoped — the TOTAL simply was not available anywhere, so
        the only number a reader had was the table's.
        """
        with self._engine.begin() as conn:
            total = conn.execute(
                sa.text("SELECT count(*) FROM normalization_clone_job_errors WHERE job_id = :jid"),
                {"jid": job_id},
            ).scalar_one()
        return int(total)

    def load_clone_job_errors_page(
        self, job_id: str, *, limit: int, offset: int
    ) -> list[dict[str, Any]]:
        with self._engine.begin() as conn:
            rows = conn.execute(
                sa.text(
                    "SELECT row_index, table_name, field, original, error "
                    "FROM normalization_clone_job_errors WHERE job_id = :jid "
                    "ORDER BY table_name, row_index LIMIT :limit OFFSET :offset"
                ),
                {"jid": job_id, "limit": limit, "offset": offset},
            ).all()
        return [
            {
                "row_index": row_index,
                "table_name": table_name,
                "field": field,
                "original": original,
                "error": error,
            }
            for row_index, table_name, field, original, error in rows
        ]


def _connection_row_to_dict(row: sa.Row[Any]) -> dict[str, Any]:
    connection_id, engine, host, port, username, encrypted_password, created_at = row
    return {
        "connection_id": connection_id,
        "engine": engine,
        "host": host,
        "port": port,
        "username": username,
        "encrypted_password": encrypted_password,
        "created_at": created_at,
    }


def rehydrate_invariant_report(raw: dict[str, Any]) -> InvariantSampleReport:
    violations = tuple(InvariantViolation(**v) for v in raw["violations"])
    return InvariantSampleReport(sampled=raw["sampled"], violations=violations)

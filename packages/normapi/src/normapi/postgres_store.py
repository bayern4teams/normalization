"""Postgres-backed metadata persistence — Source.txt §105-§107,
docs/adr/ADR-013-normalization-storage.md.

ADR-013: "Metadata (profiles, runs, dictionaries, collisions, impact
reports, sign-off records) lives in PostgreSQL — relational,
transactional, well-suited to versioned/audited entities, distinct from
the bulk columnar normalized-value data." This module covers profiles,
run *records* (the `NormalizationRun` itself: status, metrics,
timestamps), and — since M11 — collision *decisions* (a human
reviewer's real accept/reject/whitelist disposition on a collision
group, §92): all lightweight relational metadata that was, until M9,
lost on every process restart along with everything else in
`InMemoryStore`.

Deliberately NOT covered here: a run's bulk per-value execution results
(every row's real `NormalizedValue` — `_RunExecution.originals`/
`.results`). ADR-013 assigns that data to a *separate* component — the
Arrow/Parquet sidecar store (`normio.SidecarStore`, built in M1) — not
Postgres. Wiring that in is real, separate, still-open work (see M9's
verification pack); after a restart, PAST runs' status/metrics remain
correctly queryable, but their detailed per-value results do not,
exactly as disclosed there. This is a genuine, deliberate scope
boundary, not an oversight.

Each row stores its owning pydantic model as one JSONB blob (`data`),
mirroring `normexec.cache.NormalizationCache`'s own `value_json` column
— a schema migration is never needed just because `NormalizationProfile`
or `NormalizationRun` gains a field, consistent with how this project
already treats its other JSON-shaped persistent storage.
"""

from __future__ import annotations

import psycopg
from psycopg.types.json import Jsonb

from normanalysis import CollisionDecision
from normcore import NormalizationProfile, NormalizationRun


class PostgresMetadataStore:
    """One Postgres connection, opened once at app startup and reused —
    matching `NormalizationCache`'s one-connection-per-process model.
    Uses `autocommit=True` (each statement is its own transaction): every
    operation here is a single, self-contained `INSERT`/`SELECT`/`UPDATE`,
    so there is no multi-statement transaction to wrap.
    """

    def __init__(self, dsn: str) -> None:
        self._conn = psycopg.connect(dsn, autocommit=True)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS profiles ("
                "  id VARCHAR NOT NULL,"
                "  version VARCHAR NOT NULL,"
                "  data JSONB NOT NULL,"
                "  PRIMARY KEY (id, version)"
                ")"
            )
            cur.execute(
                "CREATE TABLE IF NOT EXISTS profile_active_version ("
                "  profile_id VARCHAR PRIMARY KEY,"
                "  active_version VARCHAR NOT NULL"
                ")"
            )
            cur.execute(
                "CREATE TABLE IF NOT EXISTS runs ("
                "  id VARCHAR PRIMARY KEY,"
                "  profile_id VARCHAR NOT NULL,"
                "  data JSONB NOT NULL"
                ")"
            )
            cur.execute(
                "CREATE TABLE IF NOT EXISTS collision_decisions ("
                "  run_id VARCHAR NOT NULL,"
                "  normalized_value VARCHAR NOT NULL,"
                "  data JSONB NOT NULL,"
                "  PRIMARY KEY (run_id, normalized_value)"
                ")"
            )

    # --- profiles ---------------------------------------------------

    def save_profile(self, profile: NormalizationProfile) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO profiles (id, version, data) VALUES (%s, %s, %s) "
                "ON CONFLICT (id, version) DO UPDATE SET data = EXCLUDED.data",
                (profile.id, profile.version, Jsonb(profile.model_dump(mode="json"))),
            )

    def get_profile(self, profile_id: str, version: str) -> NormalizationProfile | None:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT data FROM profiles WHERE id = %s AND version = %s",
                (profile_id, version),
            )
            row = cur.fetchone()
        return NormalizationProfile.model_validate(row[0]) if row else None

    def list_profile_versions(self, profile_id: str) -> list[NormalizationProfile]:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT data FROM profiles WHERE id = %s ORDER BY version",
                (profile_id,),
            )
            rows = cur.fetchall()
        return [NormalizationProfile.model_validate(row[0]) for row in rows]

    def profile_exists(self, profile_id: str) -> bool:
        with self._conn.cursor() as cur:
            cur.execute("SELECT 1 FROM profiles WHERE id = %s LIMIT 1", (profile_id,))
            return cur.fetchone() is not None

    def list_all_profiles(self) -> list[NormalizationProfile]:
        """Every version of every profile — the real hydration source at
        startup, so a profile version with no runs against it (or an
        older, non-active, non-run-referenced version) is never silently
        missing after a restart."""
        with self._conn.cursor() as cur:
            cur.execute("SELECT data FROM profiles")
            rows = cur.fetchall()
        return [NormalizationProfile.model_validate(row[0]) for row in rows]

    def list_all_active_versions(self) -> dict[str, str]:
        with self._conn.cursor() as cur:
            cur.execute("SELECT profile_id, active_version FROM profile_active_version")
            rows = cur.fetchall()
        return dict(rows)

    def set_active_version(self, profile_id: str, version: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO profile_active_version (profile_id, active_version) "
                "VALUES (%s, %s) "
                "ON CONFLICT (profile_id) DO UPDATE SET active_version = EXCLUDED.active_version",
                (profile_id, version),
            )

    def get_active_version(self, profile_id: str) -> str | None:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT active_version FROM profile_active_version WHERE profile_id = %s",
                (profile_id,),
            )
            row = cur.fetchone()
        return row[0] if row else None

    def list_active_profiles(self) -> list[NormalizationProfile]:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT p.data FROM profiles p "
                "JOIN profile_active_version v "
                "  ON v.profile_id = p.id AND v.active_version = p.version"
            )
            rows = cur.fetchall()
        return [NormalizationProfile.model_validate(row[0]) for row in rows]

    # --- runs ---------------------------------------------------------

    def save_run(self, run: NormalizationRun) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO runs (id, profile_id, data) VALUES (%s, %s, %s) "
                "ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data",
                (run.id, run.profile_id, Jsonb(run.model_dump(mode="json"))),
            )

    def get_run(self, run_id: str) -> NormalizationRun | None:
        with self._conn.cursor() as cur:
            cur.execute("SELECT data FROM runs WHERE id = %s", (run_id,))
            row = cur.fetchone()
        return NormalizationRun.model_validate(row[0]) if row else None

    def list_runs(self) -> list[NormalizationRun]:
        with self._conn.cursor() as cur:
            cur.execute("SELECT data FROM runs")
            rows = cur.fetchall()
        return [NormalizationRun.model_validate(row[0]) for row in rows]

    # --- collision decisions (§92, M11) --------------------------------

    def save_collision_decision(self, decision: CollisionDecision) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO collision_decisions (run_id, normalized_value, data) "
                "VALUES (%s, %s, %s) "
                "ON CONFLICT (run_id, normalized_value) DO UPDATE SET data = EXCLUDED.data",
                (
                    decision.run_id,
                    decision.normalized_value,
                    Jsonb(decision.model_dump(mode="json")),
                ),
            )

    def list_collision_decisions(self, run_id: str) -> list[CollisionDecision]:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT data FROM collision_decisions WHERE run_id = %s",
                (run_id,),
            )
            rows = cur.fetchall()
        return [CollisionDecision.model_validate(row[0]) for row in rows]

    def list_all_collision_decisions(self) -> list[CollisionDecision]:
        """Every decision ever recorded, across every run — the startup
        hydration source, mirroring `list_runs()`'s own "load everything,
        nothing silently missing after a restart" approach."""
        with self._conn.cursor() as cur:
            cur.execute("SELECT data FROM collision_decisions")
            rows = cur.fetchall()
        return [CollisionDecision.model_validate(row[0]) for row in rows]

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> PostgresMetadataStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

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

from dataclasses import dataclass

import psycopg
from psycopg.types.json import Jsonb

from normanalysis import CollisionDecision
from normapi.connections import ConnectionRecord
from normapi.mappings import ColumnMapping
from normapi.migrations import Migration, run_migrations
from normcore import NormalizationProfile, NormalizationRun


@dataclass(frozen=True, slots=True)
class RunColumnStatus:
    """M17 — one row of `run_columns`: a single (table, column)'s own
    status within a multi-column run."""

    run_id: str
    table_name: str
    column_name: str
    semantic_type: str
    status: str
    rows_processed: int
    failure_reason: str | None


@dataclass(frozen=True, slots=True)
class ChunkProgressRow:
    """M17 — one row of `run_chunks`: real resumability state."""

    run_id: str
    table_name: str
    column_name: str
    chunk_index: int
    last_key: tuple[object, ...]
    rows_processed: int


def _create_connections_table(conn: psycopg.Connection) -> None:
    """M15: the first table to go through the real migration runner
    instead of a bare `CREATE TABLE IF NOT EXISTS` — see migrations.py's
    docstring for why that matters starting now (six more tables land
    across M15-M20)."""
    with conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS connections ("
            "  id VARCHAR PRIMARY KEY,"
            "  alias VARCHAR NOT NULL,"
            "  kind VARCHAR NOT NULL,"
            "  host VARCHAR NOT NULL,"
            "  port INTEGER NOT NULL,"
            "  username VARCHAR NOT NULL,"
            "  encrypted_password TEXT NOT NULL,"
            "  database VARCHAR NOT NULL,"
            "  identity VARCHAR NOT NULL,"
            "  created_at TIMESTAMPTZ NOT NULL,"
            "  updated_at TIMESTAMPTZ NOT NULL"
            ")"
        )
        cur.execute("CREATE INDEX IF NOT EXISTS connections_identity_idx ON connections (identity)")


def _create_column_mappings_table(conn: psycopg.Connection) -> None:
    """M16: keyed by real connection identity, never a connection's own
    `id`/alias (decision 4) — deliberately no foreign key to
    `connections.id`, so a mapping survives that connection row being
    deleted and a new one created under a different alias for the same
    real database."""
    with conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS column_mappings ("
            "  connection_identity VARCHAR NOT NULL,"
            "  database VARCHAR NOT NULL,"
            "  table_name VARCHAR NOT NULL,"
            "  column_name VARCHAR NOT NULL,"
            "  semantic_type VARCHAR NOT NULL,"
            "  semantic_source VARCHAR NOT NULL,"
            "  enabled BOOLEAN NOT NULL,"
            "  updated_at TIMESTAMPTZ NOT NULL,"
            "  updated_by VARCHAR NOT NULL,"
            "  PRIMARY KEY (connection_identity, database, table_name, column_name)"
            ")"
        )


def _create_run_columns_table(conn: psycopg.Connection) -> None:
    """M17: per-(table, column) status within a multi-column run — a
    run's own top-level `status` (COMPLETED/FAILED/PARTIAL) can't
    represent "Person.firstName finished, Company.name failed" on its
    own; this table is what makes that real and queryable, and what a
    resume pass reads to know which columns still need work."""
    with conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS run_columns ("
            "  run_id VARCHAR NOT NULL,"
            "  table_name VARCHAR NOT NULL,"
            "  column_name VARCHAR NOT NULL,"
            "  semantic_type VARCHAR NOT NULL,"
            "  status VARCHAR NOT NULL,"
            "  rows_processed BIGINT NOT NULL DEFAULT 0,"
            "  failure_reason TEXT,"
            "  PRIMARY KEY (run_id, table_name, column_name)"
            ")"
        )


def _create_run_chunks_table(conn: psycopg.Connection) -> None:
    """M17: one row per committed chunk — `last_key` is JSON-encoded
    (a tuple of real primary-key values, positionally matching the
    connector's own key_columns, per M14 — never a positional index) so
    it round-trips through a JSONB column regardless of the key's real
    type (string, int, composite). A resume reads the MAX(chunk_index)
    row for a (run_id, table, column) to get the real last committed
    key, not the whole history — the history itself is real observability
    data, not overhead worth avoiding."""
    with conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS run_chunks ("
            "  run_id VARCHAR NOT NULL,"
            "  table_name VARCHAR NOT NULL,"
            "  column_name VARCHAR NOT NULL,"
            "  chunk_index INTEGER NOT NULL,"
            "  last_key JSONB NOT NULL,"
            "  rows_processed BIGINT NOT NULL,"
            "  committed_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
            "  PRIMARY KEY (run_id, table_name, column_name, chunk_index)"
            ")"
        )


_MIGRATIONS = [
    Migration(name="m15_create_connections", apply=_create_connections_table),
    Migration(name="m16_create_column_mappings", apply=_create_column_mappings_table),
    Migration(name="m17_create_run_columns", apply=_create_run_columns_table),
    Migration(name="m17_create_run_chunks", apply=_create_run_chunks_table),
]

_SELECT_CONNECTION_COLUMNS = (
    "SELECT id, alias, kind, host, port, username, encrypted_password, "
    "database, identity, created_at, updated_at FROM connections"
)

_SELECT_MAPPING_COLUMNS = (
    "SELECT connection_identity, database, table_name, column_name, semantic_type, "
    "semantic_source, enabled, updated_at, updated_by FROM column_mappings"
)


def _row_to_connection_record(row: tuple[object, ...]) -> ConnectionRecord:
    (
        id_,
        alias,
        kind,
        host,
        port,
        username,
        encrypted_password,
        database,
        identity,
        created_at,
        updated_at,
    ) = row
    return ConnectionRecord(
        id=id_,
        alias=alias,
        kind=kind,
        host=host,
        port=port,
        username=username,
        encrypted_password=encrypted_password,
        database=database,
        identity=identity,
        created_at=created_at.isoformat() if hasattr(created_at, "isoformat") else created_at,
        updated_at=updated_at.isoformat() if hasattr(updated_at, "isoformat") else updated_at,
    )


def _row_to_mapping(row: tuple[object, ...]) -> ColumnMapping:
    (
        connection_identity,
        database,
        table_name,
        column_name,
        semantic_type,
        semantic_source,
        enabled,
        updated_at,
        updated_by,
    ) = row
    return ColumnMapping(
        connection_identity=connection_identity,
        database=database,
        table_name=table_name,
        column_name=column_name,
        semantic_type=semantic_type,
        semantic_source=semantic_source,
        enabled=enabled,
        updated_at=updated_at.isoformat() if hasattr(updated_at, "isoformat") else updated_at,
        updated_by=updated_by,
    )


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
        run_migrations(self._conn, _MIGRATIONS)

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

    # --- connections (§105-adjacent, M15) ------------------------------

    def save_connection(self, record: ConnectionRecord) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO connections "
                "  (id, alias, kind, host, port, username, encrypted_password, "
                "   database, identity, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (id) DO UPDATE SET "
                "  alias = EXCLUDED.alias, kind = EXCLUDED.kind, host = EXCLUDED.host, "
                "  port = EXCLUDED.port, username = EXCLUDED.username, "
                "  encrypted_password = EXCLUDED.encrypted_password, "
                "  database = EXCLUDED.database, identity = EXCLUDED.identity, "
                "  updated_at = EXCLUDED.updated_at",
                (
                    record.id,
                    record.alias,
                    record.kind,
                    record.host,
                    record.port,
                    record.username,
                    record.encrypted_password,
                    record.database,
                    record.identity,
                    record.created_at,
                    record.updated_at,
                ),
            )

    def get_connection(self, connection_id: str) -> ConnectionRecord | None:
        with self._conn.cursor() as cur:
            cur.execute(_SELECT_CONNECTION_COLUMNS + " WHERE id = %s", (connection_id,))
            row = cur.fetchone()
        return _row_to_connection_record(row) if row else None

    def list_connections(self) -> list[ConnectionRecord]:
        with self._conn.cursor() as cur:
            cur.execute(_SELECT_CONNECTION_COLUMNS + " ORDER BY created_at")
            rows = cur.fetchall()
        return [_row_to_connection_record(row) for row in rows]

    def any_connection_exists(self) -> bool:
        """Used at startup to decide whether NORM_SECRET_KEY being unset
        is fatal (real connection rows exist, encrypted against a key
        this process no longer has) or merely means the feature is
        unused so far."""
        with self._conn.cursor() as cur:
            cur.execute("SELECT 1 FROM connections LIMIT 1")
            return cur.fetchone() is not None

    def delete_connection(self, connection_id: str) -> bool:
        with self._conn.cursor() as cur:
            cur.execute("DELETE FROM connections WHERE id = %s", (connection_id,))
            return cur.rowcount > 0

    # --- column mappings (M16) ------------------------------------------

    def save_mapping(self, mapping: ColumnMapping) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO column_mappings "
                "  (connection_identity, database, table_name, column_name, "
                "   semantic_type, semantic_source, enabled, updated_at, updated_by) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (connection_identity, database, table_name, column_name) "
                "DO UPDATE SET "
                "  semantic_type = EXCLUDED.semantic_type, "
                "  semantic_source = EXCLUDED.semantic_source, "
                "  enabled = EXCLUDED.enabled, "
                "  updated_at = EXCLUDED.updated_at, "
                "  updated_by = EXCLUDED.updated_by",
                (
                    mapping.connection_identity,
                    mapping.database,
                    mapping.table_name,
                    mapping.column_name,
                    mapping.semantic_type.value,
                    mapping.semantic_source.value,
                    mapping.enabled,
                    mapping.updated_at,
                    mapping.updated_by,
                ),
            )

    def get_mapping(
        self, connection_identity: str, database: str, table_name: str, column_name: str
    ) -> ColumnMapping | None:
        with self._conn.cursor() as cur:
            cur.execute(
                _SELECT_MAPPING_COLUMNS + " WHERE connection_identity = %s AND database = %s "
                "AND table_name = %s AND column_name = %s",
                (connection_identity, database, table_name, column_name),
            )
            row = cur.fetchone()
        return _row_to_mapping(row) if row else None

    def list_mappings_for_table(
        self, connection_identity: str, database: str, table_name: str
    ) -> list[ColumnMapping]:
        with self._conn.cursor() as cur:
            cur.execute(
                _SELECT_MAPPING_COLUMNS + " WHERE connection_identity = %s AND database = %s "
                "AND table_name = %s ORDER BY column_name",
                (connection_identity, database, table_name),
            )
            rows = cur.fetchall()
        return [_row_to_mapping(row) for row in rows]

    # --- run columns + chunk resumability (M17) -------------------------

    def upsert_run_column(
        self,
        *,
        run_id: str,
        table_name: str,
        column_name: str,
        semantic_type: str,
        status: str,
        rows_processed: int = 0,
        failure_reason: str | None = None,
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO run_columns "
                "  (run_id, table_name, column_name, semantic_type, status, "
                "   rows_processed, failure_reason) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (run_id, table_name, column_name) DO UPDATE SET "
                "  status = EXCLUDED.status, rows_processed = EXCLUDED.rows_processed, "
                "  failure_reason = EXCLUDED.failure_reason",
                (
                    run_id,
                    table_name,
                    column_name,
                    semantic_type,
                    status,
                    rows_processed,
                    failure_reason,
                ),
            )

    def list_run_columns(self, run_id: str) -> list[RunColumnStatus]:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT run_id, table_name, column_name, semantic_type, status, "
                "rows_processed, failure_reason FROM run_columns WHERE run_id = %s "
                "ORDER BY table_name, column_name",
                (run_id,),
            )
            rows = cur.fetchall()
        return [RunColumnStatus(*row) for row in rows]

    def record_chunk(
        self,
        *,
        run_id: str,
        table_name: str,
        column_name: str,
        chunk_index: int,
        last_key: tuple[object, ...],
        rows_processed: int,
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO run_chunks "
                "  (run_id, table_name, column_name, chunk_index, last_key, rows_processed) "
                "VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (run_id, table_name, column_name, chunk_index) DO NOTHING",
                (
                    run_id,
                    table_name,
                    column_name,
                    chunk_index,
                    Jsonb(list(last_key)),
                    rows_processed,
                ),
            )

    def get_last_chunk(
        self, *, run_id: str, table_name: str, column_name: str
    ) -> ChunkProgressRow | None:
        """The real resume point for a (run_id, table, column) — the
        highest `chunk_index` committed so far, or `None` if this column
        never started (a fresh run, not a resume)."""
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT run_id, table_name, column_name, chunk_index, last_key, rows_processed "
                "FROM run_chunks WHERE run_id = %s AND table_name = %s AND column_name = %s "
                "ORDER BY chunk_index DESC LIMIT 1",
                (run_id, table_name, column_name),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return ChunkProgressRow(
            run_id=row[0],
            table_name=row[1],
            column_name=row[2],
            chunk_index=row[3],
            last_key=tuple(row[4]),
            rows_processed=row[5],
        )

    def list_running_run_ids(self) -> list[str]:
        """The real "was left RUNNING at boot" check a startup
        reconciliation pass needs — reads the `runs` table's own `data`
        JSONB blob rather than a separate status column, since `status`
        already lives there (no schema change needed for this)."""
        with self._conn.cursor() as cur:
            cur.execute("SELECT id FROM runs WHERE data->>'status' = 'RUNNING'")
            rows = cur.fetchall()
        return [row[0] for row in rows]

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> PostgresMetadataStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

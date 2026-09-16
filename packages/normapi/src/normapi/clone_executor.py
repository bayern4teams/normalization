"""DB-clone-and-normalize feature — Phase 1 (schema clone) and Phase 2
(stream + normalize + populate) execution.

Phase 1 (`verify_and_create_schema`) runs synchronously from the route
handler — one DDL statement per table, fast even for many tables. Phase 2
(`start_phase2`) runs on a daemon `threading.Thread`, same process, same
`app.state`-held dispatcher/cache — see the corner-cut comment at the
actual `threading.Thread(...)` call site below for the reasoning (no
task-queue dependency exists in this codebase, and none is justified for
2 engines / one deployment).

Normalization reuses `DistinctValuePlanner.distinct_value_results`
directly (not `normalize_column_to_arrow`) — the same distinct-value-first
call `InMemoryStore._normalize_deduped` already makes for real runs. The
Arrow-native `normalize_column_to_arrow` shortcut only carries display/
comparison/search/ascii/normalization_status/confidence (see
`normexec.planner._JOIN_COLUMNS`); it drops each value's `.errors` list,
which decision #9 ("completely give full detail report") needs verbatim
in `normalization_clone_job_errors.error` — `distinct_value_results`
returns full `NormalizedValue` objects, so this path keeps the detail
that method would silently lose, for the identical dispatcher-call cost
(one call per distinct value either way).
"""

from __future__ import annotations

import threading
import uuid
from typing import TYPE_CHECKING, Any

from normio.connectors import (
    ClickHouseConnector,
    ClickHouseDestination,
    PostgresConnector,
    PostgresDestination,
)
from normio.connectors._sql_base import ROW_CHUNK_SIZE

from normapi import secrets
from normapi.scaffold_profile import SCAFFOLD_PROFILE
from normcore import CloneJobStatus, ErrorPolicy, FieldSemanticType, NormalizationContext
from normexec.planner import DistinctValuePlanner

if TYPE_CHECKING:
    from normexec.cache import NormalizationCache

    from normapi.pg_persistence import PgPersistence
    from normcore import Dispatcher


class CloneJobNotFoundError(LookupError):
    pass


class CloneJobStateError(RuntimeError):
    """Raised when an action is attempted against a clone job that isn't in
    the state it requires — e.g. verify-database on a job that already
    passed Phase 1, or (decision #6) on a job whose destination database
    the user hasn't run `CREATE DATABASE` for yet. Routes.py maps every
    case to the same 409, so this is one exception, not one per case."""


def create_database_sql(database: str) -> str:
    """Decision #6's one-line f-string — not a method, not a class. Valid
    verbatim DDL text on both Postgres and ClickHouse."""
    return f"CREATE DATABASE {database};"


def bootstrap_database(engine: str) -> str:
    """The database used only to *open* a connection for list_databases()
    (decision #1) — before the user has picked a real database, some
    always-present database is needed just to connect. Never written to,
    never returned to the caller."""
    return "postgres" if engine == "postgres" else "default"


def build_source_connector(conn: dict, database: str) -> PostgresConnector | ClickHouseConnector:
    password = secrets.decrypt(conn["encrypted_password"])
    if conn["engine"] == "postgres":
        dsn = f"postgresql://{conn['username']}:{password}@{conn['host']}:{conn['port']}/{database}"
        return PostgresConnector(conn["connection_id"], dsn)
    if conn["engine"] == "clickhouse":
        return ClickHouseConnector(
            conn["connection_id"],
            conn["host"],
            port=conn["port"],
            username=conn["username"],
            password=password,
            database=database,
        )
    msg = f"Unsupported engine: {conn['engine']!r}"
    raise ValueError(msg)


def build_destination_writer(conn: dict) -> PostgresDestination | ClickHouseDestination:
    # ponytail: a two-branch if/else, not a DestinationConnector Protocol
    # — this is the only call site that ever touches destination writers,
    # and it already knows the engine from the saved connection. Add a
    # Protocol only when a 3rd engine (MySQL) makes this a three-way
    # branch.
    password = secrets.decrypt(conn["encrypted_password"])
    if conn["engine"] == "postgres":
        return PostgresDestination(conn["host"], conn["port"], conn["username"], password)
    if conn["engine"] == "clickhouse":
        return ClickHouseDestination(conn["host"], conn["port"], conn["username"], password)
    msg = f"Unsupported engine: {conn['engine']!r}"
    raise ValueError(msg)


def create_clone_job(persistence: PgPersistence, *, request: dict) -> dict:
    """Creates the job PENDING_DB_CREATE (decision #6). `request.tables`
    is captured NOW, at creation — every table in the chosen origin
    database is cloned automatically (decision #3), so the job's table
    list is a snapshot of `list_tables()`, not re-derived at Phase 1/2
    time."""
    source_conn = persistence.get_connection(request["source_connection_id"])
    if source_conn is None:
        msg = f"No such connection: {request['source_connection_id']}"
        raise CloneJobNotFoundError(msg)
    source = build_source_connector(source_conn, request["source_database"])
    try:
        tables = list(source.list_tables())
    finally:
        source.close()

    job_id = str(uuid.uuid4())
    job = {
        "job_id": job_id,
        "status": CloneJobStatus.PENDING_DB_CREATE.value,
        "source_connection_id": request["source_connection_id"],
        "source_database": request["source_database"],
        "destination_connection_id": request["destination_connection_id"],
        "destination_database": request["destination_database"],
        "tables": tables,
        "field_configs": request["field_configs"],
        "progress": {
            "current_table": None,
            "tables_completed": [],
            "rows_done": 0,
            "checkpoints": {},
        },
        "error": None,
    }
    persistence.create_clone_job(job_id, job)
    return job


def verify_and_create_schema(persistence: PgPersistence, job_id: str) -> dict:
    """Phase 1 (decision #5): verifies the user has run the returned
    `CREATE DATABASE` command, then creates every table completely empty
    (schema clone only, no rows yet)."""
    job = persistence.get_clone_job(job_id)
    if job is None:
        raise CloneJobNotFoundError(job_id)
    if job["status"] != CloneJobStatus.PENDING_DB_CREATE.value:
        msg = f"Clone job {job_id} is {job['status']}, expected {CloneJobStatus.PENDING_DB_CREATE}"
        raise CloneJobStateError(msg)

    dest_conn = persistence.get_connection(job["destination_connection_id"])
    dest = build_destination_writer(dest_conn)
    try:
        if not dest.database_exists(job["destination_database"]):
            msg = (
                f"Destination database {job['destination_database']!r} does not exist yet — "
                "run the CREATE DATABASE command returned by POST /clone-jobs, then retry."
            )
            raise CloneJobStateError(msg)

        source_conn = persistence.get_connection(job["source_connection_id"])
        source = build_source_connector(source_conn, job["source_database"])
        try:
            for table in job["tables"]:
                columns = source.get_columns(table)
                semantic_types = {
                    column: semantic_type
                    for column, semantic_type in job["field_configs"].get(table, {}).items()
                    if semantic_type
                }
                if dest_conn["engine"] == "postgres":
                    primary_key = source.get_primary_key(table)
                    dest.create_table(
                        job["destination_database"],
                        table,
                        columns,
                        primary_key=primary_key,
                        semantic_types=semantic_types,
                    )
                else:
                    engine_name, order_by = source.get_table_engine_info(table)
                    dest.create_table(
                        job["destination_database"],
                        table,
                        columns,
                        order_by=order_by,
                        engine=engine_name,
                        semantic_types=semantic_types,
                    )
        finally:
            source.close()
    finally:
        dest.close()

    job["status"] = CloneJobStatus.SCHEMA_READY.value
    persistence.save_clone_job(job_id, job)
    return job


# --- Phase 2 --------------------------------------------------------------

# Guards against starting a second in-process thread for a job that's
# already running (a "resume" is just clicking start again on an
# orphaned-but-still-RUNNING job — this makes that idempotent within one
# process). Not a cross-process lock: see the module docstring's
# threading.Thread ponytail note.
_active_threads: dict[str, threading.Thread] = {}
_threads_lock = threading.Lock()


def start_phase2(
    persistence: PgPersistence, dispatcher: Dispatcher, cache: NormalizationCache | None, job_id: str
) -> bool:
    """Claims the job (SCHEMA_READY|RUNNING -> RUNNING) and starts Phase 2
    on a daemon thread. Returns False without starting a new thread if
    either the claim fails (wrong state — 409 at the route level) or a
    thread for this job is already alive in this process."""
    if not persistence.claim_clone_job(job_id):
        return False
    with _threads_lock:
        existing = _active_threads.get(job_id)
        if existing is not None and existing.is_alive():
            return True
        # ponytail: threading.Thread, not Celery/RQ — no task-queue
        # dependency exists in this codebase and none is justified for 2
        # engines / one deployment. A crashed process loses the in-flight
        # thread, but the job resumes from its last committed chunk
        # (checkpointed every chunk-commit), so correctness survives;
        # only "auto-restart on crash" doesn't. Upgrade to a real task
        # queue only if this needs to survive across multiple app
        # replicas.
        thread = threading.Thread(
            target=_run_phase2, args=(persistence, dispatcher, cache, job_id), daemon=True
        )
        _active_threads[job_id] = thread
        thread.start()
    return True




def _run_phase2(
    persistence: PgPersistence, dispatcher: Dispatcher, cache: NormalizationCache | None, job_id: str
) -> None:
    job = persistence.get_clone_job(job_id)
    source_conn = persistence.get_connection(job["source_connection_id"])
    dest_conn = persistence.get_connection(job["destination_connection_id"])
    source = build_source_connector(source_conn, job["source_database"])
    dest = build_destination_writer(dest_conn)
    # `cache` is deliberately NOT passed to the planner. The persistent
    # (DuckDB) tier stores one row per distinct value forever, which the
    # distinct-value architecture assumes is far smaller than the row count
    # (normexec/planner.py's spike: 100k rows / 500 distinct values).
    # Measured on real clone data (testzoominfo.Company, 1.27M rows):
    # website 96.4% unique, companyName 97.0%, companyPhone 79.8% — so the
    # cache stored ~1 entry per row, reached 3.87GB / 1.2M rows mid-run,
    # and bought back ~3% of dispatcher calls. Pure cost at this
    # cardinality. The planner already treats None as "no cache tiers"
    # (normexec/planner.py), and the per-chunk `set()` of distinct values
    # below still dedups within a chunk, which is where the cheap win is.
    # ponytail: unconditional None, not a cardinality-adaptive switch —
    # genuinely low-cardinality columns (COUNTRY, BOOLEAN) now re-dispatch
    # once per chunk instead of once per job. Add the adaptive version
    # (sample the first chunk, keep the cache below ~50% uniqueness) only
    # if that re-dispatch volume shows up in a real run's timings.
    planner = DistinctValuePlanner(dispatcher, None)
    progress = job["progress"]
    tables_completed = set(progress["tables_completed"])

    try:
        for table in job["tables"]:
            if table in tables_completed:
                continue
            progress["current_table"] = table
            field_config = job["field_configs"].get(table, {})
            # FieldSemanticType, not the raw string stored in the job's
            # JSON blob — Dispatcher.normalize's `context.semantic_type
            # is not semantic_type` identity check (normcore/dispatch.py)
            # requires the actual enum member on both sides, not a
            # same-valued string (an `is` check, not `==`).
            configured_columns = {c: FieldSemanticType(t) for c, t in field_config.items() if t}
            primary_key = (
                list(source.get_primary_key(table)) if source_conn["engine"] == "postgres" else []
            )
            # Resume (decision #10): re-stream this table from the start
            # and skip every row whose source_row_key offset is <= the
            # last committed checkpoint, until reaching it.
            # ponytail: re-stream-and-skip, not a pushdown filter (no
            # per-row filter param on read_table today) — correct, but
            # re-reads already-processed rows on resume. Add pushdown
            # filtering if resumed jobs on very large tables get costly.
            checkpoint = progress["checkpoints"].get(table, -1)

            for batch in source.read_table(table, batch_size=ROW_CHUNK_SIZE):
                rows = batch.to_pylist()
                pending: list[tuple[int, dict[str, Any]]] = []
                for row in rows:
                    offset = int(row["source_row_key"].rsplit(":", 1)[1])
                    if offset > checkpoint:
                        pending.append((offset, row))
                if not pending:
                    continue

                errors_buffer: list[dict[str, Any]] = []
                for column, semantic_type in configured_columns.items():
                    ctx = NormalizationContext(
                        field_name=column,
                        semantic_type=semantic_type,
                        table=table,
                        source=job["source_connection_id"],
                        error_policy=ErrorPolicy.RETURN_ORIGINAL,
                    )
                    distinct_values = list(
                        {row[column] for _, row in pending if row[column] is not None}
                    )
                    by_value = planner.distinct_value_results(
                        distinct_values, semantic_type, ctx, SCAFFOLD_PROFILE
                    )
                    for offset, row in pending:
                        original = row[column]
                        if original is None:
                            continue
                        result = by_value[original]
                        row[column] = result.display
                        if result.errors:
                            errors_buffer.append(
                                {
                                    "row_index": offset,
                                    "table_name": table,
                                    "field": column,
                                    "original": original,
                                    "error": "; ".join(result.errors),
                                }
                            )

                dest_rows = []
                for _, row in pending:
                    row.pop("source_row_key", None)
                    dest_rows.append(row)

                dest.bulk_insert(
                    job["destination_database"], table, dest_rows, primary_key=primary_key
                )
                if errors_buffer:
                    persistence.save_clone_job_errors(job_id, errors_buffer)

                checkpoint = max(offset for offset, _ in pending)
                progress["checkpoints"][table] = checkpoint
                progress["rows_done"] += len(pending)
                job["progress"] = progress
                persistence.save_clone_job(job_id, job)

            tables_completed.add(table)
            progress["tables_completed"] = sorted(tables_completed)
            job["progress"] = progress
            persistence.save_clone_job(job_id, job)

        progress["current_table"] = None
        job["progress"] = progress
        job["status"] = CloneJobStatus.COMPLETED.value
        persistence.save_clone_job(job_id, job)
    except Exception as exc:  # noqa: BLE001 - a job-level failure is recorded, not silently swallowed
        job["status"] = CloneJobStatus.FAILED.value
        job["error"] = str(exc)
        persistence.save_clone_job(job_id, job)
    finally:
        source.close()
        dest.close()

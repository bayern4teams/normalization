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

import datetime as dt
import multiprocessing
import os
import threading
import uuid
from concurrent.futures import ProcessPoolExecutor
from typing import TYPE_CHECKING, Any

from normanalysis.type_detection import suggest_semantic_type
from normexec.planner import DistinctValuePlanner
from normio.connectors import (
    ClickHouseConnector,
    ClickHouseDestination,
    PostgresConnector,
    PostgresDestination,
)
from normio.connectors._sql_base import SOURCE_READ_BATCH_ROWS

from normapi import secrets
from normapi.scaffold_profile import SCAFFOLD_PROFILE
from normcore import CloneJobStatus, ErrorPolicy, FieldSemanticType, NormalizationContext
from normio import storage_types

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping

    from normcore.dispatch import NormalizerRegistry
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


# --- automatic field-type detection ---------------------------------------
#
# Without this, a column the operator did not explicitly list in
# `field_configs` is cloned verbatim, so the quality of a clone is capped
# by how exhaustively somebody hand-wrote its configuration. On a real
# 13-table source, a hand-written config covered 10 columns out of 114;
# every boolean, every date outside those 10, and every URL outside them
# was copied unnormalized even though this codebase has had working
# normalizers for all three the whole time.
#
# `suggest_semantic_type` (normanalysis, §61) already does the detection and
# already checks its own guess against real values. This just calls it for
# the columns nobody configured. Three properties make that safe:
#   - an explicit config ALWAYS wins; inference only fills gaps,
#   - only a guess confirmed by real sampled values clears the threshold,
#   - what was inferred is written to the job as `inferred_field_configs`,
#     so the decision is inspectable rather than silent (§85).
def _env_seconds(name: str, default: int) -> int:
    try:
        value = int(os.environ[name])
    except (KeyError, ValueError):
        return default
    return value if value > 0 else default


_AUTODETECT_MIN_CONFIDENCE = float(os.environ.get("NORM_CLONE_AUTODETECT_MIN_CONFIDENCE", "0.9"))
_AUTODETECT_SAMPLE_ROWS = int(os.environ.get("NORM_CLONE_AUTODETECT_SAMPLE_ROWS", "200"))

# FREE_TEXT is the "nothing matched" fallback, and applying it would rewrite
# arbitrary prose (punctuation folding, whitespace collapse) in every column
# nobody configured — far too broad to do on a guess. An operator who wants
# it can still ask for it explicitly.
_NEVER_INFERRED = frozenset({FieldSemanticType.FREE_TEXT, FieldSemanticType.UNKNOWN})

# Detection only applies to columns the SOURCE stores as text. A column the
# source already types as timestamp/boolean/numeric/uuid has no
# normalization problem to solve — the database itself guarantees the
# format — and configuring one is actively harmful, because a configured
# column's destination type becomes TEXT (see SEMANTIC_TYPE_TO_PG_TYPE), so
# auto-detecting `created_at` would silently downgrade a real timestamp
# column to a string. An operator can still force a semantic type onto any
# column explicitly; this only governs what is inferred.
#
# An allow-list of substrings rather than a deny-list of typed names, so an
# unrecognised type fails toward "leave it alone" instead of toward
# rewriting it. Covers postgres text/varchar/char, ClickHouse
# String/Nullable(String)/LowCardinality(String), MySQL longtext, etc.
_TEXTUAL_NATIVE_TYPE_MARKERS = ("char", "text", "string", "clob", "enum", "json")


def _is_textual(native_type: str) -> bool:
    lowered = native_type.lower()
    return any(marker in lowered for marker in _TEXTUAL_NATIVE_TYPE_MARKERS)


def _sample_column_values(source: Any, table: str, columns: list[str]) -> dict[str, list[str]]:
    """First batch only — one bounded read per table, not a scan."""
    try:
        for batch in source.read_table(
            table, columns=columns, batch_size=_AUTODETECT_SAMPLE_ROWS
        ):
            # Arrow hands back native types (datetime, int, bool) for
            # non-text columns; `suggest_semantic_type` is defined over the
            # string form a normalizer would actually see.
            return {
                column: [str(v) for v in batch.column(column).to_pylist() if v is not None]
                for column in columns
            }
    except Exception:
        # cannot sample simply falls back to name-only evidence, which is
        # exactly what happens for an empty table anyway. Never fail job
        # creation because a sample read did not work.
        return {}
    return {}


def _infer_field_configs(
    source: Any,
    tables: list[str],
    explicit: dict[str, dict[str, str | None]],
    registry: NormalizerRegistry,
    *,
    fallback_free_text: bool = False,
) -> dict[str, dict[str, str]]:
    """`fallback_free_text` sweeps every remaining textual column into
    FREE_TEXT: unicode normalization, zero-width strip, whitespace collapse,
    punctuation folding. Off by default because folding is lossy — an en
    dash becomes a hyphen, and `(2018–present)` was not wrong to begin with
    — so it is an operator's call, not a guess this can make. Measured
    against an independently produced reference of a 13-table source, it
    accounted for every remaining prose difference."""
    inferred: dict[str, dict[str, str]] = {}
    for table in tables:
        configured = explicit.get(table, {})
        unconfigured = [
            c.name
            for c in source.get_columns(table)
            if not configured.get(c.name) and _is_textual(c.native_type)
        ]
        if not unconfigured:
            continue
        samples = _sample_column_values(source, table, unconfigured)
        for column in unconfigured:
            best = suggest_semantic_type(
                column, sample_values=samples.get(column), registry=registry
            )[0]
            if (
                best.confidence >= _AUTODETECT_MIN_CONFIDENCE
                and best.semantic_type not in _NEVER_INFERRED
            ):
                inferred.setdefault(table, {})[column] = best.semantic_type.value
            elif fallback_free_text:
                inferred.setdefault(table, {})[column] = FieldSemanticType.FREE_TEXT.value
    return inferred


def create_clone_job(
    persistence: PgPersistence, *, request: dict, registry: NormalizerRegistry | None = None
) -> dict:
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
    # In-place normalizes the source itself, so the destination is not the
    # caller's to choose — taking it from the request would let a typo
    # write staging tables into some other database and swap nothing.
    in_place = request.get("in_place", False)
    destination_connection_id = (
        request["source_connection_id"] if in_place else request["destination_connection_id"]
    )
    destination_database = (
        request["source_database"] if in_place else request["destination_database"]
    )
    explicit_configs = request["field_configs"]
    inferred_configs: dict[str, dict[str, str]] = {}
    try:
        tables = list(source.list_tables())
        if registry is not None and request.get("autodetect_field_types", True):
            inferred_configs = _infer_field_configs(
                source,
                tables,
                explicit_configs,
                registry,
                fallback_free_text=request.get("normalize_unconfigured_text", False),
            )
    finally:
        source.close()

    # Explicit always wins, per column — inference only fills the gaps.
    field_configs = {
        table: {**inferred_configs.get(table, {}), **explicit_configs.get(table, {})}
        for table in set(inferred_configs) | set(explicit_configs)
    }

    job_id = str(uuid.uuid4())
    job = {
        "job_id": job_id,
        "status": CloneJobStatus.PENDING_DB_CREATE.value,
        "source_connection_id": request["source_connection_id"],
        "source_database": request["source_database"],
        "destination_connection_id": destination_connection_id,
        "destination_database": destination_database,
        "tables": tables,
        "field_configs": field_configs,
        "inferred_field_configs": inferred_configs,
        "typed_destination_columns": request.get("typed_destination_columns", False),
        "in_place": in_place,
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


# A MONEY column normalizes to a bare amount so the column can be summed;
# its currency would otherwise be dropped on the floor exactly the way
# NUMERIC used to drop it. It goes in a companion column instead.
_CURRENCY_SUFFIX = "_currency"

# In-place normalization writes each table to a staging table beside the
# original, then swaps. The suffix is part of the resume contract: Phase 1
# creates <table><suffix>, Phase 2 fills and swaps it.
_STAGING_SUFFIX = "__normalizing"


def staging_name(table: str) -> str:
    return f"{table}{_STAGING_SUFFIX}"


# A job whose PROCESS dies — OOM kill, container restart, SIGKILL — never
# runs the `except` that would mark it FAILED, so it sits in RUNNING
# forever and is indistinguishable from a job that is simply slow.
# Phase 2 already writes the job row once per chunk for the resume
# checkpoint, so stamping the time there costs nothing extra and makes
# "still working" observable rather than assumed.
HEARTBEAT_TIMEOUT_SECONDS = _env_seconds("NORM_CLONE_HEARTBEAT_TIMEOUT_SECONDS", 900)


def _save_progress(persistence: PgPersistence, job_id: str, job: dict) -> None:
    """Persist progress and stamp the heartbeat in one step, so the two
    can never drift apart — a saved checkpoint with a stale timestamp
    would read as a dead job that is in fact working."""
    job["heartbeat_at"] = dt.datetime.now(tz=dt.UTC).isoformat()
    persistence.save_clone_job(job_id, job)


def is_stale(job: Mapping[str, Any], *, now: dt.datetime | None = None) -> bool:
    """True when a RUNNING job has not checkpointed recently enough to
    still be believable.

    Deliberately advisory: it never rewrites the job's status. Claiming
    already allows RUNNING -> RUNNING so a stale job can just be started
    again, and a job that was merely paused by a slow source should not
    be declared dead by a background sweeper that cannot know better.
    """
    if job.get("status") != CloneJobStatus.RUNNING.value:
        return False
    stamp = job.get("heartbeat_at")
    if not stamp:
        # Pre-heartbeat job, or one that crashed before its first chunk.
        # Unknowable rather than stale: saying "dead" here would mislabel
        # every job written by an older version of this code.
        return False
    try:
        beat = dt.datetime.fromisoformat(stamp)
    except ValueError:
        return False
    now = now or dt.datetime.now(tz=dt.UTC)
    return (now - beat).total_seconds() > HEARTBEAT_TIMEOUT_SECONDS
_MONEY = FieldSemanticType.MONEY.value
_TEXT_TYPE = {"postgres": "TEXT", "clickhouse": "String"}


def _destination_plan(
    semantic_types: Mapping[str, str],
    engine: str,
    key_columns: Collection[str],
    *,
    typed: bool,
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """(column_overrides, extra_columns, typed_columns) for one table.

    `key_columns` (the primary key / sorting key) are never given a native
    type: ClickHouse refuses a nullable sorting key, so a value that
    failed to cast would have nowhere to go — and a key column is the one
    place a NULL is least acceptable anyway.
    """
    overrides: dict[str, str] = {}
    extras: dict[str, str] = {}
    typed_columns: dict[str, str] = {}
    for column, semantic_type in semantic_types.items():
        if semantic_type == _MONEY:
            extras[f"{column}{_CURRENCY_SUFFIX}"] = _TEXT_TYPE.get(engine, "TEXT")
        if not typed or column in key_columns:
            continue
        sql_type = storage_types.sql_type(semantic_type, engine)
        if sql_type is not None:
            overrides[column] = sql_type
            typed_columns[column] = semantic_type
    return overrides, extras, typed_columns


def verify_and_create_schema(persistence: PgPersistence, job_id: str) -> dict:
    """Phase 1 (decision #5): verifies the user has run the returned
    `CREATE DATABASE` command, then creates every table completely empty
    (schema clone only, no rows yet).

    In-place mode (`in_place`) writes into the SOURCE database instead:
    each table is created beside its original under a staging name, and
    Phase 2 swaps it in and drops the original one table at a time. The
    database already exists, so there is nothing for the operator to
    create and no CREATE DATABASE step to verify.
    """
    job = persistence.get_clone_job(job_id)
    if job is None:
        raise CloneJobNotFoundError(job_id)
    if job["status"] != CloneJobStatus.PENDING_DB_CREATE.value:
        msg = f"Clone job {job_id} is {job['status']}, expected {CloneJobStatus.PENDING_DB_CREATE}"
        raise CloneJobStateError(msg)

    dest_conn = persistence.get_connection(job["destination_connection_id"])
    dest = build_destination_writer(dest_conn)
    try:
        in_place = job.get("in_place", False)
        if not in_place and not dest.database_exists(job["destination_database"]):
            msg = (
                f"Destination database {job['destination_database']!r} does not exist yet — "
                "run the CREATE DATABASE command returned by POST /clone-jobs, then retry."
            )
            raise CloneJobStateError(msg)

        source_conn = persistence.get_connection(job["source_connection_id"])
        source = build_source_connector(source_conn, job["source_database"])
        destination_plan: dict[str, dict[str, dict[str, str]]] = {}
        try:
            for table in job["tables"]:
                columns = source.get_columns(table)
                # In-place: build beside the original, swap in Phase 2.
                # A leftover staging table from an abandoned run would
                # make CREATE TABLE fail, so it is cleared first.
                target = staging_name(table) if in_place else table
                if in_place:
                    dest.drop_table(job["destination_database"], target)
                semantic_types = {
                    column: semantic_type
                    for column, semantic_type in job["field_configs"].get(table, {}).items()
                    if semantic_type
                }
                engine = dest_conn["engine"]
                typed = job.get("typed_destination_columns", False)
                if engine == "postgres":
                    primary_key = source.get_primary_key(table)
                    overrides, extras, typed_columns = _destination_plan(
                        semantic_types, engine, primary_key, typed=typed
                    )
                    dest.create_table(
                        job["destination_database"],
                        target,
                        columns,
                        primary_key=primary_key,
                        semantic_types=semantic_types,
                        column_overrides=overrides,
                        extra_columns=extras,
                    )
                else:
                    engine_name, order_by = source.get_table_engine_info(table)
                    overrides, extras, typed_columns = _destination_plan(
                        semantic_types, engine, order_by, typed=typed
                    )
                    dest.create_table(
                        job["destination_database"],
                        target,
                        columns,
                        order_by=order_by,
                        engine=engine_name,
                        semantic_types=semantic_types,
                        column_overrides=overrides,
                        extra_columns=extras,
                    )
                # Recorded, not recomputed in Phase 2: the INSERT must
                # agree with the DDL that was actually executed here, even
                # if the source's keys or the job's flags changed since.
                destination_plan[table] = {
                    "typed_columns": typed_columns,
                    "currency_columns": {
                        column: f"{column}{_CURRENCY_SUFFIX}"
                        for column, st in semantic_types.items()
                        if st == _MONEY
                    },
                }
        finally:
            source.close()
    finally:
        dest.close()

    job["destination_plan"] = destination_plan
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



# --- Parallel normalization (process pool) --------------------------------
#
# Phase 2 was one thread doing read -> normalize -> write serially, and
# after the cache was dropped normalization is ~80% of wall clock
# (measured stage breakdown: normalize 79.6%, err_write 9.6%, insert
# 6.8%). That work is CPU-bound Python, so it needs PROCESSES, not
# threads — the GIL makes a thread pool worthless here.
#
# MEMORY IS THE BINDING CONSTRAINT, not CPU. The container this runs in
# is capped (compose.yaml api.mem_limit) and has already been OOM-killed
# once by an unbounded cache. Three things keep this bounded:
#   1. `NORM_CLONE_WORKERS` caps worker count. Each worker is a full
#      interpreter with its own normalizer registry and dictionaries.
#      MEASURED (real testzoominfo.Company values, COMPANY_NAME, inside a
#      4096MB container, cgroup memory.peak so parent AND workers count):
#
#        workers   peak     throughput    speedup
#          1       217MB    18,732/s      -          (serial baseline)
#          2       573MB    22,167/s      1.18x
#          3       744MB    29,751/s      1.59x
#          4       911MB    34,717/s      1.85x
#
#      That is a flat ~175MB per worker. The default of 3 is 18% of a 4g
#      container, leaving ~3.3GB for the DuckDB cap (512MB), the Arrow
#      read block, and the per-chunk row dicts. Raise it only after
#      measuring your own container the way DEFAULT_MAX_RUN_ROWS was —
#      note the speedup is sublinear (46% efficiency at 4), so the memory
#      buys less than it looks like it should.
#   2. Each task carries at most one chunk's distinct values for ONE
#      column (<= SOURCE_READ_BATCH_ROWS strings), and returns that many
#      NormalizedValues. Nothing accumulates across chunks in a worker.
#   3. The pool is created per job and shut down in `_run_phase2`'s
#      finally, so an idle app holds no worker processes at all.
#
# "spawn", not "fork": the parent is a live multi-threaded uvicorn
# process with open DB connections and httpx clients. Forking that copies
# locks other threads may hold, which deadlocks the child. spawn costs a
# fresh interpreter per worker (hence the memory note above) and is the
# only safe option here.
# Also capped by CPU count: more workers than cores buys nothing and
# costs ~175MB each, which is the exact trade this whole block exists to
# avoid getting wrong.
_WORKER_COUNT = min(int(os.environ.get("NORM_CLONE_WORKERS", "3")), os.cpu_count() or 1)

# Below this many distinct values, the pickle round-trip costs more than
# the normalization it parallelizes. A full chunk of a high-cardinality
# column is ~SOURCE_READ_BATCH_ROWS values, so this only skips genuinely small
# batches (low-cardinality columns, or the tail chunk of a table).
_PARALLEL_MIN_VALUES = 500

_worker_planner: DistinctValuePlanner | None = None


def _init_clone_worker(env_id: str) -> None:
    """ProcessPoolExecutor initializer — runs once per worker process.

    Builds the registry via `build_normalizer_registry()` with no
    arguments so the worker resolves the SAME dictionaries dir and
    libpostal URL from the environment that the parent did, instead of
    carrying a second copy of that logic. Imported inside the function
    because it is only ever needed in a worker.
    """
    global _worker_planner  # noqa: PLW0603 - the pool initializer contract is a module global
    from normapi.app import build_dispatcher  # noqa: PLC0415 - worker-only import

    _worker_planner = DistinctValuePlanner(build_dispatcher(env_id=env_id), None)


def _normalize_slice(
    payload: tuple[list[str], FieldSemanticType, NormalizationContext, Any],
) -> dict[str, Any]:
    """Runs in a worker. Goes through the planner (not the dispatcher
    directly) so a slice still gets the planner's `prepare_batch` hook —
    an ADDRESS slice makes one batched libpostal call for its own values
    rather than one HTTP round-trip per address."""
    values, semantic_type, context, profile = payload
    if _worker_planner is None:
        # Cannot happen while the pool is built with our initializer, but
        # a bare RuntimeError beats an AttributeError here: the caller
        # catches it and finishes the batch serially.
        msg = "clone worker used before _init_clone_worker ran"
        raise RuntimeError(msg)
    return _worker_planner.distinct_value_results(values, semantic_type, context, profile)


def _normalize_distinct(
    pool: ProcessPoolExecutor | None,
    planner: DistinctValuePlanner,
    distinct_values: list[str],
    *,
    semantic_type: FieldSemanticType,
    context: NormalizationContext,
    profile: Any,
) -> dict[str, Any]:
    """Distinct-value normalization, fanned across the pool when there is
    enough work to pay for the IPC. Falls back to the in-process planner
    for a missing pool, a small batch, or ANY worker failure — a pool
    problem must degrade this job to "slower", never to "failed"."""
    if pool is None or len(distinct_values) < _PARALLEL_MIN_VALUES:
        return planner.distinct_value_results(distinct_values, semantic_type, context, profile)

    workers = pool._max_workers
    size = (len(distinct_values) + workers - 1) // workers
    slices = [distinct_values[i : i + size] for i in range(0, len(distinct_values), size)]
    try:
        merged: dict[str, Any] = {}
        for part in pool.map(
            _normalize_slice, [(sl, semantic_type, context, profile) for sl in slices]
        ):
            merged.update(part)
    except Exception:  # see docstring: degrade to serial, never fail the job
        return planner.distinct_value_results(distinct_values, semantic_type, context, profile)
    return merged


def _make_pool(env_id: str) -> ProcessPoolExecutor | None:
    if _WORKER_COUNT <= 1:
        return None
    try:
        return ProcessPoolExecutor(
            max_workers=_WORKER_COUNT,
            mp_context=multiprocessing.get_context("spawn"),
            initializer=_init_clone_worker,
            initargs=(env_id,),
        )
    except (OSError, ValueError):
        # No process pool available (restricted container, fd limits).
        # Serial normalization is correct, just slower.
        return None



def _apply_column(
    pending: list[tuple[int, dict[str, Any]]],
    *,
    column: str,
    semantic_type: FieldSemanticType,
    table: str,
    source_id: str,
    pool: Any,
    planner: DistinctValuePlanner,
    typed_as: str | None,
    companion: str | None,
    errors_buffer: list[dict[str, Any]],
) -> None:
    """Normalize one column across one chunk, in place.

    Extracted from `_run_phase2` so that adding the pre-insert cast and
    the MONEY companion column did not push an already-oversized function
    further past the branch limit.
    """
    ctx = NormalizationContext(
        field_name=column,
        semantic_type=semantic_type,
        table=table,
        source=source_id,
        error_policy=ErrorPolicy.RETURN_ORIGINAL,
        # This loop reads exactly two things off each result —
        # `.display` and `.errors` (for the decision #9 error report) —
        # and throws the rest away, including the per-step trace. The
        # trace is 36% of COMPANY_NAME normalize time (cProfile, real
        # data), so building it here is pure waste. Every interactive
        # path keeps it: the default is True, only bulk clone opts out.
        include_trace=False,
    )
    distinct_values = list({row[column] for _, row in pending if row[column] is not None})
    by_value = _normalize_distinct(
        pool,
        planner,
        distinct_values,
        semantic_type=semantic_type,
        context=ctx,
        profile=SCAFFOLD_PROFILE,
    )
    for offset, row in pending:
        original = row[column]
        if original is None:
            continue
        result = by_value[original]
        row[column] = result.display
        errors = list(result.errors)

        if companion is not None:
            row[companion] = result.structured.get("currency")

        # Decision #8 puts the ORIGINAL raw string in the cell when
        # normalization fails, which a natively typed column cannot hold.
        # Cast here and send a value that will not fit down the same
        # error-report path, rather than letting the database reject the
        # whole chunk (and with it the error rows that would have
        # explained why).
        if typed_as is not None:
            cast_value, cast_error = storage_types.coerce(typed_as, row[column])
            row[column] = cast_value
            if cast_error is not None:
                errors.append(cast_error)

        if errors:
            errors_buffer.append(
                {
                    "row_index": offset,
                    "table_name": table,
                    "field": column,
                    "original": original,
                    "error": "; ".join(errors),
                }
            )


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
    pool = _make_pool(dispatcher.env_id)
    progress = job["progress"]
    tables_completed = set(progress["tables_completed"])
    in_place = job.get("in_place", False)

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
            write_target = staging_name(table) if in_place else table
            table_plan = job.get("destination_plan", {}).get(table, {})
            typed_columns: dict[str, str] = table_plan.get("typed_columns", {})
            currency_columns: dict[str, str] = table_plan.get("currency_columns", {})

            for batch in source.read_table(table, batch_size=SOURCE_READ_BATCH_ROWS):
                rows = batch.to_pylist()
                pending: list[tuple[int, dict[str, Any]]] = []
                for row in rows:
                    offset = int(row["source_row_key"].rsplit(":", 1)[1])
                    if offset > checkpoint:
                        pending.append((offset, row))
                if not pending:
                    continue

                errors_buffer: list[dict[str, Any]] = []
                # Every row must carry the same keys: bulk_insert derives
                # the column list from rows[0], so a companion column that
                # only appears on rows with a non-null amount would build
                # an INSERT that is wrong for every other row.
                for _, row in pending:
                    for companion in currency_columns.values():
                        row[companion] = None
                for column, semantic_type in configured_columns.items():
                    _apply_column(
                        pending,
                        column=column,
                        semantic_type=semantic_type,
                        table=table,
                        source_id=job["source_connection_id"],
                        pool=pool,
                        planner=planner,
                        typed_as=typed_columns.get(column),
                        companion=currency_columns.get(column),
                        errors_buffer=errors_buffer,
                    )

                dest_rows = []
                for _, row in pending:
                    row.pop("source_row_key", None)
                    dest_rows.append(row)

                dest.bulk_insert(
                    job["destination_database"], write_target, dest_rows, primary_key=primary_key
                )
                if errors_buffer:
                    persistence.save_clone_job_errors(job_id, errors_buffer)

                checkpoint = max(offset for offset, _ in pending)
                progress["checkpoints"][table] = checkpoint
                progress["rows_done"] += len(pending)
                job["progress"] = progress
                _save_progress(persistence, job_id, job)

            if in_place:
                # Swap only after the table is fully written, and BEFORE
                # it is marked completed: a crash between the two replays
                # a table that is already normalized, which re-reads the
                # source and rebuilds a staging table that no longer
                # exists — so the swap is what "completed" must mean here.
                dest.swap_table(job["destination_database"], table, write_target)

            tables_completed.add(table)
            progress["tables_completed"] = sorted(tables_completed)
            job["progress"] = progress
            _save_progress(persistence, job_id, job)

        progress["current_table"] = None
        job["progress"] = progress
        job["status"] = CloneJobStatus.COMPLETED.value
        persistence.save_clone_job(job_id, job)
    except Exception as exc:
        job["status"] = CloneJobStatus.FAILED.value
        job["error"] = str(exc)
        persistence.save_clone_job(job_id, job)
    finally:
        # Workers are real processes holding real memory — never leave
        # them alive past the job, on any exit path.
        if pool is not None:
            pool.shutdown(wait=False, cancel_futures=True)
        source.close()
        dest.close()

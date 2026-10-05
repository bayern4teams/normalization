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

import dataclasses
import datetime as dt
import multiprocessing
import os
import threading
import uuid
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from typing import TYPE_CHECKING, Any

from normalizers.postcode_validation import country_from_postcode_format
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
from normapi.adjudication import Adjudication
from normapi.scaffold_profile import SCAFFOLD_PROFILE
from normcore import (
    CloneJobStatus,
    ErrorPolicy,
    FieldSemanticType,
    MissingKind,
    NormalizationContext,
    NormalizationStatus,
    NormalizedValue,
)
from normio import storage_types

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Mapping

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


def build_source_connector(
    conn: dict[str, Any], database: str, schema: str | None = None
) -> PostgresConnector | ClickHouseConnector:
    """`schema` is Postgres-only and names the namespace inside `database`
    that table names are relative to. ClickHouse has no layer between
    database and table, so its `database` argument already is this."""
    password = secrets.decrypt(conn["encrypted_password"])
    if conn["engine"] == "postgres":
        dsn = f"postgresql://{conn['username']}:{password}@{conn['host']}:{conn['port']}/{database}"
        return PostgresConnector(conn["connection_id"], dsn, schema)
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


def build_destination_writer(conn: dict[str, Any]) -> PostgresDestination | ClickHouseDestination:
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
# column's destination type becomes TEXT unless it is one of the natively
# typed NUMERIC/MONEY/BOOLEAN (normio.storage_types), so auto-detecting
# `created_at` would silently downgrade a real timestamp column to a string.
# An operator can still force a semantic type onto any column explicitly;
# this only governs what is inferred.
#
# An allow-list of substrings rather than a deny-list of typed names, so an
# unrecognised type fails toward "leave it alone" instead of toward
# rewriting it. Covers postgres text/varchar/char, ClickHouse
# String/Nullable(String)/LowCardinality(String), MySQL longtext, etc.
_TEXTUAL_NATIVE_TYPE_MARKERS = ("char", "text", "string", "clob", "enum", "json")

# The second structural exclusion: a column in the table's own KEY is never
# given an inferred semantic type.
#
# Normalization is many-to-one by design — `GB`, `uk` and `Great Britain`
# all become `United Kingdom` — and applying that to a key silently merges
# rows that were distinct. On ClickHouse the merge is not even visible:
# `ReplacingMergeTree` deduplicates by the sorting key, so two keys folded
# into one become ONE ROW. Measured on a real source, autodetect confidently
# mapped `PersonContact.freeMails` to EMAIL at 0.95 — and `freeMails` is
# that table's entire sorting key. Every join to the rest of the database
# goes through these columns too.
#
# Read from the source's structure (`get_primary_key` /
# `get_table_engine_info`), never from names: `_version` and `created_at`
# are excluded because the source types them, not because of what they are
# called. An operator can still configure a key column explicitly — an
# explicit `field_config` is checked before this and always wins.


def _is_textual(native_type: str) -> bool:
    lowered = native_type.lower()
    return any(marker in lowered for marker in _TEXTUAL_NATIVE_TYPE_MARKERS)


def _key_columns(source: Any, table: str) -> list[str]:
    """The table's own key, read from the source's structure.

    One function because two callers need the same answer and must not
    disagree about it: `plan_one_table` (which refuses to give a key column
    a native destination type) and `_infer_field_configs` (which refuses to
    infer a semantic type for one at all).
    """
    if isinstance(source, ClickHouseConnector):
        return list(source.get_table_engine_info(table)[1])
    return list(source.get_primary_key(table))


def _sample_column_values(source: Any, table: str, columns: list[str]) -> dict[str, list[str]]:
    """First batch only — one bounded read per table, not a scan."""
    try:
        for batch in source.read_table(table, columns=columns, batch_size=_AUTODETECT_SAMPLE_ROWS):
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
    country: str | None = None,
    locale: str | None = None,
) -> dict[str, dict[str, str]]:
    """`fallback_free_text` sweeps every remaining textual column into
    FREE_TEXT: unicode normalization, zero-width strip, whitespace collapse,
    punctuation folding. Off by default because folding is lossy — an en
    dash becomes a hyphen, and `(2018-present)` was not wrong to begin with
    — so it is an operator's call, not a guess this can make. Measured
    against an independently produced reference of a 13-table source, it
    accounted for every remaining prose difference."""
    inferred: dict[str, dict[str, str]] = {}
    for table in tables:
        configured = explicit.get(table, {})
        keys = set(_key_columns(source, table))
        unconfigured = [
            c.name
            for c in source.get_columns(table)
            if not configured.get(c.name) and _is_textual(c.native_type) and c.name not in keys
        ]
        if not unconfigured:
            continue
        samples = _sample_column_values(source, table, unconfigured)
        for column in unconfigured:
            best = suggest_semantic_type(
                column,
                sample_values=samples.get(column),
                registry=registry,
                country=country,
                locale=locale,
            )[0]
            if (
                best.confidence >= _AUTODETECT_MIN_CONFIDENCE
                and best.semantic_type not in _NEVER_INFERRED
            ):
                inferred.setdefault(table, {})[column] = best.semantic_type.value
            elif fallback_free_text:
                inferred.setdefault(table, {})[column] = FieldSemanticType.FREE_TEXT.value
    return inferred


def _require_tables(source: Any, tables: list[str], request: Mapping[str, Any]) -> None:
    """A clone of nothing is a failure, not a success.

    With no tables the whole pipeline runs to `COMPLETED` having created an
    empty database — the most expensive kind of wrong answer, because
    nothing anywhere says so. It is one guard here rather than a fix aimed
    at any single cause, because every cause arrives at the same place:
    the wrong database, no SELECT grants, a genuinely empty source, or the
    one measured below.

    Postgres table lookups are relative to a SCHEMA, and the default one is
    `public`. A real 13-table source kept every table in a named schema, so
    `list_tables()` returned `[]`, the job was created with no tables, and
    it reported COMPLETED having copied nothing.

    The schema is NOT guessed, even when exactly one candidate has tables:
    picking for the operator is the kind of plausible answer this project
    refuses everywhere else, and with two populated schemas it would pick
    arbitrarily. The message names the candidates instead.
    """
    if tables:
        return
    where = f"database {request['source_database']!r}"
    schema = request.get("source_schema")
    if schema:
        where += f", schema {schema!r}"
    hint = ""
    if not schema and hasattr(source, "list_schemas"):
        populated = [s for s in source.list_schemas() if s != "public"]
        if populated:
            hint = (
                f" Tables were found in {', '.join(repr(s) for s in populated)} — "
                "set `source_schema` to the one you want (one schema per job, "
                "so that the clone's table names stay unqualified)."
            )
    msg = f"No tables to clone in {where}.{hint}"
    raise CloneJobStateError(msg)


def create_clone_job(
    persistence: PgPersistence,
    *,
    request: dict[str, Any],
    registry: NormalizerRegistry | None = None,
) -> dict[str, Any]:
    """Creates the job PENDING_DB_CREATE (decision #6). `request.tables`
    is captured NOW, at creation — every table in the chosen origin
    database is cloned automatically (decision #3), so the job's table
    list is a snapshot of `list_tables()`, not re-derived at Phase 1/2
    time."""
    source_conn = persistence.get_connection(request["source_connection_id"])
    if source_conn is None:
        msg = f"No such connection: {request['source_connection_id']}"
        raise CloneJobNotFoundError(msg)
    source = build_source_connector(
        source_conn, request["source_database"], request.get("source_schema")
    )
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
        _require_tables(source, tables, request)
        if registry is not None and request.get("autodetect_field_types", True):
            inferred_configs = _infer_field_configs(
                source,
                tables,
                explicit_configs,
                registry,
                fallback_free_text=request.get("normalize_unconfigured_text", False),
                # The job's own country/locale, so a column is judged by
                # the same context that will normalize it. Without them a
                # real PHONE column is demoted for holding phones a
                # region-less parser cannot read.
                country=request.get("country"),
                locale=request.get("locale"),
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
        # Saved, not just used at creation: Phase 1 and Phase 2 reopen the
        # source from the JOB, and a schema that reached only the discovery
        # read let the tables be found and then not exist. Live run: Phase 1
        # raised `NoSuchTableError: company` from the destination DDL's key
        # lookup, after the job had been created listing all 13 tables.
        "source_schema": request.get("source_schema"),
        "destination_connection_id": destination_connection_id,
        "destination_database": destination_database,
        "tables": tables,
        "field_configs": field_configs,
        "inferred_field_configs": inferred_configs,
        "typed_destination_columns": request.get("typed_destination_columns", True),
        "country": request.get("country"),
        "locale": request.get("locale"),
        "max_new_null_rate": request.get("max_new_null_rate"),
        "cross_table_entity_key": request.get("cross_table_entity_key"),
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

# Same problem, same fix, for `comparison`. For these types `comparison` is
# a stable machine key — an ISO 3166 alpha-2, a BCP-47 subtag, an E.164
# number — and `display` is a human rendering of the same fact ("United
# States", "German", "+1 650-253-0000"). The destination only ever got
# `display`, so the key was computed and thrown away: that is how a column
# named CountryCode ended up holding "United States" and joining against
# nothing. Both are written now. The original column keeps `display`
# (a column named `Country` was not wrong before, and changing what it
# holds would break every existing consumer of a clone); the companion
# gets the key.
_CODE_SUFFIX = "_code"
_CODE_TYPES = frozenset(
    {
        FieldSemanticType.COUNTRY.value,
        FieldSemanticType.LANGUAGE.value,
        FieldSemanticType.PHONE.value,
    }
)

# CURRENCY is deliberately absent: its `display` already IS the ISO 4217
# code, so a companion would duplicate the column.

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


def _save_progress(
    persistence: PgPersistence,
    job_id: str,
    job: dict[str, Any],
    queued: list[dict[str, Any]] | None = None,
) -> None:
    """Persist progress and stamp the heartbeat in one step, so the two
    can never drift apart — a saved checkpoint with a stale timestamp
    would read as a dead job that is in fact working. Adjudication queue
    rows ride the same transaction (ADR-018): what a checkpoint covers is
    exactly what has been counted."""
    job["heartbeat_at"] = dt.datetime.now(tz=dt.UTC).isoformat()
    if queued:
        persistence.save_clone_job_and_enqueue(job_id, job, queued)
    else:
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
_COUNTRY = FieldSemanticType.COUNTRY.value


def _country_from_country(result: NormalizedValue) -> str | None:
    return result.structured.get("alpha2")


def _country_from_phone(result: NormalizedValue) -> str | None:
    """Only when the NUMBER said so. `region_source` is `number_prefix`
    when the value carried its own +CC, and `explicit`/`default_region`
    when the region came from context — trusting those would feed a
    country back to itself. Measured on a real source: 247,469 of
    1,021,941 phone numbers (24.2%) carry their own country code."""
    if result.structured.get("region_source") != "number_prefix":
        return None
    region = result.structured.get("region")
    return region if isinstance(region, str) else None


def _country_from_postcode(result: NormalizedValue) -> str | None:
    """`comparison` is the uppercased form the format rules expect. Returns
    a country only where exactly one country's postcode format fits, so a
    bare five-digit number (valid in 56 countries) yields nothing."""
    if result.comparison is None:
        return None
    return country_from_postcode_format(result.comparison)


# What a normalized value of each semantic type can say about which country
# its row is in. One table so a new signal is one entry, not a fourth place
# that knows how to read `structured`.
#
# Deliberately NOT here:
#   - URL/domain ccTLD. No authoritative source separates national from
#     generic ccTLD use, and a two-letter TLD looked up as an alpha-2 puts
#     `.io` in the British Indian Ocean Territory, `.co` in Colombia (6,281
#     domains on one real source), `.me` in Montenegro, `.tv` in Tuvalu and
#     `.ai` in Anguilla. The alternative is a hand-written exclusion list
#     that grows one found example at a time, which is what this codebase
#     prefers authoritative data over.
#   - ADDRESS. libpostal does return a country, but as a raw string
#     ("USA", "united states") needing a second normalization pass. Cheap
#     to add here once that is worth a dispatcher call per distinct
#     address.
_COUNTRY_FROM: dict[FieldSemanticType, Callable[[NormalizedValue], str | None]] = {
    FieldSemanticType.COUNTRY: _country_from_country,
    FieldSemanticType.PHONE: _country_from_phone,
    FieldSemanticType.POSTCODE: _country_from_postcode,
}
_SIGNAL_TYPE_VALUES = frozenset(t.value for t in _COUNTRY_FROM)
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
    text_type = _TEXT_TYPE.get(engine, "TEXT")
    for column, semantic_type in semantic_types.items():
        if semantic_type == _MONEY:
            extras[f"{column}{_CURRENCY_SUFFIX}"] = text_type
        if semantic_type in _CODE_TYPES:
            extras[f"{column}{_CODE_SUFFIX}"] = text_type
        if not typed or column in key_columns:
            continue
        sql_type = storage_types.sql_type(semantic_type, engine)
        if sql_type is not None:
            overrides[column] = sql_type
            typed_columns[column] = semantic_type
    return overrides, extras, typed_columns


def _require_connection(persistence: PgPersistence, connection_id: str) -> dict[str, Any]:
    """A saved connection a job already references must still exist.

    Returning None here used to flow straight into the connector builders
    as an untyped None and fail several frames later with no mention of
    the connection id."""
    connection = persistence.get_connection(connection_id)
    if connection is None:
        msg = f"No such connection: {connection_id}"
        raise CloneJobNotFoundError(msg)
    return connection


def plan_one_table(
    source: Any,
    dest_engine: str,
    table: str,
    job: Mapping[str, Any],
) -> dict[str, Any]:
    """Everything Phase 1 needs to know about one table before it writes
    any DDL, and everything a reviewer needs to see to know what it will
    write.

    Both callers go through here rather than each deriving it, because a
    preview that merely resembles the DDL is worse than no preview: it
    invites sign-off on something else. The only thing Phase 1 adds is
    executing it.
    """
    semantic_types = {
        column: semantic_type
        for column, semantic_type in job["field_configs"].get(table, {}).items()
        if semantic_type
    }
    table_engine: str | None = None
    if isinstance(source, ClickHouseConnector):
        table_engine = source.get_table_engine_info(table)[0]
    key_columns = _key_columns(source, table)
    overrides, extras, typed_columns = _destination_plan(
        semantic_types,
        dest_engine,
        key_columns,
        typed=job.get("typed_destination_columns", True),
    )
    return {
        "columns": source.get_columns(table),
        "semantic_types": semantic_types,
        "key_columns": key_columns,
        "table_engine": table_engine,
        "column_overrides": overrides,
        "extra_columns": extras,
        "typed_columns": typed_columns,
        "currency_columns": {
            column: f"{column}{_CURRENCY_SUFFIX}"
            for column, st in semantic_types.items()
            if st == _MONEY
        },
        "code_columns": {
            column: f"{column}{_CODE_SUFFIX}"
            for column, st in semantic_types.items()
            if st in _CODE_TYPES
        },
    }


def plan_job(persistence: PgPersistence, job_id: str) -> dict[str, Any]:
    """The whole plan, per table and per column, WITHOUT executing any of
    it — what autodetect decided, where each decision came from, what
    native type each column will get, and which companion columns will
    appear.

    This exists because detection is the part of a clone nobody could see.
    On a real 13-table source it claimed 8 columns out of 114 and missed
    the two highest-value ones, and the only trace was a JSON blob on the
    job. Signing off on a clone meant running it and reading the result.

    Read-only: it opens the SOURCE (as the read-only credential) and reads
    the destination's ENGINE off the saved connection row without
    connecting — the destination database need not exist yet, which is the
    whole point of reviewing before `CREATE DATABASE`.
    """
    job = persistence.get_clone_job(job_id)
    if job is None:
        raise CloneJobNotFoundError(job_id)
    dest_conn = _require_connection(persistence, job["destination_connection_id"])
    source_conn = _require_connection(persistence, job["source_connection_id"])
    source = build_source_connector(source_conn, job["source_database"], job.get("source_schema"))
    inferred = job.get("inferred_field_configs", {})
    tables = []
    try:
        for table in job["tables"]:
            plan = plan_one_table(source, dest_conn["engine"], table, job)
            companions = {**plan["currency_columns"], **plan["code_columns"]}
            tables.append(
                {
                    "table": table,
                    "destination_table": (staging_name(table) if job.get("in_place") else table),
                    "table_engine": plan["table_engine"],
                    "key_columns": list(plan["key_columns"]),
                    "columns": [
                        {
                            "column": column.name,
                            "source_type": column.native_type,
                            "semantic_type": plan["semantic_types"].get(column.name),
                            # EXPLICIT beats INFERRED beats nothing — the
                            # distinction a reviewer is actually here for.
                            "decided_by": _decided_by(
                                column.name, plan["semantic_types"], inferred.get(table, {})
                            ),
                            "destination_type": plan["column_overrides"].get(column.name),
                            "companion_column": companions.get(column.name),
                        }
                        for column in plan["columns"]
                    ],
                    "extra_columns": plan["extra_columns"],
                }
            )
    finally:
        source.close()
    return {
        "job_id": job_id,
        "status": job["status"],
        "amendable": job["status"] == CloneJobStatus.PENDING_DB_CREATE.value,
        "country": job.get("country"),
        "locale": job.get("locale"),
        "typed_destination_columns": job.get("typed_destination_columns", True),
        "cross_table_entity_key": job.get("cross_table_entity_key"),
        "max_new_null_rate": job.get("max_new_null_rate"),
        "in_place": job.get("in_place", False),
        "tables": tables,
    }


def _decided_by(
    column: str, semantic_types: Mapping[str, str], inferred: Mapping[str, str]
) -> str | None:
    if column not in semantic_types:
        return None
    return "INFERRED" if column in inferred else "EXPLICIT"


def amend_clone_job(
    persistence: PgPersistence, job_id: str, changes: Mapping[str, Any]
) -> dict[str, Any]:
    """Apply a reviewer's changes to a job that has not built anything yet.

    Only before Phase 1: after it, the DDL has been executed and the
    destination's columns are what they are, so changing the plan would
    make the job's own record disagree with the tables it already created.

    `field_configs` MERGES per table and per column, so amending one column
    does not silently drop the other 113 that autodetect got right. An
    explicit null clears a column back to passthrough, which is the only
    way to say "do not normalize this one" — omitting it means "leave it as
    planned".
    """
    job = persistence.get_clone_job(job_id)
    if job is None:
        raise CloneJobNotFoundError(job_id)
    if job["status"] != CloneJobStatus.PENDING_DB_CREATE.value:
        msg = (
            f"Clone job {job_id} is {job['status']}; the plan can only be amended while it is "
            f"{CloneJobStatus.PENDING_DB_CREATE.value}, before any table has been created."
        )
        raise CloneJobStateError(msg)

    field_configs = changes.get("field_configs")
    if field_configs is not None:
        merged = {table: dict(columns) for table, columns in job["field_configs"].items()}
        for table, columns in field_configs.items():
            merged.setdefault(table, {}).update(columns)
            # A null means passthrough; keeping the key would make Phase 2
            # try to build a FieldSemanticType out of None.
            merged[table] = {c: t for c, t in merged[table].items() if t}
        job["field_configs"] = merged

    for field in _AMENDABLE_FIELDS:
        if field in changes:
            job[field] = changes[field]

    persistence.save_clone_job(job_id, job)
    return job


# Everything a review can change. Deliberately excludes the connections,
# the databases, `in_place` and the table list: those are what the job IS,
# and a job pointed somewhere else is a different job — cheap to create,
# since nothing has been built yet.
_AMENDABLE_FIELDS = (
    "country",
    "locale",
    "typed_destination_columns",
    "max_new_null_rate",
    "cross_table_entity_key",
)


def verify_and_create_schema(persistence: PgPersistence, job_id: str) -> dict[str, Any]:
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

    dest_conn = _require_connection(persistence, job["destination_connection_id"])
    dest = build_destination_writer(dest_conn)
    try:
        in_place = job.get("in_place", False)
        if not in_place and not dest.database_exists(job["destination_database"]):
            msg = (
                f"Destination database {job['destination_database']!r} does not exist yet — "
                "run the CREATE DATABASE command returned by POST /clone-jobs, then retry."
            )
            raise CloneJobStateError(msg)

        source_conn = _require_connection(persistence, job["source_connection_id"])
        source = build_source_connector(
            source_conn, job["source_database"], job.get("source_schema")
        )
        destination_plan: dict[str, dict[str, dict[str, str]]] = {}
        try:
            for table in job["tables"]:
                plan = plan_one_table(source, dest_conn["engine"], table, job)
                # In-place: build beside the original, swap in Phase 2.
                # A leftover staging table from an abandoned run would
                # make CREATE TABLE fail, so it is cleared first.
                target = staging_name(table) if in_place else table
                if in_place:
                    dest.drop_table(job["destination_database"], target)
                shared = {
                    "semantic_types": plan["semantic_types"],
                    "column_overrides": plan["column_overrides"],
                    "extra_columns": plan["extra_columns"],
                }
                # isinstance, not `engine == "postgres"`: the two branches
                # call methods that exist on only one connector/destination
                # each, and the engine string is opaque to the type checker
                # even though it does decide which pair was built.
                if isinstance(source, PostgresConnector) and isinstance(dest, PostgresDestination):
                    dest.create_table(
                        job["destination_database"],
                        target,
                        plan["columns"],
                        primary_key=plan["key_columns"],
                        **shared,
                    )
                elif isinstance(source, ClickHouseConnector) and isinstance(
                    dest, ClickHouseDestination
                ):
                    dest.create_table(
                        job["destination_database"],
                        target,
                        plan["columns"],
                        order_by=plan["key_columns"],
                        engine=plan["table_engine"],
                        **shared,
                    )
                else:
                    msg = (
                        f"Source {type(source).__name__} and destination "
                        f"{type(dest).__name__} are different engines; a clone "
                        "replicates schema in place and cannot translate between them."
                    )
                    raise CloneJobStateError(msg)
                # Recorded, not recomputed in Phase 2: the INSERT must
                # agree with the DDL that was actually executed here, even
                # if the source's keys or the job's flags changed since.
                destination_plan[table] = {
                    "typed_columns": plan["typed_columns"],
                    "currency_columns": plan["currency_columns"],
                    "code_columns": plan["code_columns"],
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
    persistence: PgPersistence,
    dispatcher: Dispatcher,
    cache: NormalizationCache | None,
    job_id: str,
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

    workers = _WORKER_COUNT
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
    code_column: str | None,
    country: str | None,
    locale: str | None,
    signals: dict[int, tuple[str, str]] | None,
    country_is_derived: bool,
    stats: _ColumnStats,
    errors_buffer: list[dict[str, Any]],
    adjudication: Adjudication | None = None,
) -> None:
    """Normalize one column across one chunk, in place.

    Tallies into `stats` for the column-level findings.

    Extracted from `_run_phase2` so that adding the pre-insert cast and
    the MONEY companion column did not push an already-oversized function
    further past the branch limit.
    """
    ctx = NormalizationContext(
        field_name=column,
        semantic_type=semantic_type,
        table=table,
        source=source_id,
        country=country,
        locale=locale,
        error_policy=ErrorPolicy.RETURN_ORIGINAL,
        # This loop reads the projections the destination has columns
        # for (`.display`, `.comparison`, the MONEY currency out of
        # `.structured`) plus `.errors` for the decision #9 report, and
        # throws the rest away, including the per-step trace. The trace
        # is 36% of COMPANY_NAME normalize time (cProfile, real data), so
        # building it here is pure waste. Every interactive path keeps
        # it: the default is True, only bulk clone opts out.
        include_trace=False,
    )
    distinct_values = list({row[column] for _, row in pending if row[column] is not None})
    # ADR-018 resolve stage: a value someone already decided is answered
    # from its verdict and never dispatched.
    adjudicated = (
        adjudication.resolve(
            distinct_values,
            semantic_type=semantic_type,
            context=ctx,
            renormalize=lambda values: _normalize_distinct(
                pool,
                planner,
                values,
                semantic_type=semantic_type,
                context=ctx,
                profile=SCAFFOLD_PROFILE,
            ),
        )
        if adjudication is not None
        else {}
    )
    by_value = _normalize_distinct(
        pool,
        planner,
        [v for v in distinct_values if v not in adjudicated],
        semantic_type=semantic_type,
        context=ctx,
        profile=SCAFFOLD_PROFILE,
    )
    if country is not None and country_is_derived:
        _drop_rejected_country(
            by_value,
            pool=pool,
            planner=planner,
            ctx=ctx,
            country=country,
        )
    _check_idempotent(by_value, pool=pool, planner=planner, ctx=ctx, stats=stats)
    if adjudication is not None:
        ambiguous = Counter(
            row[column]
            for _, row in pending
            if row[column] is not None
            and row[column] in by_value
            and by_value[row[column]].normalization_status is NormalizationStatus.AMBIGUOUS
        )
        adjudication.collect(
            {v: by_value[v] for v in ambiguous}, ambiguous, semantic_type=semantic_type, context=ctx
        )
    by_value.update(adjudicated)
    for offset, row in pending:
        original = row[column]
        if original is None:
            continue
        result = by_value[original]
        if result.normalization_status is NormalizationStatus.INVALID:
            stats.record_invalid(original)
        # An empty string arriving as NULL is the same absence in a better
        # representation, not a value normalization destroyed — counting it
        # would inflate every text column's rate and could fail a job on
        # `max_new_null_rate` for no real loss. A value that MEANS missing
        # ("maybe", "N/A") is counted: that one really was information.
        counted = result.original_kind is not MissingKind.EMPTY_STRING
        stats.total += counted
        if counted:
            # The SAME gate `total` uses. Counting statuses for every row
            # while counting `total` for only some produced a report whose
            # own categories exceeded its own denominator.
            stats.record_status(result.normalization_status)
        errors = _apply_value(
            row,
            result,
            column=column,
            typed_as=typed_as,
            companion=companion,
            code_column=code_column,
        )
        # After the cast, not before it: a value that normalized fine and
        # then would not fit its native column is the loss this counts.
        if counted and row[column] is None:
            stats.nulled += 1
        if signals is not None:
            _record_country_signal(signals, offset, column, result, errors)

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


def _apply_value(
    row: dict[str, Any],
    result: NormalizedValue,
    *,
    column: str,
    typed_as: str | None,
    companion: str | None,
    code_column: str | None,
) -> list[str]:
    """One row, one column: write every projection the destination has a
    home for, and hand back whatever needs reporting."""
    original = row[column]
    row[column] = result.display
    errors = list(result.errors)

    if companion is not None:
        row[companion] = result.structured.get("currency")
    if code_column is not None:
        row[code_column] = result.comparison

    # A non-empty source value the normalizer read as MISSING lands as
    # NULL with nothing anywhere to say so. `display` is None for
    # MissingKind.UNKNOWN_VALUE, and the status is NORMALIZED, so
    # neither decision #8's raw-string fallback nor the cast below
    # records anything: a BOOLEAN column of "maybe"/"N/A" arrives 100%
    # NULL and reads as a column that was simply empty at source.
    # NULL and EMPTY_STRING are not reported — those need no
    # explanation — and this is checked before the cast so it fires in
    # untyped mode too, where the loss is identical.
    if row[column] is None and result.original_kind is MissingKind.UNKNOWN_VALUE:
        errors.append(f"value {original!r} means missing; stored as NULL")

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
    return errors


def _record_country_signal(
    signals: dict[int, tuple[str, str]],
    offset: int,
    column: str,
    result: NormalizedValue,
    errors: list[str],
) -> None:
    """A resolved COUNTRY column tells every OTHER column in the same row
    which country it is in, which is precisely the `ctx.country` that
    POSTCODE, PHONE, NUMERIC, MONEY and DATE all refuse to guess without.
    Per-row and free: the value was normalized anyway, this only keeps the
    alpha-2 it already produced.

    Two country columns in one row that disagree are reported and NEITHER
    is used (the row falls back to the job-level country) — picking the
    first, or the more confident, is exactly the guess this codebase does
    not make.
    """
    alpha2 = _COUNTRY_FROM[FieldSemanticType.COUNTRY](result)
    if not alpha2:
        return
    seen = signals.setdefault(offset, (column, alpha2))
    if seen[1] and seen[1] != alpha2:
        errors.append(f"country conflict: {column} says {alpha2}, {seen[0]} says {seen[1]}")
        # Empty is sticky, so a third column cannot resurrect a
        # contradicted row.
        signals[offset] = (column, "")


_SAMPLE_VALUES_PER_COLUMN = 3


@dataclasses.dataclass
class _ColumnStats:
    """What one column of one table did, summed across every chunk.

    Every finding it feeds is about the COLUMN, not about any one row, and
    nothing in this pipeline used to say anything at that level: a column
    that arrived 34.5% NULL, and a column where 99.2% of the values are not
    the type they were mapped to, both looked from the destination exactly
    like a column that simply held what it held.

    The per-status counts are the same tally read the other way round — what
    the column achieved rather than what went wrong with it. They cost
    nothing extra to keep (the status of every value is already in hand) and
    they are the one thing that previously had to be reconstructed by
    querying the destination column by column after the fact.
    """

    total: int = 0
    nulled: int = 0
    invalid: int = 0
    unstable: int = 0
    checked_stable: int = 0
    # Keyed by NormalizationStatus VALUE, counted for every status there is
    # rather than for a chosen few. Hand-picking three of the nine members
    # of `NormalizationStatus` silently dropped the rest: measured on a real
    # column, 48,416 of 50,000 values were UNCHANGED (already clean) and the
    # report simply did not mention them, so its own numbers did not add up
    # to the column's. A Counter also cannot fall behind a status added
    # later.
    statuses: Counter[str] = dataclasses.field(default_factory=Counter)
    samples: list[str] = dataclasses.field(default_factory=list)
    unstable_samples: list[str] = dataclasses.field(default_factory=list)

    def record_invalid(self, value: str) -> None:
        self.invalid += 1
        # A handful of real examples is what makes the finding actionable —
        # "99.2% of this column is not a COUNTRY" is a number, but
        # "Country located primarily in North America" is the answer.
        if len(self.samples) < _SAMPLE_VALUES_PER_COLUMN and value not in self.samples:
            self.samples.append(value)

    def record_status(self, status: NormalizationStatus) -> None:
        self.statuses[status.value] += 1

    def record_unstable(self, value: str, again: str) -> None:
        self.unstable += 1
        if len(self.unstable_samples) < _SAMPLE_VALUES_PER_COLUMN:
            self.unstable_samples.append(f"{value!r} -> {again!r}")

    def quality(self) -> dict[str, Any]:
        """The per-column report, as stored on the job.

        `statuses` sums to `values` by construction — that is the property
        that makes the report readable, and the first version did not have
        it.
        """
        return {
            "values": self.total,
            "statuses": dict(sorted(self.statuses.items())),
            "emptied": self.nulled,
            "checked_idempotent": self.checked_stable,
            "not_idempotent": self.unstable,
        }


# How many of a column's distinct NORMALIZED outputs are fed back in per
# chunk to check that normalizing them again changes nothing (§71's
# `normalize(normalize(x)) == normalize(x)`).
#
# A property test already searches for counterexamples, but only over
# GenericTextNormalizer and only over generated strings. Real data is a
# different search: it reaches every semantic type, under the job's real
# country/locale, with values no generator would produce. Bounded per chunk
# because it costs one extra normalize per value checked — and only values
# normalization actually CHANGED are worth checking, since an output equal
# to its input is a fixed point by inspection.
_IDEMPOTENCY_SAMPLE = int(os.environ.get("NORM_CLONE_IDEMPOTENCY_SAMPLE", "50"))


def _check_idempotent(
    by_value: dict[str, NormalizedValue],
    *,
    pool: Any,
    planner: DistinctValuePlanner,
    ctx: NormalizationContext,
    stats: _ColumnStats,
) -> None:
    """Feed this column's own outputs back in; a different answer is a bug.

    Only outputs normalization CHANGED are checked: an output identical to
    its input is a fixed point by inspection, so checking it would spend a
    normalize call to learn nothing. That also makes the check free for a
    column that is already clean.

    Reported, never repaired. A value that will not settle is a defect in a
    normalizer, and quietly applying the second answer would hide it while
    making the destination depend on how many times the pipeline ran.
    """
    changed = [
        result.display
        for original, result in by_value.items()
        if result.display is not None and result.display != original
    ]
    sample = sorted(set(changed))[:_IDEMPOTENCY_SAMPLE]
    if not sample:
        return
    again = _normalize_distinct(
        pool,
        planner,
        sample,
        semantic_type=ctx.semantic_type,
        context=ctx,
        profile=SCAFFOLD_PROFILE,
    )
    for value in sample:
        stats.checked_stable += 1
        settled = again.get(value)
        if settled is not None and settled.display != value:
            stats.record_unstable(value, settled.display or "")


def _drop_rejected_country(
    by_value: dict[str, NormalizedValue],
    *,
    pool: Any,
    planner: DistinctValuePlanner,
    ctx: NormalizationContext,
    country: str,
) -> None:
    """A country taken from a SIBLING TABLE is a hypothesis, not a fact.

    Where the data rejects it — the value normalized INVALID under that
    country — the hypothesis is dropped for that value and the no-country
    result stands, which is what this pipeline produced before any of this
    existed. That keeps the one guarantee cross-table inference could
    otherwise break: a wrong guess must never replace a raw value with a
    confident wrong one.

    Measured on 3,000 real (phone, sibling-table country) pairs from a
    live source: 79.3% of values gained a valid parse from the inferred
    country and 0.23% landed here, so this is the exception that makes the
    other 79% safe rather than a cost. It is only ever reached for a
    cross-table country; a country from the row's own COUNTRY column is
    evidence about that row and is never second-guessed.
    """
    rejected = [
        value
        for value, result in by_value.items()
        if result.normalization_status is NormalizationStatus.INVALID
    ]
    if not rejected:
        return
    without = _normalize_distinct(
        pool,
        planner,
        rejected,
        semantic_type=ctx.semantic_type,
        context=ctx.model_copy(update={"country": None}),
        profile=SCAFFOLD_PROFILE,
    )
    for value, result in without.items():
        if result.normalization_status is NormalizationStatus.INVALID:
            # Rejected either way, so the inferred country was not the
            # problem — a value carrying its own country code, say. Saying
            # "the inferred country does not fit" about those would be a
            # misleading report row for a decision that changed nothing.
            continue
        result.errors.append(
            f"country {country} inferred from a sibling table does not fit this value; "
            "normalized without it"
        )
        by_value[value] = result


# A cross-table entity map is held in memory for the whole of Phase 2, one
# entry per entity. Measured at ~180 bytes per entry (dict overhead plus a
# short str key and a 2-char value), so the default cap is ~360MB worst
# case on a source with that many distinct entities — sized against
# compose.yaml's api.mem_limit, not chosen freely. Past the cap the map
# stops growing and says so: rows whose entity did not make it in simply
# get no inferred country, which is the behaviour without the feature.
_ENTITY_MAP_MAX = int(os.environ.get("NORM_CLONE_ENTITY_MAP_MAX", "2000000"))


def _build_entity_country_map(
    source: Any,
    job: dict[str, Any],
    planner: DistinctValuePlanner,
    key_column: str,
) -> tuple[dict[str, str], dict[str, int]]:
    """`entity id -> alpha-2`, read from every column that can name a
    country (`_COUNTRY_FROM`) sitting in a table that also carries
    `key_column`.

    This is the cross-table half of within-row country propagation. A
    company's country lives in its Location rows; the phone that needs a
    country to parse lives in its Company row; Phase 2 streams one table at
    a time and never holds two, so nothing could connect them.

    `key_column` is declared by the operator, never guessed. Inferring the
    join would mean picking a column that happens to appear in two tables,
    and `_version`/`created_at` appear in every table of both real sources
    this was built against — a wrong join key propagates a WRONG country,
    which is worse than none.

    Entities whose rows disagree about the country are dropped, not
    resolved: on a real 1.76M-row source, 1,565,512 entities had exactly
    one country and 741 (0.047%) had two, and picking one of those two is
    the guess this codebase does not make. "Disagree" is judged within one
    rank — see the scan ordering below.
    """
    mapping: dict[str, str] = {}
    conflicted: set[str] = set()
    stated: set[str] = set()
    alpha2_of: dict[str, str | None] = {}
    counts = {"entities": 0, "conflicts": 0, "over_cap": 0}

    scans = [
        (table, column, FieldSemanticType(semantic_type))
        for table in job["tables"]
        for column, semantic_type in job["field_configs"].get(table, {}).items()
        if semantic_type in _SIGNAL_TYPE_VALUES
    ]
    # A COUNTRY column STATES the entity's country; a phone or a postcode
    # only IMPLIES one, and a company legitimately has phone numbers in
    # several countries while having one registered country. So the stated
    # signals are read first and an implied one never overrides or
    # contradicts them — without this ordering, one +1 number in a company's
    # contact rows silently dropped its stated GB.
    scans.sort(key=lambda scan: scan[2] is not FieldSemanticType.COUNTRY)
    available: dict[str, set[str]] = {}
    for table, column, semantic_type in scans:
        if table not in available:
            available[table] = {c.name for c in source.get_columns(table)}
        if key_column not in available[table]:
            continue
        _scan_entity_countries(
            source,
            table,
            key_column=key_column,
            signal_column=column,
            semantic_type=semantic_type,
            planner=planner,
            mapping=mapping,
            conflicted=conflicted,
            stated=stated,
            alpha2_of=alpha2_of,
            counts=counts,
        )

    counts["entities"] = len(mapping)
    counts["conflicts"] = len(conflicted)
    return mapping, counts


def _scan_entity_countries(
    source: Any,
    table: str,
    *,
    key_column: str,
    signal_column: str,
    semantic_type: FieldSemanticType,
    planner: DistinctValuePlanner,
    mapping: dict[str, str],
    conflicted: set[str],
    stated: set[str],
    alpha2_of: dict[str, str | None],
    counts: dict[str, int],
) -> None:
    """One (table, signal column) pass, for any column type that can say
    which country its row is in — see `_COUNTRY_FROM`.

    The context carries no country on purpose: a PHONE must say
    `number_prefix` (the number's own +CC) to be trusted here, and handing
    it a country would make it say `explicit` instead and feed a country
    straight back to itself.

    `alpha2_of` caches the extraction per distinct raw value, across
    batches and tables — a real source had 617 distinct country strings
    and 149,261 distinct postcodes behind 1.76M rows, so the scan costs
    one dispatcher call per distinct value, not per row."""
    extract = _COUNTRY_FROM[semantic_type]
    implied = semantic_type is not FieldSemanticType.COUNTRY
    ctx = NormalizationContext(
        field_name=signal_column,
        semantic_type=semantic_type,
        table=table,
        error_policy=ErrorPolicy.RETURN_ORIGINAL,
        include_trace=False,
    )
    for batch in source.read_table(
        table, columns=[key_column, signal_column], batch_size=SOURCE_READ_BATCH_ROWS
    ):
        rows = batch.to_pylist()
        unseen = {
            row[signal_column]
            for row in rows
            if row[signal_column] is not None and row[signal_column] not in alpha2_of
        }
        if unseen:
            resolved = _normalize_distinct(
                None,
                planner,
                list(unseen),
                semantic_type=semantic_type,
                context=ctx,
                profile=SCAFFOLD_PROFILE,
            )
            for value, result in resolved.items():
                alpha2_of[value] = extract(result)
        for row in rows:
            key, raw = row[key_column], row[signal_column]
            if key is None or raw is None:
                continue
            alpha2 = alpha2_of.get(raw)
            if not alpha2:
                continue
            # str(): the same entity id is String in one table and
            # Nullable(Int64) in another on a real source, so the map is
            # keyed by the one form both sides agree on.
            entity = str(key)
            if entity in conflicted or (implied and entity in stated):
                continue
            seen = mapping.setdefault(entity, alpha2)
            if seen != alpha2:
                del mapping[entity]
                conflicted.add(entity)
                stated.discard(entity)
            elif len(mapping) > _ENTITY_MAP_MAX:
                del mapping[entity]
                counts["over_cap"] += 1
            elif not implied:
                stated.add(entity)


# Real rows report under their own source-row offset, which is always >= 0.
# A column-level finding belongs to the whole column, so it takes an offset
# no row can occupy — the report table's primary key is
# (job_id, row_index, table_name, field), so this is one row per column.
_COLUMN_REPORT_ROW = -1

# Below this, a column losing values is just the data being messy (an
# unparseable date here and there) and a report row per column would drown
# the per-row findings it sits beside.
_NULL_RATE_REPORT = float(os.environ.get("NORM_CLONE_NULL_RATE_REPORT", "0.05"))

# Half a column failing its own semantic type is a mapping problem; a few
# percent is dirty data, which the per-row report already covers value by
# value. Deliberately high: the finding says "you may have told us the
# wrong type", and saying that about a merely messy column is noise.
_TYPE_MISMATCH_REPORT = float(os.environ.get("NORM_CLONE_TYPE_MISMATCH_REPORT", "0.5"))

# ...and enough values for the fraction to mean anything. "50% of this
# column is not an EMAIL" off two rows is not a finding about the mapping,
# it is one bad row — and small lookup and config tables are everywhere.
# Not an env var: this is the floor below which the statistic is not a
# statistic, not a policy to tune. The null-rate finding deliberately has
# no such floor: losing values is true and worth saying at any scale, where
# accusing an operator of mis-mapping a column is not.
_TYPE_MISMATCH_MIN_VALUES = 20


def _normalize_chunk(
    pending: list[tuple[int, dict[str, Any]]],
    *,
    table: str,
    job: dict[str, Any],
    configured_columns: dict[str, FieldSemanticType],
    typed_columns: dict[str, str],
    currency_columns: dict[str, str],
    code_columns: dict[str, str],
    pool: Any,
    planner: DistinctValuePlanner,
    seeded: Mapping[int, str],
    stats: dict[str, _ColumnStats],
    errors_buffer: list[dict[str, Any]],
    adjudication: Adjudication | None = None,
) -> None:
    """Every configured column of one chunk, COUNTRY columns first.

    Order matters: a resolved COUNTRY column supplies `ctx.country` for
    every other column of the same row, and most normalizers refuse to
    guess without it (a POSTCODE cannot be validated against "somewhere",
    `1,234` could group or decimalise). So the country columns run against
    the job-level context, and the rest run once per country found —
    grouping, because the distinct-value dedup below is per context, and a
    per-row context would defeat it entirely.

    `seeded` carries the cross-table country for rows whose entity was
    found in the job's entity map. A COUNTRY column in the row itself
    always beats it — evidence about this row beats evidence about the
    entity — and a seeded country the data then rejects is dropped per
    value (see `_drop_rejected_country`).
    """
    # Every row must carry the same keys: bulk_insert derives the column
    # list from rows[0], so a companion column that only appears on rows
    # with a non-null amount would build an INSERT that is wrong for
    # every other row.
    for _, row in pending:
        for extra in (*currency_columns.values(), *code_columns.values()):
            row[extra] = None

    job_country = job.get("country")
    signals: dict[int, tuple[str, str]] = {}
    country_first = sorted(
        configured_columns.items(),
        key=lambda item: item[1] is not FieldSemanticType.COUNTRY,
    )
    for column, semantic_type in country_first:
        # COUNTRY only, even though PHONE and POSTCODE can also name a
        # country (`_COUNTRY_FROM`). Those two also CONSUME one, so making
        # them within-row providers would mean normalizing them before the
        # row's own COUNTRY column is known — losing the country they
        # currently get from it, which is worth 73.8 points of E.164
        # coverage on a real source. They feed the cross-table entity map
        # instead, which is built in its own pass and has no such ordering.
        provides_country = semantic_type is FieldSemanticType.COUNTRY
        # No country column resolved anything (or there is none), so this
        # is one group with the job-level country — identical to the
        # behaviour before signals existed, and identical in cost.
        groups = (
            {(job_country, False): pending}
            if provides_country or not (signals or seeded)
            else _group_by_country(pending, signals, seeded, job_country)
        )
        for (country, derived), group in groups.items():
            _apply_column(
                group,
                column=column,
                semantic_type=semantic_type,
                table=table,
                source_id=job["source_connection_id"],
                pool=pool,
                planner=planner,
                typed_as=typed_columns.get(column),
                companion=currency_columns.get(column),
                code_column=code_columns.get(column),
                country=country,
                locale=job.get("locale"),
                signals=signals if provides_country else None,
                country_is_derived=derived,
                stats=stats[column],
                errors_buffer=errors_buffer,
                adjudication=adjudication,
            )


def _group_by_country(
    pending: list[tuple[int, dict[str, Any]]],
    signals: dict[int, tuple[str, str]],
    seeded: Mapping[int, str],
    default: str | None,
) -> dict[tuple[str | None, bool], list[tuple[int, dict[str, Any]]]]:
    """Partition a chunk by the country each row resolved to, and by where
    that country came from.

    Precedence: the row's own COUNTRY column, then the cross-table entity
    map, then the job-level country. A row with two country columns that
    contradicted each other has no within-row answer and falls through to
    the next source, same as a row that had none.

    The second half of the key is whether the country was inferred from
    another table. Two rows can agree on the country and still belong to
    different groups, because only the inferred one may be second-guessed
    by the data."""
    groups: dict[tuple[str | None, bool], list[tuple[int, dict[str, Any]]]] = {}
    for item in pending:
        own = signals.get(item[0], ("", ""))[1]
        inferred = seeded.get(item[0]) if not own else None
        groups.setdefault((own or inferred or default, inferred is not None), []).append(item)
    return groups


def _report_column_findings(
    persistence: PgPersistence,
    job_id: str,
    table: str,
    *,
    stats: Mapping[str, _ColumnStats],
    semantic_types: Mapping[str, FieldSemanticType],
    ceiling: float | None,
) -> None:
    """One report row per column with something to say about the column
    itself rather than about any of its rows.

    Two findings share the row because the report table is keyed by
    (job, row_index, table, field) and a column has exactly one slot:

    - **emptied** — normalization turned values into NULL. A typed
      destination column NULLs everything that will not cast, and a per-row
      finding for each one is invisible in aggregate: measured on a real
      source, typing `companyRevenue` NULLed 34.5% of it (comma-grouped
      values, with no locale to read them by) and the clone looked exactly
      like a column that was simply sparse.
    - **not this type** — the values are not what the column was mapped to.
      Measured on a real source, `location.country` held Wikidata
      *descriptions* ("Country located primarily in North America"), so
      99.2% of it came back INVALID. That is one fact about the column's
      mapping, not 3,478 independent bad rows, and reading it per row means
      reading 3,478 rows to learn it.

    AMBIGUOUS deliberately does not count toward the second. A POSTCODE
    column with no country is 100% AMBIGUOUS and perfectly well typed — the
    normalizer refused to guess, which is not the column being wrong.

    The third finding, **not idempotent**, has no threshold: §71 says
    `normalize(normalize(x)) == normalize(x)`, so ONE value that will not
    settle is a defect worth a row, not a rate to tolerate.
    """
    rows = []
    for column, stat in sorted(stats.items()):
        if not stat.total:
            continue
        findings = []
        emptied = stat.nulled / stat.total
        mistyped = stat.invalid / stat.total
        if emptied >= _NULL_RATE_REPORT:
            findings.append(
                f"normalization emptied {emptied:.1%} of this column "
                f"({stat.nulled}/{stat.total} values)"
            )
            if ceiling is not None and emptied > ceiling:
                msg = (
                    f"{table}.{column}: {findings[-1]}, over the job's "
                    f"max_new_null_rate of {ceiling}"
                )
                raise CloneJobStateError(msg)
        if stat.unstable:
            findings.append(
                f"{stat.unstable} of {stat.checked_stable} normalized values in this column "
                f"change again when normalized a second time, e.g. "
                f"{'; '.join(stat.unstable_samples)} — normalization is not converging "
                "(Source.txt §71)"
            )
        if mistyped >= _TYPE_MISMATCH_REPORT and stat.total >= _TYPE_MISMATCH_MIN_VALUES:
            examples = ", ".join(repr(v) for v in stat.samples)
            findings.append(
                f"{mistyped:.1%} of this column is not a "
                f"{semantic_types[column].value} ({stat.invalid}/{stat.total} values, "
                f"e.g. {examples}) — it may be mapped to the wrong semantic type"
            )
        if findings:
            rows.append(
                {
                    "row_index": _COLUMN_REPORT_ROW,
                    "table_name": table,
                    "field": column,
                    "original": None,
                    "error": "; ".join(findings),
                }
            )
    if rows:
        persistence.save_clone_job_errors(job_id, rows)


# The entity map is a property of the JOB, not of any table, column or
# row, so its one report row belongs to no table and no field.
_JOB_REPORT_FIELD = ""


def _report_entity_map(
    persistence: PgPersistence,
    job_id: str,
    key_column: str,
    counts: Mapping[str, int],
) -> None:
    """What the cross-table entity map actually found, recorded once.

    Worth a row even when nothing went wrong: the map silently supplying no
    countries (wrong key column, no COUNTRY column in a table that carries
    it) and the map working perfectly look identical from the destination.
    """
    message = (
        f"cross-table entity map on {key_column!r}: {counts['entities']:,} entities "
        f"with one country, {counts['conflicts']:,} dropped for disagreeing"
    )
    if counts["over_cap"]:
        message += (
            f", {counts['over_cap']:,} skipped over the "
            f"NORM_CLONE_ENTITY_MAP_MAX cap of {_ENTITY_MAP_MAX:,}"
        )
    persistence.save_clone_job_errors(
        job_id,
        [
            {
                "row_index": _COLUMN_REPORT_ROW,
                "table_name": _JOB_REPORT_FIELD,
                "field": _JOB_REPORT_FIELD,
                "original": None,
                "error": message,
            }
        ],
    )


def _seed_from_entity_map(
    pending: list[tuple[int, dict[str, Any]]],
    key_column: str,
    entity_countries: Mapping[str, str],
) -> dict[int, str]:
    """Row offset -> the country this row's ENTITY resolved to elsewhere.

    An empty key column means the feature is off for this table, which
    costs one branch per chunk."""
    if not key_column:
        return {}
    seeded = {}
    for offset, row in pending:
        key = row.get(key_column)
        if key is None:
            continue
        alpha2 = entity_countries.get(str(key))
        if alpha2:
            seeded[offset] = alpha2
    return seeded


def _normalize_table(
    table: str,
    *,
    job: dict[str, Any],
    job_id: str,
    source: Any,
    dest: Any,
    source_engine: str,
    persistence: PgPersistence,
    planner: DistinctValuePlanner,
    pool: Any,
    progress: dict[str, Any],
    in_place: bool,
    entity_countries: Mapping[str, str],
    adjudication: Adjudication | None = None,
) -> None:
    """One table, end to end: stream it, normalize every configured
    column, insert, checkpoint, and — in-place only — swap it in.

    Extracted from `_run_phase2`, which had grown to 63 statements across
    15 branches doing connection setup, the per-table work and failure
    handling all at once. Marking the table completed stays with the
    caller, which owns that set.
    """
    progress["current_table"] = table
    field_config = job["field_configs"].get(table, {})
    # FieldSemanticType, not the raw string stored in the job's
    # JSON blob — Dispatcher.normalize's `context.semantic_type
    # is not semantic_type` identity check (normcore/dispatch.py)
    # requires the actual enum member on both sides, not a
    # same-valued string (an `is` check, not `==`).
    configured_columns = {c: FieldSemanticType(t) for c, t in field_config.items() if t}
    primary_key = list(source.get_primary_key(table)) if source_engine == "postgres" else []
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
    code_columns: dict[str, str] = table_plan.get("code_columns", {})
    stats = {column: _ColumnStats() for column in configured_columns}
    # Only this table's own key column matters: a table that does not carry
    # it gets no cross-table country, which is the behaviour without the
    # feature. Empty means off for this table.
    declared_key: str = job.get("cross_table_entity_key") or ""
    key_column = (
        declared_key
        if entity_countries and declared_key in {c.name for c in source.get_columns(table)}
        else ""
    )

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
        seeded = _seed_from_entity_map(pending, key_column, entity_countries)
        _normalize_chunk(
            pending,
            table=table,
            job=job,
            configured_columns=configured_columns,
            typed_columns=typed_columns,
            currency_columns=currency_columns,
            code_columns=code_columns,
            pool=pool,
            planner=planner,
            seeded=seeded,
            stats=stats,
            errors_buffer=errors_buffer,
            adjudication=adjudication,
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
        _save_progress(
            persistence, job_id, job, adjudication.drain() if adjudication is not None else None
        )

    # Before the swap, deliberately: a job that trips its own
    # max_new_null_rate ceiling in in-place mode must leave the ORIGINAL
    # table in place. Failing after the swap would have already replaced
    # the source with the table the ceiling exists to reject.
    _report_column_findings(
        persistence,
        job_id,
        table,
        stats=stats,
        semantic_types=configured_columns,
        ceiling=job.get("max_new_null_rate"),
    )
    # What each column achieved, not only what went wrong with it. Kept on
    # the job rather than in the error report because it is a result, not a
    # finding — and read separately from `GET /clone-jobs/{id}`, which the
    # UI polls every two seconds and should not carry a per-column table.
    job.setdefault("quality", {})[table] = {
        column: stat.quality() for column, stat in sorted(stats.items()) if stat.total
    }

    if in_place:
        # Swap only after the table is fully written, and BEFORE
        # it is marked completed: a crash between the two replays
        # a table that is already normalized, which re-reads the
        # source and rebuilds a staging table that no longer
        # exists — so the swap is what "completed" must mean here.
        dest.swap_table(job["destination_database"], table, write_target)

    job["progress"] = progress
    _save_progress(persistence, job_id, job)


def _run_phase2(
    persistence: PgPersistence,
    dispatcher: Dispatcher,
    cache: NormalizationCache | None,
    job_id: str,
) -> None:
    # Phase 2 runs on a daemon thread, so a missing job or connection here
    # surfaces as an AttributeError deep in the first table rather than as
    # anything a caller can read. They are genuinely unexpected — the job
    # was claimed moments ago — so this is an assertion of an invariant,
    # not error handling for a case that happens.
    job = persistence.get_clone_job(job_id)
    if job is None:
        raise CloneJobNotFoundError(job_id)
    source_conn = _require_connection(persistence, job["source_connection_id"])
    dest_conn = _require_connection(persistence, job["destination_connection_id"])
    source = build_source_connector(source_conn, job["source_database"], job.get("source_schema"))
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
    entity_countries: dict[str, str] = {}
    adjudication = Adjudication(persistence, SCAFFOLD_PROFILE)

    try:
        key_column = job.get("cross_table_entity_key") or None
        if key_column:
            # Rebuilt on resume rather than persisted: it is one bounded
            # extra read of two columns per country-bearing table (617
            # distinct country strings behind 1.76M rows on a real source),
            # and it is advisory context, not state a resumed job must
            # agree with byte for byte.
            entity_countries, counts = _build_entity_country_map(source, job, planner, key_column)
            _report_entity_map(persistence, job_id, key_column, counts)
        for table in job["tables"]:
            if table in tables_completed:
                continue
            _normalize_table(
                table,
                job=job,
                job_id=job_id,
                source=source,
                dest=dest,
                source_engine=source_conn["engine"],
                persistence=persistence,
                planner=planner,
                pool=pool,
                progress=progress,
                in_place=in_place,
                entity_countries=entity_countries,
                adjudication=adjudication,
            )
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

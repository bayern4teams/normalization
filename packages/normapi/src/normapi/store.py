"""In-memory profile/run store, optionally backed by Postgres for
persistence — Source.txt §98, ADR-013.

M9 adds real persistence: when constructed with a `postgres_dsn`
(normally `NORM_PG_DSN`), every profile/run write is mirrored to
`PostgresMetadataStore` (see postgres_store.py), and the in-memory dicts
are hydrated from Postgres once at startup — so a process restart no
longer loses every profile and run. The in-memory dicts remain the hot
read path (no DB round-trip per request); Postgres is the durable
write-through target, not a cache-through read path, matching how
`NormalizationCache` already treats its own two tiers. When no DSN is
given (every existing test's plain `InMemoryStore()`/`InMemoryStore(cache)`
construction), behavior is unchanged from M1-M8 — pure in-memory, nothing
survives a restart.

A run's bulk per-value execution results (`_RunExecution.originals`/
`.results`) are handled separately, per ADR-013: they're written through
to `normio.SidecarStore` (Arrow/Parquet, built in M1, now wired in here)
rather than Postgres, matching ADR-013's own metadata-vs-bulk-data split.
When a `sidecar_parquet_root`/`sidecar_duckdb_path` pair is given
(normally `NORM_SIDECAR_PARQUET_ROOT`/`NORM_SIDECAR_DUCKDB_PATH`, both
declared in compose.yaml since M0 but never read by any code until now),
`execute_run()` writes every result to the sidecar, and `get_execution()`
transparently reconstructs a run's results from it when the in-memory
`_executions` dict doesn't have them (i.e. after a restart) — the
`invariant_report` on a sidecar-hydrated execution is `sampled=0`,
`violations=()`, since runtime invariant sampling is a live-only
artifact that cannot be reconstructed after the fact, not a fabricated
"still clean" claim.

M6 adds real run *execution*: `execute_run()` actually normalizes the
supplied values through a live Dispatcher (not a stub), storing the
original/result pairs so `/runs/{id}/errors`, `/runs/{id}/collisions`,
and `/impact` can report real data derived from an actual normalization
pass instead of hardcoded empty lists.

M8 wires in the distinct-value-first planner + two-tier cache
(`normexec`, real and tested since M1 but never actually connected to
this execution path — found during the M7 follow-up self-audit's
sibling M8 planning) — a real gap against §102's "repeated values
should be normalized once per profile/version." `execute_run()` now
dedups on distinct raw values and reuses cached results across calls
sharing the same (profile_version, semantic_type, context, env_id).
"""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pyarrow as pa
from normcore.contract import (
    NORMALIZED_VALUE_ARROW_SCHEMA,
    arrow_row_to_normalized_value,
    normalized_value_to_arrow_row,
)
from normexec.planner import DistinctValuePlanner
from normexec.sinks import SidecarRunSink
from normexec.stream import stream_column
from normio.capabilities import CatalogConnector
from normio.sidecar_store import SidecarStore

from normanalysis import (
    QUALITY_METRIC_DEFS,
    CollisionDecision,
    CollisionDecisionType,
    ColumnStats,
    InvariantSampleReport,
    RunRecorder,
    compute_column_stats_from_results,
    find_collisions,
    record_run_metrics,
    sample_and_check,
)
from normapi.postgres_store import ColumnStatsRow, PostgresMetadataStore
from normcore import (
    FieldNormalizationConfig,
    FieldSemanticType,
    NormalizationContext,
    NormalizationProfile,
    NormalizationRun,
    NormalizationRunMetrics,
    NormalizationStatus,
    NormalizedValue,
    ProfileStatus,
    RunColumnSpec,
    RunProgress,
    RunStatus,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from normexec.cache import NormalizationCache
    from normexec.stream import ChunkProgress
    from normio.capabilities import StreamingCatalogSourceConnector, StreamingSourceConnector

    from normanalysis import NormalizationMetrics, TelemetryHandles
    from normapi.executor import RunExecutor
    from normcore import Dispatcher, ErrorPolicy


class ProfileNotFoundError(LookupError):
    pass


class RunNotFoundError(LookupError):
    pass


class RunNotExecutableError(RuntimeError):
    """Raised when execute_run() is called on a run that already reached
    a terminal status — a run's field execution happens at most once,
    consistent with NormalizationRun being immutable once terminal."""


class UnknownCollisionError(LookupError):
    """Raised when a collision decision references a normalized_value
    that isn't actually a real collision group for that run (§92,
    M11)."""


_SIDECAR_SCHEMA = pa.schema(
    [
        pa.field("source_row_key", pa.large_string()),
        pa.field("row_ordinal", pa.int64()),
        *NORMALIZED_VALUE_ARROW_SCHEMA,
    ]
)


def _results_to_record_batch(results: list[NormalizedValue]) -> pa.RecordBatch:
    """One row per result, `source_row_key` = its index (see
    `_write_execution_to_sidecar`'s docstring for why an index is a
    legitimate stand-in for a real source_row_key here) and `row_ordinal`
    the same index as a genuine int64 — the field `_table_to_results`
    actually sorts by. `source_row_key` becomes a real, non-numeric,
    connector-derived key once M17 wires streamed source data into this
    same sidecar (`normio`'s connectors now emit keys like
    `personID\\x1fcontactString`, not a positional index); `row_ordinal`
    is what stays sortable regardless of what `source_row_key` looks
    like."""
    rows = [normalized_value_to_arrow_row(result) for result in results]
    arrays = [
        pa.array(
            [
                str(i)
                if field.name == "source_row_key"
                else i
                if field.name == "row_ordinal"
                else rows[i][field.name]
                for i in range(len(rows))
            ],
            type=field.type,
        )
        for field in _SIDECAR_SCHEMA
    ]
    return pa.RecordBatch.from_arrays(arrays, schema=_SIDECAR_SCHEMA)


def _table_to_results(table: pa.Table) -> tuple[list[str | None], list[NormalizedValue]]:
    """Inverse of `_results_to_record_batch`, reading a whole run back
    (originals, results) in original row order. Sorts by `row_ordinal` —
    a real int64 column — rather than parsing `source_row_key` as an int;
    the latter crashes the instant a source_row_key stops being a
    positional integer (verified real gap, found during M14: a
    connector-derived key is a composite string, e.g.
    `"10000023481\\x1flonnyr@gmail.com"`, and `int(...)` on that raises
    ValueError)."""
    rows = table.to_pylist()
    rows.sort(key=lambda row: row["row_ordinal"])
    results = [arrow_row_to_normalized_value(row) for row in rows]
    originals: list[str | None] = [row["original"] for row in rows]
    return originals, results


def _chunk_table_to_results(table: pa.Table) -> tuple[list[str | None], list[NormalizedValue]]:
    """Reads back a M17 multi-column run's real per-value results in
    natural (part-file, then within-part) order. Unlike `_table_to_results`
    (the pasted-values shape), M17's chunk schema
    (`normexec.stream._CHUNK_SIDECAR_SCHEMA`) has no `row_ordinal`
    column to sort by — none is needed: `SidecarStore.read_run` already
    orders parts by `part_path` (zero-padded chunk index, so
    lexicographic order is numeric order), and within one chunk,
    `stream.py`'s `_results_to_batch` preserves the connector's own
    keyset-paginated row order. No explicit sort key survives round-
    tripping through this schema, so relying on read order here is the
    only option, not a shortcut."""
    rows = table.to_pylist()
    results = [arrow_row_to_normalized_value(row) for row in rows]
    originals: list[str | None] = [row["original"] for row in rows]
    return originals, results


def _resolve_key_columns(connector: StreamingSourceConnector, table: str) -> list[str]:
    """M17: real primary-key columns, via `CatalogConnector.table_spec`
    (per M14, never parsed out of a sorting-key expression) — `read_chunk`
    requires at least one key column, so a table with no declared primary
    key cannot be streamed this way (unlike `read_table`'s positional-key
    fallback, which has no meaning for keyset pagination)."""
    if not isinstance(connector, CatalogConnector):
        msg = "Streaming a column requires a connector with catalog support to resolve its key"
        raise ValueError(msg)
    key_columns = list(connector.table_spec(table).primary_key)
    if not key_columns:
        msg = f"Table {table!r} has no declared primary key; cannot be streamed chunk by chunk"
        raise ValueError(msg)
    return key_columns


def _column_stats_row_to_model(row: ColumnStatsRow) -> ColumnStats:
    return ColumnStats(
        table=row.table_name,
        column=row.column_name,
        semantic_type=row.semantic_type,
        rows_processed=row.rows_processed,
        rows_changed=row.rows_changed,
        rows_ambiguous=row.rows_ambiguous,
        warnings_total=row.warnings_total,
        errors_total=row.errors_total,
        unique_before=row.unique_before,
        unique_after=row.unique_after,
        quality_metric_name=row.quality_metric_name,
        quality_issue_count=row.quality_issue_count,
    )


def _column_stats_to_row(run_id: str, stats: ColumnStats) -> ColumnStatsRow:
    return ColumnStatsRow(
        run_id=run_id,
        table_name=stats.table,
        column_name=stats.column,
        semantic_type=stats.semantic_type,
        rows_processed=stats.rows_processed,
        rows_changed=stats.rows_changed,
        rows_ambiguous=stats.rows_ambiguous,
        warnings_total=stats.warnings_total,
        errors_total=stats.errors_total,
        unique_before=stats.unique_before,
        unique_after=stats.unique_after,
        quality_metric_name=stats.quality_metric_name,
        quality_issue_count=stats.quality_issue_count,
    )


def _quality_sql_predicate_for(semantic_type: FieldSemanticType) -> str | None:
    """The fixed DuckDB predicate fragment (never user input — see
    `SidecarStore.compute_column_stats`'s docstring) for the one quality
    metric (if any) `semantic_type` feeds, or `None` for a semantic type
    the quality dashboard doesn't track."""
    metric_def = next((m for m in QUALITY_METRIC_DEFS if m.semantic_type is semantic_type), None)
    return metric_def.sql_predicate if metric_def is not None else None


def _estimate_total_rows(
    connector: StreamingSourceConnector, columns: tuple[RunColumnSpec, ...]
) -> int | None:
    """Best-effort progress-bar denominator — sums each DISTINCT table's
    `approx_rows` (per M14, never an exact bound) across the run's
    columns. `None` if the connector has no catalog support or any
    lookup fails, rather than a guessed number."""
    if not isinstance(connector, CatalogConnector):
        return None
    tables = {column_spec.table for column_spec in columns}
    try:
        return sum(connector.table_spec(table).approx_rows or 0 for table in tables)
    except ValueError:
        return None


class _RunExecution:
    __slots__ = ("field_name", "invariant_report", "originals", "results", "semantic_type")

    def __init__(
        self,
        *,
        field_name: str,
        semantic_type: FieldSemanticType,
        originals: list[str | None],
        results: list[NormalizedValue],
        invariant_report: InvariantSampleReport,
    ) -> None:
        self.field_name = field_name
        self.semantic_type = semantic_type
        self.originals = originals
        self.results = results
        self.invariant_report = invariant_report


class InMemoryStore:
    def __init__(
        self,
        cache: NormalizationCache | None = None,
        *,
        postgres_dsn: str | None = None,
        sidecar_parquet_root: str | Path | None = None,
        sidecar_duckdb_path: str | Path | None = None,
        telemetry: tuple[TelemetryHandles, NormalizationMetrics] | None = None,
    ) -> None:
        # profile_id -> {version: NormalizationProfile}
        self._profiles: dict[str, dict[str, NormalizationProfile]] = {}
        # profile_id -> currently active version (per ADR-014, only one
        # version is ACTIVE at a time; earlier versions become DEPRECATED)
        self._active_version: dict[str, str] = {}
        self._runs: dict[str, NormalizationRun] = {}
        self._executions: dict[str, _RunExecution] = {}
        # M17: `_runs`/`_executions` are mutated from background threads
        # (M11's single execution thread, now M17's bounded worker pool —
        # several chunk-writers can be live at once, not just one
        # background thread, making the pre-M17 unguarded-dict race a
        # routine occurrence instead of a rare one). One coarse lock
        # around every read/write of these two dicts, not a per-run lock
        # — simple and correct; a real, disclosed trade-off is that
        # `_hydrate_execution_from_sidecar`'s disk I/O runs while this
        # lock is held (see `get_execution`), so a slow sidecar read
        # briefly blocks other runs' access too. Not a bottleneck at this
        # program's scale, but not free either.
        self._runs_lock = threading.Lock()
        # (run_id, normalized_value) -> a human reviewer's real decision
        # on that collision group (§92, M11).
        self._collision_decisions: dict[tuple[str, str], CollisionDecision] = {}
        # (run_id, table, column) -> that column's bounded rollup stats
        # (M18) — what `GET /overview`/`GET /quality` read instead of
        # ever hydrating a run's full per-value results. A dedicated lock
        # (not `_runs_lock`) since this dict is written independently of
        # `_runs`/`_executions` and read in one large sweep by the two
        # dashboard routes; no need to share the coarser lock's blast
        # radius with them.
        self._column_stats: dict[tuple[str, str, str], ColumnStats] = {}
        self._stats_lock = threading.Lock()
        # Optional (defaults to no caching, matching prior behavior for
        # any caller/test that constructs a bare InMemoryStore) — real
        # distinct-value dedup + cross-call caching only activates when a
        # NormalizationCache is supplied, which normapi.app always does.
        self._cache = cache
        # Optional (defaults to pure in-memory, matching every existing
        # test's construction) — real persistence only activates when a
        # Postgres DSN is supplied, which normapi.app does when NORM_PG_DSN
        # is set. See this module's docstring for the write-through design.
        self._pg = PostgresMetadataStore(postgres_dsn) if postgres_dsn else None
        if self._pg is not None:
            self._hydrate_from_postgres(self._pg)
        # Optional (defaults to pure in-memory, same rationale as above)
        # — real per-value result persistence only activates when BOTH
        # sidecar paths are given, matching NORM_SIDECAR_PARQUET_ROOT/
        # NORM_SIDECAR_DUCKDB_PATH both being set. Unlike Postgres,
        # there's nothing to eagerly hydrate at startup — sidecar data is
        # looked up lazily, per run_id, only when get_execution() actually
        # needs it (see _hydrate_execution_from_sidecar).
        self._sidecar = (
            SidecarStore(sidecar_parquet_root, sidecar_duckdb_path)
            if sidecar_parquet_root and sidecar_duckdb_path
            else None
        )
        # Optional (defaults to no telemetry emission, same rationale as
        # above) — §122 real OTel metrics/spans only emitted when
        # `normapi.app.create_app()` supplies handles, closing the gap
        # where `setup_telemetry()`/`NormalizationMetrics` were real and
        # tested since M1 but never actually reachable from the live app
        # (found during M12's observability-export work).
        self._telemetry = telemetry

    @property
    def postgres_store(self) -> PostgresMetadataStore | None:
        """Exposes the same Postgres connection profiles/runs already
        write through to — M15's connection registry reuses it rather
        than opening a second Postgres connection for one more table."""
        return self._pg

    def _hydrate_from_postgres(self, pg: PostgresMetadataStore) -> None:
        """Reconstructs in-memory state from whatever a PREVIOUS process
        already persisted — the actual "survives a restart" mechanism.
        Runs before this store serves a single request. Loads every
        version of every profile (not just active or run-referenced
        ones), so nothing is silently missing after a restart."""
        for profile in pg.list_all_profiles():
            self._profiles.setdefault(profile.id, {})[profile.version] = profile
        self._active_version.update(pg.list_all_active_versions())
        for run in pg.list_runs():
            self._runs[run.id] = run
        for decision in pg.list_all_collision_decisions():
            self._collision_decisions[(decision.run_id, decision.normalized_value)] = decision
        for row in pg.list_all_column_stats():
            self._column_stats[(row.run_id, row.table_name, row.column_name)] = (
                _column_stats_row_to_model(row)
            )

    def create_profile(
        self,
        *,
        name: str,
        description: str,
        locale_policy: dict[str, str],
        default_operations: tuple[str, ...],
        field_configs: tuple[FieldNormalizationConfig, ...],
        created_by: str,
    ) -> NormalizationProfile:
        profile_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        profile = NormalizationProfile(
            id=profile_id,
            name=name,
            version="v1",
            description=description,
            status=ProfileStatus.ACTIVE,
            locale_policy=locale_policy,
            default_operations=default_operations,
            field_configs=field_configs,
            created_at=now,
            updated_at=now,
            created_by=created_by,
            parent_version=None,
        )
        self._profiles[profile_id] = {"v1": profile}
        self._active_version[profile_id] = "v1"
        if self._pg is not None:
            self._pg.save_profile(profile)
            self._pg.set_active_version(profile_id, "v1")
        return profile

    def create_version(
        self,
        profile_id: str,
        *,
        description: str | None,
        locale_policy: dict[str, str] | None,
        default_operations: tuple[str, ...] | None,
        field_configs: tuple[FieldNormalizationConfig, ...] | None,
        created_by: str,
    ) -> NormalizationProfile:
        """New version, immutable per ADR-014 — the previous version is
        never edited, only superseded as the active one."""
        if profile_id not in self._profiles:
            raise ProfileNotFoundError(profile_id)

        current_version = self._active_version[profile_id]
        current = self._profiles[profile_id][current_version]
        next_version = f"v{int(current_version.removeprefix('v')) + 1}"
        now = datetime.now(UTC).isoformat()

        new_profile = NormalizationProfile(
            id=profile_id,
            name=current.name,
            version=next_version,
            description=description if description is not None else current.description,
            status=ProfileStatus.ACTIVE,
            locale_policy=locale_policy if locale_policy is not None else current.locale_policy,
            default_operations=(
                default_operations if default_operations is not None else current.default_operations
            ),
            field_configs=(field_configs if field_configs is not None else current.field_configs),
            created_at=now,
            updated_at=now,
            created_by=created_by,
            parent_version=current_version,
        )

        deprecated_current = current.model_copy(update={"status": ProfileStatus.DEPRECATED})
        self._profiles[profile_id][current_version] = deprecated_current
        self._profiles[profile_id][next_version] = new_profile
        self._active_version[profile_id] = next_version
        if self._pg is not None:
            self._pg.save_profile(deprecated_current)
            self._pg.save_profile(new_profile)
            self._pg.set_active_version(profile_id, next_version)
        return new_profile

    def rollback_profile(self, profile_id: str, target_version: str) -> NormalizationProfile:
        """Reactivates a prior version (§59/§94's "Rollback Profile") —
        does NOT delete the version being rolled back from, so rolling
        forward again afterward is always possible."""
        if profile_id not in self._profiles:
            raise ProfileNotFoundError(profile_id)
        if target_version not in self._profiles[profile_id]:
            raise ProfileNotFoundError(f"{profile_id}@{target_version}")

        current_version = self._active_version[profile_id]
        if current_version != target_version:
            current = self._profiles[profile_id][current_version]
            deprecated_current = current.model_copy(update={"status": ProfileStatus.DEPRECATED})
            self._profiles[profile_id][current_version] = deprecated_current
            if self._pg is not None:
                self._pg.save_profile(deprecated_current)

        target = self._profiles[profile_id][target_version]
        reactivated = target.model_copy(update={"status": ProfileStatus.ACTIVE})
        self._profiles[profile_id][target_version] = reactivated
        self._active_version[profile_id] = target_version
        if self._pg is not None:
            self._pg.save_profile(reactivated)
            self._pg.set_active_version(profile_id, target_version)
        return reactivated

    def get_profile(self, profile_id: str, version: str | None = None) -> NormalizationProfile:
        if profile_id not in self._profiles:
            raise ProfileNotFoundError(profile_id)
        resolved_version = version or self._active_version[profile_id]
        if resolved_version not in self._profiles[profile_id]:
            raise ProfileNotFoundError(f"{profile_id}@{resolved_version}")
        return self._profiles[profile_id][resolved_version]

    def list_profile_versions(self, profile_id: str) -> list[NormalizationProfile]:
        if profile_id not in self._profiles:
            raise ProfileNotFoundError(profile_id)
        return list(self._profiles[profile_id].values())

    def list_profiles(self) -> list[NormalizationProfile]:
        return [self._profiles[pid][v] for pid, v in self._active_version.items()]

    def create_run(self, *, profile_id: str, env_id: str, source_snapshot: str) -> NormalizationRun:
        profile = self.get_profile(profile_id)
        run_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        run = NormalizationRun(
            id=run_id,
            profile_id=profile_id,
            profile_version=profile.version,
            env_id=env_id,
            source_snapshot=source_snapshot,
            started_at=now,
            status=RunStatus.PENDING,
            metrics=NormalizationRunMetrics(),
        )
        with self._runs_lock:
            self._runs[run_id] = run
        if self._pg is not None:
            self._pg.save_run(run)
        return run

    def start_run_execution(
        self,
        run_id: str,
        *,
        dispatcher: Dispatcher,
        field_name: str,
        semantic_type: FieldSemanticType | None = None,
        resolve_values: Callable[[], Sequence[str | None]],
        error_policy: ErrorPolicy | None = None,
        field_ref: str | None = None,
        executor: RunExecutor | None = None,
    ) -> NormalizationRun:
        """Starts a run's execution in the background and returns
        immediately (M11) — Source.txt §70's own `RunStatus` already
        modeled RUNNING/FAILED as real lifecycle states; M6-M10's
        `execute_run()` always finished synchronously within the same
        request, so no caller could ever actually observe them. Poll
        `GET /runs/{id}`: the run stays PENDING until the background
        work's `RunRecorder.start()` transitions it to RUNNING (the
        recorder itself owns that PENDING->RUNNING transition and
        rejects being constructed on anything but a PENDING run — this
        method deliberately does NOT also set RUNNING itself, to avoid
        two different places racing to make the same transition), then
        COMPLETED/FAILED when done.

        `resolve_values` is called INSIDE the background work, not
        before returning — for a source-mode run this is where the real,
        potentially slow connector read happens, off the request/
        response path (M10's row cap existed specifically because that
        read used to block the request; it still applies as a memory
        bound, but no longer as a latency one).

        `execute_run` itself is untouched and remains the synchronous,
        directly-testable primitive every existing test already uses;
        this is a thin background wrapper around it, used only by the
        live HTTP route.

        `executor` (M17): when given, the work runs on `RunExecutor`'s
        bounded worker pool instead of a raw `threading.Thread` — the
        live HTTP route (`normapi.routes.create_run`) always passes one;
        direct test calls that construct an `InMemoryStore` and call this
        method without one keep the original raw-thread behavior
        unchanged, so no existing test needed rewriting for this.

        `semantic_type`/`field_ref` (M16): both optional now — see
        `execute_run`'s own docstring for the real bug this closes
        (`execution.semantic_type` used to win unconditionally over a
        matched profile field_config's semantic_type, and `field_name`
        alone was never a real `field_ref` a profile's `field_configs`
        could actually match against)."""
        run = self.get_run(run_id)
        if run.is_terminal():
            msg = f"Run {run_id!r} already reached terminal status {run.status!r}"
            raise RunNotExecutableError(msg)

        def task() -> None:
            self._run_execution_worker(
                run_id=run_id,
                dispatcher=dispatcher,
                field_name=field_name,
                semantic_type=semantic_type,
                resolve_values=resolve_values,
                error_policy=error_policy,
                field_ref=field_ref,
            )

        if executor is not None:
            executor.submit(task)
        else:
            threading.Thread(target=task, daemon=True).start()
        return run

    def _run_execution_worker(
        self,
        *,
        run_id: str,
        dispatcher: Dispatcher,
        field_name: str,
        semantic_type: FieldSemanticType | None,
        resolve_values: Callable[[], Sequence[str | None]],
        error_policy: ErrorPolicy | None,
        field_ref: str | None = None,
    ) -> None:
        """A background thread with an uncaught exception just dies
        silently in Python — this `except Exception` is the mechanism by
        which a failure (a bad source table/column, a connector outage,
        an unexpected normalizer crash) actually reaches the shared run
        record as a real FAILED status with a reason, rather than
        leaving the run stuck at RUNNING forever."""
        try:
            values = resolve_values()
            self.execute_run(
                run_id,
                dispatcher=dispatcher,
                field_name=field_name,
                semantic_type=semantic_type,
                values=values,
                error_policy=error_policy,
                field_ref=field_ref,
            )
        except Exception as exc:
            failed = self.get_run(run_id).model_copy(
                update={
                    "status": RunStatus.FAILED,
                    "finished_at": datetime.now(UTC).isoformat(),
                    "failure_reason": str(exc),
                }
            )
            with self._runs_lock:
                self._runs[run_id] = failed
            if self._pg is not None:
                self._pg.save_run(failed)

    def execute_run(
        self,
        run_id: str,
        *,
        dispatcher: Dispatcher,
        field_name: str,
        semantic_type: FieldSemanticType | None = None,
        values: Sequence[str | None],
        error_policy: ErrorPolicy | None = None,
        field_ref: str | None = None,
    ) -> NormalizationRun:
        """Actually normalizes `values` through the live Dispatcher and
        stores the original/result pairs against the run — real
        execution, not a scaffold no-op.

        `error_policy=None` (the caller didn't explicitly override it)
        defers to the run's own profile per field — see
        `NormalizationProfile.build_context`'s docstring for the full
        resolution order. An explicit value here always wins.

        `field_ref` (M16): the real key a profile's `field_configs` are
        matched against — `{connection_identity}.{database}.{table}.
        {column}` for a connection-based source (materialized by a saved
        `normapi.mappings.ColumnMapping`), or just `field_name` for
        pasted-values mode, where no such structured identity exists.
        Before M16, this was always the bare `field_name`, so a profile's
        real `field_ref`-keyed field_configs (e.g.
        `"abc123....origin2.Person.fullName"`) could never match a bare
        `"fullName"` — `error_policy`/`locale_overrides`/`dictionary_refs`
        were silently unapplied even when a matching config existed.

        `semantic_type` (M16): now optional. An explicit value here is an
        override and always wins (matching `error_policy`'s own
        precedent); when omitted, resolved from the matched field
        config's own `semantic_type`. Before M16, the caller-supplied
        value won *unconditionally* — there was no fallback at all, so a
        profile's saved mapping was silently never consulted even when
        the caller passed nothing meaningful. `ValueError` if neither is
        available."""
        run = self.get_run(run_id)
        if run.is_terminal():
            msg = f"Run {run_id!r} already reached terminal status {run.status!r}"
            raise RunNotExecutableError(msg)

        profile = self.get_profile(run.profile_id, run.profile_version)
        effective_field_ref = field_ref if field_ref is not None else field_name
        field_config = profile.config_for(effective_field_ref)
        effective_semantic_type = semantic_type
        if effective_semantic_type is None:
            effective_semantic_type = (
                field_config.semantic_type if field_config is not None else None
            )
        if effective_semantic_type is None:
            msg = (
                f"No semantic_type given for {effective_field_ref!r} and no matching "
                f"profile field config to fall back to"
            )
            raise ValueError(msg)
        ctx = profile.build_context(
            effective_field_ref, effective_semantic_type, error_policy=error_policy
        )

        recorder = RunRecorder(run)
        recorder.start()
        recorder.record_field()

        originals = list(values)
        results = self._normalize_deduped(
            originals,
            dispatcher=dispatcher,
            semantic_type=effective_semantic_type,
            ctx=ctx,
            profile=profile,
            recorder=recorder,
        )
        for result in results:
            changed = result.normalization_status is not NormalizationStatus.UNCHANGED
            recorder.record_value(changed=changed, status=result.normalization_status)
            for _ in result.warnings:
                recorder.record_warning()
            if result.errors:
                recorder.record_error()

        invariant_report = sample_and_check(
            dispatcher, effective_semantic_type, ctx, profile, originals=originals, results=results
        )

        finished = recorder.finish(RunStatus.COMPLETED)
        with self._runs_lock:
            self._runs[run_id] = finished
            self._executions[run_id] = _RunExecution(
                field_name=field_name,
                semantic_type=effective_semantic_type,
                originals=originals,
                results=results,
                invariant_report=invariant_report,
            )
        if self._pg is not None:
            self._pg.save_run(finished)
        if self._sidecar is not None:
            self._write_execution_to_sidecar(run_id, field_name, results)
        stats = compute_column_stats_from_results(
            table=field_name,
            column="",
            semantic_type=effective_semantic_type,
            originals=originals,
            results=results,
        )
        self._record_column_stats(run_id, stats)
        if self._telemetry is not None:
            handles, telemetry_metrics = self._telemetry
            record_run_metrics(
                handles,
                telemetry_metrics,
                finished.metrics,
                field_name=field_name,
                semantic_type=effective_semantic_type,
            )
        return finished

    def start_multi_column_execution(
        self,
        run_id: str,
        *,
        dispatcher: Dispatcher,
        connector: StreamingCatalogSourceConnector,
        connection_identity: str,
        database: str,
        columns: tuple[RunColumnSpec, ...],
        sidecar_source_id: str,
        executor: RunExecutor,
        pg_store: PostgresMetadataStore | None,
        chunk_size: int = 100_000,
    ) -> NormalizationRun:
        """M17 (docs/plan/M13-M22-program-plan.md): a real multi-column,
        chunked, resumable run — decision 5's "one run holds many
        columns," built on `normexec.stream.stream_column` (real keyset-
        paginated streaming, never sample-capped) and `RunExecutor`'s
        bounded worker pool (replacing the M11 raw-thread-per-run model).

        Columns within ONE run are processed SEQUENTIALLY, not fanned out
        across the pool — a deliberate, disclosed scope decision for this
        milestone (see the M17 verification pack): true per-column
        parallelism is a real possible future enhancement, not attempted
        here, since it would need per-column progress/failure isolation
        this milestone's `run_columns` table already tracks but the
        recorder/progress-snapshot plumbing does not yet coordinate
        across concurrent writers.

        Requires a sidecar (`self._sidecar is not None`) — there is no
        pasted-values equivalent for multi-column execution; results
        always go to real Parquet, never held only in `_executions`.
        """
        run = self.get_run(run_id)
        if run.is_terminal():
            msg = f"Run {run_id!r} already reached terminal status {run.status!r}"
            raise RunNotExecutableError(msg)
        if self._sidecar is None:
            msg = "Multi-column execution requires a configured sidecar store"
            raise RunNotExecutableError(msg)

        executor.submit(
            lambda: self._run_multi_column_worker(
                run_id,
                dispatcher=dispatcher,
                connector=connector,
                connection_identity=connection_identity,
                database=database,
                columns=columns,
                sidecar_source_id=sidecar_source_id,
                pg_store=pg_store,
                chunk_size=chunk_size,
            )
        )
        return run

    def _run_multi_column_worker(
        self,
        run_id: str,
        *,
        dispatcher: Dispatcher,
        connector: StreamingCatalogSourceConnector,
        connection_identity: str,
        database: str,
        columns: tuple[RunColumnSpec, ...],
        sidecar_source_id: str,
        pg_store: PostgresMetadataStore | None,
        chunk_size: int,
    ) -> None:
        """Runs in a `RunExecutor` worker thread. Mirrors
        `_run_execution_worker`'s "an uncaught exception becomes a real
        FAILED status, never a run stuck at RUNNING forever" contract.

        `connector` (M18): a DEDICATED instance built by the route
        specifically for this run (see `routes.start_multi_column_run`'s
        docstring for the real thread-safety bug this replaced a shared,
        pooled connector to fix) — this worker owns its whole lifecycle
        and is responsible for closing it, whether the run succeeds or
        fails, since nothing else will ever reuse it."""
        try:
            self._run_multi_column_worker_inner(
                run_id,
                dispatcher=dispatcher,
                connector=connector,
                connection_identity=connection_identity,
                database=database,
                columns=columns,
                sidecar_source_id=sidecar_source_id,
                pg_store=pg_store,
                chunk_size=chunk_size,
            )
        except Exception as exc:
            failed = self.get_run(run_id).model_copy(
                update={
                    "status": RunStatus.FAILED,
                    "finished_at": datetime.now(UTC).isoformat(),
                    "failure_reason": str(exc),
                }
            )
            self.refresh_run(failed)
            if pg_store is not None:
                pg_store.save_run(failed)
        finally:
            connector.close()

    def _run_multi_column_worker_inner(
        self,
        run_id: str,
        *,
        dispatcher: Dispatcher,
        connector: StreamingCatalogSourceConnector,
        connection_identity: str,
        database: str,
        columns: tuple[RunColumnSpec, ...],
        sidecar_source_id: str,
        pg_store: PostgresMetadataStore | None,
        chunk_size: int,
    ) -> None:
        assert self._sidecar is not None  # checked by the caller
        run = self.get_run(run_id)
        recorder = RunRecorder(run)
        started = recorder.start().model_copy(
            update={"columns": columns, "progress": RunProgress()}
        )
        self.refresh_run(started)
        if pg_store is not None:
            pg_store.save_run(started)

        profile = self.get_profile(run.profile_id, run.profile_version)
        sink = SidecarRunSink(self._sidecar, source_id=sidecar_source_id)

        total_rows_estimate = _estimate_total_rows(connector, columns)
        chunks_done = 0
        any_column_failed = False
        last_progress = RunProgress(total_rows_estimate=total_rows_estimate)

        for column_spec in columns:
            table, column, semantic_type = (
                column_spec.table,
                column_spec.column,
                column_spec.semantic_type,
            )
            if pg_store is not None:
                pg_store.upsert_run_column(
                    run_id=run_id,
                    table_name=table,
                    column_name=column,
                    semantic_type=semantic_type.value,
                    status="RUNNING",
                )

            key_columns = _resolve_key_columns(connector, table)
            field_ref = f"{connection_identity}.{database}.{table}.{column}"
            ctx = profile.build_context(field_ref, semantic_type, error_policy=None)

            resume_row = (
                pg_store.get_last_chunk(run_id=run_id, table_name=table, column_name=column)
                if pg_store is not None
                else None
            )
            resume_after_key = resume_row.last_key if resume_row is not None else None

            def on_chunk_committed(progress: ChunkProgress) -> None:
                nonlocal chunks_done, last_progress
                chunks_done += 1
                if pg_store is not None:
                    pg_store.record_chunk(
                        run_id=progress.run_id,
                        table_name=progress.table,
                        column_name=progress.column,
                        chunk_index=progress.chunk_index,
                        last_key=progress.last_key,
                        rows_processed=progress.rows_processed,
                    )
                last_progress = RunProgress(
                    total_rows_estimate=total_rows_estimate,
                    rows_done=recorder.snapshot().metrics.records_processed,
                    chunks_done=chunks_done,
                    current_table=progress.table,
                    current_column=progress.column,
                )
                snapshot = recorder.snapshot().model_copy(
                    update={"columns": columns, "progress": last_progress}
                )
                self.refresh_run(snapshot)

            column_rows_processed = 0
            try:
                column_rows_processed = stream_column(
                    connector,
                    run_id=run_id,
                    table=table,
                    column=column,
                    key_columns=key_columns,
                    semantic_type=semantic_type,
                    context=ctx,
                    profile=profile,
                    dispatcher=dispatcher,
                    cache=self._cache,
                    recorder=recorder,
                    sink=sink,
                    chunk_size=chunk_size,
                    resume_after_key=resume_after_key,
                    on_chunk_committed=on_chunk_committed,
                )
            except Exception as exc:
                any_column_failed = True
                if pg_store is not None:
                    pg_store.upsert_run_column(
                        run_id=run_id,
                        table_name=table,
                        column_name=column,
                        semantic_type=semantic_type.value,
                        status="FAILED",
                        failure_reason=str(exc),
                    )
                continue
            if pg_store is not None:
                pg_store.upsert_run_column(
                    run_id=run_id,
                    table_name=table,
                    column_name=column,
                    semantic_type=semantic_type.value,
                    status="COMPLETED",
                    rows_processed=column_rows_processed,
                )
            self._record_column_stats_from_sidecar(
                run_id=run_id,
                table=table,
                column=column,
                semantic_type=semantic_type,
                sidecar_source_id=sidecar_source_id,
            )

        final_status = RunStatus.PARTIAL if any_column_failed else RunStatus.COMPLETED
        finished = recorder.finish(final_status).model_copy(
            update={"columns": columns, "progress": last_progress}
        )
        self.refresh_run(finished)
        if pg_store is not None:
            pg_store.save_run(finished)

    def _write_execution_to_sidecar(
        self,
        run_id: str,
        field_name: str,
        results: list[NormalizedValue],
    ) -> None:
        """Persists a run's real per-value results to Arrow/Parquet
        (ADR-013's bulk-data tier) — `source_id="api"` since these
        values arrived directly in the request body, not through a real
        connected data source (§105's connectors aren't wired into the
        live API yet); `table=field_name`, since one run always
        normalizes exactly one field, and it doubles as the lookup key
        `_hydrate_execution_from_sidecar` needs after a restart. Row
        order is preserved by construction (`part_index=0`, one batch,
        rows appended in `results` order), so `source_row_key` is simply
        each row's index — reconstructible without a real upstream
        source system."""
        assert self._sidecar is not None  # narrows for mypy; caller already checked
        batch = _results_to_record_batch(results)
        self._sidecar.write_batch(
            source_id="api", table=field_name, run_id=run_id, batch=batch, part_index=0
        )

    def _normalize_deduped(
        self,
        originals: list[str | None],
        *,
        dispatcher: Dispatcher,
        semantic_type: FieldSemanticType,
        ctx: NormalizationContext,
        profile: NormalizationProfile,
        recorder: RunRecorder,
    ) -> list[NormalizedValue]:
        """§102: "Repeated values should be normalized once per profile/
        version." Thin wrapper around `DistinctValuePlanner.
        normalize_values` (M17) — the actual distinct-value dedup,
        cache-hit attribution, and None-handling logic now lives there,
        shared with `normexec.stream`'s M17 chunked-execution path,
        rather than duplicated here."""
        planner = DistinctValuePlanner(dispatcher, self._cache)
        return planner.normalize_values(
            originals,
            semantic_type,
            ctx,
            profile,
            on_computed=recorder.record_computation,
            on_cache_stat=lambda hit: recorder.record_cache(hit=hit),
        )

    def get_run(self, run_id: str) -> NormalizationRun:
        with self._runs_lock:
            if run_id not in self._runs:
                raise RunNotFoundError(run_id)
            return self._runs[run_id]

    def get_execution(self, run_id: str) -> _RunExecution | None:
        """None if the run was never executed (a real, valid state — a
        PENDING run created but not yet fed values), not an error."""
        with self._runs_lock:
            if run_id not in self._runs:
                raise RunNotFoundError(run_id)
            cached = self._executions.get(run_id)
            if cached is not None:
                return cached
            if self._sidecar is not None:
                hydrated = self._hydrate_execution_from_sidecar(run_id)
                if hydrated is not None:
                    self._executions[run_id] = hydrated
                    return hydrated
            return None

    def _hydrate_execution_from_sidecar(self, run_id: str) -> _RunExecution | None:
        """Reconstructs a run's real per-value results from Parquet —
        the counterpart to `_write_execution_to_sidecar`, exercised when
        `_executions` doesn't have them in-process (i.e. after a
        restart). `invariant_report` is `sampled=0, violations=()` since
        runtime invariant sampling only ever happens live, during the
        original `execute_run()` call — never fabricated as "still
        clean" for a run this process didn't actually execute."""
        assert self._sidecar is not None  # narrows for mypy; caller already checked
        location = self._sidecar.find_run_table(run_id)
        if location is None:
            return None
        source_id, table = location
        arrow_table = self._sidecar.read_run(source_id=source_id, table=table, run_id=run_id)
        originals, results = _table_to_results(arrow_table)
        # Every row carries its own real semantic_type (part of the
        # persisted schema); a zero-value run has none to read, so
        # UNKNOWN is an honest "no data to infer from" sentinel, not a
        # guess — a zero-row run has no other real signal available.
        semantic_type = results[0].semantic_type if results else FieldSemanticType.UNKNOWN
        return _RunExecution(
            field_name=table,
            semantic_type=semantic_type,
            originals=originals,
            results=results,
            invariant_report=InvariantSampleReport(sampled=0, violations=()),
        )

    def get_column_execution(
        self, run_id: str, table: str | None, column: str | None
    ) -> _RunExecution | None:
        """M18: the per-column counterpart to `get_execution` — every
        real per-value report route (`/errors`, `/values`, `/collisions`,
        `/profile`, `/handoff`, `/impact`, `/runs/compare`) fans out per
        (table, column) for a multi-column run rather than being
        rearchitected to be bounded (a deliberate, disclosed M18 scope
        decision: only `/overview`/`/quality`/`/values`' pagination are
        bounded — see `normanalysis.column_stats`'s module docstring).

        `table` falsy: delegates to `get_execution` unchanged — every
        existing single-column caller (every pre-M17 test, every
        pasted-values run) keeps working exactly as before.

        `table` given: looks up that EXACT (table, column) in the
        sidecar's catalog (`list_run_tables`, not `find_run_table`'s
        "whichever matched first" — the real fix for a multi-column
        run's reports silently returning data for the wrong column)."""
        if not table:
            return self.get_execution(run_id)
        with self._runs_lock:
            if run_id not in self._runs:
                raise RunNotFoundError(run_id)
        if self._sidecar is None:
            return None
        column_key = column or ""
        match = next(
            (
                entry
                for entry in self._sidecar.list_run_tables(run_id)
                if entry[1] == table and entry[2] == column_key
            ),
            None,
        )
        if match is None:
            return None
        source_id, table_name, column_name = match
        arrow_table = self._sidecar.read_run(
            source_id=source_id, table=table_name, run_id=run_id, column=column_name
        )
        originals, results = _chunk_table_to_results(arrow_table)
        semantic_type = results[0].semantic_type if results else FieldSemanticType.UNKNOWN
        return _RunExecution(
            field_name=column_name or table_name,
            semantic_type=semantic_type,
            originals=originals,
            results=results,
            invariant_report=InvariantSampleReport(sampled=0, violations=()),
        )

    def get_column_values_page(
        self,
        run_id: str,
        table: str | None,
        column: str | None,
        *,
        offset: int,
        limit: int,
    ) -> list[dict[str, object]] | None:
        """M18: `GET /runs/{id}/values`'s real page — for a sidecar-backed
        selection, pushed down to DuckDB (`SidecarStore.
        read_run_paginated`) rather than ever reading the whole column
        into Python first, the fix for the plan's own explicit callout
        ("never `to_pylist()` on a 12M-row table"). For the legacy
        no-selector/in-memory path (already bounded by M10's row cap),
        slices the existing `_RunExecution` in Python — cheap at that
        scale, no need for a DuckDB round-trip.

        Returns `None` when the run/column has no execution at all
        (distinct from an empty page at the end of real data)."""
        if not table:
            execution = self.get_execution(run_id)
            if execution is None:
                return None
            pairs = list(zip(execution.originals, execution.results, strict=True))
            page = pairs[offset : offset + limit]
            return [
                {"original": original, "result": result.model_dump(mode="json")}
                for original, result in page
            ]

        with self._runs_lock:
            if run_id not in self._runs:
                raise RunNotFoundError(run_id)
        if self._sidecar is None:
            return None
        column_key = column or ""
        match = next(
            (
                entry
                for entry in self._sidecar.list_run_tables(run_id)
                if entry[1] == table and entry[2] == column_key
            ),
            None,
        )
        if match is None:
            return None
        source_id, table_name, column_name = match
        arrow_table = self._sidecar.read_run_paginated(
            source_id=source_id,
            table=table_name,
            run_id=run_id,
            column=column_name,
            offset=offset,
            limit=limit,
        )
        originals, results = _chunk_table_to_results(arrow_table)
        return [
            {"original": original, "result": result.model_dump(mode="json")}
            for original, result in zip(originals, results, strict=True)
        ]

    def _record_column_stats(self, run_id: str, stats: ColumnStats) -> None:
        """Write-through, mirroring every other piece of state this store
        persists: the in-memory `_column_stats` dict is the hot read path
        for `/overview`/`/quality`; Postgres (when configured) is the
        durable tier those two dashboards keep working from after a
        restart."""
        with self._stats_lock:
            self._column_stats[(run_id, stats.table, stats.column)] = stats
        if self._pg is not None:
            self._pg.upsert_column_stats(_column_stats_to_row(run_id, stats))

    def _record_column_stats_from_sidecar(
        self,
        *,
        run_id: str,
        table: str,
        column: str,
        semantic_type: FieldSemanticType,
        sidecar_source_id: str,
    ) -> None:
        """The M17 chunked-streaming counterpart to `_record_column_stats`
        — computes the SAME bounded rollup via one DuckDB aggregate query
        over the sidecar's real Parquet files for this (table, column)
        (`SidecarStore.compute_column_stats`), never materializing a
        single per-value result in Python. Called once, after that
        column's `stream_column()` call finishes."""
        assert self._sidecar is not None  # narrows for mypy; caller already checked
        try:
            raw = self._sidecar.compute_column_stats(
                source_id=sidecar_source_id,
                table=table,
                run_id=run_id,
                column=column,
                quality_sql_predicate=_quality_sql_predicate_for(semantic_type),
            )
        except FileNotFoundError:
            # A column whose source table had zero matching rows never
            # calls `sink.write_chunk` (stream_column's loop exits on the
            # very first `read_chunk() is None`), so the sidecar catalog
            # has no entry to query — a real, legitimate zero-row column,
            # not an error; record it as all-zero stats rather than
            # silently omitting it from /overview and /quality.
            raw = {
                "rows_processed": 0,
                "rows_changed": 0,
                "rows_ambiguous": 0,
                "warnings_total": 0,
                "errors_total": 0,
                "unique_before": 0,
                "unique_after": 0,
                "quality_issue_count": 0 if _quality_sql_predicate_for(semantic_type) else None,
            }
        metric_def = next(
            (m for m in QUALITY_METRIC_DEFS if m.semantic_type is semantic_type), None
        )
        stats = ColumnStats(
            table=table,
            column=column,
            semantic_type=semantic_type.value,
            rows_processed=raw["rows_processed"] or 0,
            rows_changed=raw["rows_changed"] or 0,
            rows_ambiguous=raw["rows_ambiguous"] or 0,
            warnings_total=raw["warnings_total"] or 0,
            errors_total=raw["errors_total"] or 0,
            unique_before=raw["unique_before"] or 0,
            unique_after=raw["unique_after"] or 0,
            quality_metric_name=metric_def.name if metric_def is not None else None,
            quality_issue_count=raw["quality_issue_count"],
        )
        self._record_column_stats(run_id, stats)

    def list_all_column_stats(self) -> list[ColumnStats]:
        """Every (run, table, column) rollup currently known — the real,
        bounded read path for `GET /overview`/`GET /quality` (a fixed
        number of scalar fields per row, regardless of how many source
        rows that column had), never a loop over `get_execution`."""
        with self._stats_lock:
            return list(self._column_stats.values())

    def list_runs(self) -> list[NormalizationRun]:
        with self._runs_lock:
            return list(self._runs.values())

    def refresh_run(self, run: NormalizationRun) -> None:
        """Overwrites the in-memory copy of `run` with a caller-supplied
        one — used by `normapi.executor.reconcile_running_runs` (M17) to
        sync the in-memory `_runs` dict after writing a reconciled
        FAILED status straight to Postgres, and by M17's multi-column
        chunk loop to publish incremental progress snapshots as chunks
        complete (`GET /runs/{id}` needs to see `rows_done` increase
        while a run is still RUNNING, not just at completion)."""
        with self._runs_lock:
            self._runs[run.id] = run

    def record_collision_decision(
        self,
        run_id: str,
        normalized_value: str,
        *,
        decision: CollisionDecisionType,
        decided_by: str,
        note: str | None = None,
        table: str | None = None,
        column: str | None = None,
    ) -> CollisionDecision:
        """§92: a human reviewer's real, persisted disposition on one
        collision group. Rejects a `normalized_value` that isn't
        actually a real collision group for this run — recording a
        decision on something that was never flagged would be
        meaningless, not just unhelpful.

        `table`/`column` (M18): selects which column's collision groups
        to check against, for a multi-column run — omitted, this is the
        original single-column lookup, unchanged."""
        execution = self.get_column_execution(run_id, table, column)
        if execution is None:
            msg = f"Run {run_id!r} has no execution to have collisions from"
            raise UnknownCollisionError(msg)
        groups = find_collisions(execution.originals, execution.results)
        if not any(group.normalized_value == normalized_value for group in groups):
            msg = f"{normalized_value!r} is not a real collision group for run {run_id!r}"
            raise UnknownCollisionError(msg)

        record = CollisionDecision(
            run_id=run_id,
            normalized_value=normalized_value,
            decision=decision,
            decided_by=decided_by,
            decided_at=datetime.now(UTC).isoformat(),
            note=note,
        )
        self._collision_decisions[(run_id, normalized_value)] = record
        if self._pg is not None:
            self._pg.save_collision_decision(record)
        return record

    def list_collision_decisions(self, run_id: str) -> list[CollisionDecision]:
        return [
            decision
            for (decision_run_id, _), decision in self._collision_decisions.items()
            if decision_run_id == run_id
        ]

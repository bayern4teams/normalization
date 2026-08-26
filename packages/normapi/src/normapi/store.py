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
from normio.sidecar_store import SidecarStore

from normanalysis import (
    CollisionDecision,
    CollisionDecisionType,
    InvariantSampleReport,
    RunRecorder,
    find_collisions,
    record_run_metrics,
    sample_and_check,
)
from normapi.postgres_store import PostgresMetadataStore
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
    RunStatus,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from normexec.cache import NormalizationCache

    from normanalysis import NormalizationMetrics, TelemetryHandles
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
        # (run_id, normalized_value) -> a human reviewer's real decision
        # on that collision group (§92, M11).
        self._collision_decisions: dict[tuple[str, str], CollisionDecision] = {}
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
    ) -> NormalizationRun:
        """Starts a run's execution in a background thread and returns
        immediately (M11) — Source.txt §70's own `RunStatus` already
        modeled RUNNING/FAILED as real lifecycle states; M6-M10's
        `execute_run()` always finished synchronously within the same
        request, so no caller could ever actually observe them. Poll
        `GET /runs/{id}`: the run stays PENDING until the background
        thread's `RunRecorder.start()` transitions it to RUNNING (the
        recorder itself owns that PENDING->RUNNING transition and
        rejects being constructed on anything but a PENDING run — this
        method deliberately does NOT also set RUNNING itself, to avoid
        two different places racing to make the same transition), then
        COMPLETED/FAILED when done.

        `resolve_values` is called INSIDE the background thread, not
        before returning — for a source-mode run this is where the real,
        potentially slow connector read happens, off the request/
        response path (M10's row cap existed specifically because that
        read used to block the request; it still applies as a memory
        bound, but no longer as a latency one).

        `execute_run` itself is untouched and remains the synchronous,
        directly-testable primitive every existing test already uses;
        this is a thin background-thread wrapper around it, used only by
        the live HTTP route.

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

        thread = threading.Thread(
            target=self._run_execution_worker,
            kwargs={
                "run_id": run_id,
                "dispatcher": dispatcher,
                "field_name": field_name,
                "semantic_type": semantic_type,
                "resolve_values": resolve_values,
                "error_policy": error_policy,
                "field_ref": field_ref,
            },
            daemon=True,
        )
        thread.start()
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
        self._runs[run_id] = finished
        if self._pg is not None:
            self._pg.save_run(finished)
        self._executions[run_id] = _RunExecution(
            field_name=field_name,
            semantic_type=effective_semantic_type,
            originals=originals,
            results=results,
            invariant_report=invariant_report,
        )
        if self._sidecar is not None:
            self._write_execution_to_sidecar(run_id, field_name, results)
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
        version." Distinct non-null values go through the real
        `DistinctValuePlanner` (cache-aware, M1-built but never wired to
        this execution path until this M8 fix); `None` is computed once
        outside the planner since it isn't a valid `list[str]` element
        but is just as legitimately repeatable within one run."""
        distinct_non_null = list(dict.fromkeys(v for v in originals if v is not None))

        # Attribute hits/misses from LOCAL, per-request state (which
        # distinct values `on_computed` actually fired for — a miss —
        # not the rest, a hit) rather than diffing the shared
        # `NormalizationCache.stats` counter before/after. `create_run`'s
        # route handler is synchronous, so Starlette dispatches concurrent
        # requests to a thread pool sharing this same store/cache
        # instance; a before/after delta on a globally-shared mutable
        # counter can be corrupted by another request's cache activity
        # landing in between the two reads, misattributing hits/misses
        # across unrelated runs. Tracking locally makes this race-free.
        computed_values: set[str] = set()

        def on_computed(value: str, result: NormalizedValue, duration: float) -> None:
            computed_values.add(value)
            recorder.record_computation(value, result, duration)

        planner = DistinctValuePlanner(dispatcher, self._cache)
        by_value = planner.distinct_value_results(
            distinct_non_null, semantic_type, ctx, profile, on_computed=on_computed
        )

        if self._cache is not None:
            for value in distinct_non_null:
                recorder.record_cache(hit=value not in computed_values)

        none_result = (
            dispatcher.normalize(None, semantic_type, ctx, profile)
            if any(v is None for v in originals)
            else None
        )

        def resolve(value: str | None) -> NormalizedValue:
            if value is None:
                if none_result is None:  # pragma: no cover - unreachable, see none_result above
                    msg = "internal error: encountered a None value without a precomputed result"
                    raise AssertionError(msg)
                return none_result
            return by_value[value]

        return [resolve(value) for value in originals]

    def get_run(self, run_id: str) -> NormalizationRun:
        if run_id not in self._runs:
            raise RunNotFoundError(run_id)
        return self._runs[run_id]

    def get_execution(self, run_id: str) -> _RunExecution | None:
        """None if the run was never executed (a real, valid state — a
        PENDING run created but not yet fed values), not an error."""
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

    def list_runs(self) -> list[NormalizationRun]:
        return list(self._runs.values())

    def record_collision_decision(
        self,
        run_id: str,
        normalized_value: str,
        *,
        decision: CollisionDecisionType,
        decided_by: str,
        note: str | None = None,
    ) -> CollisionDecision:
        """§92: a human reviewer's real, persisted disposition on one
        collision group. Rejects a `normalized_value` that isn't
        actually a real collision group for this run — recording a
        decision on something that was never flagged would be
        meaningless, not just unhelpful."""
        execution = self.get_execution(run_id)
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

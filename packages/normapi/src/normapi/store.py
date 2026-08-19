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

Deliberately still NOT persisted: a run's bulk per-value execution
results (`_RunExecution.originals`/`.results`) — ADR-013 assigns bulk
normalized-value data to a separate Arrow/Parquet sidecar store
(`normio.SidecarStore`, built in M1, not yet wired into this execution
path), not Postgres. A restart correctly recovers every past run's
status/metrics but not its detailed per-value results — see
postgres_store.py's module docstring and M9's verification pack for the
full disclosure.

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

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from normexec.planner import DistinctValuePlanner

from normanalysis import InvariantSampleReport, RunRecorder, sample_and_check
from normapi.postgres_store import PostgresMetadataStore
from normcore import (
    FieldNormalizationConfig,
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
    from collections.abc import Sequence

    from normexec.cache import NormalizationCache

    from normcore import Dispatcher, ErrorPolicy, FieldSemanticType


class ProfileNotFoundError(LookupError):
    pass


class RunNotFoundError(LookupError):
    pass


class RunNotExecutableError(RuntimeError):
    """Raised when execute_run() is called on a run that already reached
    a terminal status — a run's field execution happens at most once,
    consistent with NormalizationRun being immutable once terminal."""


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
        self, cache: NormalizationCache | None = None, *, postgres_dsn: str | None = None
    ) -> None:
        # profile_id -> {version: NormalizationProfile}
        self._profiles: dict[str, dict[str, NormalizationProfile]] = {}
        # profile_id -> currently active version (per ADR-014, only one
        # version is ACTIVE at a time; earlier versions become DEPRECATED)
        self._active_version: dict[str, str] = {}
        self._runs: dict[str, NormalizationRun] = {}
        self._executions: dict[str, _RunExecution] = {}
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

    def execute_run(
        self,
        run_id: str,
        *,
        dispatcher: Dispatcher,
        field_name: str,
        semantic_type: FieldSemanticType,
        values: Sequence[str | None],
        error_policy: ErrorPolicy,
    ) -> NormalizationRun:
        """Actually normalizes `values` through the live Dispatcher and
        stores the original/result pairs against the run — real
        execution, not a scaffold no-op."""
        run = self.get_run(run_id)
        if run.is_terminal():
            msg = f"Run {run_id!r} already reached terminal status {run.status!r}"
            raise RunNotExecutableError(msg)

        profile = self.get_profile(run.profile_id, run.profile_version)
        ctx = NormalizationContext(
            field_name=field_name, semantic_type=semantic_type, error_policy=error_policy
        )

        recorder = RunRecorder(run)
        recorder.start()
        recorder.record_field()

        originals = list(values)
        results = self._normalize_deduped(
            originals,
            dispatcher=dispatcher,
            semantic_type=semantic_type,
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
            dispatcher, semantic_type, ctx, profile, originals=originals, results=results
        )

        finished = recorder.finish(RunStatus.COMPLETED)
        self._runs[run_id] = finished
        if self._pg is not None:
            self._pg.save_run(finished)
        self._executions[run_id] = _RunExecution(
            field_name=field_name,
            semantic_type=semantic_type,
            originals=originals,
            results=results,
            invariant_report=invariant_report,
        )
        return finished

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
        return self._executions.get(run_id)

    def list_runs(self) -> list[NormalizationRun]:
        return list(self._runs.values())

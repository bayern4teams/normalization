"""In-memory profile/run store backing the M1 API scaffold.

This is deliberately NOT the eventual PostgreSQL-backed metadata store
(ADR-013) — it exists to prove the §98 API's shape and the
create-profile/version/run request flow end-to-end against a real running
server, per M1's Gate G1 requirement. Real persistence, concurrent-access
safety, and the full profile-versioning audit trail land with the
PostgreSQL-backed store in a later milestone. State does not survive a
process restart — this is explicitly a scaffold, not a database.

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
    def __init__(self, cache: NormalizationCache | None = None) -> None:
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
            self._profiles[profile_id][current_version] = current.model_copy(
                update={"status": ProfileStatus.DEPRECATED}
            )

        target = self._profiles[profile_id][target_version]
        reactivated = target.model_copy(update={"status": ProfileStatus.ACTIVE})
        self._profiles[profile_id][target_version] = reactivated
        self._active_version[profile_id] = target_version
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

        hits_before = self._cache.stats.hits if self._cache is not None else 0
        misses_before = self._cache.stats.misses if self._cache is not None else 0

        planner = DistinctValuePlanner(dispatcher, self._cache)
        by_value = planner.distinct_value_results(
            distinct_non_null, semantic_type, ctx, profile, on_computed=recorder.record_computation
        )

        if self._cache is not None:
            for _ in range(self._cache.stats.hits - hits_before):
                recorder.record_cache(hit=True)
            for _ in range(self._cache.stats.misses - misses_before):
                recorder.record_cache(hit=False)

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

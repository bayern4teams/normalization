"""Profile/run store backing the §98 API, in-process dicts as the read
path with PostgreSQL as a write-through persistence layer (ADR-013).

Every read here still hits the in-memory dicts directly — this class
started as an M1 scaffold with no persistence at all, and audit findings
confirmed that a restart or a second replica lost every profile and run
with no warning. `PgPersistence` (normapi.pg_persistence) is now an
optional write-through side channel: pass one in and every mutation below
also durably writes to Postgres. Passing `persistence=None` (still the
default, e.g. for unit tests with no database available) keeps the
original pure-in-memory, does-not-survive-a-restart behavior.

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

A real 250,000-row run OOM-killed the process the persistence layer
above was verified against — `_executions` held every run's full result
list forever, and a giant per-run write amplified it further. Two
changes here fix that instead of just describing it: `_executions` is
now a small bounded LRU (`_MAX_CACHED_EXECUTIONS`), evicting the oldest
entry and reconstructing from Postgres on a miss when persistence is
configured (`get_execution`), and `execute_run` rejects a request over
`max_run_rows` outright (`RunTooLargeError`, mapped to HTTP 413 in
routes.py) instead of attempting it and letting the OOM killer decide.
"""

from __future__ import annotations

import uuid
from collections import OrderedDict
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from normexec.planner import DistinctValuePlanner

from normanalysis import InvariantSampleReport, RunRecorder, sample_and_check
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

from normapi.pg_persistence import rehydrate_invariant_report

if TYPE_CHECKING:
    from collections.abc import Sequence

    from normexec.cache import NormalizationCache

    from normapi.pg_persistence import PgPersistence
    from normcore import Dispatcher, ErrorPolicy

# How many runs' full result sets InMemoryStore will hold in memory at
# once, across every run this process has ever executed or hydrated —
# the actual cause of the OOM was unbounded retention here, not any one
# run's size alone. Anything beyond this many runs old is evicted and,
# with persistence configured, reconstructed from Postgres on next access
# rather than lost.
_MAX_CACHED_EXECUTIONS = 20

# Default ceiling on a single run's row count. Measured, not guessed —
# an earlier version of this comment picked 100,000 by extrapolating from
# a 30,000-row success and a 250,000-row OOM kill; live memory sampling
# (docker stats, once-a-second, during a real run) showed that guess was
# wrong: PERSON_NAME, a representatively rich semantic type (multi-step
# trace, hashes/masks per step), peaks at roughly 50-70KB of process
# memory per genuinely-distinct row. 90,000 rows peaked at ~4.7GB and
# OOM-killed the container under a 2GB limit; 50,000 rows peaked at
# ~3.4GB and completed cleanly under a 4GB limit (compose.yaml's
# api.mem_limit). 40,000 is that verified-working number with real
# margin below it, not the number itself, since a live deployment also
# has concurrent requests and base process overhead a single isolated
# test doesn't represent. Configurable (app.py reads NORM_MAX_RUN_ROWS)
# so an operator who has measured their own container's real headroom —
# the same way this default was chosen — can raise it deliberately.
DEFAULT_MAX_RUN_ROWS = 40_000


class ProfileNotFoundError(LookupError):
    pass


class RunNotFoundError(LookupError):
    pass


class RunNotExecutableError(RuntimeError):
    """Raised when execute_run() is called on a run that already reached
    a terminal status — a run's field execution happens at most once,
    consistent with NormalizationRun being immutable once terminal."""


class RunTooLargeError(ValueError):
    """Raised when execute_run() is asked to process more rows than
    `max_run_rows` allows — a deliberate, predictable rejection in place
    of attempting it and risking an OOM kill (see module docstring)."""

    def __init__(self, row_count: int, max_run_rows: int) -> None:
        super().__init__(
            f"Run has {row_count} rows, which exceeds the configured limit of "
            f"{max_run_rows} (NORM_MAX_RUN_ROWS)."
        )
        self.row_count = row_count
        self.max_run_rows = max_run_rows


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
        persistence: PgPersistence | None = None,
        max_run_rows: int = DEFAULT_MAX_RUN_ROWS,
    ) -> None:
        self._persistence = persistence
        self.max_run_rows = max_run_rows

        if persistence is not None:
            profiles, active_version, runs = persistence.load_all()
            self._profiles = profiles
            self._active_version = active_version
            self._runs = runs
        else:
            # profile_id -> {version: NormalizationProfile}
            self._profiles = {}
            # profile_id -> currently active version (per ADR-014, only one
            # version is ACTIVE at a time; earlier versions become DEPRECATED)
            self._active_version = {}
            self._runs = {}

        # Bounded LRU (see _MAX_CACHED_EXECUTIONS) — never eagerly
        # populated at startup even with persistence configured; a
        # previously-executed run's full results are reconstructed from
        # Postgres lazily, on the first access that actually needs them
        # (get_execution), not loaded speculatively for every historical
        # run this profile has ever run.
        self._executions: OrderedDict[str, _RunExecution] = OrderedDict()

        # Optional (defaults to no caching, matching prior behavior for
        # any caller/test that constructs a bare InMemoryStore) — real
        # distinct-value dedup + cross-call caching only activates when a
        # NormalizationCache is supplied, which normapi.app always does.
        self._cache = cache

    def _cache_execution(self, run_id: str, execution: _RunExecution) -> None:
        self._executions[run_id] = execution
        self._executions.move_to_end(run_id)
        if len(self._executions) > _MAX_CACHED_EXECUTIONS:
            self._executions.popitem(last=False)

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
        if self._persistence is not None:
            self._persistence.save_profile(profile)
            self._persistence.save_active_version(profile_id, "v1")
        return profile

    def _build_next_version(
        self,
        current: NormalizationProfile,
        next_version: str,
        *,
        description: str | None,
        locale_policy: dict[str, str] | None,
        default_operations: tuple[str, ...] | None,
        field_configs: tuple[FieldNormalizationConfig, ...] | None,
        created_by: str,
    ) -> NormalizationProfile:
        """The field-merging logic for `create_version`, factored out so
        both the persistence=None path below and PgPersistence's
        transactionally-locked `create_version_atomic` (which calls this
        as a callback from inside its own Postgres transaction) use the
        identical rule for what a "next version" contains."""
        now = datetime.now(UTC).isoformat()
        return NormalizationProfile(
            id=current.id,
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
            parent_version=current.version,
        )

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
        never edited, only superseded as the active one.

        With persistence configured, this is the transactionally-locked
        path (`create_version_atomic`) — two replicas calling this for
        the SAME profile_id at the same instant serialize on a Postgres
        row lock instead of each computing the same next-version number
        independently and one silently overwriting the other (confirmed
        live: both got 201, one's write vanished with no error — see the
        audit report's F9)."""
        if self._persistence is not None:
            new_profile = self._persistence.create_version_atomic(
                profile_id,
                lambda current, next_version: self._build_next_version(
                    current,
                    next_version,
                    description=description,
                    locale_policy=locale_policy,
                    default_operations=default_operations,
                    field_configs=field_configs,
                    created_by=created_by,
                ),
            )
            if new_profile is None:
                raise ProfileNotFoundError(profile_id)
            # Best-effort local mirror for anything still reading the
            # dicts directly (e.g. a bare persistence=None-style caller
            # mixing modes in a test) — Postgres is authoritative reads
            # below don't depend on this being correct.
            self._profiles.setdefault(profile_id, {})[new_profile.version] = new_profile
            self._active_version[profile_id] = new_profile.version
            return new_profile

        if profile_id not in self._profiles:
            raise ProfileNotFoundError(profile_id)
        current_version = self._active_version[profile_id]
        current = self._profiles[profile_id][current_version]
        next_version = f"v{int(current_version.removeprefix('v')) + 1}"
        new_profile = self._build_next_version(
            current,
            next_version,
            description=description,
            locale_policy=locale_policy,
            default_operations=default_operations,
            field_configs=field_configs,
            created_by=created_by,
        )
        deprecated_current = current.model_copy(update={"status": ProfileStatus.DEPRECATED})
        self._profiles[profile_id][current_version] = deprecated_current
        self._profiles[profile_id][next_version] = new_profile
        self._active_version[profile_id] = next_version
        return new_profile

    def rollback_profile(self, profile_id: str, target_version: str) -> NormalizationProfile:
        """Reactivates a prior version (§59/§94's "Rollback Profile") —
        does NOT delete the version being rolled back from, so rolling
        forward again afterward is always possible. Same locking
        strategy as `create_version` when persistence is configured."""
        if self._persistence is not None:
            reactivated = self._persistence.rollback_profile_atomic(profile_id, target_version)
            if reactivated is None:
                raise ProfileNotFoundError(f"{profile_id}@{target_version}")
            self._profiles.setdefault(profile_id, {})[target_version] = reactivated
            self._active_version[profile_id] = target_version
            return reactivated

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
        """Reads straight from Postgres when persistence is configured
        (F10 fix) — a sibling replica's write is visible here on this
        very call, not only after this replica's own restart."""
        if self._persistence is not None:
            profile = self._persistence.get_profile(profile_id, version)
            if profile is None:
                suffix = f"@{version}" if version else ""
                raise ProfileNotFoundError(f"{profile_id}{suffix}")
            return profile

        if profile_id not in self._profiles:
            raise ProfileNotFoundError(profile_id)
        resolved_version = version or self._active_version[profile_id]
        if resolved_version not in self._profiles[profile_id]:
            raise ProfileNotFoundError(f"{profile_id}@{resolved_version}")
        return self._profiles[profile_id][resolved_version]

    def list_profile_versions(self, profile_id: str) -> list[NormalizationProfile]:
        if self._persistence is not None:
            versions = self._persistence.list_profile_versions(profile_id)
            if versions is None:
                raise ProfileNotFoundError(profile_id)
            return versions

        if profile_id not in self._profiles:
            raise ProfileNotFoundError(profile_id)
        return list(self._profiles[profile_id].values())

    def list_profiles(self) -> list[NormalizationProfile]:
        if self._persistence is not None:
            return self._persistence.list_profiles()
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
        if self._persistence is not None:
            self._persistence.save_run(run)
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
        if len(values) > self.max_run_rows:
            raise RunTooLargeError(len(values), self.max_run_rows)

        run = self.get_run(run_id)
        if run.is_terminal():
            msg = f"Run {run_id!r} already reached terminal status {run.status!r}"
            raise RunNotExecutableError(msg)

        if self._persistence is not None and not self._persistence.claim_run_for_execution(run_id):
            # Someone else — another replica, or a concurrent call on
            # this one — already claimed this run between the read above
            # and here. Without this atomic claim, two replicas executing
            # the same run_id concurrently would both compute full
            # results and last-write-wins on save, the same silent
            # overwrite F9 found for profile versioning.
            msg = f"Run {run_id!r} is already being executed (claimed by another request)"
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
        self._cache_execution(
            run_id,
            _RunExecution(
                field_name=field_name,
                semantic_type=semantic_type,
                originals=originals,
                results=results,
                invariant_report=invariant_report,
            ),
        )
        if self._persistence is not None:
            self._persistence.save_run(finished)
            self._persistence.save_execution(
                run_id,
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
        """Reads straight from Postgres when persistence is configured —
        same F10 rationale as get_profile: a sibling replica's
        create_run/execute_run is visible here immediately."""
        if self._persistence is not None:
            run = self._persistence.get_run(run_id)
            if run is None:
                raise RunNotFoundError(run_id)
            return run

        if run_id not in self._runs:
            raise RunNotFoundError(run_id)
        return self._runs[run_id]

    def get_execution(self, run_id: str) -> _RunExecution | None:
        """None if the run was never executed (a real, valid state — a
        PENDING run created but not yet fed values), not an error.

        A hit on the bounded in-memory cache is the common case (a run
        just executed by this same process, or recently accessed). A
        miss with persistence configured reconstructs the full
        `_RunExecution` from Postgres — the cost of that reconstruction
        is real (this is exactly the data collisions/impact/overview
        need in full to compute their aggregates, an inherent cost of
        what those features do, not something a storage-layer fix
        removes) but it no longer has to be held forever to pay it once."""
        self.get_run(run_id)  # raises RunNotFoundError; checks Postgres when configured (F10)

        cached = self._executions.get(run_id)
        if cached is not None:
            self._executions.move_to_end(run_id)
            return cached

        if self._persistence is None:
            return None

        meta = self._persistence.load_execution_meta(run_id)
        if meta is None:
            return None
        rows = self._persistence.load_execution_all_rows(run_id)
        execution = _RunExecution(
            field_name=meta["field_name"],
            semantic_type=FieldSemanticType(meta["semantic_type"]),
            originals=[original for original, _ in rows],
            results=[NormalizedValue.model_validate_json(result) for _, result in rows],
            invariant_report=rehydrate_invariant_report(meta["invariant_report"]),
        )
        self._cache_execution(run_id, execution)
        return execution

    def get_run_values_page(
        self, run_id: str, *, limit: int, offset: int
    ) -> list[tuple[str | None, NormalizedValue]]:
        """The paginated counterpart to `get_execution` for GET
        /runs/{id}/values specifically — goes straight to Postgres when
        persistence is configured instead of reconstructing (or reusing
        a cached reconstruction of) the whole run just to hand back one
        page of it, so a client paging through a 250,000-row run's
        values never causes the full-run cost `get_execution` otherwise
        has to pay somewhere. Without persistence, pages the in-memory
        list directly (test/no-DB path)."""
        self.get_run(run_id)  # raises RunNotFoundError; checks Postgres when configured (F10)

        if self._persistence is not None:
            rows = self._persistence.load_execution_rows_page(run_id, limit=limit, offset=offset)
            return [
                (original, NormalizedValue.model_validate_json(result)) for original, result in rows
            ]

        execution = self._executions.get(run_id)
        if execution is None:
            return []
        paired = list(zip(execution.originals, execution.results, strict=True))
        return paired[offset : offset + limit]

    def list_runs(self) -> list[NormalizationRun]:
        if self._persistence is not None:
            return self._persistence.list_runs()
        return list(self._runs.values())

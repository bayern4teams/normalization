"""In-memory profile/run store backing the M1 API scaffold.

This is deliberately NOT the eventual PostgreSQL-backed metadata store
(ADR-013) — it exists to prove the §98 API's shape and the
create-profile/version/run request flow end-to-end against a real running
server, per M1's Gate G1 requirement. Real persistence, concurrent-access
safety, and the full profile-versioning audit trail land with the
PostgreSQL-backed store in a later milestone. State does not survive a
process restart — this is explicitly a scaffold, not a database.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from normcore import (
    FieldNormalizationConfig,
    NormalizationProfile,
    NormalizationRun,
    NormalizationRunMetrics,
    ProfileStatus,
    RunStatus,
)


class ProfileNotFoundError(LookupError):
    pass


class RunNotFoundError(LookupError):
    pass


class InMemoryStore:
    def __init__(self) -> None:
        # profile_id -> {version: NormalizationProfile}
        self._profiles: dict[str, dict[str, NormalizationProfile]] = {}
        # profile_id -> currently active version (per ADR-014, only one
        # version is ACTIVE at a time; earlier versions become DEPRECATED)
        self._active_version: dict[str, str] = {}
        self._runs: dict[str, NormalizationRun] = {}

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

    def get_profile(self, profile_id: str, version: str | None = None) -> NormalizationProfile:
        if profile_id not in self._profiles:
            raise ProfileNotFoundError(profile_id)
        resolved_version = version or self._active_version[profile_id]
        if resolved_version not in self._profiles[profile_id]:
            raise ProfileNotFoundError(f"{profile_id}@{resolved_version}")
        return self._profiles[profile_id][resolved_version]

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

    def get_run(self, run_id: str) -> NormalizationRun:
        if run_id not in self._runs:
            raise RunNotFoundError(run_id)
        return self._runs[run_id]

    def list_runs(self) -> list[NormalizationRun]:
        return list(self._runs.values())

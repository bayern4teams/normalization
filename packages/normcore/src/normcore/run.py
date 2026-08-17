"""Run and version-locking models — Source.txt §70, §73.

NormalizationRun records one execution of a profile against a source
snapshot. NormalizationVersion is the version-locking record ADR-014
describes: every library, dictionary, and ICU/Unicode/CLDR version that
participated in producing a given env_id, kept queryable independently of
recomputing env_fingerprint.py.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from normcore.enums import RunStatus


class NormalizationVersion(BaseModel):
    """Source.txt §73 — the human-readable expansion of one `env_id`.

    Where `env_id` is a single opaque hash used for comparison and cache
    keying, `NormalizationVersion` is the same information kept legible:
    given an `env_id`, what libraries/dictionaries/ICU version actually
    produced it. One row per distinct `env_id` ever observed.
    """

    model_config = ConfigDict(frozen=True)

    env_id: str
    profile_version: str
    dictionary_versions: dict[str, str] = Field(default_factory=dict)
    library_versions: dict[str, str] = Field(default_factory=dict)
    icu_version: str | None = None
    unicode_version: str | None = None
    cldr_version: str | None = None
    libpostal_data_sha256: str | None = None


class NormalizationRunMetrics(BaseModel):
    """Aggregate counters for one run — populated incrementally by
    normexec as batches complete, and finalized when the run ends.
    """

    model_config = ConfigDict(frozen=True)

    records_processed: int = 0
    fields_processed: int = 0
    changed_values: int = 0
    unchanged_values: int = 0
    warnings: int = 0
    errors: int = 0
    cache_hits: int = 0
    cache_misses: int = 0


class NormalizationRun(BaseModel):
    """Source.txt §70 — one execution of a profile against a source
    snapshot. Immutable once `status` reaches a terminal state
    (COMPLETED/FAILED/PARTIAL) — a re-run creates a new `NormalizationRun`,
    never mutates a historical one (this is what makes "Compare With
    Previous" in the Run UI, §94, meaningful).
    """

    model_config = ConfigDict(frozen=True)

    id: str
    profile_id: str
    profile_version: str
    env_id: str
    source_snapshot: str
    started_at: str  # ISO 8601
    finished_at: str | None = None
    status: RunStatus = RunStatus.PENDING
    metrics: NormalizationRunMetrics = Field(default_factory=NormalizationRunMetrics)

    def is_terminal(self) -> bool:
        return self.status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.PARTIAL)

"""Run and version-locking models — Source.txt §70, §73.

NormalizationRun records one execution of a profile against a source
snapshot. NormalizationVersion is the version-locking record ADR-014
describes: every library, dictionary, and ICU/Unicode/CLDR version that
participated in producing a given env_id, kept queryable independently of
recomputing env_fingerprint.py.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from normcore.enums import FieldSemanticType, RunStatus


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
    # Source.txt §122 observability counters.
    parser_failures: int = 0
    validation_failures: int = 0
    library_calls: int = 0
    duration_seconds: float = 0.0
    rows_per_second: float = 0.0
    avg_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cache_hit_ratio(self) -> float:
        total = self.cache_hits + self.cache_misses
        return self.cache_hits / total if total else 0.0


class RunColumnSpec(BaseModel):
    """M17 (docs/plan/M13-M22-program-plan.md) — one column a multi-
    column run normalizes: decision 5 of the program, "one run holds
    many columns" as a core run-model extension rather than fan-out into
    several single-column runs. `table`/`column` identify the source
    location; `semantic_type` is resolved the same way a single-column
    run already resolves it (an explicit override here, or a matching
    profile field config — see `normapi.store.InMemoryStore.execute_run`
    for the real resolution order, fixed in M16)."""

    model_config = ConfigDict(frozen=True)

    table: str
    column: str
    semantic_type: FieldSemanticType


class ColumnCachePolicy(BaseModel):
    """Phase 3 item 2 (2026-08-29 throughput/memory program): the
    cardinality-aware cache decision made for one column of a run — "at
    97-99.9% distinct [cache writes] are pure cost with no possible
    future hit" (the plan's own framing). Recorded per column so the
    decision is auditable, never silent, per the plan's explicit
    requirement.

    `source` distinguishes a real connector-provided estimate (e.g.
    ClickHouse's `uniqExact`, cheap and exact) from the generic fallback
    every connector gets for free: estimating from the first chunk
    actually read (`normexec.stream.stream_column`) when the connector
    implements no cardinality capability. `distinct_ratio` is `None` only
    when a table/chunk was completely empty (nothing to estimate from) —
    `use_cache` stays `True` in that case, matching this run's pre-
    Phase-3 default.
    """

    model_config = ConfigDict(frozen=True)

    table: str
    column: str
    use_cache: bool
    distinct_ratio: float | None
    source: Literal["connector_estimate", "first_chunk_sample"]


class RunProgress(BaseModel):
    """M17 — mid-run progress for a multi-column chunked execution,
    updated incrementally as chunks complete (unlike `metrics`, which is
    the run's cumulative roll-up and stays meaningful for both single-
    and multi-column runs alike). `total_rows_estimate` comes from a
    connector's `TableSpec.approx_rows` (best-effort, per M14) — never
    trusted as an exact bound, only as a progress-bar denominator."""

    model_config = ConfigDict(frozen=True)

    total_rows_estimate: int | None = None
    rows_done: int = 0
    chunks_done: int = 0
    current_table: str | None = None
    current_column: str | None = None
    # M20 (docs/plan/M13-M22-program-plan.md): a real, surfaced count of
    # rows a `created_at` incremental watermark structurally cannot see —
    # `created_at IS NULL` rows never satisfy `created_at > watermark`,
    # so they would otherwise be silently skipped forever (plan callout
    # #1). Always 0 for a non-incremental run, or a table whose
    # `created_at` column has no real NULL rows (verified: `Person`/
    # `Company` both currently have zero, per M14/M17's own live checks —
    # a latent trap in the column TYPE, not a live bug today).
    rows_skipped_null_watermark: int = 0


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
    # M11: set only when status reaches FAILED — a run's background
    # execution (see normapi.store.InMemoryStore.start_run_execution)
    # raising an unexpected exception (a bad source table/column, a
    # connector outage, ...) is captured here rather than silently
    # leaving the run stuck at RUNNING forever.
    failure_reason: str | None = None
    # M17: empty for the pre-M17 single-field execution path (pasted
    # values, or a single-column source-mode run) — real content only
    # for a multi-column chunked run started via the new columns-based
    # execution path. `progress` stays None until the first chunk
    # commits, matching `metrics`' own "zero counters until something
    # actually happened" default.
    columns: tuple[RunColumnSpec, ...] = ()
    progress: RunProgress | None = None
    # Phase 3 item 2: empty unless a cache was actually configured for
    # this run (see `RunRecorder.record_cache_policy`) — a run with no
    # cache has nothing to decide a policy about, matching `columns`'
    # own "empty until the real thing happened" default.
    cache_policy: tuple[ColumnCachePolicy, ...] = ()

    def is_terminal(self) -> bool:
        return self.status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.PARTIAL)

"""Request/response schemas for the §98 API surface.

Reuses normcore domain models directly as response bodies wherever a
model already represents exactly what the endpoint returns
(NormalizationProfile, NormalizationRun, NormalizedValue, Dictionary) —
no parallel "API DTO" duplicating fields that would drift from the real
contract. Request-only shapes (things clients send that aren't a stored
entity themselves) get their own thin models here.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from normcore import (
    CloneJobStatus,
    ErrorPolicy,
    FieldNormalizationConfig,
    FieldSemanticType,
)

# 'postgres' | 'clickhouse' — matches decision scope (Postgres+ClickHouse
# only); not a normcore StrEnum since it's a normapi/normio-local
# connection-engine choice, not a domain-model concept.
ConnectionEngine = Literal["postgres", "clickhouse"]


class ProfileCreateRequest(BaseModel):
    name: str
    description: str = ""
    locale_policy: dict[str, str] = Field(default_factory=dict)
    default_operations: tuple[str, ...] = ()
    field_configs: tuple[FieldNormalizationConfig, ...] = ()
    created_by: str


class ProfileVersionRequest(BaseModel):
    """Body for POST /normalization/profiles/{id}/versions — creates a new
    version of an existing profile. Only fields being changed need to be
    supplied; omitted fields carry over from the profile being versioned.
    """

    description: str | None = None
    locale_policy: dict[str, str] | None = None
    default_operations: tuple[str, ...] | None = None
    field_configs: tuple[FieldNormalizationConfig, ...] | None = None
    created_by: str


class PreviewRequest(BaseModel):
    field_name: str
    semantic_type: FieldSemanticType
    values: list[str | None]
    error_policy: ErrorPolicy = ErrorPolicy.RETURN_ORIGINAL


class FieldTestRequest(BaseModel):
    field_name: str
    semantic_type: FieldSemanticType
    value: str | None
    error_policy: ErrorPolicy = ErrorPolicy.RETURN_ORIGINAL


class RunExecutionRequest(BaseModel):
    """Optional body for POST /normalization/runs — when supplied, the
    run actually normalizes `values` through the live Dispatcher (M6);
    when omitted, the run is created PENDING with no field execution,
    exactly matching M1's original scaffold behavior."""

    field_name: str
    semantic_type: FieldSemanticType
    values: list[str | None]
    error_policy: ErrorPolicy = ErrorPolicy.RETURN_ORIGINAL


class ProfileRollbackRequest(BaseModel):
    target_version: str


class DetectTypeRequest(BaseModel):
    """§61 automatic field type detection — a suggestion only, never
    auto-applied (§85 "no silent changes")."""

    field_name: str
    sample_values: list[str | None] = Field(default_factory=list)


class DictionaryCreateRequest(BaseModel):
    id: str
    entries: dict[str, Any] = Field(default_factory=dict)
    locale: str | None = None
    source: str
    license: str
    created_by: str


class DictionaryVersionRequest(BaseModel):
    entries: dict[str, Any] = Field(default_factory=dict)
    locale: str | None = None
    source: str | None = None
    license: str | None = None
    created_by: str
    merge: bool = False


class DictionaryRollbackRequest(BaseModel):
    target_version: str
    by: str


class TypeSuggestionResponse(BaseModel):
    semantic_type: FieldSemanticType
    confidence: float
    reason: str


class ProfileSuggestionResponse(BaseModel):
    semantic_type: FieldSemanticType
    recommended_summary: str
    risk: str
    real_steps: list[str]


class FieldSummary(BaseModel):
    """One row of GET /normalization/fields — derived from every known
    profile's field_configs, not a separately-maintained list."""

    field_ref: str
    semantic_type: FieldSemanticType
    profile_ids: list[str]


class DictionarySummary(BaseModel):
    id: str
    version: str
    locale: str | None
    source: str
    license: str
    entry_count: int
    is_custom: bool = False
    active_version: str | None = None


class ConnectionCreateRequest(BaseModel):
    """Decisions #2/#13: a server-level (host+port+username+password+
    engine) saved credential. The database is picked fresh each use, never
    baked in here."""

    engine: ConnectionEngine
    host: str
    port: int
    username: str
    password: str


class Connection(BaseModel):
    """Response shape — never carries the password, encrypted or not
    (decision #12: decrypted only in memory at connect-time)."""

    connection_id: str
    engine: ConnectionEngine
    host: str
    port: int
    username: str
    created_at: str


class DatabaseDiscoveryRequest(BaseModel):
    """Optional ad-hoc credential override for the "not yet saved"
    discovery case (§4's `POST /connections/{id}/databases`) — when
    `connection_id` in the path is the literal `"adhoc"`, every field
    here is required; otherwise this body is omitted and the saved
    connection's credentials are used as-is."""

    engine: ConnectionEngine | None = None
    host: str | None = None
    port: int | None = None
    username: str | None = None
    password: str | None = None


class ColumnInfoResponse(BaseModel):
    name: str
    native_type: str


class CloneJobCreateRequest(BaseModel):
    """Body for `POST /clone-jobs`. Every table in `source_database` is
    cloned automatically (decision #3) — `field_configs` only decides,
    per already-included table/column, a semantic type or passthrough
    (a column absent from its table's map, or mapped to null, is
    passthrough)."""

    model_config = ConfigDict(extra="forbid")  # a removed or misspelt option is an error

    source_connection_id: str
    source_database: str
    # Postgres only: the namespace inside `source_database` that table names
    # are relative to. Unset uses the connection's default (`public`), which
    # is why a source keeping its tables in a named schema used to produce a
    # job with no tables that still reported COMPLETED. One schema per job,
    # so the clone's own table names stay unqualified.
    source_schema: str | None = None
    destination_connection_id: str = Field(min_length=1)
    destination_database: str = Field(min_length=1)
    # Off by default: a column absent from `field_configs` is cloned
    # verbatim. Detection still runs and the plan (`GET .../plan`) shows its
    # suggestion per column with the share of sampled values that validate;
    # opt a column in by giving it that type (here or via PATCH .../plan).
    # On applies every confident suggestion to the whole job; an explicit
    # entry always overrides the guess.
    autodetect_field_types: bool = False
    # Sweep every remaining textual column into FREE_TEXT (unicode
    # normalization, zero-width strip, whitespace collapse, punctuation
    # folding). Off by default: folding is lossy, so it is the operator's
    # call rather than something inference should decide.
    normalize_unconfigured_text: bool = False
    # The country and locale every normalizer gets as context. Most
    # normalizers refuse to guess without them and say so rather than
    # picking: a POSTCODE returns AMBIGUOUS with no country to validate
    # against, `1,234` stays AMBIGUOUS with no locale to say whether the
    # comma groups or decimalises, `$948,000` likewise, and `12/05/1990`
    # is never read as either MDY or DMY. Measured on a real 1.27M-row
    # source, supplying them moved PHONE from 74.1% AMBIGUOUS to 99.5%
    # PARSED. Left unset, every one of those refusals stands — which is
    # correct, just much less useful. Not inferred: a wrong locale
    # silently changes what a number MEANS.
    country: str | None = None
    locale: str | None = None
    # Column name identifying the same real-world entity across tables
    # (e.g. a company id). Given one, a COUNTRY column in ANY table that
    # carries it supplies `country` for every row of every OTHER table
    # sharing that entity — the case a within-row signal cannot reach,
    # because Phase 2 streams one table at a time and never holds two.
    # Measured on a real source: 339,596 phone numbers across 357
    # countries gained a country this way, 79.3% of which then parsed
    # instead of staying AMBIGUOUS.
    #
    # Declared, never inferred. Inferring it would mean picking a column
    # that happens to appear in two tables, and `_version`/`created_at`
    # appear in every table of both real sources this was built against;
    # a wrong join key propagates a WRONG country, which is worse than
    # none. An entity whose rows disagree about the country is dropped
    # rather than resolved, and a value the inferred country turns out not
    # to fit keeps its no-country result.
    cross_table_entity_key: str | None = None
    # Give NUMERIC/MONEY/BOOLEAN columns a real SQL type (NUMERIC, BOOLEAN)
    # instead of TEXT, so downstream SUM/AVG work without casting. On by
    # default: an untyped clone of a numeric column cannot be summed, which
    # is most of the reason to normalize it. A value that will not cast
    # becomes NULL plus an error-report row keeping the original, and the
    # column-level null-rate report (below) says how often that happened —
    # without that report this default would hide the loss, which is why it
    # was off before one existed.
    typed_destination_columns: bool = True
    # Fail the job when normalizing empties more than this fraction of any
    # one column's non-null source values. Unset means report and continue:
    # every column over NORM_CLONE_NULL_RATE_REPORT (5% by default) gets a
    # row in the error report either way. Set it when a clone feeds
    # something that cannot tolerate a silently gutted column.
    max_new_null_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    # D4: per table and column, source values a person confirmed are
    # disguised nulls (from a job's `quality[...]["disguised_missing"]`).
    # They are written as NULL with an error row keeping the original.
    # Exact values only: nothing is matched loosely, nothing is guessed.
    confirmed_missing: dict[str, dict[str, list[str]]] | None = None
    # ADR-019: an answer below its type's calibrated threshold (the committed
    # table, risk-controlled at cost ratio 20) becomes AMBIGUOUS, original
    # kept, and goes to the review queue. Off by default: every clone reports
    # those answers in its quality report either way.
    calibrated_abstention: bool = False

    @model_validator(mode="after")
    def _destination_is_not_the_origin(self) -> CloneJobCreateRequest:
        """ADR-013: the origin is never written. The same connection and the same
        database is the origin itself; anything else is a separate copy."""
        if (
            self.destination_connection_id == self.source_connection_id
            and self.destination_database == self.source_database
        ):
            msg = (
                "The destination is the origin. Choose another database: "
                "every clone writes a separate copy."
            )
            raise ValueError(msg)
        return self

    # ponytail: stored inside normalization_clone_jobs.data's JSON blob,
    # not a separate table — consumed exactly twice (Phase 1 DDL, Phase 2
    # normalization) by the job that owns it. Promote to its own table
    # only if "reuse this column config across jobs" becomes a real
    # requirement.
    field_configs: dict[str, dict[str, FieldSemanticType | None]] = Field(default_factory=dict)


class CloneJobAmendRequest(BaseModel):
    """Body for `PATCH /clone-jobs/{id}/plan` — what a reviewer may change
    after reading the plan and before anything is built.

    Every field is optional and only what was SENT is applied, so a review
    that changes one column does not have to restate the other 113 that
    autodetect got right. `field_configs` merges per table and per column;
    an explicit null on a column clears it back to passthrough.

    Absent on purpose: the connections, the databases and the
    table list. Those are what the job is, and nothing has been built yet,
    so a job pointed somewhere else is cheap to create rather than amend.
    """

    field_configs: dict[str, dict[str, FieldSemanticType | None]] | None = None
    country: str | None = None
    locale: str | None = None
    typed_destination_columns: bool | None = None
    max_new_null_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    cross_table_entity_key: str | None = None
    confirmed_missing: dict[str, dict[str, list[str]]] | None = None
    calibrated_abstention: bool | None = None


class CloneJobCreateResponse(BaseModel):
    job_id: str
    status: CloneJobStatus
    create_database_sql: str


class AdjudicationQueueEntry(BaseModel):
    """One open (or answered) question — ADR-018. `safe_preview` and the
    masked `detail` follow the error report's PII rule: the raw value is
    at rest in the metadata database, never in a response."""

    key: str
    semantic_type: FieldSemanticType
    safe_preview: str
    context: dict[str, Any]
    detail: dict[str, Any]
    first_job_id: str
    last_job_id: str
    occurrences: int
    decided: bool
    verdicts: list[AdjudicationVerdict] = Field(default_factory=list)


class AdjudicationVerdictRequest(BaseModel):
    decided_value: str = Field(min_length=1)
    # `human:<id>` or `agent:<id>` (Q15), checked in the route against
    # `normapi.adjudication.DECIDED_BY`.
    decided_by: str
    rationale: str = Field(min_length=1)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class AdjudicationVerdict(BaseModel):
    """`decided_value` itself is not echoed (it is the answer to a value
    the API never returns raw); `decided_display` is what it normalizes
    to, masked the same way."""

    key: str
    decided_display_preview: str | None
    decided_by: str
    decided_at: str
    rationale: str
    confidence: float | None
    env_id: str
    profile_version: str


class NotImplementedResponse(BaseModel):
    """Honest, schema-valid placeholder for §98 endpoints whose real
    implementation is still out of scope at the current milestone —
    returned with HTTP 501 rather than silently faking success.
    """

    detail: str
    planned_milestone: str


__all__ = [
    "AdjudicationQueueEntry",
    "AdjudicationVerdict",
    "AdjudicationVerdictRequest",
    "CloneJobCreateRequest",
    "CloneJobCreateResponse",
    "ColumnInfoResponse",
    "Connection",
    "ConnectionCreateRequest",
    "DatabaseDiscoveryRequest",
    "DetectTypeRequest",
    "DictionaryCreateRequest",
    "DictionaryRollbackRequest",
    "DictionarySummary",
    "DictionaryVersionRequest",
    "FieldSummary",
    "FieldTestRequest",
    "NotImplementedResponse",
    "PreviewRequest",
    "ProfileCreateRequest",
    "ProfileRollbackRequest",
    "ProfileSuggestionResponse",
    "ProfileVersionRequest",
    "RunExecutionRequest",
    "TypeSuggestionResponse",
]

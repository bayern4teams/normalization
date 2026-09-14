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

from pydantic import BaseModel, Field

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

    source_connection_id: str
    source_database: str
    destination_connection_id: str
    destination_database: str
    # ponytail: stored inside normalization_clone_jobs.data's JSON blob,
    # not a separate table — consumed exactly twice (Phase 1 DDL, Phase 2
    # normalization) by the job that owns it. Promote to its own table
    # only if "reuse this column config across jobs" becomes a real
    # requirement.
    field_configs: dict[str, dict[str, FieldSemanticType | None]] = Field(default_factory=dict)


class CloneJobCreateResponse(BaseModel):
    job_id: str
    status: CloneJobStatus
    create_database_sql: str


class NotImplementedResponse(BaseModel):
    """Honest, schema-valid placeholder for §98 endpoints whose real
    implementation is still out of scope at the current milestone —
    returned with HTTP 501 rather than silently faking success.
    """

    detail: str
    planned_milestone: str


__all__ = [
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

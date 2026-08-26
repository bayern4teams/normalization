"""Request/response schemas for the §98 API surface.

Reuses normcore domain models directly as response bodies wherever a
model already represents exactly what the endpoint returns
(NormalizationProfile, NormalizationRun, NormalizedValue, Dictionary) —
no parallel "API DTO" duplicating fields that would drift from the real
contract. Request-only shapes (things clients send that aren't a stored
entity themselves) get their own thin models here.
"""

from __future__ import annotations

from typing import Any, Self

from pydantic import BaseModel, Field, SecretStr, model_validator

from normanalysis import CollisionDecisionType
from normapi.connections import CONNECTION_KINDS
from normcore import (
    ErrorPolicy,
    FieldNormalizationConfig,
    FieldSemanticType,
    RunColumnSpec,
    SemanticSource,
)


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


class RunSourceRequest(BaseModel):
    """M10: read a run's values from a real, server-registered source
    connector (Source.txt §105) instead of pasting them. `row_limit`
    caps how many rows this SYNCHRONOUS request will read — there is no
    async/chunked execution path yet (that's M11's job); this cap keeps a
    request against an accidentally-huge table from blocking forever.
    100_000 mirrors SourceConnector.read_table's own default batch_size,
    a reasonable per-request ceiling for a synchronous HTTP call.

    `database` (M16): when given, `source_id` is a connection id from
    M15's registry rather than a `NORM_SOURCES_CONFIG_PATH` file entry —
    resolved via `SourceRegistry.get_by_connection`. When omitted, the
    original M10 file-config `source_id` path is used unchanged (zero
    behavior change for existing callers)."""

    source_id: str
    table: str
    column: str
    row_limit: int = Field(default=10_000, gt=0, le=100_000)
    database: str | None = None


class RunExecutionRequest(BaseModel):
    """Optional body for POST /normalization/runs — when supplied, the
    run actually normalizes values through the live Dispatcher (M6);
    when omitted, the run is created PENDING with no field execution,
    exactly matching M1's original scaffold behavior. Exactly one of
    `values` (pasted, M6) or `source` (read from a real connector, M10)
    must be supplied.

    `semantic_type` (M16): now optional. Omitted means "resolve from a
    matching profile field config" (a saved M16 column mapping,
    materialized into the profile) — see `InMemoryStore.execute_run`'s
    docstring for the real bug this fixes: before M16 this field was
    required and always won unconditionally, so a profile's own saved
    mapping was never even consulted. Given explicitly, it's still an
    override that always wins, same precedent `error_policy` already
    follows."""

    field_name: str
    semantic_type: FieldSemanticType | None = None
    values: list[str | None] | None = None
    source: RunSourceRequest | None = None
    # None (the default — omitted from the request body) means "defer to
    # the run's own profile's per-field error_policy" (§60-62, M10) rather
    # than silently forcing RETURN_ORIGINAL regardless of profile config;
    # an explicit value here still always wins as a one-off override.
    error_policy: ErrorPolicy | None = None

    @model_validator(mode="after")
    def _exactly_one_of_values_or_source(self) -> Self:
        if (self.values is None) == (self.source is None):
            msg = "Exactly one of `values` or `source` must be supplied"
            raise ValueError(msg)
        return self


class MultiColumnRunRequest(BaseModel):
    """POST /normalization/runs/{run_id}/columns body — M17. A real
    multi-column, chunked, resumable run against a connection-based
    source (M15) — decision 5 of the M13-M22 program, "one run holds
    many columns." `columns[].semantic_type` must be given explicitly;
    unlike the single-column path (M16), this endpoint does not itself
    re-resolve semantic types from saved column mappings — a caller
    building this request from saved mappings (e.g. the future M21 UI)
    reads them via M16's `GET .../mappings` routes and fills
    `semantic_type` in directly."""

    connection_id: str
    database: str
    columns: tuple[RunColumnSpec, ...]
    chunk_size: int = Field(default=100_000, gt=0, le=1_000_000)

    @model_validator(mode="after")
    def _at_least_one_column(self) -> Self:
        if not self.columns:
            msg = "columns must be non-empty"
            raise ValueError(msg)
        return self


class DestinationRunRequest(BaseModel):
    """POST /normalization/runs/{run_id}/destination body — M19. Mirrors
    one real source table into a real destination database: every
    column mapped in `columns` is normalized (and, for NUMERIC/DATE, real
    typed), every other real column of `source_table` is copied verbatim
    — decision 6/7 of the M13-M22 program.

    `i_understand_same_server` (M19's own hard rule, plan callout #3):
    the ONLY way to target a different database on the SAME server as
    the source — never bypasses the exact-identity self-write refusal,
    only the same-server-different-database one. Defaults to `False`;
    must be deliberately set `True` to write next to the real source."""

    source_connection_id: str
    source_database: str
    source_table: str
    destination_connection_id: str
    destination_database: str
    destination_table: str
    columns: tuple[RunColumnSpec, ...]
    chunk_size: int = Field(default=100_000, gt=0, le=1_000_000)
    i_understand_same_server: bool = False

    @model_validator(mode="after")
    def _at_least_one_mapped_column(self) -> Self:
        if not self.columns:
            msg = "columns must be non-empty"
            raise ValueError(msg)
        if any(c.table != self.source_table for c in self.columns):
            msg = "every column must belong to source_table — a destination run mirrors ONE table"
            raise ValueError(msg)
        return self


class CollisionDecisionRequest(BaseModel):
    """§92 Collision Dashboard: a human reviewer's real disposition on
    one collision group. `normalized_value` is carried in the body
    rather than the URL path — a collision group's real value (e.g.
    accented, containing spaces) doesn't need URL-path-encoding
    treatment this way."""

    normalized_value: str
    decision: CollisionDecisionType
    decided_by: str
    note: str | None = None
    table: str | None = None
    column: str | None = None


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
    """POST /normalization/connections body — M15. `password` is
    `SecretStr` so it never appears verbatim in a FastAPI validation-error
    response or a `repr()`/log of the parsed model; `port` omitted means
    the real default port for `kind` (normapi.connections.DEFAULT_PORTS).
    """

    alias: str
    kind: str
    host: str
    port: int | None = None
    username: str
    password: SecretStr
    database: str

    @model_validator(mode="after")
    def _kind_is_known(self) -> Self:
        if self.kind not in CONNECTION_KINDS:
            allowed = sorted(CONNECTION_KINDS)
            msg = f"Unknown connection kind {self.kind!r} (expected one of {allowed})"
            raise ValueError(msg)
        return self


class ConnectionTestRequest(BaseModel):
    """POST /normalization/connections/test body — same shape as create
    but never persisted; used to validate credentials before saving."""

    kind: str
    host: str
    port: int | None = None
    username: str
    password: SecretStr
    database: str

    @model_validator(mode="after")
    def _kind_is_known(self) -> Self:
        if self.kind not in CONNECTION_KINDS:
            allowed = sorted(CONNECTION_KINDS)
            msg = f"Unknown connection kind {self.kind!r} (expected one of {allowed})"
            raise ValueError(msg)
        return self


class ConnectionUpdateRequest(BaseModel):
    """PATCH /normalization/connections/{id} body — every field optional,
    only supplied fields change. `password`, when supplied, is
    re-encrypted; omitted means the stored credential is untouched."""

    alias: str | None = None
    host: str | None = None
    port: int | None = None
    username: str | None = None
    password: SecretStr | None = None
    database: str | None = None


class ConnectionResponse(BaseModel):
    """GET/POST /normalization/connections response — deliberately has NO
    password field at all (absent from the schema, not present-as-null),
    so no code path can accidentally serialize a credential into it."""

    id: str
    alias: str
    kind: str
    host: str
    port: int
    username: str
    database: str
    identity: str
    created_at: str
    updated_at: str


class ConnectionTestResponse(BaseModel):
    ok: bool
    databases: list[str] = Field(default_factory=list)
    error: str | None = None


class ConnectionKindInfo(BaseModel):
    kind: str
    default_port: int


class ColumnSpecResponse(BaseModel):
    """M16 — a table's column, as reported by `normio.catalog.ColumnSpec`
    (a plain dataclass, not itself a pydantic model), wrapped for the
    catalog API's response body."""

    name: str
    type: str
    nullable: bool
    is_primary_key: bool


class TableSpecResponse(BaseModel):
    name: str
    engine: str | None
    approx_rows: int | None
    columns: list[ColumnSpecResponse]


class ColumnMappingUpsertRequest(BaseModel):
    """PUT .../columns/{column}/mapping body — M16. `profile_id`, when
    given, additionally materializes this mapping into that profile as a
    new version (see `normapi.mappings.materialize_field_config`); when
    omitted, only the mapping itself is saved, editable again later
    before ever touching a profile."""

    semantic_type: FieldSemanticType
    enabled: bool = True
    updated_by: str
    profile_id: str | None = None


class ColumnMappingResponse(BaseModel):
    database: str
    table_name: str
    column_name: str
    semantic_type: FieldSemanticType
    semantic_source: SemanticSource
    enabled: bool
    updated_at: str
    updated_by: str


class NotImplementedResponse(BaseModel):
    """Honest, schema-valid placeholder for §98 endpoints whose real
    implementation is still out of scope at the current milestone —
    returned with HTTP 501 rather than silently faking success.
    """

    detail: str
    planned_milestone: str


__all__ = [
    "CollisionDecisionRequest",
    "ColumnMappingResponse",
    "ColumnMappingUpsertRequest",
    "ColumnSpecResponse",
    "ConnectionCreateRequest",
    "ConnectionKindInfo",
    "ConnectionResponse",
    "ConnectionTestRequest",
    "ConnectionTestResponse",
    "ConnectionUpdateRequest",
    "DetectTypeRequest",
    "DictionaryCreateRequest",
    "DictionaryRollbackRequest",
    "DictionarySummary",
    "DictionaryVersionRequest",
    "FieldSummary",
    "FieldTestRequest",
    "MultiColumnRunRequest",
    "NotImplementedResponse",
    "PreviewRequest",
    "ProfileCreateRequest",
    "ProfileRollbackRequest",
    "ProfileSuggestionResponse",
    "ProfileVersionRequest",
    "RunExecutionRequest",
    "RunSourceRequest",
    "TableSpecResponse",
    "TypeSuggestionResponse",
]

"""Source.txt §98 API routes.

    POST /normalization/profiles
    GET  /normalization/profiles
    GET  /normalization/fields
    POST /normalization/preview
    POST /normalization/runs
    GET  /normalization/runs                          (M7, §94)
    GET  /normalization/runs/{id}
    GET  /normalization/profiles/{id}                  (M7, §95)
    GET  /normalization/profiles/{id}/versions          (M7, §95)
    GET  /normalization/runs/{id}/errors
    GET  /normalization/runs/{id}/collisions
    GET  /normalization/runs/{id}/values               (M7, §121)
    POST /normalization/profiles/{id}/versions
    POST /normalization/profiles/{id}/rollback   (M6, §59/§94)
    POST /normalization/dictionaries
    GET  /normalization/dictionaries
    GET  /normalization/dictionaries/{id}             (M7, §115)
    POST /normalization/dictionaries/{id}/versions   (M6, §59)
    POST /normalization/dictionaries/{id}/rollback   (M6, §59)
    DELETE /normalization/dictionaries/{id}          (M6, §59)
    POST /normalization/field-test
    GET  /normalization/impact
    GET  /normalization/runs/compare                 (M6, §96/§97)
    GET  /normalization/runs/{id}/profile             (M6, §77)
    GET  /normalization/overview                      (M7, §90)
    GET  /normalization/quality                        (M7, §93)
    POST /normalization/detect-type                    (M7-audit, §61)
    GET  /normalization/suggest-profile                (M7-audit, §62/§84)
    GET  /normalization/sources                         (M10, §105)
    GET  /normalization/sources/{id}/tables              (M10, §105)
    POST /normalization/runs/{id}/collisions/decision     (M11, §92)

Every route is registered and returns a schema-valid response (M1's Gate
G1 requirement). As of M6: profile/run CRUD+rollback, field-test/preview,
dictionary write/versioning/rollback, and impact/collision/A-B analysis
are all wired to real logic — no remaining 501 stubs on the §98 surface.

M11: every POST/PUT/PATCH/DELETE route on this router requires
`Authorization: Bearer <NORM_API_KEY>` when that env var is set (see
normapi.auth) — a single router-level dependency, not per-route, so a
future mutating route is protected by construction.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, cast

from fastapi import APIRouter, Body, Depends, HTTPException
from normcore.pii import safe_preview
from normio.capabilities import CatalogConnector, CatalogSourceConnector, StreamingSourceConnector

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

from normanalysis import (
    CollisionDecision,
    HandoffArtifact,
    build_handoff_artifact,
    compare_runs,
    compute_impact,
    compute_overview_from_stats,
    compute_quality_from_stats,
    find_collisions,
    profile_field,
    suggest_profile,
    suggest_semantic_type,
)
from normapi.auth import enforce_api_key_for_mutations
from normapi.connections import (
    DEFAULT_PORTS,
    ConnectionRecord,
    ConnectionResolver,
    connection_identity,
)
from normapi.dependencies import (
    get_connection_resolver,
    get_custom_dictionary_store,
    get_dictionary_loader,
    get_dispatcher,
    get_postgres_store,
    get_run_executor,
    get_source_registry,
    get_store,
)
from normapi.executor import RunExecutor
from normapi.mappings import ColumnMapping, materialize_field_config
from normapi.postgres_store import PostgresMetadataStore
from normapi.scaffold_profile import SCAFFOLD_PROFILE
from normapi.schemas import (
    CollisionDecisionRequest,
    ColumnMappingResponse,
    ColumnMappingUpsertRequest,
    ColumnSpecResponse,
    ConnectionCreateRequest,
    ConnectionKindInfo,
    ConnectionResponse,
    ConnectionTestRequest,
    ConnectionTestResponse,
    ConnectionUpdateRequest,
    DetectTypeRequest,
    DictionaryCreateRequest,
    DictionaryRollbackRequest,
    DictionarySummary,
    DictionaryVersionRequest,
    FieldSummary,
    FieldTestRequest,
    MultiColumnRunRequest,
    PreviewRequest,
    ProfileCreateRequest,
    ProfileRollbackRequest,
    ProfileSuggestionResponse,
    ProfileVersionRequest,
    RunExecutionRequest,
    TableSpecResponse,
    TypeSuggestionResponse,
)
from normapi.sources import SourceRegistry, UnknownSourceError, build_connector_from_parts
from normapi.store import (
    InMemoryStore,
    ProfileNotFoundError,
    RunNotExecutableError,
    RunNotFoundError,
    UnknownCollisionError,
)
from normcore import (
    Dispatcher,
    FieldSemanticType,
    NormalizationContext,
    NormalizationError,
    NormalizationProfile,
    NormalizationRun,
    NormalizedValue,
    SemanticSource,
)
from normdict import (
    BuiltinIdCollisionError,
    CustomDictionaryDeletedError,
    CustomDictionaryError,
    CustomDictionaryNotFoundError,
    CustomDictionaryStore,
    DictionaryLoader,
    DictionaryNotFoundError,
)

router = APIRouter(prefix="/normalization", dependencies=[Depends(enforce_api_key_for_mutations)])


# --- profiles -----------------------------------------------------------


@router.post("/profiles", response_model=NormalizationProfile, status_code=201)
def create_profile(
    body: ProfileCreateRequest, store: Annotated[InMemoryStore, Depends(get_store)]
) -> NormalizationProfile:
    return store.create_profile(
        name=body.name,
        description=body.description,
        locale_policy=body.locale_policy,
        default_operations=body.default_operations,
        field_configs=body.field_configs,
        created_by=body.created_by,
    )


@router.get("/profiles", response_model=list[NormalizationProfile])
def list_profiles(
    store: Annotated[InMemoryStore, Depends(get_store)],
) -> list[NormalizationProfile]:
    return store.list_profiles()


@router.get("/profiles/{profile_id}", response_model=NormalizationProfile)
def get_profile(
    profile_id: str, store: Annotated[InMemoryStore, Depends(get_store)]
) -> NormalizationProfile:
    try:
        return store.get_profile(profile_id)
    except ProfileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"No such profile: {profile_id}") from exc


@router.get("/profiles/{profile_id}/versions", response_model=list[NormalizationProfile])
def list_profile_versions(
    profile_id: str, store: Annotated[InMemoryStore, Depends(get_store)]
) -> list[NormalizationProfile]:
    """§95 profile versioning — every version ever created for this
    profile, active and deprecated alike (never deleted)."""
    try:
        return store.list_profile_versions(profile_id)
    except ProfileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"No such profile: {profile_id}") from exc


@router.post(
    "/profiles/{profile_id}/versions", response_model=NormalizationProfile, status_code=201
)
def create_profile_version(
    profile_id: str,
    body: ProfileVersionRequest,
    store: Annotated[InMemoryStore, Depends(get_store)],
) -> NormalizationProfile:
    try:
        return store.create_version(
            profile_id,
            description=body.description,
            locale_policy=body.locale_policy,
            default_operations=body.default_operations,
            field_configs=body.field_configs,
            created_by=body.created_by,
        )
    except ProfileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"No such profile: {profile_id}") from exc


@router.post("/profiles/{profile_id}/rollback", response_model=NormalizationProfile)
def rollback_profile(
    profile_id: str,
    body: ProfileRollbackRequest,
    store: Annotated[InMemoryStore, Depends(get_store)],
) -> NormalizationProfile:
    """§59/§94's "Rollback Profile" — reactivates a prior version without
    deleting the version being rolled back from."""
    try:
        return store.rollback_profile(profile_id, body.target_version)
    except ProfileNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail=f"No such profile/version: {profile_id}@{body.target_version}"
        ) from exc


# --- fields ---------------------------------------------------------------


@router.get("/fields", response_model=list[FieldSummary])
def list_fields(store: Annotated[InMemoryStore, Depends(get_store)]) -> list[FieldSummary]:
    """Derived from every known profile's field_configs — not a
    separately-maintained list, so it can never drift from what profiles
    actually reference."""
    by_field: dict[str, FieldSummary] = {}
    for profile in store.list_profiles():
        for config in profile.field_configs:
            if config.field_ref not in by_field:
                by_field[config.field_ref] = FieldSummary(
                    field_ref=config.field_ref,
                    semantic_type=config.semantic_type,
                    profile_ids=[profile.id],
                )
            elif profile.id not in by_field[config.field_ref].profile_ids:
                by_field[config.field_ref].profile_ids.append(profile.id)
    return list(by_field.values())


@router.post("/detect-type", response_model=list[TypeSuggestionResponse])
def detect_type(
    body: DetectTypeRequest,
    dispatcher: Annotated[Dispatcher, Depends(get_dispatcher)],
) -> list[TypeSuggestionResponse]:
    """§61 automatic field type detection — a ranked list of
    suggestions, never applied automatically (§85: the user must accept/
    modify/reject)."""
    suggestions = suggest_semantic_type(
        body.field_name,
        sample_values=body.sample_values or None,
        registry=dispatcher.registry,
    )
    return [
        TypeSuggestionResponse(
            semantic_type=s.semantic_type, confidence=s.confidence, reason=s.reason
        )
        for s in suggestions
    ]


@router.get("/suggest-profile", response_model=ProfileSuggestionResponse)
def suggest_profile_route(
    semantic_type: FieldSemanticType,
    dispatcher: Annotated[Dispatcher, Depends(get_dispatcher)],
    sample_value: str | None = None,
) -> ProfileSuggestionResponse:
    """§62/§84 normalization profile auto-generation — a suggestion only;
    `real_steps` is read from the live registry, never fabricated."""
    suggestion = suggest_profile(
        semantic_type,
        registry=dispatcher.registry,
        sample_value=sample_value,
    )
    return ProfileSuggestionResponse(
        semantic_type=suggestion.semantic_type,
        recommended_summary=suggestion.recommended_summary,
        risk=suggestion.risk,
        real_steps=list(suggestion.real_steps),
    )


# --- sources (§105, M10) -----------------------------------------------------


@router.get("/sources", response_model=list[str])
def list_sources(
    sources: Annotated[SourceRegistry, Depends(get_source_registry)],
) -> list[str]:
    """Real, server-registered source_ids only (`NORM_SOURCES_CONFIG_PATH`)
    — never a client-suppliable value, so this is simply what's actually
    connected, not a catalog of hypothetical sources."""
    return sources.list_source_ids()


@router.get("/sources/{source_id}/tables", response_model=list[str])
def list_source_tables(
    source_id: str,
    sources: Annotated[SourceRegistry, Depends(get_source_registry)],
) -> list[str]:
    try:
        connector = sources.get(source_id)
    except UnknownSourceError as exc:
        raise HTTPException(status_code=404, detail=f"No such source: {source_id}") from exc
    return list(connector.list_tables())


# --- connections (M15, docs/plan/M13-M22-program-plan.md) -----------------


def _connection_registry_unavailable() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail=(
            "Connection registry unavailable: both NORM_SECRET_KEY and "
            "NORM_PG_DSN must be set to store connections"
        ),
    )


def _to_connection_response(record: ConnectionRecord) -> ConnectionResponse:
    return ConnectionResponse(
        id=record.id,
        alias=record.alias,
        kind=record.kind,
        host=record.host,
        port=record.port,
        username=record.username,
        database=record.database,
        identity=record.identity,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _scrub(message: str, *secrets_to_scrub: str) -> str:
    """Removes any literal occurrence of a plaintext secret from an
    error message before it's returned to the client or could reach a
    log line — defense in depth against a driver-level exception
    embedding a DSN/connection string that happens to contain the
    password, on top of never deliberately including it."""
    for secret in secrets_to_scrub:
        if secret:
            message = message.replace(secret, "***")
    return message


def _probe_connection(
    *, kind: str, host: str, port: int, username: str, password: str, database: str
) -> list[str]:
    """Builds a real connector, proves it can actually connect
    (`list_tables()` — every SourceConnector has this), and returns
    `list_databases()` when the connector also supports `CatalogConnector`
    (empty list otherwise). Always closes the connector before returning,
    whether it succeeds or raises — this connector is never pooled, it
    exists only for the duration of this check."""
    connector = build_connector_from_parts(
        "connection-probe",
        kind=kind,
        host=host,
        port=port,
        username=username,
        password=password,
        database=database,
    )
    try:
        connector.list_tables()
        if isinstance(connector, CatalogConnector):
            return list(connector.list_databases())
        return []
    finally:
        connector.close()


@router.get("/connection-kinds", response_model=list[ConnectionKindInfo])
def list_connection_kinds() -> list[ConnectionKindInfo]:
    return [
        ConnectionKindInfo(kind=kind, default_port=port)
        for kind, port in sorted(DEFAULT_PORTS.items())
    ]


@router.post("/connections/test", response_model=ConnectionTestResponse)
def test_connection(body: ConnectionTestRequest) -> ConnectionTestResponse:
    """Validates credentials against the real database WITHOUT persisting
    anything — the UI's "Test" button before Save. Never raises on a bad
    credential; a failed connection is a normal, expected outcome this
    returns as data (`ok=False`), not an HTTP error."""
    port = body.port or DEFAULT_PORTS[body.kind]
    password = body.password.get_secret_value()
    try:
        databases = _probe_connection(
            kind=body.kind,
            host=body.host,
            port=port,
            username=body.username,
            password=password,
            database=body.database,
        )
    except Exception as exc:  # broad: any driver failure -> a scrubbed result, not a 500
        return ConnectionTestResponse(ok=False, error=_scrub(str(exc), password))
    return ConnectionTestResponse(ok=True, databases=databases)


@router.post("/connections", response_model=ConnectionResponse, status_code=201)
def create_connection(
    body: ConnectionCreateRequest,
    pg_store: Annotated[PostgresMetadataStore | None, Depends(get_postgres_store)],
    resolver: Annotated[ConnectionResolver | None, Depends(get_connection_resolver)],
) -> ConnectionResponse:
    if pg_store is None or resolver is None:
        raise _connection_registry_unavailable()
    port = body.port or DEFAULT_PORTS[body.kind]
    password = body.password.get_secret_value()
    try:
        _probe_connection(
            kind=body.kind,
            host=body.host,
            port=port,
            username=body.username,
            password=password,
            database=body.database,
        )
    except Exception as exc:  # see test_connection's identical rationale
        raise HTTPException(status_code=400, detail=_scrub(str(exc), password)) from exc

    now = datetime.now(UTC).isoformat()
    record = ConnectionRecord(
        id=str(uuid.uuid4()),
        alias=body.alias,
        kind=body.kind,
        host=body.host,
        port=port,
        username=body.username,
        encrypted_password=resolver.encrypt(password),
        database=body.database,
        identity=connection_identity(body.kind, body.host, port, body.database),
        created_at=now,
        updated_at=now,
    )
    pg_store.save_connection(record)
    return _to_connection_response(record)


@router.get("/connections", response_model=list[ConnectionResponse])
def list_connections(
    pg_store: Annotated[PostgresMetadataStore | None, Depends(get_postgres_store)],
) -> list[ConnectionResponse]:
    if pg_store is None:
        return []
    return [_to_connection_response(record) for record in pg_store.list_connections()]


@router.patch("/connections/{connection_id}", response_model=ConnectionResponse)
def update_connection(
    connection_id: str,
    body: ConnectionUpdateRequest,
    pg_store: Annotated[PostgresMetadataStore | None, Depends(get_postgres_store)],
    resolver: Annotated[ConnectionResolver | None, Depends(get_connection_resolver)],
    sources: Annotated[SourceRegistry, Depends(get_source_registry)],
) -> ConnectionResponse:
    if pg_store is None or resolver is None:
        raise _connection_registry_unavailable()
    existing = pg_store.get_connection(connection_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"No such connection: {connection_id}")

    new_host = body.host if body.host is not None else existing.host
    new_port = body.port if body.port is not None else existing.port
    new_database = body.database if body.database is not None else existing.database
    new_encrypted_password = (
        resolver.encrypt(body.password.get_secret_value())
        if body.password is not None
        else existing.encrypted_password
    )
    updated = ConnectionRecord(
        id=existing.id,
        alias=body.alias if body.alias is not None else existing.alias,
        kind=existing.kind,
        host=new_host,
        port=new_port,
        username=body.username if body.username is not None else existing.username,
        encrypted_password=new_encrypted_password,
        database=new_database,
        identity=connection_identity(existing.kind, new_host, new_port, new_database),
        created_at=existing.created_at,
        updated_at=datetime.now(UTC).isoformat(),
    )
    pg_store.save_connection(updated)
    sources.refresh(connection_id)
    return _to_connection_response(updated)


@router.delete("/connections/{connection_id}", status_code=204)
def delete_connection(
    connection_id: str,
    pg_store: Annotated[PostgresMetadataStore | None, Depends(get_postgres_store)],
    sources: Annotated[SourceRegistry, Depends(get_source_registry)],
) -> None:
    if pg_store is None:
        raise _connection_registry_unavailable()
    deleted = pg_store.delete_connection(connection_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"No such connection: {connection_id}")
    sources.refresh(connection_id)


# --- catalog browsing (M16) -------------------------------------------------


def _require_connection(
    pg_store: PostgresMetadataStore | None, connection_id: str
) -> ConnectionRecord:
    if pg_store is None:
        raise _connection_registry_unavailable()
    record = pg_store.get_connection(connection_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No such connection: {connection_id}")
    return record


def _require_catalog_connector(
    sources: SourceRegistry, connection_id: str, database: str, kind: str
) -> CatalogSourceConnector:
    connector = sources.get_by_connection(connection_id, database)
    if not isinstance(connector, CatalogConnector):
        raise HTTPException(
            status_code=501, detail=f"{kind!r} connections do not support catalog browsing"
        )
    return cast("CatalogSourceConnector", connector)


@router.get("/connections/{connection_id}/databases", response_model=list[str])
def list_connection_databases(
    connection_id: str,
    pg_store: Annotated[PostgresMetadataStore | None, Depends(get_postgres_store)],
    sources: Annotated[SourceRegistry, Depends(get_source_registry)],
) -> list[str]:
    record = _require_connection(pg_store, connection_id)
    connector = _require_catalog_connector(sources, connection_id, record.database, record.kind)
    return list(connector.list_databases())


@router.get("/connections/{connection_id}/databases/{database}/tables", response_model=list[str])
def list_connection_tables(
    connection_id: str,
    database: str,
    pg_store: Annotated[PostgresMetadataStore | None, Depends(get_postgres_store)],
    sources: Annotated[SourceRegistry, Depends(get_source_registry)],
) -> list[str]:
    record = _require_connection(pg_store, connection_id)
    connector = _require_catalog_connector(sources, connection_id, database, record.kind)
    return list(connector.list_tables())


@router.get(
    "/connections/{connection_id}/databases/{database}/tables/{table}/columns",
    response_model=TableSpecResponse,
)
def get_connection_table_columns(
    connection_id: str,
    database: str,
    table: str,
    pg_store: Annotated[PostgresMetadataStore | None, Depends(get_postgres_store)],
    sources: Annotated[SourceRegistry, Depends(get_source_registry)],
) -> TableSpecResponse:
    record = _require_connection(pg_store, connection_id)
    connector = _require_catalog_connector(sources, connection_id, database, record.kind)
    try:
        spec = connector.table_spec(table)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return TableSpecResponse(
        name=spec.name,
        engine=spec.engine,
        approx_rows=spec.approx_rows,
        columns=[
            ColumnSpecResponse(
                name=c.name, type=c.type, nullable=c.nullable, is_primary_key=c.is_primary_key
            )
            for c in spec.columns
        ],
    )


@router.get(
    "/connections/{connection_id}/databases/{database}/tables/{table}/samples",
    response_model=dict[str, list[str]],
)
def sample_connection_table(
    connection_id: str,
    database: str,
    table: str,
    *,
    pg_store: Annotated[PostgresMetadataStore | None, Depends(get_postgres_store)],
    sources: Annotated[SourceRegistry, Depends(get_source_registry)],
    n: int = 5,
) -> dict[str, list[str]]:
    """One response for EVERY column's samples — a UI rendering the
    Explore step for a real table (e.g. `Company`'s 14 columns) needs
    exactly one request here, not one per column."""
    record = _require_connection(pg_store, connection_id)
    connector = _require_catalog_connector(sources, connection_id, database, record.kind)
    try:
        columns = connector.list_columns(table)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        column.name: [str(v) for v in connector.sample_values(table, column.name, limit=n)]
        for column in columns
    }


# --- column mappings (M16) --------------------------------------------------


def _to_mapping_response(mapping: ColumnMapping) -> ColumnMappingResponse:
    return ColumnMappingResponse(
        database=mapping.database,
        table_name=mapping.table_name,
        column_name=mapping.column_name,
        semantic_type=mapping.semantic_type,
        semantic_source=mapping.semantic_source,
        enabled=mapping.enabled,
        updated_at=mapping.updated_at,
        updated_by=mapping.updated_by,
    )


def _materialize_into_profile(
    store: InMemoryStore, profile_id: str, mapping: ColumnMapping
) -> None:
    """Decision from the M13-M22 program's M16 section: the mappings
    table is the UI-facing editable surface, but `run.profile_version`
    stays the one thing execution actually reads — this is the one
    function that turns a saved mapping into a real profile version,
    replacing any existing field_config for the same `field_ref` rather
    than appending a duplicate."""
    try:
        profile = store.get_profile(profile_id)
    except ProfileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"No such profile: {profile_id}") from exc
    new_config = materialize_field_config(mapping)
    kept = tuple(c for c in profile.field_configs if c.field_ref != new_config.field_ref)
    store.create_version(
        profile_id,
        description=None,
        locale_policy=None,
        default_operations=None,
        field_configs=(*kept, new_config),
        created_by=mapping.updated_by,
    )


@router.put(
    "/connections/{connection_id}/databases/{database}/tables/{table}/columns/{column}/mapping",
    response_model=ColumnMappingResponse,
)
def upsert_column_mapping(
    connection_id: str,
    database: str,
    table: str,
    column: str,
    body: ColumnMappingUpsertRequest,
    *,
    store: Annotated[InMemoryStore, Depends(get_store)],
    pg_store: Annotated[PostgresMetadataStore | None, Depends(get_postgres_store)],
) -> ColumnMappingResponse:
    record = _require_connection(pg_store, connection_id)
    assert pg_store is not None  # narrowed by _require_connection raising otherwise
    mapping = ColumnMapping(
        connection_identity=record.identity,
        database=database,
        table_name=table,
        column_name=column,
        semantic_type=body.semantic_type,
        semantic_source=SemanticSource.USER,
        enabled=body.enabled,
        updated_at=datetime.now(UTC).isoformat(),
        updated_by=body.updated_by,
    )
    pg_store.save_mapping(mapping)
    if body.profile_id is not None:
        _materialize_into_profile(store, body.profile_id, mapping)
    return _to_mapping_response(mapping)


@router.get(
    "/connections/{connection_id}/databases/{database}/tables/{table}/mappings",
    response_model=list[ColumnMappingResponse],
)
def list_column_mappings(
    connection_id: str,
    database: str,
    table: str,
    pg_store: Annotated[PostgresMetadataStore | None, Depends(get_postgres_store)],
) -> list[ColumnMappingResponse]:
    record = _require_connection(pg_store, connection_id)
    assert pg_store is not None
    mappings = pg_store.list_mappings_for_table(record.identity, database, table)
    return [_to_mapping_response(m) for m in mappings]


# --- preview / field-test ---------------------------------------------------


@router.post("/preview", response_model=list[NormalizedValue])
def preview(
    body: PreviewRequest,
    dispatcher: Annotated[Dispatcher, Depends(get_dispatcher)],
) -> list[NormalizedValue]:
    ctx = NormalizationContext(
        field_name=body.field_name,
        semantic_type=body.semantic_type,
        error_policy=body.error_policy,
    )
    return [
        dispatcher.normalize(value, body.semantic_type, ctx, SCAFFOLD_PROFILE)
        for value in body.values
    ]


@router.post("/field-test", response_model=NormalizedValue)
def field_test(
    body: FieldTestRequest,
    dispatcher: Annotated[Dispatcher, Depends(get_dispatcher)],
) -> NormalizedValue:
    ctx = NormalizationContext(
        field_name=body.field_name,
        semantic_type=body.semantic_type,
        error_policy=body.error_policy,
    )
    return dispatcher.normalize(body.value, body.semantic_type, ctx, SCAFFOLD_PROFILE)


# --- runs -------------------------------------------------------------------


@router.get("/runs", response_model=list[NormalizationRun])
def list_runs(store: Annotated[InMemoryStore, Depends(get_store)]) -> list[NormalizationRun]:
    return store.list_runs()


def _resolve_values_thunk(
    execution: RunExecutionRequest, sources: SourceRegistry
) -> Callable[[], Sequence[str | None]]:
    """Builds the callable `start_run_execution` invokes from inside the
    background thread. For a file-config `source` (`database` unset),
    the cheap in-memory registry lookup (does source_id exist at all)
    happens here, synchronously, for an immediate 404 on a typo'd id —
    the real connector read is deferred into the returned closure so it
    runs off the request/response path.

    For a connection-based `source` (M15/M16, `database` given), that
    synchronous pre-check is deliberately SKIPPED: unlike a file-config
    source (whose connector already exists, built eagerly at startup —
    checking it is a free dict lookup), a connection-based source builds
    its connector lazily on first use, which means actually connecting to
    the real database. Doing that on the request path would reintroduce
    exactly the blocking-request problem M11's async execution exists to
    avoid. A bad/deleted connection id therefore surfaces the same way a
    bad table/column already does: a polled FAILED status with
    `failure_reason`, not a synchronous 404."""
    if execution.values is not None:
        pasted_values = execution.values

        def resolve_pasted() -> Sequence[str | None]:
            return pasted_values

        return resolve_pasted

    # RunExecutionRequest's own validator guarantees this is set.
    assert execution.source is not None
    source = execution.source
    if source.database is None:
        try:
            sources.get(source.source_id)
        except UnknownSourceError as exc:
            raise HTTPException(
                status_code=404, detail=f"No such source: {source.source_id}"
            ) from exc

    def resolve_from_source() -> Sequence[str | None]:
        return sources.read_column_values(
            source.source_id,
            source.table,
            source.column,
            row_limit=source.row_limit,
            database=source.database,
        )

    return resolve_from_source


def _resolve_field_ref(
    execution: RunExecutionRequest, pg_store: PostgresMetadataStore | None
) -> str | None:
    """M16: builds the real `field_ref` a profile's `field_configs` (and
    a materialized column mapping) are keyed by —
    `{connection_identity}.{database}.{table}.{column}` — for a
    connection-based source. Returns `None` for pasted-values mode or a
    file-config source, where `execute_run` falls back to the bare
    `field_name` unchanged (no structured identity exists for either).
    A connection id that no longer resolves is not an error here — the
    run simply proceeds with no field_ref (falls back to field_name,
    same as before M16), and the real "does this connection exist" check
    still happens where it always has: inside the background execution
    thread when it actually tries to read from the source."""
    if execution.source is None or execution.source.database is None or pg_store is None:
        return None
    source = execution.source
    record = pg_store.get_connection(source.source_id)
    if record is None:
        return None
    return f"{record.identity}.{source.database}.{source.table}.{source.column}"


@router.post("/runs", response_model=NormalizationRun, status_code=201)
def create_run(
    profile_id: str,
    source_snapshot: str,
    *,
    store: Annotated[InMemoryStore, Depends(get_store)],
    dispatcher: Annotated[Dispatcher, Depends(get_dispatcher)],
    sources: Annotated[SourceRegistry, Depends(get_source_registry)],
    pg_store: Annotated[PostgresMetadataStore | None, Depends(get_postgres_store)],
    executor: Annotated[RunExecutor, Depends(get_run_executor)],
    execution: Annotated[RunExecutionRequest | None, Body()] = None,
) -> NormalizationRun:
    """`execution` is optional (M6): when supplied, the run's field
    execution actually starts against the live Dispatcher; when omitted,
    behavior is unchanged from M1 — a PENDING run with no field
    execution. `execution.values` (pasted, M6) and `execution.source`
    (read from a real connected source, M10) are the two ways to supply
    those values — `RunExecutionRequest` itself enforces exactly one is
    present.

    M11: execution is asynchronous. This call returns immediately — the
    run is still PENDING at that instant and transitions to RUNNING
    shortly after in the background, then COMPLETED/FAILED; poll
    `GET /runs/{id}` for the terminal status. For `source`-mode, only the cheap
    "does this source_id exist" check happens synchronously here (an
    immediate 404 for a typo'd source_id); the actual table/column read
    happens in the background, so a bad table/column now surfaces as a
    polled FAILED status with `failure_reason`, not a synchronous 400.

    `execution.semantic_type` is now optional (M16) — see
    `InMemoryStore.execute_run`'s docstring for the resolution order
    against a matching profile field config."""
    try:
        run = store.create_run(
            profile_id=profile_id, env_id=dispatcher.env_id, source_snapshot=source_snapshot
        )
    except ProfileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"No such profile: {profile_id}") from exc

    if execution is not None:
        resolve_values = _resolve_values_thunk(execution, sources)
        run = store.start_run_execution(
            run.id,
            dispatcher=dispatcher,
            field_name=execution.field_name,
            semantic_type=execution.semantic_type,
            resolve_values=resolve_values,
            error_policy=execution.error_policy,
            field_ref=_resolve_field_ref(execution, pg_store),
            executor=executor,
        )
    return run


@router.post("/runs/{run_id}/columns", response_model=NormalizationRun, status_code=202)
def start_multi_column_run(
    run_id: str,
    body: MultiColumnRunRequest,
    *,
    store: Annotated[InMemoryStore, Depends(get_store)],
    dispatcher: Annotated[Dispatcher, Depends(get_dispatcher)],
    resolver: Annotated[ConnectionResolver | None, Depends(get_connection_resolver)],
    pg_store: Annotated[PostgresMetadataStore | None, Depends(get_postgres_store)],
    executor: Annotated[RunExecutor, Depends(get_run_executor)],
) -> NormalizationRun:
    """M17 — starts a real multi-column, chunked, resumable run against
    an existing PENDING run (created via `POST /runs` with no
    `execution` body) and a connection-based source. Returns 202: unlike
    `POST /runs`'s single-column path, this ALWAYS executes
    asynchronously — there is no synchronous pasted-values equivalent for
    multi-column execution.

    M18 fix: builds a connector DEDICATED to this run (via `resolver` +
    `build_connector_from_parts`, the same "never pooled" pattern
    `_probe_connection` already uses) rather than `SourceRegistry.
    get_by_connection`'s process-wide cached single instance. A real bug,
    found via live verification: `clickhouse_connect`'s client is not
    thread-safe for concurrent queries, and the cached instance is
    process-wide — two multi-column runs started against the SAME
    connection execute concurrently on `RunExecutor`'s worker pool, so
    both were sharing one non-thread-safe client and failing with
    "Please use a separate client instance per thread/process." A
    catalog-browsing request (M16) is a single short-lived call, so
    sharing was safe there; a chunked streaming run holds its connector
    for the run's entire, potentially long, duration — safe only with a
    connector no other request can ever be concurrently using."""
    record = _require_connection(pg_store, body.connection_id)
    if resolver is None:
        raise _connection_registry_unavailable()
    resolved = resolver.resolve(body.connection_id)
    connector = build_connector_from_parts(
        body.connection_id,
        kind=resolved.kind,
        host=resolved.host,
        port=resolved.port,
        username=resolved.username,
        password=resolved.password,
        database=body.database,
    )
    if not isinstance(connector, CatalogConnector) or not isinstance(
        connector, StreamingSourceConnector
    ):
        connector.close()
        raise HTTPException(
            status_code=501,
            detail=f"{record.kind!r} connections do not support multi-column streaming runs",
        )
    try:
        return store.start_multi_column_execution(
            run_id,
            dispatcher=dispatcher,
            connector=connector,
            connection_identity=record.identity,
            database=body.database,
            columns=body.columns,
            sidecar_source_id=body.connection_id,
            executor=executor,
            pg_store=pg_store,
            chunk_size=body.chunk_size,
        )
    except RunNotFoundError as exc:
        connector.close()
        raise HTTPException(status_code=404, detail=f"No such run: {run_id}") from exc
    except RunNotExecutableError as exc:
        connector.close()
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/runs/compare")
def compare_run_pair(
    run_id_a: str,
    run_id_b: str,
    store: Annotated[InMemoryStore, Depends(get_store)],
    table: str | None = None,
    column: str | None = None,
) -> dict[str, object]:
    """§96 A/B normalization — compares two runs executed over the same
    aligned input values (typically the same field under two different
    profile versions). Registered before `/runs/{run_id}` — Starlette
    matches path routes in registration order, so "compare" would
    otherwise be captured as a `run_id` path parameter by the more
    generic route below (a real bug caught by hitting the live server,
    not by reasoning about route declarations).

    `table`/`column` (M18): selects which column to compare for a
    multi-column run — the same selector on both sides, since comparison
    only makes sense between aligned batches of the same field."""
    try:
        run_a = store.get_run(run_id_a)
        run_b = store.get_run(run_id_b)
        execution_a = store.get_column_execution(run_id_a, table, column)
        execution_b = store.get_column_execution(run_id_b, table, column)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"No such run: {exc}") from exc

    if execution_a is None or execution_b is None:
        raise HTTPException(
            status_code=409, detail="Both runs must have been executed with field values"
        )
    if execution_a.field_name != execution_b.field_name:
        raise HTTPException(status_code=409, detail="Runs must be for the same field to compare")
    if len(execution_a.results) != len(execution_b.results):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Runs must have the same number of executed values to compare "
                f"(A has {len(execution_a.results)}, B has {len(execution_b.results)})"
            ),
        )

    report = compare_runs(
        execution_a.field_name,
        profile_version_a=run_a.profile_version,
        results_a=execution_a.results,
        profile_version_b=run_b.profile_version,
        results_b=execution_b.results,
    )
    return report.model_dump(mode="json")


@router.get("/runs/{run_id}", response_model=NormalizationRun)
def get_run(run_id: str, store: Annotated[InMemoryStore, Depends(get_store)]) -> NormalizationRun:
    try:
        return store.get_run(run_id)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"No such run: {run_id}") from exc


@router.get("/runs/{run_id}/errors", response_model=list[NormalizationError])
def get_run_errors(
    run_id: str,
    store: Annotated[InMemoryStore, Depends(get_store)],
    table: str | None = None,
    column: str | None = None,
) -> list[NormalizationError]:
    """`table`/`column` (M18): selects one column of a multi-column run;
    omitted, falls back to the original single-column lookup unchanged."""
    try:
        execution = store.get_column_execution(run_id, table, column)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"No such run: {run_id}") from exc
    if execution is None:
        return []

    errors: list[NormalizationError] = []
    pairs = zip(execution.originals, execution.results, strict=True)
    for index, (original, result) in enumerate(pairs):
        if not result.errors:
            continue
        preview = safe_preview(original) if original is not None else "null"
        for message in result.errors:
            errors.append(
                NormalizationError(
                    field=execution.field_name,
                    record_ref=str(index),
                    operation="normalize",
                    error=message,
                    severity="error",
                    safe_preview=preview,
                    rule_id=None,
                    library_version=None,
                )
            )
    return errors


@router.get("/runs/{run_id}/values")
def get_run_values(
    run_id: str,
    store: Annotated[InMemoryStore, Depends(get_store)],
    *,
    table: str | None = None,
    column: str | None = None,
    offset: int = 0,
    limit: int = 1000,
) -> list[dict[str, object]]:
    """The run's real aligned (original, normalized result) pairs — backs
    §121's per-value Normalization Comparison Workspace table (Value/v1/
    v2/Difference/Reason), which needs row-level data the aggregate
    /runs/compare endpoint deliberately doesn't return.

    M18: real pagination (`offset`/`limit`, default page size 1000,
    capped at 10000) pushed down to DuckDB for a sidecar-backed
    selection — never materializes a full multi-million-row column into
    Python just to return one page of it. `table`/`column` select one
    column of a multi-column run; omitted, the original single-column
    (already-bounded) behavior is unchanged."""
    limit = max(1, min(limit, 10_000))
    offset = max(0, offset)
    try:
        page = store.get_column_values_page(run_id, table, column, offset=offset, limit=limit)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"No such run: {run_id}") from exc
    return page if page is not None else []


@router.get("/runs/{run_id}/collisions")
def get_run_collisions(
    run_id: str,
    store: Annotated[InMemoryStore, Depends(get_store)],
    table: str | None = None,
    column: str | None = None,
) -> list[dict[str, object]]:
    """§92 Collision Dashboard: each group's current real decision (if
    any human has recorded one — accept/reject/whitelist) is attached
    under `decision`, `null` when no one has reviewed it yet.
    `table`/`column` (M18): selects one column of a multi-column run."""
    try:
        execution = store.get_column_execution(run_id, table, column)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"No such run: {run_id}") from exc
    if execution is None:
        return []
    groups = find_collisions(execution.originals, execution.results)
    decisions = {d.normalized_value: d for d in store.list_collision_decisions(run_id)}
    return [
        {
            **group.model_dump(mode="json"),
            "decision": (
                decisions[group.normalized_value].model_dump(mode="json")
                if group.normalized_value in decisions
                else None
            ),
        }
        for group in groups
    ]


@router.post(
    "/runs/{run_id}/collisions/decision", response_model=CollisionDecision, status_code=201
)
def record_collision_decision(
    run_id: str,
    body: CollisionDecisionRequest,
    store: Annotated[InMemoryStore, Depends(get_store)],
) -> CollisionDecision:
    """§92: Accept rule / Reject rule / Whitelist collision — the real
    backend behind the Collision Dashboard's action buttons. `body.table`/
    `.column` (M18) select one column of a multi-column run."""
    try:
        return store.record_collision_decision(
            run_id,
            body.normalized_value,
            decision=body.decision,
            decided_by=body.decided_by,
            note=body.note,
            table=body.table,
            column=body.column,
        )
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"No such run: {run_id}") from exc
    except UnknownCollisionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/runs/{run_id}/profile")
def get_run_profile(
    run_id: str,
    store: Annotated[InMemoryStore, Depends(get_store)],
    table: str | None = None,
    column: str | None = None,
) -> dict[str, object]:
    """§77 normalization profiling — rows/changed/unchanged/warnings/
    errors/potentially-lossy counts plus top transformation patterns,
    computed from the run's actual executed field batch. `table`/
    `column` (M18): selects one column of a multi-column run."""
    try:
        execution = store.get_column_execution(run_id, table, column)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"No such run: {run_id}") from exc
    if execution is None:
        raise HTTPException(
            status_code=409, detail=f"Run {run_id} has not been executed with field values"
        )
    profile = profile_field(execution.field_name, execution.results)
    return profile.model_dump(mode="json")


@router.get("/runs/{run_id}/handoff", response_model=HandoffArtifact)
def get_run_handoff(
    run_id: str,
    store: Annotated[InMemoryStore, Depends(get_store)],
    table: str | None = None,
    column: str | None = None,
) -> HandoffArtifact:
    """§134 — the artifact this project hands off to the downstream Data
    Discovery & Entity Context Engine: normalized schema metadata,
    semantic type, normalized comparison values, parsed components,
    country/language metadata, validation flags, collision diagnostics,
    and the stable versioned normalization profile that produced them.
    `table`/`column` (M18): selects one column of a multi-column run."""
    try:
        run = store.get_run(run_id)
        execution = store.get_column_execution(run_id, table, column)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"No such run: {run_id}") from exc
    if execution is None:
        raise HTTPException(
            status_code=409, detail=f"Run {run_id} has not been executed with field values"
        )
    profile = store.get_profile(run.profile_id, run.profile_version)
    return build_handoff_artifact(
        field_name=execution.field_name,
        semantic_type=execution.semantic_type,
        profile=profile,
        env_id=run.env_id,
        originals=execution.originals,
        results=execution.results,
    )


# --- dictionaries -------------------------------------------------------


@router.get("/dictionaries", response_model=list[DictionarySummary])
def list_dictionaries(
    loader: Annotated[DictionaryLoader, Depends(get_dictionary_loader)],
    custom_store: Annotated[CustomDictionaryStore, Depends(get_custom_dictionary_store)],
) -> list[DictionarySummary]:
    summaries = []
    for dict_id in loader.list_dictionary_ids():
        for version in loader.list_versions(dict_id):
            dictionary = loader.load(dict_id, version)
            summaries.append(
                DictionarySummary(
                    id=dictionary.id,
                    version=dictionary.version,
                    locale=dictionary.locale,
                    source=dictionary.source,
                    license=dictionary.license,
                    entry_count=len(dictionary.entries),
                    is_custom=False,
                    active_version=None,
                )
            )
    for dict_id in custom_store.list_custom_ids():
        if custom_store.is_deleted(dict_id):
            continue
        active_version = custom_store.get_active_version(dict_id)
        for version in custom_store.list_versions(dict_id):
            dictionary = custom_store.load(dict_id, version)
            summaries.append(
                DictionarySummary(
                    id=dictionary.id,
                    version=dictionary.version,
                    locale=dictionary.locale,
                    source=dictionary.source,
                    license=dictionary.license,
                    entry_count=len(dictionary.entries),
                    is_custom=True,
                    active_version=active_version,
                )
            )
    return summaries


@router.post("/dictionaries", response_model=DictionarySummary, status_code=201)
def create_dictionary(
    body: DictionaryCreateRequest,
    custom_store: Annotated[CustomDictionaryStore, Depends(get_custom_dictionary_store)],
) -> DictionarySummary:
    try:
        dictionary = custom_store.create(
            body.id,
            entries=body.entries,
            locale=body.locale,
            source=body.source,
            license_=body.license,
            created_by=body.created_by,
        )
    except BuiltinIdCollisionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CustomDictionaryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return DictionarySummary(
        id=dictionary.id,
        version=dictionary.version,
        locale=dictionary.locale,
        source=dictionary.source,
        license=dictionary.license,
        entry_count=len(dictionary.entries),
        is_custom=True,
        active_version=dictionary.version,
    )


@router.get("/dictionaries/{dictionary_id}")
def get_dictionary(
    dictionary_id: str,
    loader: Annotated[DictionaryLoader, Depends(get_dictionary_loader)],
    custom_store: Annotated[CustomDictionaryStore, Depends(get_custom_dictionary_store)],
    version: str | None = None,
) -> dict[str, object]:
    """Full dictionary content (including entries) — the list endpoint
    only carries entry_count; §115's import/export and entry editing
    need the real entries payload."""
    if dictionary_id in loader.list_dictionary_ids():
        try:
            dictionary = loader.load(dictionary_id, version)
        except DictionaryNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {**dictionary.model_dump(mode="json"), "is_custom": False}

    try:
        dictionary = custom_store.load(dictionary_id, version)
    except CustomDictionaryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {**dictionary.model_dump(mode="json"), "is_custom": True}


@router.post(
    "/dictionaries/{dictionary_id}/versions", response_model=DictionarySummary, status_code=201
)
def create_dictionary_version(
    dictionary_id: str,
    body: DictionaryVersionRequest,
    custom_store: Annotated[CustomDictionaryStore, Depends(get_custom_dictionary_store)],
) -> DictionarySummary:
    try:
        dictionary = custom_store.add_version(
            dictionary_id,
            entries=body.entries,
            locale=body.locale,
            source=body.source,
            license_=body.license,
            created_by=body.created_by,
            merge=body.merge,
        )
    except CustomDictionaryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (BuiltinIdCollisionError, CustomDictionaryDeletedError, CustomDictionaryError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return DictionarySummary(
        id=dictionary.id,
        version=dictionary.version,
        locale=dictionary.locale,
        source=dictionary.source,
        license=dictionary.license,
        entry_count=len(dictionary.entries),
        is_custom=True,
        active_version=dictionary.version,
    )


@router.post("/dictionaries/{dictionary_id}/rollback", response_model=DictionarySummary)
def rollback_dictionary(
    dictionary_id: str,
    body: DictionaryRollbackRequest,
    custom_store: Annotated[CustomDictionaryStore, Depends(get_custom_dictionary_store)],
) -> DictionarySummary:
    try:
        dictionary = custom_store.rollback(dictionary_id, body.target_version, by=body.by)
    except CustomDictionaryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CustomDictionaryDeletedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    active_version = custom_store.get_active_version(dictionary_id)
    return DictionarySummary(
        id=dictionary.id,
        version=dictionary.version,
        locale=dictionary.locale,
        source=dictionary.source,
        license=dictionary.license,
        entry_count=len(dictionary.entries),
        is_custom=True,
        active_version=active_version,
    )


@router.delete("/dictionaries/{dictionary_id}", status_code=204)
def delete_dictionary(
    dictionary_id: str,
    by: str,
    custom_store: Annotated[CustomDictionaryStore, Depends(get_custom_dictionary_store)],
) -> None:
    try:
        custom_store.delete(dictionary_id, by=by)
    except CustomDictionaryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# --- impact ---------------------------------------------------------------


@router.get("/impact")
def get_impact(
    run_id: str,
    store: Annotated[InMemoryStore, Depends(get_store)],
    table: str | None = None,
    column: str | None = None,
) -> dict[str, object]:
    """§78/§97 impact analysis for a run's executed field batch.
    `table`/`column` (M18): selects one column of a multi-column run."""
    try:
        execution = store.get_column_execution(run_id, table, column)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"No such run: {run_id}") from exc
    if execution is None:
        raise HTTPException(
            status_code=409, detail=f"Run {run_id} has not been executed with field values"
        )
    report = compute_impact(execution.field_name, execution.originals, execution.results)
    return report.model_dump(mode="json")


# --- overview / quality (M7, §90, §93) --------------------------------------


@router.get("/overview")
def get_overview(store: Annotated[InMemoryStore, Depends(get_store)]) -> dict[str, object]:
    """§90 normalization overview dashboard — aggregated from every known
    profile's field_configs and every executed column's real, bounded
    rollup stats (M18: NEVER a loop over `get_execution`/full per-value
    results — see `normanalysis.column_stats`'s module docstring for why
    that was a real, plan-flagged OOM risk once M17 made multi-million-
    row multi-column runs a live possibility)."""
    profile_field_refs = [
        config.field_ref for profile in store.list_profiles() for config in profile.field_configs
    ]
    report = compute_overview_from_stats(profile_field_refs, store.list_all_column_stats())
    return report.model_dump(mode="json")


@router.get("/quality")
def get_quality(store: Annotated[InMemoryStore, Depends(get_store)]) -> dict[str, object]:
    """§93 quality dashboard — per-semantic-type validation issue tallies
    across every executed column's real, bounded rollup stats (M18: same
    rearchitecture as `/overview`, same reason)."""
    report = compute_quality_from_stats(store.list_all_column_stats())
    return report.model_dump(mode="json")

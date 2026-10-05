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

Every route is registered and returns a schema-valid response (M1's Gate
G1 requirement). As of M6: profile/run CRUD+rollback, field-test/preview,
dictionary write/versioning/rollback, and impact/collision/A-B analysis
are all wired to real logic — no remaining 501 stubs on the §98 surface.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Response
from normcore.pii import safe_preview
from normexec.cache import NormalizationCache

from normanalysis import (
    HandoffArtifact,
    build_handoff_artifact,
    compare_runs,
    compute_impact,
    compute_overview,
    compute_quality_report,
    find_collisions,
    profile_field,
    suggest_profile,
    suggest_semantic_type,
)
from normapi import adjudication, clone_executor, secrets
from normapi.clone_executor import CloneJobNotFoundError, CloneJobStateError
from normapi.dependencies import (
    get_cache,
    get_connections,
    get_custom_dictionary_store,
    get_dictionary_loader,
    get_dispatcher,
    get_store,
)
from normapi.pg_persistence import PgPersistence
from normapi.scaffold_profile import SCAFFOLD_PROFILE
from normapi.schemas import (
    AdjudicationQueueEntry,
    AdjudicationVerdict,
    AdjudicationVerdictRequest,
    CloneJobAmendRequest,
    CloneJobCreateRequest,
    CloneJobCreateResponse,
    ColumnInfoResponse,
    Connection,
    ConnectionCreateRequest,
    DatabaseDiscoveryRequest,
    DetectTypeRequest,
    DictionaryCreateRequest,
    DictionaryRollbackRequest,
    DictionarySummary,
    DictionaryVersionRequest,
    FieldSummary,
    FieldTestRequest,
    PreviewRequest,
    ProfileCreateRequest,
    ProfileRollbackRequest,
    ProfileSuggestionResponse,
    ProfileVersionRequest,
    RunExecutionRequest,
    TypeSuggestionResponse,
)
from normapi.store import (
    InMemoryStore,
    ProfileNotFoundError,
    RunNotFoundError,
    RunTooLargeError,
)
from normcore import (
    CloneJobStatus,
    Dispatcher,
    FieldSemanticType,
    NormalizationContext,
    NormalizationError,
    NormalizationProfile,
    NormalizationRun,
    NormalizedValue,
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

router = APIRouter(prefix="/normalization")


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


@router.post("/runs", response_model=NormalizationRun, status_code=201)
def create_run(
    profile_id: str,
    source_snapshot: str,
    store: Annotated[InMemoryStore, Depends(get_store)],
    dispatcher: Annotated[Dispatcher, Depends(get_dispatcher)],
    execution: Annotated[RunExecutionRequest | None, Body()] = None,
) -> NormalizationRun:
    """`execution` is optional (M6): when supplied, the run actually
    normalizes `execution.values` through the live Dispatcher and the
    run reaches COMPLETED with real metrics/errors/collisions/impact
    data attached; when omitted, behavior is unchanged from M1 — a
    PENDING run with no field execution."""
    try:
        run = store.create_run(
            profile_id=profile_id, env_id=dispatcher.env_id, source_snapshot=source_snapshot
        )
    except ProfileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"No such profile: {profile_id}") from exc

    if execution is not None:
        try:
            run = store.execute_run(
                run.id,
                dispatcher=dispatcher,
                field_name=execution.field_name,
                semantic_type=execution.semantic_type,
                values=execution.values,
                error_policy=execution.error_policy,
            )
        except RunTooLargeError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
    return run


@router.get("/runs/compare")
def compare_run_pair(
    run_id_a: str,
    run_id_b: str,
    store: Annotated[InMemoryStore, Depends(get_store)],
) -> dict[str, object]:
    """§96 A/B normalization — compares two runs executed over the same
    aligned input values (typically the same field under two different
    profile versions). Registered before `/runs/{run_id}` — Starlette
    matches path routes in registration order, so "compare" would
    otherwise be captured as a `run_id` path parameter by the more
    generic route below (a real bug caught by hitting the live server,
    not by reasoning about route declarations)."""
    try:
        run_a = store.get_run(run_id_a)
        run_b = store.get_run(run_id_b)
        execution_a = store.get_execution(run_id_a)
        execution_b = store.get_execution(run_id_b)
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
    run_id: str, store: Annotated[InMemoryStore, Depends(get_store)]
) -> list[NormalizationError]:
    try:
        execution = store.get_execution(run_id)
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


_MAX_VALUES_PAGE_SIZE = 1000


@router.get("/runs/{run_id}/values")
def get_run_values(
    run_id: str,
    store: Annotated[InMemoryStore, Depends(get_store)],
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, object]]:
    """The run's real aligned (original, normalized result) pairs — backs
    §121's per-value Normalization Comparison Workspace table (Value/v1/
    v2/Difference/Reason), which needs row-level data the aggregate
    /runs/compare endpoint deliberately doesn't return.

    Paginated (default page 100, hard cap 1000) — a 5,000-row run alone
    measured at ~24MB for one unpaginated response before this fix, and
    that scales linearly with run size with no ceiling. Goes straight to
    the store's paginated accessor, which queries Postgres directly when
    configured rather than reconstructing the whole run first."""
    limit = max(1, min(limit, _MAX_VALUES_PAGE_SIZE))
    offset = max(0, offset)
    try:
        # get_run first: a 404 for a nonexistent run should say so, not
        # silently return an empty page indistinguishable from "no more
        # rows" on a valid run.
        store.get_run(run_id)
        page = store.get_run_values_page(run_id, limit=limit, offset=offset)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"No such run: {run_id}") from exc
    return [
        {"original": original, "result": result.model_dump(mode="json")}
        for original, result in page
    ]


@router.get("/runs/{run_id}/collisions")
def get_run_collisions(
    run_id: str, store: Annotated[InMemoryStore, Depends(get_store)]
) -> list[dict[str, object]]:
    try:
        execution = store.get_execution(run_id)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"No such run: {run_id}") from exc
    if execution is None:
        return []
    groups = find_collisions(execution.originals, execution.results)
    return [group.model_dump(mode="json") for group in groups]


@router.get("/runs/{run_id}/profile")
def get_run_profile(
    run_id: str, store: Annotated[InMemoryStore, Depends(get_store)]
) -> dict[str, object]:
    """§77 normalization profiling — rows/changed/unchanged/warnings/
    errors/potentially-lossy counts plus top transformation patterns,
    computed from the run's actual executed field batch."""
    try:
        execution = store.get_execution(run_id)
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
    run_id: str, store: Annotated[InMemoryStore, Depends(get_store)]
) -> HandoffArtifact:
    """§134 — the artifact this project hands off to the downstream Data
    Discovery & Entity Context Engine: normalized schema metadata,
    semantic type, normalized comparison values, parsed components,
    country/language metadata, validation flags, collision diagnostics,
    and the stable versioned normalization profile that produced them."""
    try:
        run = store.get_run(run_id)
        execution = store.get_execution(run_id)
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
) -> dict[str, object]:
    """§78/§97 impact analysis for a run's executed field batch."""
    try:
        execution = store.get_execution(run_id)
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
    profile's field_configs and every executed run's real metrics."""
    profile_field_refs = [
        config.field_ref for profile in store.list_profiles() for config in profile.field_configs
    ]
    executed_runs = []
    for run in store.list_runs():
        execution = store.get_execution(run.id)
        if execution is not None:
            executed_runs.append((run, execution.field_name, execution.results))
    report = compute_overview(profile_field_refs, executed_runs)
    return report.model_dump(mode="json")


@router.get("/quality")
def get_quality(store: Annotated[InMemoryStore, Depends(get_store)]) -> dict[str, object]:
    """§93 quality dashboard — per-semantic-type validation issue tallies
    across every executed run currently known to the store."""
    run_batches = []
    for run in store.list_runs():
        execution = store.get_execution(run.id)
        if execution is not None:
            run_batches.append((execution.semantic_type, execution.results))
    report = compute_quality_report(run_batches)
    return report.model_dump(mode="json")


# --- DB-clone-and-normalize: saved connections ------------------------------
# Server-level credentials (decisions #2, #13); the password is encrypted
# at rest (decision #12) and never returned in a response.


@router.post("/connections", response_model=Connection, status_code=201)
def create_connection(
    body: ConnectionCreateRequest,
    connections: Annotated[PgPersistence, Depends(get_connections)],
) -> Connection:
    connection_id = str(uuid.uuid4())
    row = connections.save_connection(
        connection_id,
        engine=body.engine,
        host=body.host,
        port=body.port,
        username=body.username,
        password=body.password,
    )
    return Connection(**{k: v for k, v in row.items() if k != "encrypted_password"})


@router.get("/connections", response_model=list[Connection])
def list_connections(
    connections: Annotated[PgPersistence, Depends(get_connections)],
) -> list[Connection]:
    return [
        Connection(**{k: v for k, v in row.items() if k != "encrypted_password"})
        for row in connections.list_connections()
    ]


@router.delete("/connections/{connection_id}", status_code=204)
def delete_connection(
    connection_id: str,
    connections: Annotated[PgPersistence, Depends(get_connections)],
) -> None:
    connections.delete_connection(connection_id)


def _resolve_connection(
    connection_id: str,
    body: DatabaseDiscoveryRequest | None,
    connections: PgPersistence,
) -> dict[str, Any]:
    """Unifies the "saved connection" and "not-yet-saved, ad-hoc inline
    credentials" cases (§4) behind one shape — both end up as a dict with
    an `encrypted_password` field, so every downstream connector-builder
    (`clone_executor.build_source_connector`) only has one code path to
    handle regardless of which case produced it."""
    if connection_id == "adhoc":
        if body is None or not (
            body.engine and body.host and body.port and body.username and body.password
        ):
            raise HTTPException(
                status_code=422,
                detail="adhoc discovery requires engine, host, port, username, and password",
            )
        return {
            "connection_id": "adhoc",
            "engine": body.engine,
            "host": body.host,
            "port": body.port,
            "username": body.username,
            "encrypted_password": secrets.encrypt(body.password),
        }
    conn = connections.get_connection(connection_id)
    if conn is None:
        raise HTTPException(status_code=404, detail=f"No such connection: {connection_id}")
    return conn


# --- DB-clone-and-normalize: discovery ---------------------------------------
# Decision #1: the app queries the server itself for its list of
# databases/tables/columns — never a network port scan.


@router.post("/connections/{connection_id}/databases", response_model=list[str])
def discover_databases(
    connection_id: str,
    connections: Annotated[PgPersistence, Depends(get_connections)],
    body: Annotated[DatabaseDiscoveryRequest | None, Body()] = None,
) -> list[str]:
    conn = _resolve_connection(connection_id, body, connections)
    source = clone_executor.build_source_connector(
        conn, clone_executor.bootstrap_database(conn["engine"])
    )
    try:
        return list(source.list_databases())
    finally:
        source.close()


@router.get("/connections/{connection_id}/databases/{database}/schemas", response_model=list[str])
def discover_schemas(
    connection_id: str,
    database: str,
    connections: Annotated[PgPersistence, Depends(get_connections)],
) -> list[str]:
    """Namespaces inside a Postgres database that actually hold tables.

    Empty for ClickHouse, which has no layer between database and table.
    Worth its own call because table discovery is relative to ONE of these:
    a source keeping its tables in a named schema answers `[]` to every
    table query made against the default one."""
    conn = _resolve_connection(connection_id, None, connections)
    source = clone_executor.build_source_connector(conn, database)
    try:
        lister = getattr(source, "list_schemas", None)
        return list(lister()) if lister else []
    finally:
        source.close()


@router.get("/connections/{connection_id}/databases/{database}/tables", response_model=list[str])
def discover_tables(
    connection_id: str,
    database: str,
    connections: Annotated[PgPersistence, Depends(get_connections)],
    schema: str | None = None,
) -> list[str]:
    conn = _resolve_connection(connection_id, None, connections)
    source = clone_executor.build_source_connector(conn, database, schema)
    try:
        return list(source.list_tables())
    finally:
        source.close()


_MAX_COLUMNS_PAGE_SIZE = 1000


@router.get(
    "/connections/{connection_id}/databases/{database}/tables/{table}/columns",
    response_model=list[ColumnInfoResponse],
)
def discover_columns(
    connection_id: str,
    database: str,
    table: str,
    connections: Annotated[PgPersistence, Depends(get_connections)],
    limit: int = 100,
    offset: int = 0,
    schema: str | None = None,
) -> list[ColumnInfoResponse]:
    """Paginated — same query-param names and capped page size as
    `GET /runs/{run_id}/values`.

    `schema` must match whatever the table was discovered under: a column
    lookup in the wrong namespace finds no such table."""
    limit = max(1, min(limit, _MAX_COLUMNS_PAGE_SIZE))
    offset = max(0, offset)
    conn = _resolve_connection(connection_id, None, connections)
    source = clone_executor.build_source_connector(conn, database, schema)
    try:
        columns = source.get_columns(table)
    finally:
        source.close()
    page = columns[offset : offset + limit]
    return [ColumnInfoResponse(name=c.name, native_type=c.native_type) for c in page]


# --- DB-clone-and-normalize: clone jobs --------------------------------------


@router.post("/clone-jobs", response_model=CloneJobCreateResponse, status_code=201)
def create_clone_job(
    body: CloneJobCreateRequest,
    connections: Annotated[PgPersistence, Depends(get_connections)],
    dispatcher: Annotated[Dispatcher, Depends(get_dispatcher)],
) -> CloneJobCreateResponse:
    try:
        job = clone_executor.create_clone_job(
            connections,
            # model_dump, not a hand-copied dict: the hand-copied version
            # listed 8 of the request's fields and silently dropped the
            # rest, so `typed_destination_columns` and `in_place` were
            # unreachable over HTTP however they were sent. mode="json"
            # also does the FieldSemanticType -> str conversion that copy
            # was doing by hand.
            request=body.model_dump(mode="json"),
            registry=dispatcher.registry,
        )
    except CloneJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CloneJobStateError as exc:
        # A source with nothing to clone. 422, not 500: the request is
        # well-formed and the server is fine — the database or schema it
        # names holds no tables, and the detail says where they are.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return CloneJobCreateResponse(
        job_id=job["job_id"],
        status=CloneJobStatus(job["status"]),
        # In-place reuses the source database, so there is nothing for the
        # operator to create and Phase 1 verifies nothing.
        create_database_sql=(
            "" if body.in_place else clone_executor.create_database_sql(body.destination_database)
        ),
    )


@router.get("/clone-jobs/{job_id}")
def get_clone_job(
    job_id: str,
    connections: Annotated[PgPersistence, Depends(get_connections)],
) -> dict[str, Any]:
    job = connections.get_clone_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No such clone job: {job_id}")
    # A job whose process was killed never got to mark itself FAILED, so
    # RUNNING alone cannot be trusted. Reported rather than rewritten: the
    # caller can restart it (claim already allows RUNNING -> RUNNING), and
    # a merely slow job must not be declared dead on its behalf.
    return {**job, "stale": clone_executor.is_stale(job)}


@router.get("/clone-jobs/{job_id}/plan")
def get_clone_job_plan(
    job_id: str,
    connections: Annotated[PgPersistence, Depends(get_connections)],
) -> dict[str, Any]:
    """The plan Phase 1 will execute, before it executes any of it: per
    column, the detected or configured semantic type, which of the two it
    was, the native destination type it will get, and the companion column
    it will gain.

    Detection is the part of a clone nobody could see. On a real 13-table
    source it claimed 8 columns out of 114 and missed the two highest-value
    ones, and the only trace was a JSON blob on the job — so signing off on
    a clone meant running it and reading the result. Computed from the same
    function Phase 1 uses, so it cannot describe something else.

    Read-only, and does not touch the destination database, which need not
    exist yet."""
    try:
        return clone_executor.plan_job(connections, job_id)
    except CloneJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/clone-jobs/{job_id}/plan")
def amend_clone_job_plan(
    job_id: str,
    body: CloneJobAmendRequest,
    connections: Annotated[PgPersistence, Depends(get_connections)],
) -> dict[str, Any]:
    """Change the plan after reading it and before Phase 1 builds anything.

    `exclude_unset`: only fields the caller actually sent are applied, so
    omitting one means "leave it" rather than "set it to null" — the
    difference between amending one column and silently clearing the
    country."""
    try:
        return clone_executor.amend_clone_job(
            connections, job_id, body.model_dump(mode="json", exclude_unset=True)
        )
    except CloneJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CloneJobStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/clone-jobs/{job_id}/quality")
def get_clone_job_quality(
    job_id: str,
    connections: Annotated[PgPersistence, Depends(get_connections)],
) -> dict[str, Any]:
    """Per column, what normalization achieved: how many values came out
    NORMALIZED, PARSED, AMBIGUOUS, INVALID, how many were emptied, and how
    many were checked for idempotency.

    Separate from `GET /clone-jobs/{id}` because that one is polled every
    two seconds and this is a table of every configured column in every
    table. Separate from the error report because these are results, not
    findings — a 100% AMBIGUOUS POSTCODE column has nothing wrong with it.

    Empty until Phase 2 has finished a table; a table appears as it
    completes, so a long job's numbers are readable while it runs."""
    job = connections.get_clone_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No such clone job: {job_id}")
    return {"job_id": job_id, "status": job["status"], "tables": job.get("quality", {})}


@router.post("/clone-jobs/{job_id}/verify-database")
def verify_clone_job_database(
    job_id: str,
    connections: Annotated[PgPersistence, Depends(get_connections)],
) -> dict[str, Any]:
    """Decision #6: verifies the user has run the `CREATE DATABASE`
    command shown by `POST /clone-jobs`, then runs Phase 1 DDL (schema
    clone, every table completely empty) for every table."""
    try:
        return clone_executor.verify_and_create_schema(connections, job_id)
    except CloneJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"No such clone job: {job_id}") from exc
    except CloneJobStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/clone-jobs/{job_id}/start")
def start_clone_job(
    job_id: str,
    connections: Annotated[PgPersistence, Depends(get_connections)],
    dispatcher: Annotated[Dispatcher, Depends(get_dispatcher)],
    cache: Annotated[NormalizationCache, Depends(get_cache)],
) -> dict[str, Any]:
    """Phase 2 (decision #4: background, pollable — not a blocking
    request). Also the resume entry point (decision #10): calling this
    again on an orphaned RUNNING job re-streams and skips already-
    committed rows rather than redoing the whole table."""
    started = clone_executor.start_phase2(connections, dispatcher, cache, job_id)
    if not started:
        job = connections.get_clone_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"No such clone job: {job_id}")
        raise HTTPException(
            status_code=409,
            detail=f"Clone job {job_id} is {job['status']}, expected SCHEMA_READY or RUNNING",
        )
    running = connections.get_clone_job(job_id)
    if running is None:  # pragma: no cover - just claimed above, so it exists
        raise HTTPException(status_code=404, detail=f"No such clone job: {job_id}")
    return running


_MAX_CLONE_ERRORS_PAGE_SIZE = 1000


@router.get("/clone-jobs/{job_id}/errors", response_model=list[NormalizationError])
def get_clone_job_errors(
    job_id: str,
    response: Response,
    connections: Annotated[PgPersistence, Depends(get_connections)],
    limit: int = 100,
    offset: int = 0,
) -> list[NormalizationError]:
    """Decision #9: a complete, paginated error/warning report. Same
    `NormalizationError`-shaped response as `GET /runs/{run_id}/errors`.

    `X-Total-Count` is THIS job's row count. A header rather than a wrapper
    object so the existing response shape is unchanged: the number was the
    thing missing, not the list. Without it the only count available to a
    reader was the table's, which holds every job's rows — 4.3M of them
    from an earlier run were once read as one run's output."""
    limit = max(1, min(limit, _MAX_CLONE_ERRORS_PAGE_SIZE))
    offset = max(0, offset)
    if connections.get_clone_job(job_id) is None:
        raise HTTPException(status_code=404, detail=f"No such clone job: {job_id}")
    response.headers["X-Total-Count"] = str(connections.count_clone_job_errors(job_id))
    rows = connections.load_clone_job_errors_page(job_id, limit=limit, offset=offset)
    return [
        NormalizationError(
            field=f"{row['table_name']}.{row['field']}",
            record_ref=str(row["row_index"]),
            operation="clone-normalize",
            error=row["error"],
            severity="error",
            safe_preview=safe_preview(row["original"]) if row["original"] is not None else "null",
            rule_id=None,
            library_version=None,
        )
        for row in rows
    ]


# --- Adjudication (ADR-018): the exit for AMBIGUOUS ---

_MAX_QUEUE_PAGE_SIZE = 1000


def _mask_leaves(value: Any) -> Any:
    """Every string inside a queue entry's detail is derived from the raw
    value (a date's candidate readings, a phone's digits), so each one is
    masked exactly like the value itself."""
    if isinstance(value, str):
        return safe_preview(value)
    if isinstance(value, dict):
        return {k: _mask_leaves(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask_leaves(v) for v in value]
    return value


def _verdict_view(row: dict[str, Any]) -> AdjudicationVerdict:
    display = row["decided_display"]
    return AdjudicationVerdict(
        key=row["key"],
        decided_display_preview=safe_preview(display) if display is not None else None,
        decided_by=row["decided_by"],
        decided_at=row["decided_at"],
        rationale=row["rationale"],
        confidence=row["confidence"],
        env_id=row["env_id"],
        profile_version=row["profile_version"],
    )


def _queue_view(
    row: dict[str, Any], verdicts: list[dict[str, Any]] | None = None
) -> AdjudicationQueueEntry:
    return AdjudicationQueueEntry(
        key=row["key"],
        semantic_type=FieldSemanticType(row["semantic_type"]),
        safe_preview=safe_preview(row["original"]),
        context=json.loads(row["context"]),
        detail=_mask_leaves(json.loads(row["detail"])),
        first_job_id=row["first_job_id"],
        last_job_id=row["last_job_id"],
        occurrences=row["occurrences"],
        decided=bool(row["decided"]),
        verdicts=[_verdict_view(v) for v in verdicts or []],
    )


@router.get("/adjudication/queue", response_model=list[AdjudicationQueueEntry])
def list_adjudication_queue(
    response: Response,
    connections: Annotated[PgPersistence, Depends(get_connections)],
    semantic_type: FieldSemanticType | None = None,
    status: Literal["pending", "decided"] | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[AdjudicationQueueEntry]:
    """Most frequent first: one answer to the top entry settles the most
    rows. `X-Total-Count` as on the clone-job error report."""
    total, rows = connections.list_queue(
        semantic_type=semantic_type.value if semantic_type is not None else None,
        decided=None if status is None else status == "decided",
        limit=max(1, min(limit, _MAX_QUEUE_PAGE_SIZE)),
        offset=max(0, offset),
    )
    response.headers["X-Total-Count"] = str(total)
    return [_queue_view(row) for row in rows]


@router.get("/adjudication/queue/{key}", response_model=AdjudicationQueueEntry)
def get_adjudication_entry(
    key: str, connections: Annotated[PgPersistence, Depends(get_connections)]
) -> AdjudicationQueueEntry:
    row = connections.get_queue_entry(key)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No such queue entry: {key}")
    return _queue_view(row, connections.list_verdicts(key))


@router.post(
    "/adjudication/queue/{key}/verdicts", response_model=AdjudicationVerdict, status_code=201
)
def post_adjudication_verdict(
    key: str,
    body: AdjudicationVerdictRequest,
    connections: Annotated[PgPersistence, Depends(get_connections)],
    dispatcher: Annotated[Dispatcher, Depends(get_dispatcher)],
) -> AdjudicationVerdict:
    """A verdict is stored only if the decided value normalizes cleanly in
    the entry's own context — an answer that is itself ambiguous or
    invalid would put a wrong value in every later run (Q16)."""
    row = connections.get_queue_entry(key)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No such queue entry: {key}")
    if adjudication.DECIDED_BY.fullmatch(body.decided_by) is None:
        raise HTTPException(
            status_code=422, detail="decided_by must be 'human:<id>' or 'agent:<id>'"
        )
    context = NormalizationContext.model_validate_json(row["context"])
    if row["profile_version"] != SCAFFOLD_PROFILE.version:
        raise HTTPException(
            status_code=409,
            detail="queue entry belongs to another profile version; it no longer applies",
        )
    result = dispatcher.normalize(
        body.decided_value, context.semantic_type, context, SCAFFOLD_PROFILE
    )
    if result.normalization_status not in adjudication.CLEAN_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"decided value normalizes to {result.normalization_status.value}, "
            "not to a clean value; nothing stored",
        )
    verdict = {
        "key": key,
        "semantic_type": row["semantic_type"],
        "context_hash": row["context_hash"],
        "profile_version": row["profile_version"],
        "decided_value": body.decided_value,
        "decided_display": result.display,
        "decided_by": body.decided_by,
        "decided_at": dt.datetime.now(tz=dt.UTC).isoformat(),
        "rationale": body.rationale,
        "confidence": body.confidence,
        "env_id": dispatcher.env_id,
    }
    connections.add_verdict(verdict)
    return _verdict_view(verdict)

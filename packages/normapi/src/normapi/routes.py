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

from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException
from normcore.pii import safe_preview

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
from normapi.dependencies import (
    get_custom_dictionary_store,
    get_dictionary_loader,
    get_dispatcher,
    get_store,
)
from normapi.scaffold_profile import SCAFFOLD_PROFILE
from normapi.schemas import (
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

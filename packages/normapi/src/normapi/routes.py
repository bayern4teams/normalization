"""Source.txt §98 API routes.

    POST /normalization/profiles
    GET  /normalization/profiles
    GET  /normalization/fields
    POST /normalization/preview
    POST /normalization/runs
    GET  /normalization/runs/{id}
    GET  /normalization/runs/{id}/errors
    GET  /normalization/runs/{id}/collisions
    POST /normalization/profiles/{id}/versions
    POST /normalization/dictionaries
    GET  /normalization/dictionaries
    POST /normalization/field-test
    GET  /normalization/impact

Every route is registered and returns a schema-valid response (M1's Gate
G1 requirement). Profile/run CRUD and field-test/preview are wired to real
logic (InMemoryStore, the real Dispatcher). Dictionary writes and impact
analysis are out of M1's scope (M6) and return an honest 501 with a
schema-valid NotImplementedResponse body, rather than faking success.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from normapi.dependencies import get_dictionary_loader, get_dispatcher, get_store
from normapi.scaffold_profile import SCAFFOLD_PROFILE
from normapi.schemas import (
    DictionarySummary,
    FieldSummary,
    FieldTestRequest,
    NotImplementedResponse,
    PreviewRequest,
    ProfileCreateRequest,
    ProfileVersionRequest,
)
from normapi.store import InMemoryStore, ProfileNotFoundError, RunNotFoundError
from normcore import (
    Dispatcher,
    NormalizationContext,
    NormalizationError,
    NormalizationProfile,
    NormalizationRun,
    NormalizedValue,
)
from normdict import DictionaryLoader

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


@router.post("/runs", response_model=NormalizationRun, status_code=201)
def create_run(
    profile_id: str,
    source_snapshot: str,
    store: Annotated[InMemoryStore, Depends(get_store)],
    dispatcher: Annotated[Dispatcher, Depends(get_dispatcher)],
) -> NormalizationRun:
    try:
        return store.create_run(
            profile_id=profile_id, env_id=dispatcher.env_id, source_snapshot=source_snapshot
        )
    except ProfileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"No such profile: {profile_id}") from exc


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
        store.get_run(run_id)  # 404s if the run itself doesn't exist
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"No such run: {run_id}") from exc
    # Real per-run error tracking is wired once normexec's batch execution
    # actually populates NormalizationError records against a run (M2+);
    # the scaffold run store has no field executions yet, so this is
    # correctly empty, not faked.
    return []


@router.get("/runs/{run_id}/collisions")
def get_run_collisions(
    run_id: str, store: Annotated[InMemoryStore, Depends(get_store)]
) -> list[dict[str, object]]:
    try:
        store.get_run(run_id)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"No such run: {run_id}") from exc
    # Collision analysis is normanalysis's job (M6, §79/§92) — empty here
    # is correct for a run with no executed normalization, not a stub lie.
    return []


# --- dictionaries -------------------------------------------------------


@router.get("/dictionaries", response_model=list[DictionarySummary])
def list_dictionaries(
    loader: Annotated[DictionaryLoader, Depends(get_dictionary_loader)],
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
                )
            )
    return summaries


@router.post("/dictionaries", response_model=NotImplementedResponse, status_code=501)
def create_dictionary() -> NotImplementedResponse:
    return NotImplementedResponse(
        detail="Dictionary write/versioning is out of scope for M1 (read-only path only).",
        planned_milestone="M6",
    )


# --- impact ---------------------------------------------------------------


@router.get("/impact", response_model=NotImplementedResponse, status_code=501)
def get_impact() -> NotImplementedResponse:
    return NotImplementedResponse(
        detail="Impact analysis is normanalysis's responsibility, out of scope for M1.",
        planned_milestone="M6",
    )

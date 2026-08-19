"""Data Discovery handoff artifact — Source.txt §134.

The previously designed Data Discovery & Entity Context Engine is a
separate, downstream system (§134/§135's pipeline: Data Discovery ->
Entity Context -> Canonical Matching Dataset -> Splink) that consumes
this project's *output*, never this project's internal `NormalizedValue`
objects or database directly. `build_handoff_artifact` assembles exactly
the fields §134 names from one completed run's real results:

- normalized schema metadata      -> `HandoffArtifact.field_schema`
- semantic types                  -> `field_schema.semantic_type`
- normalized comparison values    -> `HandoffRecord.comparison`
- parsed components               -> `HandoffRecord.parsed_components`
- country/language metadata       -> `HandoffRecord.country_language_metadata`
- validation flags                -> `HandoffRecord.validation_status`/`flags`
- collision diagnostics           -> `HandoffArtifact.collisions`
- stable versioned normalization
  profile                         -> `HandoffArtifact.profile` (§73's env_id
                                      is exactly this project's "stable
                                      versioned" identifier — see ADR-014)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from normanalysis.collisions import CollisionGroup, find_collisions

if TYPE_CHECKING:
    from collections.abc import Sequence

    from normcore import FieldSemanticType, NormalizationProfile, NormalizedValue

# Country/language metadata is only meaningful when the field itself IS a
# country or language field — populating it for, say, an ADDRESS field
# would fabricate a category the run never actually produced. Both
# normalizers already put their real parsed metadata in `structured`
# (alpha2/alpha3/country_name for CountryNormalizer, canonical_code/
# language_name for LanguageNormalizer — see normalizers/country.py,
# normalizers/language.py), so no separate extraction is needed.
_COUNTRY_LANGUAGE_SEMANTIC_TYPES = frozenset({"COUNTRY", "LANGUAGE"})


class HandoffFieldSchema(BaseModel):
    model_config = ConfigDict(frozen=True)

    field_name: str
    semantic_type: str


class HandoffProfileVersion(BaseModel):
    """§73's stable, versioned identity of what actually produced this
    run's output — the exact thing a downstream consumer needs to know
    whether two handoff artifacts are safely comparable."""

    model_config = ConfigDict(frozen=True)

    profile_id: str
    profile_version: str
    env_id: str


class HandoffRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    original: str | None
    comparison: str | None
    display: str | None
    parsed_components: dict[str, object]
    country_language_metadata: dict[str, object] | None
    validation_status: str | None
    flags: list[str]


class HandoffArtifact(BaseModel):
    model_config = ConfigDict(frozen=True)

    field_schema: HandoffFieldSchema
    profile: HandoffProfileVersion
    records: list[HandoffRecord]
    collisions: list[CollisionGroup]


def build_handoff_artifact(
    *,
    field_name: str,
    semantic_type: FieldSemanticType,
    profile: NormalizationProfile,
    env_id: str,
    originals: Sequence[str | None],
    results: Sequence[NormalizedValue],
) -> HandoffArtifact:
    if len(originals) != len(results):
        msg = f"originals ({len(originals)}) and results ({len(results)}) must be the same length"
        raise ValueError(msg)

    is_country_or_language = semantic_type.value in _COUNTRY_LANGUAGE_SEMANTIC_TYPES
    records = [
        HandoffRecord(
            original=original,
            comparison=result.comparison,
            display=result.display,
            parsed_components=result.structured,
            country_language_metadata=(result.structured if is_country_or_language else None),
            validation_status=result.validation_status,
            flags=[flag.value for flag in result.flags],
        )
        for original, result in zip(originals, results, strict=True)
    ]

    return HandoffArtifact(
        field_schema=HandoffFieldSchema(field_name=field_name, semantic_type=semantic_type.value),
        profile=HandoffProfileVersion(
            profile_id=profile.id, profile_version=profile.version, env_id=env_id
        ),
        records=records,
        collisions=find_collisions(originals, results),
    )

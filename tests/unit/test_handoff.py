"""Proves the Data Discovery handoff artifact — Source.txt §134 — carries
every field the spec names, built from real normalizer output (not
hand-built NormalizedValue fixtures pretending to be real results).
"""

from __future__ import annotations

import pytest
from normalizers.country import CountryNormalizer
from normalizers.name import NameNormalizer

from normanalysis import build_handoff_artifact
from normcore import (
    Dispatcher,
    FieldSemanticType,
    NormalizationContext,
    NormalizationProfile,
    NormalizerRegistry,
)
from normdict import DictionaryLoader

_DICT_ROOT = "tests/data/dictionaries"


def _profile() -> NormalizationProfile:
    return NormalizationProfile(
        id="p1",
        name="test",
        version="v3",
        created_at="2026-08-17T00:00:00Z",
        updated_at="2026-08-17T00:00:00Z",
        created_by="test",
    )


def _dispatcher(*normalizers: object) -> Dispatcher:
    registry = NormalizerRegistry()
    for normalizer in normalizers:
        registry.register(normalizer)  # type: ignore[arg-type]
    return Dispatcher(registry, env_id="e" * 64)


@pytest.mark.unit
def test_handoff_field_schema_and_profile_carry_real_identity() -> None:
    dispatcher = _dispatcher(CountryNormalizer())
    profile = _profile()
    ctx = NormalizationContext(field_name="ship_country", semantic_type=FieldSemanticType.COUNTRY)
    results = [dispatcher.normalize("Germany", FieldSemanticType.COUNTRY, ctx, profile)]

    artifact = build_handoff_artifact(
        field_name="ship_country",
        semantic_type=FieldSemanticType.COUNTRY,
        profile=profile,
        env_id=dispatcher.env_id,
        originals=["Germany"],
        results=results,
    )

    assert artifact.field_schema.field_name == "ship_country"
    assert artifact.field_schema.semantic_type == "COUNTRY"
    assert artifact.profile.profile_id == "p1"
    assert artifact.profile.profile_version == "v3"
    assert artifact.profile.env_id == dispatcher.env_id


@pytest.mark.unit
def test_handoff_record_carries_comparison_value_and_parsed_components() -> None:
    dispatcher = _dispatcher(CountryNormalizer())
    profile = _profile()
    ctx = NormalizationContext(field_name="country", semantic_type=FieldSemanticType.COUNTRY)
    results = [dispatcher.normalize("Germany", FieldSemanticType.COUNTRY, ctx, profile)]

    artifact = build_handoff_artifact(
        field_name="country",
        semantic_type=FieldSemanticType.COUNTRY,
        profile=profile,
        env_id=dispatcher.env_id,
        originals=["Germany"],
        results=results,
    )

    record = artifact.records[0]
    assert record.original == "Germany"
    assert record.comparison is not None  # real normalized comparison value
    assert record.parsed_components["alpha2"] == "DE"  # real CountryNormalizer output


@pytest.mark.unit
def test_country_language_metadata_populated_only_for_country_and_language_fields() -> None:
    dispatcher = _dispatcher(CountryNormalizer())
    profile = _profile()
    ctx = NormalizationContext(field_name="country", semantic_type=FieldSemanticType.COUNTRY)
    results = [dispatcher.normalize("France", FieldSemanticType.COUNTRY, ctx, profile)]

    country_artifact = build_handoff_artifact(
        field_name="country",
        semantic_type=FieldSemanticType.COUNTRY,
        profile=profile,
        env_id=dispatcher.env_id,
        originals=["France"],
        results=results,
    )
    assert country_artifact.records[0].country_language_metadata is not None
    assert country_artifact.records[0].country_language_metadata["alpha2"] == "FR"


@pytest.mark.unit
def test_country_language_metadata_is_none_for_unrelated_semantic_types() -> None:
    loader = DictionaryLoader(_DICT_ROOT)
    dispatcher = _dispatcher(NameNormalizer(loader))
    profile = _profile()
    ctx = NormalizationContext(field_name="name", semantic_type=FieldSemanticType.PERSON_NAME)
    results = [dispatcher.normalize("John Smith", FieldSemanticType.PERSON_NAME, ctx, profile)]

    artifact = build_handoff_artifact(
        field_name="name",
        semantic_type=FieldSemanticType.PERSON_NAME,
        profile=profile,
        env_id=dispatcher.env_id,
        originals=["John Smith"],
        results=results,
    )
    assert artifact.records[0].country_language_metadata is None
    # parsed_components (structured) is still populated regardless — it's
    # a distinct concept from country/language metadata specifically.


@pytest.mark.unit
def test_handoff_surfaces_real_validation_failure() -> None:
    dispatcher = _dispatcher(CountryNormalizer())
    profile = _profile()
    ctx = NormalizationContext(field_name="country", semantic_type=FieldSemanticType.COUNTRY)
    # An unresolvable country string -> real INVALID/"INVALID" status.
    result = dispatcher.normalize(
        "Not A Real Country Xyz123", FieldSemanticType.COUNTRY, ctx, profile
    )

    artifact = build_handoff_artifact(
        field_name="country",
        semantic_type=FieldSemanticType.COUNTRY,
        profile=profile,
        env_id=dispatcher.env_id,
        originals=["Not A Real Country Xyz123"],
        results=[result],
    )
    record = artifact.records[0]
    assert record.validation_status == "INVALID"
    assert record.validation_status == result.validation_status
    assert record.flags == [flag.value for flag in result.flags]


@pytest.mark.unit
def test_handoff_collision_diagnostics_reflect_real_collapsing_values() -> None:
    dispatcher = _dispatcher(CountryNormalizer())
    profile = _profile()
    ctx = NormalizationContext(field_name="country", semantic_type=FieldSemanticType.COUNTRY)
    originals = ["Germany", "germany", "GERMANY"]
    results = [
        dispatcher.normalize(value, FieldSemanticType.COUNTRY, ctx, profile) for value in originals
    ]

    artifact = build_handoff_artifact(
        field_name="country",
        semantic_type=FieldSemanticType.COUNTRY,
        profile=profile,
        env_id=dispatcher.env_id,
        originals=originals,
        results=results,
    )
    assert len(artifact.collisions) == 1
    assert set(artifact.collisions[0].original_values) == {"Germany", "germany", "GERMANY"}


@pytest.mark.unit
def test_handoff_rejects_mismatched_originals_and_results_length() -> None:
    profile = _profile()
    with pytest.raises(ValueError, match="same length"):
        build_handoff_artifact(
            field_name="x",
            semantic_type=FieldSemanticType.COUNTRY,
            profile=profile,
            env_id="e" * 64,
            originals=["a", "b"],
            results=[],
        )

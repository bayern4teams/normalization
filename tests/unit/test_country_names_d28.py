"""D28: a leading "The" on an exact name, and names shared by several countries."""

from __future__ import annotations

import pytest
from normalizers.country import CountryNormalizer
from normalizers.country_codes import resolve_country_alpha2
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType, NormalizationStatus


def _normalize(value: str):
    ctx = NormalizationContext(field_name="c", semantic_type=FieldSemanticType.COUNTRY)
    return CountryNormalizer().normalize(value, ctx)


@pytest.mark.parametrize(
    ("value", "code"),
    [
        ("The Netherlands", "NL"),
        ("the netherlands", "NL"),
        ("THE GAMBIA", "GM"),
        ("The Bahamas", "BS"),
        ("Netherlands", "NL"),
    ],
)
def test_the_is_stripped_before_an_exact_name(value: str, code: str) -> None:
    result = _normalize(value)
    assert result.normalization_status is NormalizationStatus.NORMALIZED
    assert result.comparison == code


@pytest.mark.parametrize(
    ("value", "readings"),
    [
        ("Congo", {"CG", "CD"}),
        ("congo", {"CG", "CD"}),
        ("Korea", {"KR", "KP"}),
        ("Virgin Islands", {"VG", "VI"}),
    ],
)
def test_a_name_of_several_countries_is_ambiguous(value: str, readings: set[str]) -> None:
    result = _normalize(value)
    assert result.normalization_status is NormalizationStatus.AMBIGUOUS
    assert set(result.structured["candidates"]) == readings
    assert result.comparison is None
    assert resolve_country_alpha2(value) is None


@pytest.mark.parametrize(
    "value",
    [
        "The Congo",  # the rest is not unambiguous
        "The Korea",
        "The US",  # the rest is a code, not a name
        "The Netherland",  # the rest is not exact
        "Palestinian Territory",  # only GeoNames lists these (owner, b4)
        "Bonaire, Saint Eustatius and Saba",
    ],
)
def test_stays_invalid(value: str) -> None:
    assert _normalize(value).normalization_status is NormalizationStatus.INVALID


def test_full_congo_names_stay_distinct() -> None:
    assert _normalize("Republic of the Congo").comparison == "CG"
    assert _normalize("Democratic Republic of the Congo").comparison == "CD"

"""D20: case does not mean "code"; `_` reads as `-` only inside a valid locale tag."""

from __future__ import annotations

import pytest
from normalizers.language import LanguageNormalizer
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType, NormalizationStatus


def _normalize(value: str, country: str | None = None):
    ctx = NormalizationContext(
        field_name="l", semantic_type=FieldSemanticType.LANGUAGE, country=country
    )
    return LanguageNormalizer().normalize(value, ctx)


@pytest.mark.parametrize("value", ["mon", "MON", "Mon"])
def test_mon_is_ambiguous_in_any_case(value: str) -> None:
    result = _normalize(value)
    assert result.normalization_status is NormalizationStatus.AMBIGUOUS
    assert {r["code"] for r in result.structured["readings"]} == {"mn", "mnw"}


def test_row_country_still_settles_lower_case_mon() -> None:
    assert _normalize("mon", country="MM").comparison == "mnw"


@pytest.mark.parametrize(("value", "code"), [("en", "en"), ("EN", "en"), ("gaa", "gaa")])
def test_a_stored_code_stays_a_code(value: str, code: str) -> None:
    assert _normalize(value).comparison == code


def test_underscore_inside_a_locale_tag_reads_as_a_hyphen() -> None:
    underscore, hyphen = _normalize("en_US"), _normalize("en-US")
    assert underscore.normalization_status is NormalizationStatus.NORMALIZED
    assert underscore.comparison == hyphen.comparison == "en"
    assert underscore.structured["tag_territory"] == hyphen.structured["tag_territory"] == "US"


def test_underscore_in_a_name_is_not_a_hyphen() -> None:
    assert _normalize("Kuku_Yalanji").normalization_status is NormalizationStatus.INVALID

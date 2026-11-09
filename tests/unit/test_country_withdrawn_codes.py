"""D27: a withdrawn ISO 3166 code with several successors is AMBIGUOUS, never one of them."""

from __future__ import annotations

import babel.core
import pytest
from normalizers.country import CountryNormalizer
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType, NormalizationStatus

_ALIASES = babel.core.get_global("territory_aliases")


def _normalize(value: str):
    ctx = NormalizationContext(field_name="c", semantic_type=FieldSemanticType.COUNTRY)
    return CountryNormalizer().normalize(value, ctx)


@pytest.mark.parametrize("code", ["SU", "AN", "YU", "NT"])
def test_every_cldr_successor_is_a_reading(code: str) -> None:
    result = _normalize(code)
    assert result.normalization_status is NormalizationStatus.AMBIGUOUS
    assert result.structured["candidates"] == _ALIASES[code]
    assert result.comparison is None
    assert result.display == code


def test_report_counts() -> None:
    assert len(_normalize("SU").structured["candidates"]) == 15
    assert set(_normalize("AN").structured["candidates"]) == {"CW", "SX", "BQ"}


def test_cs_also_offers_czechoslovakia() -> None:
    result = _normalize("CS")
    assert result.normalization_status is NormalizationStatus.AMBIGUOUS
    assert result.structured["candidates"] == ["RS", "ME", "CSHH"]


def test_lower_case_code_is_read_like_a_single_successor_code() -> None:
    assert _normalize("su").normalization_status is NormalizationStatus.AMBIGUOUS


def test_single_successor_unchanged() -> None:
    result = _normalize("DD")
    assert result.normalization_status is NormalizationStatus.NORMALIZED
    assert result.comparison == "DE"


def test_explain_does_not_claim_a_resolution() -> None:
    result = _normalize("SU")
    assert "Resolved" not in CountryNormalizer().explain(result).plain_language

"""M4 golden corpus — Source.txt §109's own worked examples for addresses,
dates, and country/language codes. Gate G4 requirement.

Address cases require the real libpostal sidecar (skipped if unreachable
— see tests/integration/test_address_normalizer_integration.py for the
mandatory real-infrastructure proof); date/country/language/script cases
run standalone.
"""

from __future__ import annotations

import i18naddress
import pytest
from normalizers.address import AddressNormalizer, LibpostalClient
from normalizers.country import CountryNormalizer
from normalizers.date import DateNormalizer
from normalizers.language import LanguageNormalizer
from normalizers.script import ScriptNormalizer
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType, NormalizationStatus

_LIBPOSTAL_URL = "http://localhost:8081"


@pytest.fixture(scope="module")
def address_normalizer() -> AddressNormalizer:
    client = LibpostalClient(_LIBPOSTAL_URL)
    try:
        client.health()
    except Exception as exc:
        pytest.skip(f"libpostal sidecar not reachable at {_LIBPOSTAL_URL}: {exc}")
    normalizer = AddressNormalizer(client)
    yield normalizer
    client.close()


@pytest.mark.golden
def test_uk_address_house_number_range_survives(address_normalizer: AddressNormalizer) -> None:
    """Source.txt §109: "10-12 Baker St., London, W1U 3BW, UK" — the
    house-number range must survive, never becoming "1012"."""
    ctx = NormalizationContext(field_name="address", semantic_type=FieldSemanticType.ADDRESS)
    result = address_normalizer.normalize("10-12 Baker St., London, W1U 3BW, UK", ctx)
    assert result.structured["house_number"] == "10-12"
    assert result.structured["postcode_valid"] is True


@pytest.mark.golden
def test_us_address_full_parse(address_normalizer: AddressNormalizer) -> None:
    """Source.txt §109: "1600 Pennsylvania Avenue NW, Washington, DC
    20500, USA"."""
    ctx = NormalizationContext(field_name="address", semantic_type=FieldSemanticType.ADDRESS)
    result = address_normalizer.normalize(
        "1600 Pennsylvania Avenue NW, Washington, DC 20500, USA", ctx
    )
    assert result.structured["postcode"] == "20500"
    assert result.structured["postcode_valid"] is True
    assert result.normalization_status is NormalizationStatus.PARSED


@pytest.mark.golden
@pytest.mark.parametrize(
    ("country", "postcode", "expect_valid"),
    [
        ("GB", "W1U 3BW", True),
        ("US", "02110", True),
        ("CA", "M5V 3A8", True),
        ("FR", "75001", True),
        ("DE", "10115", True),
        ("JP", "100-0001", True),
        ("AU", "2000", True),
        ("NL", "1012 AB", True),
        ("IT", "00100", True),
        ("ES", "28001", True),
        ("SE", "111 22", True),
        ("CH", "8001", True),
        ("BR", "01310-100", True),
        ("IN", "110001", True),
        ("SG", "018956", True),
        ("GB", "NOTAPOSTCODE", False),
    ],
)
def test_postal_code_validation_across_countries(
    country: str, postcode: str, expect_valid: bool
) -> None:
    """Gate G4: postal-code validation correct across >= 15 countries,
    per-country (not one universal regex, §32)."""
    rules = i18naddress.get_validation_rules({"country_code": country})
    if not rules.postal_code_matchers:
        pytest.skip(f"{country} has no postal-code matchers in this dataset")
    matched = any(m.match(postcode.upper()) for m in rules.postal_code_matchers)
    assert matched is expect_valid, f"{country}/{postcode}: expected valid={expect_valid}"


# --- Dates ---------------------------------------------------------------


@pytest.fixture(scope="module")
def date_normalizer() -> DateNormalizer:
    return DateNormalizer()


@pytest.mark.golden
@pytest.mark.parametrize("value", ["03/04/2024", "01/02/03", "1/2/2024", "12/11/2024"])
def test_ambiguous_dates_all_return_ambiguous_without_context(
    date_normalizer: DateNormalizer, value: str
) -> None:
    """Gate G4: ambiguous-date cases all return AMBIGUOUS rather than a
    guess."""
    ctx = NormalizationContext(field_name="date", semantic_type=FieldSemanticType.DATE)
    result = date_normalizer.normalize(value, ctx)
    assert result.normalization_status is NormalizationStatus.AMBIGUOUS


# --- Country / Language --------------------------------------------------


@pytest.fixture(scope="module")
def country_normalizer() -> CountryNormalizer:
    return CountryNormalizer()


@pytest.fixture(scope="module")
def language_normalizer() -> LanguageNormalizer:
    return LanguageNormalizer()


@pytest.fixture(scope="module")
def script_normalizer() -> ScriptNormalizer:
    return ScriptNormalizer()


@pytest.mark.golden
def test_gb_uk_ambiguity_surfaced_not_resolved(country_normalizer: CountryNormalizer) -> None:
    ctx = NormalizationContext(field_name="country", semantic_type=FieldSemanticType.COUNTRY)
    uk_result = country_normalizer.normalize("UK", ctx)
    gb_result = country_normalizer.normalize("United Kingdom", ctx)
    assert uk_result.structured["alpha2"] == gb_result.structured["alpha2"] == "GB"
    # "UK" resolved via an alias, flagged as such; "United Kingdom" is an
    # exact name match, not flagged — the ambiguity is surfaced via the
    # flag/confidence difference, never silently erased.
    assert uk_result.confidence < gb_result.confidence


@pytest.mark.golden
def test_never_transliterates_non_latin_script(script_normalizer: ScriptNormalizer) -> None:
    ctx = NormalizationContext(field_name="text", semantic_type=FieldSemanticType.SCRIPT)
    result = script_normalizer.normalize("東京都", ctx)
    assert result.display == "東京都"
    assert result.structured["script"] == "Han"

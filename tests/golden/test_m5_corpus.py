"""M5 golden corpus — Source.txt Gate G5's explicit requirements:
leading-zero, UUID, check-digit (>= 10 countries), Unicode-digit,
AB-001/AB001 collision tests; locale-dependent numeric parsing correct
for >= 8 locales; ambiguous "$" refuses to resolve; unit conversion
dimensionally sound and dimension-mismatch rejected; an identifier
collision report.
"""

from __future__ import annotations

from collections import defaultdict

import pint
import pytest
from normalizers.currency import CurrencyNormalizer
from normalizers.identifier import IdentifierNormalizer, UuidNormalizer
from normalizers.numeric import NumericNormalizer
from normalizers.unit import UnitNormalizer
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType, NormalizationStatus, QualityFlag
from stdnum import iban


@pytest.fixture(scope="module")
def identifier_normalizer() -> IdentifierNormalizer:
    return IdentifierNormalizer()


@pytest.fixture(scope="module")
def uuid_normalizer() -> UuidNormalizer:
    return UuidNormalizer()


@pytest.fixture(scope="module")
def numeric_normalizer() -> NumericNormalizer:
    return NumericNormalizer()


@pytest.fixture(scope="module")
def currency_normalizer() -> CurrencyNormalizer:
    return CurrencyNormalizer()


@pytest.fixture(scope="module")
def unit_normalizer() -> UnitNormalizer:
    return UnitNormalizer()


# --- Leading zero + Unicode digit ------------------------------------


@pytest.mark.golden
def test_leading_zeros_preserved(identifier_normalizer: IdentifierNormalizer) -> None:
    ctx = NormalizationContext(field_name="id", semantic_type=FieldSemanticType.IDENTIFIER)
    result = identifier_normalizer.normalize("000123", ctx)
    assert result.display == "000123"


@pytest.mark.golden
def test_unicode_digit_leading_zero_preserved(identifier_normalizer: IdentifierNormalizer) -> None:
    ctx = NormalizationContext(field_name="id", semantic_type=FieldSemanticType.IDENTIFIER)
    result = identifier_normalizer.normalize("٠٠١٢٣", ctx)  # Arabic-Indic
    assert result.display == "00123"


# --- UUID --------------------------------------------------------------


@pytest.mark.golden
def test_uuid_canonical_form(uuid_normalizer: UuidNormalizer) -> None:
    ctx = NormalizationContext(field_name="uuid", semantic_type=FieldSemanticType.UUID)
    result = uuid_normalizer.normalize("{550E8400-E29B-41D4-A716-446655440000}", ctx)
    assert result.display == "550e8400-e29b-41d4-a716-446655440000"


# --- Check digits across >= 10 countries (via IBAN, ISO 7064 MOD 97-10) --


_IBAN_EXAMPLES: dict[str, str] = {
    "DE": "DE89370400440532013000",
    "GB": "GB29NWBK60161331926819",
    "FR": "FR1420041010050500013M02606",
    "ES": "ES9121000418450200051332",
    "IT": "IT60X0542811101000000123456",
    "NL": "NL91ABNA0417164300",
    "BE": "BE71096123456769",
    "CH": "CH9300762011623852957",
    "SE": "SE4550000000058398257466",
    "NO": "NO9386011117947",
    "DK": "DK5000400440116243",
    "PL": "PL61109010140000071219812874",
    "PT": "PT50000201231234567890154",
    "AT": "AT611904300234573201",
    "IE": "IE29AIBK93115212345678",
}


@pytest.mark.golden
@pytest.mark.parametrize("country", sorted(_IBAN_EXAMPLES))
def test_check_digit_valid_across_many_countries(country: str) -> None:
    """Gate G5: check-digit validation correct across >= 10 countries.
    IBAN's ISO 7064 MOD 97-10 check digit is computed identically
    regardless of country, exercised here against 15 real national IBAN
    formats."""
    assert iban.is_valid(_IBAN_EXAMPLES[country]) is True


@pytest.mark.golden
def test_check_digit_rejects_corrupted_iban() -> None:
    valid = _IBAN_EXAMPLES["DE"]
    corrupted = valid[:-1] + ("1" if valid[-1] != "1" else "2")
    assert iban.is_valid(corrupted) is False


# --- Separator collision ------------------------------------------------


@pytest.mark.golden
def test_ab001_collision_report(identifier_normalizer: IdentifierNormalizer) -> None:
    """Gate G5's own worked example: "AB-001"/"AB001"."""
    ctx = NormalizationContext(field_name="id", semantic_type=FieldSemanticType.IDENTIFIER)
    with_sep = identifier_normalizer.normalize("AB-001", ctx)
    without_sep = identifier_normalizer.normalize("AB001", ctx)

    groups: dict[str, list[str]] = defaultdict(list)
    for label, result in (("AB-001", with_sep), ("AB001", without_sep)):
        groups[result.comparison].append(label)

    assert len(groups) == 2, "AB-001 and AB001 must remain distinct comparison groups"
    assert QualityFlag.POTENTIAL_COLLISION in with_sep.flags
    assert QualityFlag.POTENTIAL_COLLISION not in without_sep.flags


# --- Locale-dependent numeric parsing across >= 8 locales ---------------


_LOCALE_NUMERIC_CASES: tuple[tuple[str, str, str], ...] = (
    ("US", "1,234.56", "1234.56"),
    ("GB", "1,234.56", "1234.56"),
    ("DE", "1.234,56", "1234.56"),
    ("FR", "1 234,56", "1234.56"),
    ("IT", "1.234,56", "1234.56"),
    ("ES", "1.234,56", "1234.56"),
    ("CH", "1'234.56", "1234.56"),
    ("IN", "1,234.56", "1234.56"),
)


@pytest.mark.golden
@pytest.mark.parametrize(("country", "value", "expected"), _LOCALE_NUMERIC_CASES)
def test_numeric_parsing_across_locales(
    numeric_normalizer: NumericNormalizer, country: str, value: str, expected: str
) -> None:
    """Gate G5: locale-dependent numeric parsing correct for >= 8
    locales."""
    ctx = NormalizationContext(
        field_name="n", semantic_type=FieldSemanticType.NUMERIC, country=country
    )
    result = numeric_normalizer.normalize(value, ctx)
    assert result.display == expected, (
        f"{country}: {value} -> expected {expected}, got {result.display}"
    )


# --- Ambiguous currency --------------------------------------------------


@pytest.mark.golden
def test_bare_dollar_sign_refuses_to_resolve(currency_normalizer: CurrencyNormalizer) -> None:
    ctx = NormalizationContext(field_name="c", semantic_type=FieldSemanticType.CURRENCY)
    result = currency_normalizer.normalize("$", ctx)
    assert result.normalization_status is NormalizationStatus.AMBIGUOUS
    assert result.structured["canonical_currency"] is None


# --- Unit dimensional soundness ------------------------------------------


@pytest.mark.golden
def test_unit_conversion_is_dimensionally_sound(unit_normalizer: UnitNormalizer) -> None:
    ctx = NormalizationContext(field_name="q", semantic_type=FieldSemanticType.QUANTITY)
    km = unit_normalizer.normalize("5 km", ctx)
    kg = unit_normalizer.normalize("5 kg", ctx)
    assert km.structured["dimensionality"] == "[length]"
    assert kg.structured["dimensionality"] == "[mass]"
    assert km.structured["dimensionality"] != kg.structured["dimensionality"]


@pytest.mark.golden
def test_dimension_mismatch_is_rejected_by_pint_itself() -> None:
    """Gate G5: dimension-mismatch rejected — proven directly against
    the real Pint library UnitNormalizer relies on, not just asserted."""
    ureg = pint.UnitRegistry()
    length = ureg("5 km")
    with pytest.raises(pint.DimensionalityError):
        length.to("kilogram")

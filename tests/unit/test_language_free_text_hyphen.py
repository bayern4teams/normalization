"""D13 fix 3: a hyphen splits a value only when it is a valid BCP 47 tag (attack verdict 2)."""

import pytest
from normalizers.language import LanguageNormalizer
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType, NormalizationStatus

_CTX = NormalizationContext(field_name="lang", semantic_type=FieldSemanticType.LANGUAGE)


@pytest.mark.unit
@pytest.mark.parametrize("value", ["Mon-Khmer", "Ga-Adangme", "Mon-Myanmar", "Ron-Romanian"])
def test_free_text_after_a_hyphen_is_not_a_variant(value: str) -> None:
    result = LanguageNormalizer().normalize(value, _CTX)
    assert result.normalization_status is not NormalizationStatus.NORMALIZED
    assert result.comparison not in {"mn", "ga", "ro"}


@pytest.mark.unit
def test_a_cldr_variant_still_splits() -> None:
    result = LanguageNormalizer().normalize("ca-ES-valencia", _CTX)
    assert result.normalization_status is NormalizationStatus.NORMALIZED
    assert result.comparison == "ca"

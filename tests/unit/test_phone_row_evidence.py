"""D21: an international-form phone names the row's country; a national-format one does not."""

from __future__ import annotations

from normalizers.language import LanguageNormalizer
from normapi.clone_executor import _phone_row_countries
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType, NormalizationStatus

_MM = "+95 9 212 3456"
_DE = "+49 30 901820"


def _countries(*phones: dict[str, object]) -> dict[int, tuple[str, str]]:
    return _phone_row_countries(list(enumerate(phones)), ["p", "q"])


def test_international_phone_names_the_country() -> None:
    assert _countries({"p": _MM, "q": None}) == {0: ("p", "MM")}


def test_national_format_names_nothing() -> None:
    assert _countries({"p": "09 212 3456", "q": None}) == {}


def test_unusable_values_name_nothing() -> None:
    assert _countries({"p": "+95", "q": 959212}) == {}


def test_two_phones_that_disagree_name_nothing() -> None:
    assert _countries({"p": _MM, "q": _DE}) == {0: ("q", "")}


def _language(country: str | None):
    ctx = NormalizationContext(
        field_name="l", semantic_type=FieldSemanticType.LANGUAGE, country=country
    )
    return LanguageNormalizer().normalize("Mon", ctx)


def test_the_named_country_settles_mon() -> None:
    assert _language(_countries({"p": _MM, "q": None})[0][1]).comparison == "mnw"
    assert _language(None).normalization_status is NormalizationStatus.AMBIGUOUS

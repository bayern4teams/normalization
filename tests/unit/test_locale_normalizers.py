"""Unit tests for CountryNormalizer, LanguageNormalizer, ScriptNormalizer
— Source.txt Phase 10 (§33-§35)."""

from __future__ import annotations

import pytest
from normalizers.country import CountryNormalizer
from normalizers.language import LanguageNormalizer
from normalizers.script import ScriptNormalizer
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType, MissingKind, NormalizationStatus, QualityFlag


@pytest.fixture(scope="module")
def country_normalizer() -> CountryNormalizer:
    return CountryNormalizer()


@pytest.fixture(scope="module")
def language_normalizer() -> LanguageNormalizer:
    return LanguageNormalizer()


@pytest.fixture(scope="module")
def script_normalizer() -> ScriptNormalizer:
    return ScriptNormalizer()


def _ctx(semantic_type: FieldSemanticType) -> NormalizationContext:
    return NormalizationContext(field_name="field", semantic_type=semantic_type)


# --- CountryNormalizer -------------------------------------------------


@pytest.mark.unit
class TestCountryNormalizer:
    def test_supported_types(self, country_normalizer: CountryNormalizer) -> None:
        assert country_normalizer.supported_types == frozenset({FieldSemanticType.COUNTRY})

    def test_none_and_empty(self, country_normalizer: CountryNormalizer) -> None:
        ctx = _ctx(FieldSemanticType.COUNTRY)
        assert country_normalizer.normalize(None, ctx).original_kind is MissingKind.NULL
        assert country_normalizer.normalize("", ctx).original_kind is MissingKind.EMPTY_STRING

    @pytest.mark.parametrize("value", ["United States", "USA", "US", "U.S.A."])
    def test_us_variants_resolve_to_same_code(
        self, country_normalizer: CountryNormalizer, value: str
    ) -> None:
        ctx = _ctx(FieldSemanticType.COUNTRY)
        result = country_normalizer.normalize(value, ctx)
        assert result.structured["alpha2"] == "US"

    def test_united_kingdom_resolves_cleanly(self, country_normalizer: CountryNormalizer) -> None:
        ctx = _ctx(FieldSemanticType.COUNTRY)
        result = country_normalizer.normalize("United Kingdom", ctx)
        assert result.structured["alpha2"] == "GB"
        assert QualityFlag.AMBIGUOUS_LOCALE not in result.flags

    def test_uk_abbreviation_flagged_as_alias(self, country_normalizer: CountryNormalizer) -> None:
        """Source.txt §33's own worked example: UK vs United Kingdom vs
        Great Britain are not silently treated as identical."""
        ctx = _ctx(FieldSemanticType.COUNTRY)
        result = country_normalizer.normalize("UK", ctx)
        assert result.structured["alpha2"] == "GB"
        assert QualityFlag.AMBIGUOUS_LOCALE in result.flags
        assert result.warnings != []

    def test_great_britain_flagged_as_alias(self, country_normalizer: CountryNormalizer) -> None:
        ctx = _ctx(FieldSemanticType.COUNTRY)
        result = country_normalizer.normalize("Great Britain", ctx)
        assert result.structured["alpha2"] == "GB"
        assert QualityFlag.AMBIGUOUS_LOCALE in result.flags

    def test_unrecognized_country_is_invalid(self, country_normalizer: CountryNormalizer) -> None:
        ctx = _ctx(FieldSemanticType.COUNTRY)
        result = country_normalizer.normalize("Not A Real Country XYZ", ctx)
        assert result.normalization_status is NormalizationStatus.INVALID

    def test_original_never_overwritten(self, country_normalizer: CountryNormalizer) -> None:
        ctx = _ctx(FieldSemanticType.COUNTRY)
        result = country_normalizer.normalize("usa", ctx)
        assert result.original == "usa"


# --- LanguageNormalizer --------------------------------------------------


@pytest.mark.unit
class TestLanguageNormalizer:
    def test_supported_types(self, language_normalizer: LanguageNormalizer) -> None:
        assert language_normalizer.supported_types == frozenset({FieldSemanticType.LANGUAGE})

    @pytest.mark.parametrize("value", ["English", "en", "eng", "EN"])
    def test_english_variants_resolve_to_same_code(
        self, language_normalizer: LanguageNormalizer, value: str
    ) -> None:
        """Source.txt §34's own worked example."""
        ctx = _ctx(FieldSemanticType.LANGUAGE)
        result = language_normalizer.normalize(value, ctx)
        assert result.structured["canonical_code"] == "en"

    def test_source_value_retained(self, language_normalizer: LanguageNormalizer) -> None:
        ctx = _ctx(FieldSemanticType.LANGUAGE)
        result = language_normalizer.normalize("eng", ctx)
        assert result.structured["source_value"] == "eng"
        assert result.structured["canonical_code"] == "en"

    def test_unrecognized_language_is_invalid(
        self, language_normalizer: LanguageNormalizer
    ) -> None:
        ctx = _ctx(FieldSemanticType.LANGUAGE)
        result = language_normalizer.normalize("not a real language", ctx)
        assert result.normalization_status is NormalizationStatus.INVALID


# --- ScriptNormalizer ------------------------------------------------------


@pytest.mark.unit
class TestScriptNormalizer:
    def test_supported_types(self, script_normalizer: ScriptNormalizer) -> None:
        assert script_normalizer.supported_types == frozenset({FieldSemanticType.SCRIPT})

    def test_latin_script_detected(self, script_normalizer: ScriptNormalizer) -> None:
        ctx = _ctx(FieldSemanticType.SCRIPT)
        result = script_normalizer.normalize("Hello world", ctx)
        assert result.structured["script"] == "Latin"

    def test_cyrillic_script_detected(self, script_normalizer: ScriptNormalizer) -> None:
        ctx = _ctx(FieldSemanticType.SCRIPT)
        result = script_normalizer.normalize("Москва", ctx)
        assert result.structured["script"] == "Cyrillic"

    def test_han_script_detected(self, script_normalizer: ScriptNormalizer) -> None:
        ctx = _ctx(FieldSemanticType.SCRIPT)
        result = script_normalizer.normalize("北京市", ctx)
        assert result.structured["script"] == "Han"

    def test_never_transliterates(self, script_normalizer: ScriptNormalizer) -> None:
        """Source.txt §35's explicit prohibition — display/comparison
        stay exactly as the original script, never auto-transliterated."""
        ctx = _ctx(FieldSemanticType.SCRIPT)
        value = "Москва"
        result = script_normalizer.normalize(value, ctx)
        assert result.display == value
        assert result.comparison == value

    def test_language_hint_is_a_hint_not_a_fact(self, script_normalizer: ScriptNormalizer) -> None:
        ctx = _ctx(FieldSemanticType.SCRIPT)
        result = script_normalizer.normalize("Bonjour le monde", ctx)
        assert "language_hint" in result.structured
        assert "language_hint_confidence" in result.structured
        assert 0.0 <= result.structured["language_hint_confidence"] <= 1.0

    def test_digits_and_punctuation_alone_have_no_script(
        self, script_normalizer: ScriptNormalizer
    ) -> None:
        ctx = _ctx(FieldSemanticType.SCRIPT)
        result = script_normalizer.normalize("12345 !@#", ctx)
        assert result.structured["script"] is None

"""Unit tests for CountryNormalizer, LanguageNormalizer, ScriptNormalizer
— Source.txt Phase 10 (§33-§35)."""

from __future__ import annotations

import pytest
from normalizers.country import CountryNormalizer
from normalizers.language import LanguageNormalizer
from normalizers.script import ScriptNormalizer
from normcore.context import NormalizationContext
from normcore.enums import (
    FieldSemanticType,
    MissingKind,
    NormalizationStatus,
    QualityFlag,
    Reversibility,
)


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


@pytest.mark.unit
class TestCountryNormalizerExactFields:
    """A real mutmut run (M12) found 26 surviving mutants in
    `CountryNormalizer.normalize` — the field-by-field checks above
    only ever assert `structured["alpha2"]`/flags, never pin down
    exact `confidence`/`comparison`/`search`/`lossiness`/defaults."""

    def test_missing_none_every_field(self, country_normalizer: CountryNormalizer) -> None:
        result = country_normalizer.normalize(None, _ctx(FieldSemanticType.COUNTRY))
        assert result.original is None
        assert result.original_kind is MissingKind.NULL
        assert result.display is None
        assert result.comparison is None
        assert result.search is None
        assert result.structured == {}
        assert result.validation_status == "MISSING"
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.confidence == 1.0
        assert result.errors == []
        assert result.flags == []
        assert result.warnings == []
        assert result.lossiness is Reversibility.LOSSLESS
        assert result.profile_version == ""
        assert result.env_id == ""
        assert result.trace == []

    def test_missing_empty_every_field(self, country_normalizer: CountryNormalizer) -> None:
        result = country_normalizer.normalize("", _ctx(FieldSemanticType.COUNTRY))
        assert result.original == ""
        assert result.original_kind is MissingKind.EMPTY_STRING
        assert result.validation_status == "MISSING"
        assert result.confidence == 1.0

    def test_unresolved_every_field(self, country_normalizer: CountryNormalizer) -> None:
        result = country_normalizer.normalize(
            "Not A Real Country XYZ", _ctx(FieldSemanticType.COUNTRY)
        )
        assert result.original == "Not A Real Country XYZ"
        assert result.display == "Not A Real Country XYZ"
        assert result.comparison is None
        assert result.search is None
        assert result.structured == {}
        assert result.validation_status == "INVALID"
        assert result.normalization_status is NormalizationStatus.INVALID
        assert result.confidence == 0.0
        assert result.errors == ["not a recognized country name or code"]
        assert result.flags == []
        assert result.warnings == []
        assert result.lossiness is Reversibility.LOSSLESS
        assert result.profile_version == ""
        assert result.env_id == ""
        assert len(result.trace) == 1
        assert result.trace[0].changed is False
        assert result.trace[0].library == "pycountry"

    def test_valid_exact_iso_match_every_field(self, country_normalizer: CountryNormalizer) -> None:
        result = country_normalizer.normalize("United States", _ctx(FieldSemanticType.COUNTRY))
        assert result.original == "United States"
        assert result.display == "United States"
        assert result.comparison == "US"
        assert result.search == "us"
        assert result.structured == {
            "country_name": "United States",
            "alpha2": "US",
            "alpha3": "USA",
            "numeric": "840",
            "original": "United States",
        }
        assert result.validation_status == "VALID"
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.confidence == 1.0
        assert result.errors == []
        assert result.flags == []
        assert result.warnings == []
        assert result.lossiness is Reversibility.PARTIALLY_REVERSIBLE
        assert result.profile_version == ""
        assert result.env_id == ""
        assert len(result.trace) == 1
        assert result.trace[0].changed is True
        assert result.trace[0].library == "pycountry"

    def test_via_non_iso_alias_confidence_and_fields(
        self, country_normalizer: CountryNormalizer
    ) -> None:
        """The non-ISO-alias branch: confidence drops to exactly 0.85,
        not just <1.0."""
        result = country_normalizer.normalize("UK", _ctx(FieldSemanticType.COUNTRY))
        assert result.confidence == 0.85
        assert result.display == "United Kingdom"
        assert result.comparison == "GB"
        assert result.search == "gb"
        assert result.warnings == [
            "'UK' is a common but non-ISO abbreviation, resolved to "
            "GB (United Kingdom) via an alias table, not an exact code match."
        ]


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

    def test_missing_none_every_field(self, language_normalizer: LanguageNormalizer) -> None:
        result = language_normalizer.normalize(None, _ctx(FieldSemanticType.LANGUAGE))
        assert result.original is None
        assert result.original_kind is MissingKind.NULL
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.validation_status == "MISSING"
        assert result.confidence == 1.0
        assert result.display is None
        assert result.profile_version == ""
        assert result.env_id == ""

    def test_missing_empty_every_field(self, language_normalizer: LanguageNormalizer) -> None:
        result = language_normalizer.normalize("", _ctx(FieldSemanticType.LANGUAGE))
        assert result.original == ""
        assert result.original_kind is MissingKind.EMPTY_STRING
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.validation_status == "MISSING"
        assert result.confidence == 1.0

    def test_resolved_language_every_field(self, language_normalizer: LanguageNormalizer) -> None:
        """A real mutmut run (M12) found 33 surviving mutants in
        `LanguageNormalizer.normalize` — mostly literal constants
        (`1.0`, `""` defaults, `lossiness`) never pinned down exactly by
        the checks above."""
        result = language_normalizer.normalize("eng", _ctx(FieldSemanticType.LANGUAGE))
        assert result.original == "eng"
        assert result.display == "English"
        assert result.comparison == "en"
        assert result.search == "en"
        assert result.structured == {
            "source_value": "eng",
            "canonical_code": "en",
            "language_name": "English",
        }
        assert result.validation_status == "VALID"
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.confidence == 1.0
        assert result.errors == []
        assert result.lossiness is Reversibility.PARTIALLY_REVERSIBLE
        assert result.profile_version == ""
        assert result.env_id == ""
        assert len(result.trace) == 1
        assert result.trace[0].changed is True
        assert result.trace[0].library == "pycountry"

    def test_alpha3_only_language_falls_back_correctly(
        self, language_normalizer: LanguageNormalizer
    ) -> None:
        """`canonical_code` is `getattr(language, "alpha_2", None) or
        language.alpha_3` — a real language with no alpha_2 code
        (verified live against pycountry's own dataset) must fall
        through to alpha_3, not error or produce `None`."""
        result = language_normalizer.normalize("aaa", _ctx(FieldSemanticType.LANGUAGE))
        assert result.display == "Ghotuo"
        assert result.structured["canonical_code"] == "aaa"
        assert result.comparison == "aaa"

    def test_unresolved_language_every_field(self, language_normalizer: LanguageNormalizer) -> None:
        result = language_normalizer.normalize(
            "not a real language", _ctx(FieldSemanticType.LANGUAGE)
        )
        assert result.original == "not a real language"
        assert result.display == "not a real language"
        assert result.comparison is None
        assert result.search is None
        assert result.structured == {}
        assert result.validation_status == "INVALID"
        assert result.normalization_status is NormalizationStatus.INVALID
        assert result.confidence == 0.0
        assert result.errors == ["not a recognized language name or code"]
        assert result.lossiness is Reversibility.LOSSLESS
        assert len(result.trace) == 1
        assert result.trace[0].changed is False
        assert result.profile_version == ""
        assert result.env_id == ""


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

    def test_missing_none_every_field(self, script_normalizer: ScriptNormalizer) -> None:
        result = script_normalizer.normalize(None, _ctx(FieldSemanticType.SCRIPT))
        assert result.original is None
        assert result.original_kind is MissingKind.NULL
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.validation_status == "MISSING"
        assert result.confidence == 1.0
        assert result.display is None
        assert result.profile_version == ""
        assert result.env_id == ""

    def test_missing_empty_every_field(self, script_normalizer: ScriptNormalizer) -> None:
        result = script_normalizer.normalize("", _ctx(FieldSemanticType.SCRIPT))
        assert result.original == ""
        assert result.original_kind is MissingKind.EMPTY_STRING
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.validation_status == "MISSING"
        assert result.confidence == 1.0

    def test_no_script_every_field(self, script_normalizer: ScriptNormalizer) -> None:
        """A real mutmut run (M12) found 33 surviving mutants in
        `ScriptNormalizer.normalize` — mostly literal constants
        (`0.0`, `""` defaults, `lossiness`, the `VALID`/`UNKNOWN`
        ternary) never pinned down exactly by the checks above."""
        result = script_normalizer.normalize("12345 !@#", _ctx(FieldSemanticType.SCRIPT))
        assert result.original == "12345 !@#"
        assert result.display == "12345 !@#"
        assert result.comparison == "12345 !@#"
        assert result.search == "12345 !@#"
        assert result.structured == {
            "script": None,
            "script_confidence": 0.0,
            "language_hint": None,
            "language_hint_confidence": 0.0,
        }
        assert result.validation_status == "UNKNOWN"
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.confidence == 0.0
        assert result.errors == []
        assert result.lossiness is Reversibility.LOSSLESS
        assert result.profile_version == ""
        assert result.env_id == ""
        assert len(result.trace) == 1
        assert result.trace[0].changed is False
        assert result.trace[0].library == "PyICU/lingua"

    def test_detected_script_every_field(self, script_normalizer: ScriptNormalizer) -> None:
        result = script_normalizer.normalize("Hello", _ctx(FieldSemanticType.SCRIPT))
        assert result.original == "Hello"
        assert result.display == "Hello"
        assert result.comparison == "Hello"
        assert result.search == "Hello"
        assert result.structured["script"] == "Latin"
        assert result.structured["script_confidence"] == 1.0
        assert result.validation_status == "VALID"
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.confidence == 1.0
        assert result.errors == []
        assert result.lossiness is Reversibility.LOSSLESS
        assert result.profile_version == ""
        assert result.env_id == ""
        assert len(result.trace) == 1
        assert result.trace[0].changed is False

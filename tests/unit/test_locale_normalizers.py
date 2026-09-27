"""Unit tests for CountryNormalizer, LanguageNormalizer, ScriptNormalizer
— Source.txt Phase 10 (§33-§35)."""

from __future__ import annotations

import importlib.util
import pathlib

import pytest
from normalizers.country import CountryNormalizer
from normalizers.country_codes import resolve_country_alpha2
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


@pytest.mark.unit
class TestEmpiricalCountryAliases:
    """Every alias here was found by running a real 1.76M-row CountryCode
    column through the normalizer, not chosen speculatively — the module
    docstring asks for exactly that. Most are ISO renames that pycountry
    no longer resolves under the old name."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("Turkey", "TR"),  # ISO renamed it Türkiye in 2022
            ("Turkiye", "TR"),
            ("Macedonia, the Former Yugoslav Republic of", "MK"),  # renamed 2019
            ("Macedonia", "MK"),
            ("Russia", "RU"),
            ("US Virgin Islands", "VI"),
            ("U.S. Virgin Islands", "VI"),  # via the dotless alias retry
            ("Democratic Republic of the Congo", "CD"),
            ("Cape Verde", "CV"),  # renamed Cabo Verde
            ("Swaziland", "SZ"),  # renamed Eswatini 2018
            ("The Bahamas", "BS"),
            ("Ivory Coast", "CI"),
            ("Bosnia and Herzegowina", "BA"),  # misspelling seen in the data
        ],
    )
    def test_renamed_and_common_names_resolve(self, value: str, expected: str) -> None:
        assert resolve_country_alpha2(value) == expected

    def test_the_two_congos_stay_distinct(self) -> None:
        # The most dangerous possible mistake in this table: CD is
        # Kinshasa, CG is Brazzaville. The DRC alias must not shadow the
        # Republic of the Congo, which pycountry resolves on its own.
        assert resolve_country_alpha2("Democratic Republic of the Congo") == "CD"
        assert resolve_country_alpha2("Republic of the Congo") == "CG"

    def test_diacritic_spelling_still_resolves_without_an_alias(self) -> None:
        # "Türkiye" already resolves via pycountry, so it is deliberately
        # NOT in the alias table — a dead alias is worse than none.
        assert resolve_country_alpha2("Türkiye") == "TR"

    @pytest.mark.parametrize("value", ["Kosovo", "Virgin Islands", "Oo", "Moscow", "122006"])
    def test_genuinely_unresolvable_values_stay_unresolved(self, value: str) -> None:
        # Kosovo has no ISO 3166-1 code; a bare "Virgin Islands" is
        # ambiguous (US=VI, British=VG); the rest are real values from the
        # column that simply are not countries. Guessing here would be
        # worse than returning None.
        assert resolve_country_alpha2(value) is None


@pytest.mark.unit
class TestCldrCountryResolution:
    """CLDR replaced nine hand-curated aliases and added endonyms. The
    hand table used to grow one empirically-found name at a time; these
    cases all resolve from authoritative data instead.
    """

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            # Endonyms — a country's name in its own language.
            ("Deutschland", "DE"),
            ("日本", "JP"),
            ("россия", "RU"),
            ("España", "ES"),
            # Exonyms from other major languages.
            ("Allemagne", "DE"),
            ("Alemania", "DE"),
            # ISO renames, previously hand-listed.
            ("Turkey", "TR"),
            ("Türkiye", "TR"),
            ("Swaziland", "SZ"),
            ("Cape Verde", "CV"),
            ("Ivory Coast", "CI"),
            ("Burma", "MM"),
            # Colloquial names CLDR does carry.
            ("Holland", "NL"),
            ("England", "GB"),
            ("America", "US"),
        ],
    )
    def test_cldr_names_resolve(self, value: str, expected: str) -> None:
        assert resolve_country_alpha2(value) == expected

    @pytest.mark.parametrize(
        ("value", "expected"),
        [("ZR", "CD"), ("BU", "MM"), ("TP", "TL"), ("DD", "DE"), ("UK", "GB")],
    )
    def test_retired_codes_resolve_to_their_single_successor(
        self, value: str, expected: str
    ) -> None:
        assert resolve_country_alpha2(value) == expected

    @pytest.mark.parametrize("value", ["SU", "YU", "AN", "CS"])
    def test_retired_codes_with_several_successors_stay_unresolved(self, value: str) -> None:
        """ "SU" is 15 states and "YU" is two — picking one would be a
        guess, which this module never makes."""
        assert resolve_country_alpha2(value) is None

    def test_uk_variants_all_agree_regardless_of_case(self) -> None:
        variants = [
            "GB",
            "gb",
            "UK",
            "uk",
            "U.K.",
            "united kingdom",
            "UNITED KINGDOM",
            "Great Britain",
            "GBR",
            "England",
        ]
        assert {resolve_country_alpha2(v) for v in variants} == {"GB"}

    @pytest.mark.parametrize(
        "value",
        [
            "Kosovo",  # XK is user-assigned, not ISO 3166-1
            "European Union",  # an organization, not a country
            "Eurozone",
            "United Nations",
            "Unknown Region",  # CLDR's ZZ
            "Outlying Oceania",  # CLDR's QO macro-region
        ],
    )
    def test_non_iso_territories_do_not_resolve(self, value: str) -> None:
        """CLDR's territory list is wider than ISO 3166-1. Anything ISO
        does not list must not leak out of a function that promises an
        ISO 3166-1 alpha-2 code."""
        assert resolve_country_alpha2(value) is None

    def test_iso_standard_wins_over_cldr_on_conflict(self) -> None:
        """ "nga" is Nigeria's ISO alpha-3 AND some locale's CLDR name for
        Russia. pycountry is consulted first precisely so the standard
        wins; this is the only such collision in the data."""
        assert resolve_country_alpha2("nga") == "NG"


@pytest.mark.unit
class TestGeneratedCldrTablesAreCurrent:
    """The country, currency and language tables are generated from
    Babel's CLDR data, so they can drift from the installed Babel.

    This FAILS on a mismatch rather than skipping. It used to skip when
    `babel.__version__` differed from the version stamped in the generated
    file, which sounded lenient and was actually the worst outcome: a
    Babel bump silently disabled the only check that the 3MB of shipped
    lookup data still matches its source, and a stale table is
    confidently wrong. Fixing a failure is one command:

        python scripts/generate_cldr_names.py
    """

    @staticmethod
    def _rebuild() -> dict[str, dict[str, str]]:
        """Rebuilt once for the whole class — the walk over ~1080 CLDR
        locales is the expensive part, and all four tables come from it."""
        spec = importlib.util.spec_from_file_location(
            "_gen",
            pathlib.Path(__file__).resolve().parents[2] / "scripts" / "generate_cldr_names.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        built: dict[str, dict[str, str]] = module.build()
        return built

    @pytest.fixture(scope="class")
    def rebuilt(self) -> dict[str, dict[str, str]]:
        return self._rebuild()

    def test_country_names(self, rebuilt: dict[str, dict[str, str]]) -> None:
        from normalizers._cldr_country_names import CLDR_COUNTRY_NAMES

        assert rebuilt["CLDR_COUNTRY_NAMES"] == CLDR_COUNTRY_NAMES

    def test_currency_names_and_symbols(self, rebuilt: dict[str, dict[str, str]]) -> None:
        from normalizers._cldr_currency_names import (
            CLDR_CURRENCY_NAMES,
            CLDR_CURRENCY_SYMBOLS,
        )

        assert rebuilt["CLDR_CURRENCY_NAMES"] == CLDR_CURRENCY_NAMES
        assert rebuilt["CLDR_CURRENCY_SYMBOLS"] == CLDR_CURRENCY_SYMBOLS

    def test_language_names(self, rebuilt: dict[str, dict[str, str]]) -> None:
        from normalizers._cldr_language_names import CLDR_LANGUAGE_NAMES

        assert rebuilt["CLDR_LANGUAGE_NAMES"] == CLDR_LANGUAGE_NAMES

    def test_stamped_babel_version_matches_installed(self) -> None:
        """A drift the data comparison above cannot see: the tables can
        agree with a NEWER Babel by luck (a release that changed no name
        this filter keeps), while the header still claims the older one.
        The header is the only record of which CLDR release the shipped
        data came from, so it must not go stale unnoticed."""
        import babel
        from normalizers._cldr_country_names import BABEL_VERSION

        assert babel.__version__ == BABEL_VERSION, (
            f"tables stamped Babel {BABEL_VERSION}, installed {babel.__version__} — "
            "run python scripts/generate_cldr_names.py"
        )


@pytest.mark.unit
class TestLanguageTagParsing:
    """Every BCP 47 tag used to come back INVALID — pycountry knows only
    bare ISO 639 codes and names, but "en-US" is one of the commonest
    real-world spellings of a language."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("en-US", "en"),
            ("en_GB", "en"),
            ("EN-us", "en"),
            ("fr_FR", "fr"),
            ("pt-BR", "pt"),
            ("zh-Hans-CN", "zh"),
            ("zh-Hant", "zh"),
            ("sr-Latn", "sr"),
            ("es-419", "es"),
            ("de-DE-1901", "de"),
        ],
    )
    def test_tags_resolve_to_their_language_subtag(self, value: str, expected: str) -> None:
        result = LanguageNormalizer().normalize(value, _ctx(FieldSemanticType.LANGUAGE))
        assert result.comparison == expected

    def test_plain_codes_and_names_are_unaffected(self) -> None:
        normalizer = LanguageNormalizer()
        assert {
            normalizer.normalize(v, _ctx(FieldSemanticType.LANGUAGE)).comparison
            for v in ("en", "eng", "English")
        } == {"en"}

    def test_tag_components_are_recorded_not_discarded(self) -> None:
        """Collapsing en-US and en-GB to "en" is the point, but the
        region must stay inspectable rather than vanish."""
        result = LanguageNormalizer().normalize("zh-Hans-CN", _ctx(FieldSemanticType.LANGUAGE))
        assert result.structured["tag_script"] == "Hans"
        assert result.structured["tag_territory"] == "CN"

    @pytest.mark.parametrize(
        ("value", "expected"), [("iw", "he"), ("in", "id"), ("ji", "yi"), ("mo", "ro")]
    )
    def test_deprecated_subtags_resolve(self, value: str, expected: str) -> None:
        result = LanguageNormalizer().normalize(value, _ctx(FieldSemanticType.LANGUAGE))
        assert result.comparison == expected

    def test_deprecated_subtag_is_consistent_tagged_or_bare(self) -> None:
        normalizer = LanguageNormalizer()
        assert (
            normalizer.normalize("iw", _ctx(FieldSemanticType.LANGUAGE)).comparison
            == normalizer.normalize("iw-IL", _ctx(FieldSemanticType.LANGUAGE)).comparison
            == "he"
        )

    def test_live_pycountry_code_keeps_its_own_answer(self) -> None:
        """ "sh" is still a pycountry entry, so the ISO answer wins over
        CLDR's "sr_Latn" alias — same authority order as COUNTRY."""
        result = LanguageNormalizer().normalize("sh", _ctx(FieldSemanticType.LANGUAGE))
        assert result.comparison == "sh"

    @pytest.mark.parametrize("value", ["xx-YY", "not a language", "zzz"])
    def test_unparseable_stays_invalid(self, value: str) -> None:
        result = LanguageNormalizer().normalize(value, _ctx(FieldSemanticType.LANGUAGE))
        assert result.normalization_status is NormalizationStatus.INVALID


@pytest.mark.unit
class TestLanguageEndonyms:
    """A language written in its OWN language used to come back INVALID:
    pycountry knows English names only, and `Deutsch`, `Français`,
    `español` and `日本語` are the second-commonest real-world spelling of
    a language after the bare code. CLDR (`_cldr_language_names`) supplies
    53.3k of them."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("Deutsch", "de"),
            ("Français", "fr"),
            ("español", "es"),
            ("日本語", "ja"),
            ("中文", "zh"),  # two characters — the short-name filter is Latin-only
            ("русский", "ru"),
            ("العربية", "ar"),
            ("português", "pt"),
            ("Nederlands", "nl"),
            ("svenska", "sv"),
            ("türkçe", "tr"),
            ("한국어", "ko"),
            ("polski", "pl"),
            ("allemand", "de"),  # a translated name, not only the endonym
            ("tedesco", "de"),
        ],
    )
    def test_endonyms_and_translated_names_resolve(
        self, language_normalizer: LanguageNormalizer, value: str, expected: str
    ) -> None:
        ctx = NormalizationContext(field_name="lang", semantic_type=FieldSemanticType.LANGUAGE)
        result = language_normalizer.normalize(value, ctx)
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.structured["canonical_code"] == expected

    @pytest.mark.parametrize("value", ["xx", "qa", "zzz", "not a language", "12345", "ci"])
    def test_junk_still_invalid(self, language_normalizer: LanguageNormalizer, value: str) -> None:
        """Two-letter Latin CLDR names are excluded at generation time, so
        a 53k-entry table cannot start answering for code-shaped junk —
        ISO 639-1 is pycountry's to own."""
        ctx = NormalizationContext(field_name="lang", semantic_type=FieldSemanticType.LANGUAGE)
        assert (
            language_normalizer.normalize(value, ctx).normalization_status
            is NormalizationStatus.INVALID
        )

    def test_pycountry_still_wins(self, language_normalizer: LanguageNormalizer) -> None:
        """CLDR is consulted last. `lookup()` resolving a name must keep
        its own answer, and the tag path must be unaffected."""
        ctx = NormalizationContext(field_name="lang", semantic_type=FieldSemanticType.LANGUAGE)
        for value, expected in (("English", "en"), ("en", "en"), ("eng", "en"), ("en-US", "en")):
            result = language_normalizer.normalize(value, ctx)
            assert result.structured["canonical_code"] == expected, value


@pytest.mark.unit
class TestUkConstituentCountries:
    """None of the four has an ISO 3166-1 code — they are ISO 3166-2
    subdivisions of GB — yet all four appear in real country columns."""

    @pytest.mark.parametrize(
        "value",
        ["England", "Scotland", "Wales", "Northern Ireland", "SCOTLAND", "  wales  "],
    )
    def test_all_four_resolve_to_gb(self, value: str) -> None:
        assert resolve_country_alpha2(value) == "GB"

    @pytest.mark.parametrize("value", ["Texas", "Bavaria", "Ontario", "Queensland"])
    def test_other_iso_3166_2_subdivisions_do_not_resolve(self, value: str) -> None:
        """The four above are hand-listed precisely so this stays true: a
        general `pycountry.subdivisions` fallback would resolve all of
        these too, which is a much larger claim than normalizing a country
        field. A state is not a country."""
        assert resolve_country_alpha2(value) is None


@pytest.mark.unit
class TestSeparatorsAtTheEdgesOfALookupValue:
    """`/türkiye` and `, , , , United Kingdom` are a country name wrapped in
    the packaging of whatever produced the cell. Both were found in real
    columns and neither resolved.

    The rule is EDGES ONLY: an interior separator is genuinely ambiguous, so
    `US, GB` must stay unresolved rather than become a guess about which one
    was meant.
    """

    @pytest.mark.parametrize(
        ("raw", "alpha2"),
        [
            ("/türkiye", "TR"),
            ("/turkey", "TR"),
            (", , , , United Kingdom", "GB"),
            ("United Kingdom,", "GB"),
            ("/united states", "US"),
            ("|DE|", "DE"),
        ],
    )
    def test_a_wrapped_country_name_resolves(self, raw: str, alpha2: str) -> None:
        assert resolve_country_alpha2(raw) == alpha2

    @pytest.mark.parametrize("raw", ["US, GB", "France / Germany", "-", ", , ,"])
    def test_an_interior_separator_is_still_ambiguous(self, raw: str) -> None:
        assert resolve_country_alpha2(raw) is None

    @pytest.mark.parametrize(
        ("raw", "alpha2"),
        [("U.S.", "US"), ("U.K.", "GB"), ("Guinea-Bissau", "GW"), ("Timor-Leste", "TL")],
    )
    def test_separators_that_are_part_of_the_name_survive(self, raw: str, alpha2: str) -> None:
        """ "." and "-" are deliberately NOT in the stripped set."""
        assert resolve_country_alpha2(raw) == alpha2

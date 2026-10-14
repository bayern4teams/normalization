"""Reproducers for the confident-wrong normalizer findings in
docs/plans/defects/PART1_TRACEABILITY.md (N1-N10): a guess shown as an
answer, or a refusal where the input states the answer. One class per
finding; each failed on main (002eda0) before its fix.
"""

from __future__ import annotations

import unicodedata
from collections import Counter
from typing import Any

import pytest
from babel import Locale
from hypothesis import given, settings
from hypothesis import strategies as st
from normapi.app import build_dispatcher
from normapi.scaffold_profile import SCAFFOLD_PROFILE
from normcore.context import NormalizationContext
from normcore.dispatch import NEGATIVE_CONTROL
from normcore.enums import FieldSemanticType, NormalizationStatus

from normanalysis import type_detection

pytestmark = pytest.mark.unit

_DISPATCHER = build_dispatcher(env_id="test-confident-wrong")
_CLEAN = {NormalizationStatus.NORMALIZED, NormalizationStatus.PARSED}


def _norm(semantic_type: FieldSemanticType, value: str | None, **context: Any) -> Any:
    ctx = NormalizationContext(field_name="f", semantic_type=semantic_type, **context)
    return _DISPATCHER.normalize(value, semantic_type, ctx, SCAFFOLD_PROFILE)


def _cldr_order(locale: str) -> str | None:
    pattern = Locale.parse(locale).date_formats["short"].pattern
    d, m, y = (pattern.find(c) for c in "dMy")
    if y < min(d, m):
        return None
    return "DMY" if d < m else "MDY"


class TestDayMonthOrderFromCldr:
    """N4: the order came from a hand table `{"US"}`; CLDR has many M/d/y
    locales, so `10/7/2026` in ee-GH was read as 10 July."""

    @pytest.mark.parametrize("locale", ["ee-GH", "en-PH", "en-US", "en-GB", "de-DE", "fr-FR"])
    def test_locale_with_region_follows_its_cldr_short_pattern(self, locale: str) -> None:
        order = _cldr_order(locale.replace("-", "_"))
        r = _norm(FieldSemanticType.DATE, "10/7/2026", locale=locale)
        assert r.normalization_status in _CLEAN
        assert r.display == ("2026-10-07" if order == "MDY" else "2026-07-10")

    def test_country_whose_languages_disagree_is_not_guessed(self) -> None:
        # Canada's CLDR short dates are year-first in both official
        # languages: neither states a day/month order for `03/04/2024`.
        r = _norm(FieldSemanticType.DATE, "03/04/2024", country="CA")
        assert r.normalization_status is NormalizationStatus.AMBIGUOUS

    def test_country_follows_its_languages(self) -> None:
        assert _norm(FieldSemanticType.DATE, "03/04/2024", country="PH").display == "2024-03-04"
        assert _norm(FieldSemanticType.DATE, "03/04/2024", country="DE").display == "2024-04-03"
        assert _norm(FieldSemanticType.DATE, "03/04/2024", country="US").display == "2024-03-04"

    def test_locale_without_region_stays_unresolved(self) -> None:
        r = _norm(FieldSemanticType.DATE, "03/04/2024", locale="en")
        assert r.normalization_status is NormalizationStatus.AMBIGUOUS


class TestBothReadingsAgree:
    """N9: `05/05/2024` is the same date in either order."""

    @pytest.mark.parametrize("value", ["05/05/2024", "08.08.2014", "1-1-2020"])
    def test_equal_day_and_month_is_not_ambiguous(self, value: str) -> None:
        r = _norm(FieldSemanticType.DATE, value)
        assert r.normalization_status in _CLEAN
        day, month, year = value.replace(".", "/").replace("-", "/").split("/")
        assert r.display == f"{int(year):04d}-{int(month):02d}-{int(day):02d}"

    def test_different_day_and_month_still_ambiguous(self) -> None:
        r = _norm(FieldSemanticType.DATE, "05/06/2024")
        assert r.normalization_status is NormalizationStatus.AMBIGUOUS


class TestDatetimeKeepsItsTime:
    """N1: `3pm March 15 2024` lost its time in a DATETIME column."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("3pm March 15 2024", "2024-03-15T15:00:00"),
            ("4 pm March 15 2024", "2024-03-15T16:00:00"),
            ("March 15 2024 11:30 am", "2024-03-15T11:30:00"),
            ("15 March 2024 23:05", "2024-03-15T23:05:00"),
        ],
    )
    def test_stated_time_is_kept(self, value: str, expected: str) -> None:
        r = _norm(FieldSemanticType.DATETIME, value)
        assert r.normalization_status in _CLEAN
        assert r.display == expected

    def test_date_column_still_truncates(self) -> None:
        assert _norm(FieldSemanticType.DATE, "3pm March 15 2024").display == "2024-03-15"

    def test_no_time_stated_none_invented(self) -> None:
        assert _norm(FieldSemanticType.DATETIME, "March 15 2024").display == "2024-03-15"


class TestFourDigitsInADatetimeColumn:
    """N2: OnTime's WheelsOn (HHMM) `2220` became the year 2220. ISO 8601
    reads four digits as a year (YYYY) and as a basic-format time (hhmm)."""

    @pytest.mark.parametrize("value", ["2220", "1230", "0005"])
    def test_valid_hhmm_is_ambiguous(self, value: str) -> None:
        r = _norm(FieldSemanticType.DATETIME, value, country="US")
        assert r.normalization_status is NormalizationStatus.AMBIGUOUS
        assert r.display == value

    @pytest.mark.parametrize("value", ["1999", "1960", "2460"])
    def test_not_a_time_stays_a_year(self, value: str) -> None:
        # `2024` is also 20:24, so it is ambiguous here; these are no time.
        r = _norm(FieldSemanticType.DATETIME, value)
        assert r.normalization_status in _CLEAN
        assert r.display == value

    def test_date_column_keeps_the_year(self) -> None:
        r = _norm(FieldSemanticType.DATE, "2220")
        assert r.normalization_status in _CLEAN
        assert r.display == "2220"


class TestTwoNumbersNoYear:
    """N10: `24/03` became 2024-03, though 24 March with no year is as
    plausible."""

    @pytest.mark.parametrize("value", ["24/03", "03/24", "12/11"])
    def test_day_month_or_month_year_is_ambiguous(self, value: str) -> None:
        r = _norm(FieldSemanticType.DATE, value)
        assert r.normalization_status is NormalizationStatus.AMBIGUOUS

    @pytest.mark.parametrize(("value", "expected"), [("03/2024", "2024-03"), ("1/00", "2000-01")])
    def test_month_year_with_no_day_reading_still_parses(self, value: str, expected: str) -> None:
        r = _norm(FieldSemanticType.DATE, value, country="US")
        assert r.normalization_status in _CLEAN
        assert r.display == expected


class TestBareHostSchemeNotGuessed:
    """N3: `example.com` became `https://example.com` at 0.8; the input states
    no scheme, so http and https are both readings."""

    @pytest.mark.parametrize("value", ["example.com", "www.example.co.uk/path"])
    def test_bare_host_is_ambiguous_with_both_schemes(self, value: str) -> None:
        r = _norm(FieldSemanticType.URL, value)
        assert r.normalization_status is NormalizationStatus.AMBIGUOUS
        assert r.display == value
        assert r.comparison is None
        assert {c["scheme"] for c in r.structured["candidates"]} == {"http", "https"}

    def test_what_the_host_states_is_still_reported(self) -> None:
        r = _norm(FieldSemanticType.URL, "www.example.co.uk/path")
        assert r.structured["registrable_domain"] == "example.co.uk"

    def test_stated_scheme_unchanged(self) -> None:
        r = _norm(FieldSemanticType.URL, "http://Example.com/")
        assert r.normalization_status is NormalizationStatus.NORMALIZED
        assert r.display == "http://example.com/"


class TestMissingTokenThatIsAlsoAValue:
    """N5: `NA` in a COUNTRY column was read as NOT_APPLICABLE, though it is
    also Namibia's ISO code. A token in the missing-value table is AMBIGUOUS
    when a type that can say no (it rejects a negative control) reads it as
    a value; free-text types, which accept anything, prove nothing."""

    @pytest.mark.parametrize(("value", "reading"), [("NA", "Namibia"), ("n.a.", "Namibia")])
    def test_country_code_and_missing_token_is_ambiguous(self, value: str, reading: str) -> None:
        r = _norm(FieldSemanticType.COUNTRY, value)
        assert r.normalization_status is NormalizationStatus.AMBIGUOUS
        assert r.display == value
        readings = [c.get("display") for c in r.structured["candidates"]]
        assert reading in readings
        assert any(c["interpretation"] == "missing" for c in r.structured["candidates"])

    def test_language_code_too(self) -> None:
        r = _norm(FieldSemanticType.LANGUAGE, "na")
        assert r.normalization_status is NormalizationStatus.AMBIGUOUS

    @pytest.mark.parametrize(
        "semantic_type",
        [FieldSemanticType.COMPANY_NAME, FieldSemanticType.IDENTIFIER, FieldSemanticType.CODE],
    )
    def test_types_that_accept_anything_keep_the_token_missing(
        self, semantic_type: FieldSemanticType
    ) -> None:
        r = _norm(semantic_type, "N/A")
        assert r.validation_status == "MISSING"
        assert r.display is None

    def test_token_no_type_reads_stays_missing(self) -> None:
        r = _norm(FieldSemanticType.COUNTRY, "N/A")
        assert r.validation_status == "MISSING"

    def test_one_negative_control_for_detection_and_dispatch(self) -> None:
        assert NEGATIVE_CONTROL == type_detection._NEGATIVE_CONTROL


class TestTextThatNamesNoPhoneOrCurrency:
    """N7: PHONE and CURRENCY answered AMBIGUOUS for any text, so `TBD` or
    `unknown` (not in the missing-value table) was indistinguishable from a
    number without a region or a `$` without a country."""

    @pytest.mark.parametrize("value", ["TBD", "pending", "x", "tel:"])
    def test_phone_text_that_is_no_number_is_invalid(self, value: str) -> None:
        assert _norm(FieldSemanticType.PHONE, value).normalization_status is (
            NormalizationStatus.INVALID
        )
        assert _norm(FieldSemanticType.PHONE, value, country="US").normalization_status is (
            NormalizationStatus.INVALID
        )

    def test_phone_without_region_still_ambiguous(self) -> None:
        r = _norm(FieldSemanticType.PHONE, "(201) 555-0123")
        assert r.normalization_status is NormalizationStatus.AMBIGUOUS

    @pytest.mark.parametrize("value", ["TBD", "dollars please", "ZZZ"])
    def test_currency_text_that_names_none_is_invalid(self, value: str) -> None:
        r = _norm(FieldSemanticType.CURRENCY, value)
        assert r.normalization_status is NormalizationStatus.INVALID

    @pytest.mark.parametrize(("value", "member"), [("$", "USD"), ("kr", "SEK"), ("¥", "JPY")])
    def test_shared_symbol_is_ambiguous_with_its_cldr_codes(self, value: str, member: str) -> None:
        r = _norm(FieldSemanticType.CURRENCY, value)
        assert r.normalization_status is NormalizationStatus.AMBIGUOUS
        assert member in r.structured["candidates"]

    @pytest.mark.parametrize(
        ("value", "country", "code"),
        [
            ("$", "US", "USD"),
            ("$", "AU", "AUD"),
            ("¥", "JP", "JPY"),
            ("¥", "CN", "CNY"),
            ("£", "GB", "GBP"),
        ],
    )
    def test_shared_symbol_resolves_by_the_countrys_cldr_tender(
        self, value: str, country: str, code: str
    ) -> None:
        r = _norm(FieldSemanticType.CURRENCY, value, country=country)
        assert r.normalization_status is NormalizationStatus.NORMALIZED
        assert r.display == code

    def test_euro_sign_needs_no_context(self) -> None:
        assert _norm(FieldSemanticType.CURRENCY, "€").display == "EUR"


# Characters the two properties below are built from: invisible and control
# characters normalizers drop, missing-value tokens' punctuation, combining
# marks, and letters and digits from several scripts.
_TRICKY = "\x00\x7f\xad\u200b\u200d\ufeff\u0301\u00a0\u2028\x85\t'-.,&/()@ "
_LETTERS = "aBxyzÄöüßéñçøåłşğ\u0131İžčřДЖЯжяمحمد中文한국あア019"
_TEXT_TYPES = [
    FieldSemanticType.PERSON_NAME,
    FieldSemanticType.GIVEN_NAME,
    FieldSemanticType.FAMILY_NAME,
    FieldSemanticType.COMPANY_NAME,
    FieldSemanticType.FREE_TEXT,
    FieldSemanticType.IDENTIFIER,
    FieldSemanticType.TAX_ID,
    FieldSemanticType.CODE,
]
_REFUSED = {
    NormalizationStatus.AMBIGUOUS,
    NormalizationStatus.INVALID,
    NormalizationStatus.FAILED,
    NormalizationStatus.NEEDS_REVIEW,
}


def _letters_and_digits(text: str) -> Counter[str]:
    """Case-, width- and mark-insensitive: dotless i->`I` or `ß`->`SS` is case
    mapping and a re-attached accent is not a lost letter."""
    folded = unicodedata.normalize("NFKD", text.upper()).casefold()
    return Counter(c for c in folded if unicodedata.category(c)[0] in "LN")


class TestOnePassAndNoSilentDrops:
    """N8: COMPANY_NAME / PERSON_NAME did not converge in one pass (`-\\x00` ->
    `-` -> missing). Properties over every type; ADDRESS needs libpostal."""

    @pytest.mark.parametrize(
        "semantic_type",
        [t for t in FieldSemanticType if t not in (FieldSemanticType.ADDRESS,)],
        ids=lambda t: t.value,
    )
    @settings(max_examples=150, derandomize=True, deadline=None)
    @given(value=st.text(alphabet=_TRICKY + "aB1", max_size=6))
    def test_every_type_converges_in_one_pass(
        self, semantic_type: FieldSemanticType, value: str
    ) -> None:
        first = _norm(semantic_type, value, country="US", locale="en-US")
        if first.display is None:
            return
        second = _norm(semantic_type, first.display, country="US", locale="en-US")
        assert second.display == first.display, (value, first.display, second.display)

    @pytest.mark.parametrize("semantic_type", _TEXT_TYPES, ids=lambda t: t.value)
    @settings(max_examples=300, derandomize=True, deadline=None)
    @given(value=st.text(alphabet=_TRICKY + _LETTERS, min_size=1, max_size=14))
    def test_no_letter_or_digit_silently_dropped(
        self, semantic_type: FieldSemanticType, value: str
    ) -> None:
        """Siblings that keep the text (names, company, identifiers, free
        text): a confident answer holds every letter and digit of its input."""
        r = _norm(semantic_type, value, country="US", locale="en-US")
        if r.normalization_status in _REFUSED | {NormalizationStatus.REPAIRED} or r.display is None:
            return
        assert not (_letters_and_digits(value) - _letters_and_digits(r.display)), (
            value,
            r.display,
        )

    @pytest.mark.parametrize(
        "semantic_type",
        [
            FieldSemanticType.PERSON_NAME,
            FieldSemanticType.GIVEN_NAME,
            FieldSemanticType.FAMILY_NAME,
            FieldSemanticType.COMPANY_NAME,
            FieldSemanticType.FREE_TEXT,
        ],
        ids=lambda t: t.value,
    )
    # `ab\x00c`: N6. A clone cannot carry NUL into a Postgres column (Postgres
    # sources hold none, cross-engine clones are refused); the remaining case
    # was this silent drop in the text siblings.
    @pytest.mark.parametrize("value", ["CafÃ©", "ß\x85", "ab\x00c"])
    def test_text_repair_is_disclosed_by_every_sibling(
        self, semantic_type: FieldSemanticType, value: str
    ) -> None:
        r = _norm(semantic_type, value, country="US", locale="en-US")
        assert r.normalization_status is NormalizationStatus.REPAIRED
        assert r.repaired is not None
        assert {f.value for f in r.flags} >= {"MOJIBAKE_FIXED", "ENCODING_REPAIRED"}


class TestNumberLocaleFromCldr:
    """N11 (found by this branch's held-out check): NUMERIC and MONEY with
    country=NO raised UnknownLocaleError (`no_NO` is not a Babel locale) out
    of the normalizer, failing the job; and a country's first official
    language was taken as its number convention, a guess where they differ."""

    @pytest.mark.parametrize("semantic_type", [FieldSemanticType.NUMERIC, FieldSemanticType.MONEY])
    @pytest.mark.parametrize("value", ["12", "1,5", "Oslo", "kr 12"])
    def test_norway_never_raises(self, semantic_type: FieldSemanticType, value: str) -> None:
        _norm(semantic_type, value, country="NO")

    def test_norway_uses_its_shared_convention(self) -> None:
        r = _norm(FieldSemanticType.NUMERIC, "1\u00a0234,5", country="NO")
        assert r.structured["canonical_value"] == "1234.5"

    def test_languages_that_disagree_do_not_pick_one(self) -> None:
        # en_CA reads 1234, fr_CA reads 1.234
        r = _norm(FieldSemanticType.NUMERIC, "1,234", country="CA")
        assert r.normalization_status is NormalizationStatus.AMBIGUOUS

    @pytest.mark.parametrize(("country", "expected"), [("US", "1234"), ("DE", "1.234")])
    def test_one_convention_still_resolves(self, country: str, expected: str) -> None:
        r = _norm(FieldSemanticType.NUMERIC, "1,234", country=country)
        assert r.structured["canonical_value"] == expected

    def test_unknown_locale_never_raises(self) -> None:
        _norm(FieldSemanticType.NUMERIC, "1,5", locale="xx-YY")
        _norm(FieldSemanticType.NUMERIC, "1,5", country="ZZ")

"""Dates must never gain precision they did not have.

A source that states only a year has to normalize to a year. The old
behaviour could only emit YYYY-MM-DD, so `1966` was refused outright —
and any "fix" that filled in January 1st would be inventing a month and a
day that are nowhere in the data. Junk affixes welded onto the digits
(`d1989-12-11`, `1990年`) are a separate, equally general problem: they are
stripped, but only when they directly abut a digit, which is what keeps
`March 1990` intact.
"""

from __future__ import annotations

from datetime import datetime, tzinfo

import dateparser.parser
import pytest
from normalizers.date import DateNormalizer
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType, NormalizationStatus, QualityFlag


@pytest.fixture
def normalizer() -> DateNormalizer:
    return DateNormalizer()


@pytest.fixture
def ctx() -> NormalizationContext:
    return NormalizationContext(field_name="founded", semantic_type=FieldSemanticType.DATE)


@pytest.mark.parametrize(
    ("value", "expected", "precision"),
    [
        ("1966", "1966", "year"),
        ("1990-03", "1990-03", "month"),
        ("1989-12-11", "1989-12-11", "day"),
        ("March 1990", "1990-03", "month"),
        # "circa 1990" is APPROXIMATELY 1990, and EDTF has a notation
        # for saying so. This asserted a bare "1990" while the approximation
        # was being silently dropped — the same class of invented certainty
        # the rest of this table guards against.
        ("circa 1990", "1990~", "year"),
        # placeholder components reduce precision, they do not become 01
        ("1982-XX-XX", "1982", "year"),
        ("1998-01-XX", "1998-01", "month"),
        ("1982/07/XX", "1982-07", "month"),
    ],
)
def test_precision_is_preserved_never_invented(
    normalizer: DateNormalizer, ctx: NormalizationContext, value: str, expected: str, precision: str
) -> None:
    result = normalizer.normalize(value, ctx)
    assert result.display == expected
    assert result.structured["precision"] == precision


@pytest.mark.unit
@pytest.mark.parametrize(
    ("value", "semantic_type", "expected", "precision"),
    [
        # one number read as both month and day
        ("03/2024", FieldSemanticType.DATE, "2024-03", "month"),
        ("12/2024", FieldSemanticType.DATE, "2024-12", "month"),
        ("03.2024", FieldSemanticType.DATE, "2024-03", "month"),
        ("03-2024", FieldSemanticType.DATE, "2024-03", "month"),
        ("03 2024", FieldSemanticType.DATE, "2024-03", "month"),
        # missing components filled from today's date
        ("03/2024 10:30", FieldSemanticType.DATE, "2024-03", "month"),
        ("03/2024 10:30", FieldSemanticType.DATETIME, "2024-03", "month"),
        ("2024 10:30", FieldSemanticType.DATE, "2024", "year"),
        # a time of day on a partial ISO date: no day 01
        ("2024-03 10:30", FieldSemanticType.DATETIME, "2024-03", "month"),
        # what the input does state still parses
        ("March 3, 2024", FieldSemanticType.DATE, "2024-03-03", "day"),
        ("3 March 2024", FieldSemanticType.DATE, "2024-03-03", "day"),
        ("Mar/2024", FieldSemanticType.DATE, "2024-03", "month"),
        ("00/2024", FieldSemanticType.DATE, "2024", "year"),
    ],
)
def test_no_component_the_input_does_not_state(
    normalizer: DateNormalizer,
    value: str,
    semantic_type: FieldSemanticType,
    expected: str,
    precision: str,
) -> None:
    ctx = NormalizationContext(field_name="d", semantic_type=semantic_type)
    result = normalizer.normalize(value, ctx)
    assert (result.display, result.structured["precision"]) == (expected, precision)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("value", "country", "expected", "precision"),
    [
        # a two-digit year 00 is the year 2000, not a placeholder (found by the rayyan benchmark)
        ("12/31/00", None, "2000-12-31", "day"),
        ("1/1/00", "US", "2000-01-01", "day"),
        ("1/00", None, "2000-01", "month"),
        # an all-zero group no component claims is a placeholder
        ("00/2024", None, "2024", "year"),
    ],
)
def test_an_all_zero_number_is_a_year_or_a_placeholder(
    normalizer: DateNormalizer, value: str, country: str | None, expected: str, precision: str
) -> None:
    ctx = NormalizationContext(
        field_name="d", semantic_type=FieldSemanticType.DATE, country=country
    )
    result = normalizer.normalize(value, ctx)
    assert (result.display, result.structured["precision"]) == (expected, precision)


@pytest.mark.unit
@pytest.mark.parametrize("value", ["13/2024", "2024/13", "NA", "today"])
def test_a_number_that_is_no_component_is_invalid(
    normalizer: DateNormalizer, ctx: NormalizationContext, value: str
) -> None:
    # each used to borrow the missing parts from the day the code ran (2024-10-13, today)
    assert normalizer.normalize(value, ctx).normalization_status == NormalizationStatus.INVALID


def test_partial_precision_is_flagged(
    normalizer: DateNormalizer, ctx: NormalizationContext
) -> None:
    assert QualityFlag.PARTIAL_DATE in normalizer.normalize("1966", ctx).flags
    assert QualityFlag.PARTIAL_DATE not in normalizer.normalize("1966-02-03", ctx).flags


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("d1989-12-11", "1989-12-11"),
        ("d1982-XX-XX", "1982"),
        ("zzz1966zzz", "1966"),
        ("1990年", "1990"),
    ],
)
def test_affixes_glued_to_the_digits_are_stripped(
    normalizer: DateNormalizer, ctx: NormalizationContext, value: str, expected: str
) -> None:
    result = normalizer.normalize(value, ctx)
    assert result.display == expected
    assert QualityFlag.PARSER_FALLBACK in result.flags


def test_a_word_separated_from_the_digits_is_not_an_affix(
    normalizer: DateNormalizer, ctx: NormalizationContext
) -> None:
    # If the strip were unconditional this would lose the month entirely.
    assert normalizer.normalize("March 1990", ctx).display == "1990-03"


def test_a_year_the_input_never_stated_is_refused(
    normalizer: DateNormalizer, ctx: NormalizationContext
) -> None:
    # dateparser fills unread components from today and used to return year
    # 36 for this, silently, at 0.95 confidence.
    result = normalizer.normalize("1990年", ctx)
    assert result.display == "1990"


@pytest.mark.parametrize("value", ["XXXX-XX-XX", "??", "2024-13-45", "not a date at all"])
def test_unparseable_values_stay_invalid(
    normalizer: DateNormalizer, ctx: NormalizationContext, value: str
) -> None:
    result = normalizer.normalize(value, ctx)
    assert result.normalization_status is NormalizationStatus.INVALID
    assert result.display == value


def test_repair_never_smuggles_a_value_past_the_ambiguity_guard(
    normalizer: DateNormalizer, ctx: NormalizationContext
) -> None:
    # Stripping the `d` would make this an ambiguous DMY/MDY numeric date,
    # which must still be refused rather than resolved by the repair path.
    result = normalizer.normalize("d03/04/2024", ctx)
    assert result.normalization_status is not NormalizationStatus.PARSED


def test_a_datetime_field_keeps_its_time_of_day() -> None:
    # Every path used to call .date(), so a column declared DATETIME lost
    # its time silently — losing precision rather than inventing it, but
    # wrong for the same reason.
    normalizer = DateNormalizer()
    ctx = NormalizationContext(field_name="created_at", semantic_type=FieldSemanticType.DATETIME)
    assert normalizer.normalize("2026-09-22 05:40:21.531498", ctx).display == (
        "2026-09-22T05:40:21.531498"
    )


def test_a_date_field_still_truncates_a_timestamp(
    normalizer: DateNormalizer, ctx: NormalizationContext
) -> None:
    # DATE is what the field was declared to be, so dropping the time is
    # the declared intent here, not data loss.
    assert normalizer.normalize("2026-09-22 05:40:21", ctx).display == "2026-09-22"


@pytest.mark.unit
class TestEdtfQualifiedAndRangeDates:
    """dateparser flattens a decade or a qualified year into a single day
    and reports success: "1990s" became "1990", inventing year precision
    out of a decade, and "circa 1990" lost the qualifier entirely."""

    @pytest.mark.parametrize(
        ("value", "expected", "precision"),
        [
            ("1990s", "199X", "decade"),
            ("early 1990s", "199X", "decade"),
            ("199X", "199X", "decade"),
            ("circa 1990", "1990~", "year"),
            ("about 1990", "1990~", "year"),
            ("1990?", "1990?", "year"),
            ("1990/2000", "1990/2000", "interval"),
            ("[1667,1668]", "[1667,1668]", "interval"),
        ],
    )
    def test_qualified_dates_keep_their_qualifier(
        self,
        normalizer: DateNormalizer,
        ctx: NormalizationContext,
        value: str,
        expected: str,
        precision: str,
    ) -> None:
        result = normalizer.normalize(value, ctx)
        assert result.display == expected
        assert result.structured["precision"] == precision

    def test_a_decade_is_not_a_year(
        self, normalizer: DateNormalizer, ctx: NormalizationContext
    ) -> None:
        """The whole point: "1990s" means 1990-1999, and reporting it as
        the single day 1990-01-01 invents nine years of precision."""
        result = normalizer.normalize("1990s", ctx)
        assert result.structured["earliest"] == "1990-01-01"
        assert result.structured["latest"] == "1999-12-31"

    def test_bounds_make_a_range_queryable(
        self, normalizer: DateNormalizer, ctx: NormalizationContext
    ) -> None:
        result = normalizer.normalize("1990/2000", ctx)
        assert result.structured["earliest"] == "1990-01-01"
        assert result.structured["latest"] == "2000-12-31"

    def test_an_ambiguous_numeric_date_still_refuses_to_guess(
        self, normalizer: DateNormalizer, ctx: NormalizationContext
    ) -> None:
        """The EDTF pass runs before the day/month ambiguity guard, so
        "12/05/1990" must not be read as an interval and slip past it."""
        result = normalizer.normalize("12/05/1990", ctx)
        assert result.normalization_status is NormalizationStatus.AMBIGUOUS

    @pytest.mark.parametrize("value", ["1990", "1990-03", "1990-03-15", "March 1990", "2024-01-15"])
    def test_ordinary_dates_do_not_go_through_edtf(
        self, normalizer: DateNormalizer, ctx: NormalizationContext, value: str
    ) -> None:
        """dateparser handles far more formats and languages, so the
        common path must not be rerouted through a narrower parser."""
        result = normalizer.normalize(value, ctx)
        assert result.structured.get("source_format") != "EDTF"


@pytest.mark.unit
@pytest.mark.parametrize("today", [datetime(2026, 11, 9), datetime(2026, 4, 9)])
def test_a_month_the_parser_took_from_the_clock_is_not_stated(
    monkeypatch: pytest.MonkeyPatch, normalizer: DateNormalizer, today: datetime
) -> None:
    # D24: under D/M/Y the parser reads `11/30` as day 11 of 2030 and fills the
    # month from today. In November that month matched the `11` and the value
    # read as November 2030. The clock is a boundary (L5), so it is pinned here.
    class _Clock(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> _Clock:
            return cls.fromtimestamp(today.timestamp(), tz)

    monkeypatch.setattr(dateparser.parser, "datetime", _Clock)
    ctx = NormalizationContext(
        field_name="d", semantic_type=FieldSemanticType.DATETIME, country="NO"
    )
    result = normalizer.normalize("11/30 10:30 p.m.", ctx)
    assert result.normalization_status is NormalizationStatus.INVALID

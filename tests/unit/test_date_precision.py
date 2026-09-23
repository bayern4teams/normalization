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
        ("circa 1990", "1990", "year"),
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

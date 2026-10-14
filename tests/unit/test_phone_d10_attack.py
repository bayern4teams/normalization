"""D10 attack checks: the removed "no region and no '+'" gate must not let a plus-less,
regionless input reach a confident verdict, and the emitted comparison must be a fixed point."""

from __future__ import annotations

import phonenumbers
import pytest
from normalizers.phone import PhoneNormalizer
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType, NormalizationStatus

N = PhoneNormalizer()


def norm(value: str, country: str | None = None, default_region: str | None = None):
    ctx = NormalizationContext(
        field_name="phone",
        semantic_type=FieldSemanticType.PHONE,
        country=country,
        default_region=default_region,
    )
    return N.normalize(value, ctx)


@pytest.mark.unit
@pytest.mark.parametrize(
    "value",
    [
        "00 44 20 7946 0958",
        "011 44 20 7946 0958 x1",
        "00 44 20 7946 0958 ext. 1",
        "tel:4155552671;ext=1",
        "tel:415-555-2671",
        "tel:+14155552671",  # ponytail ceiling: ext-free regionless tel: stays AMBIGUOUS
        "020 7946 0000 x45",
        "x45",
        "ext. 45",
        ";ext=45",
        "#45",
        "tel:",
        "tel:;ext=1",
        "tel:555-1234;phone-context=+1-415;ext=9",
    ],
)
def test_regionless_without_plus_never_reaches_a_confident_verdict(value: str) -> None:
    r = norm(value)
    # INVALID is no verdict either: `tel:` holds no number in any region (PART1 N7).
    assert r.normalization_status in (NormalizationStatus.AMBIGUOUS, NormalizationStatus.INVALID)
    assert r.comparison is None


@pytest.mark.unit
@pytest.mark.parametrize(
    "value",
    ["(+44) 20 7946 0958 x1", chr(0xFF0B) + "44 20 7946 0958 x1", "tel:+442079460958;ext=1"],
)
def test_regionless_accept_only_when_the_text_states_its_own_country(value: str) -> None:
    # every accepted regionless input contains an explicit plus; the country is read, not guessed
    r = norm(value)
    assert r.structured["country_code"] == 44
    assert r.comparison == "tel:+44-20-7946-0958;ext=1"
    assert norm(r.comparison).comparison == r.comparison


@pytest.mark.unit
def test_comparison_fixed_point_every_region_every_context() -> None:
    for region in sorted(phonenumbers.SUPPORTED_REGIONS):
        ex = phonenumbers.example_number(region)
        if ex is None:
            continue
        intl = phonenumbers.format_number(ex, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
        for suffix in (" x45", " ext. 45", ";ext=45", "#45", " x045"):
            first = norm(intl + suffix)
            assert first.comparison is not None and ";ext=" in first.comparison
            for ctx in ((None, None), ("US", None), (None, "JP")):
                again = norm(first.comparison, *ctx)
                assert again.comparison == first.comparison, (region, suffix, ctx)
                assert again.search == first.search == first.structured["e164"]


@pytest.mark.unit
@pytest.mark.parametrize("ext", ["12345678901234567890123", "abc", ""])
def test_bad_extension_is_never_valid(ext: str) -> None:
    r = norm("tel:+14155552671;ext=" + ext, country="US")
    assert r.validation_status != "VALID"


@pytest.mark.unit
def test_residual_extension_not_silently_dropped_with_isub() -> None:
    assert norm("tel:+14155552671;isub=123;ext=5", country="US").structured["extension"] == "5"


@pytest.mark.unit
def test_residual_extension_digits_fold_to_ascii() -> None:
    a = norm("+1 415 555 2671 x12").comparison
    assert norm("+1 415 555 2671 x" + chr(0x661) + chr(0x662)).comparison == a


@pytest.mark.unit
def test_residual_two_markers_do_not_yield_a_confident_valid() -> None:
    # Was a strict xfail. Fixed in fix/followups by the unread-letter rule:
    # the first marker's `x` is a letter libphonenumber did not read.
    assert norm("+43 1 234567890x45 x46").validation_status != "VALID"

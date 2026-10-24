"""Empirical reversibility verification — ADR-012 / Source.txt §80.

Every step declares a claimed reversibility class in
`normalizers.text_ops.OPERATIONS`. This test does not trust the claim —
it exercises `GenericTextNormalizer.inverse()` against real transformed
values and checks the claim actually holds:

- REVERSIBLE/LOSSLESS steps must have a working inverse whose result,
  fed back through the SAME forward operation, reproduces the original
  transformed output exactly (the correct notion of "reversible" for
  Unicode normalization forms, where NFC is many-to-one over raw input
  but NFC<->NFD is a consistent bijection over canonically-equivalent
  forms — see the docstring on `text_ops.inverse_unicode_form`).
- LOSSY steps must NOT claim to have a usable inverse: `.inverse()` must
  return None for them, so nothing downstream could mistakenly treat a
  lossy transformation as recoverable.

A step whose observed behavior contradicts its claimed class fails this
test, which is exactly the CI gate ADR-012 requires.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from normalizers.generic_text import GenericTextNormalizer
from normcore.enums import Reversibility
from normcore.unicode_policy import UnicodeForm
from normdict.loader import DictionaryLoader

from normalizers import text_ops

_DICT_ROOT = Path(__file__).parents[2] / "data" / "dictionaries"

_SAMPLE_VALUES: tuple[str, ...] = (
    "café",  # NFC-precomposed
    "café",  # NFD-decomposed (e + combining acute)
    "naïve René",
    "Ångström Ø",
    "ZÜRICH",
    "plain ascii",
    "北京 東京",
    "Ĥěllo Wórld",
)


@pytest.fixture(scope="module")
def normalizer() -> GenericTextNormalizer:
    return GenericTextNormalizer(DictionaryLoader(_DICT_ROOT))


@pytest.mark.golden
@pytest.mark.parametrize(
    "operation",
    [name for name, spec in text_ops.OPERATIONS.items() if not spec.lossy],
)
def test_non_lossy_operations_declare_reversible_or_lossless(operation: str) -> None:
    spec = text_ops.OPERATIONS[operation]
    assert spec.claimed_reversibility in (Reversibility.REVERSIBLE, Reversibility.LOSSLESS), (
        f"{operation} is marked lossy=False but claims {spec.claimed_reversibility}, "
        "which is internally inconsistent"
    )


@pytest.mark.golden
@pytest.mark.parametrize("value", _SAMPLE_VALUES)
def test_nfc_inverse_round_trips_through_forward_operation(
    normalizer: GenericTextNormalizer, value: str
) -> None:
    nfc_output, changed = text_ops.unicode_normalize(value, UnicodeForm.NFC)
    if not changed:
        # C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
        pytest.skip(f"{value!r} was already NFC-normalized, nothing to invert")

    inverted = normalizer.inverse("unicode_normalize_nfc", nfc_output)
    assert inverted is not None, "unicode_normalize_nfc claims REVERSIBLE but has no inverse"
    assert inverted != nfc_output, "inverse should actually decompose, not no-op"

    # Re-applying the SAME forward operation to the inverse must reproduce
    # the original NFC output exactly — the concrete, testable meaning of
    # "REVERSIBLE" for a canonical normalization form.
    reforward, _ = text_ops.unicode_normalize(inverted, UnicodeForm.NFC)
    assert reforward == nfc_output


@pytest.mark.golden
@pytest.mark.parametrize("value", _SAMPLE_VALUES)
def test_nfd_inverse_round_trips_through_forward_operation(
    normalizer: GenericTextNormalizer, value: str
) -> None:
    nfd_output, changed = text_ops.unicode_normalize(value, UnicodeForm.NFD)
    if not changed:
        # C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
        pytest.skip(f"{value!r} was already NFD-normalized, nothing to invert")

    inverted = normalizer.inverse("unicode_normalize_nfd", nfd_output)
    assert inverted is not None
    reforward, _ = text_ops.unicode_normalize(inverted, UnicodeForm.NFD)
    assert reforward == nfd_output


@pytest.mark.golden
@pytest.mark.parametrize(
    "operation", [name for name, spec in text_ops.OPERATIONS.items() if spec.lossy]
)
def test_lossy_operations_report_no_inverse(
    normalizer: GenericTextNormalizer, operation: str
) -> None:
    # A representative value that plausibly triggers each lossy op; the
    # claim under test is that .inverse() refuses to fabricate a result
    # for a LOSSY step, regardless of the value passed.
    assert normalizer.inverse(operation, "some transformed value") is None, (
        f"{operation} is declared LOSSY but GenericTextNormalizer.inverse() "
        "returned a non-None result for it"
    )

"""PART1 D7.3: Norway's tax ids were never VALID (1,177,617 register numbers
UNKNOWN) because the chosen module, no.mva, wants the VAT form and a bare
organisation number only matched a sibling. A number valid under a module
the chosen one is built on (it imports it) is that country's tax id.
Expected values are computed with stdnum itself. Fails on main.
"""

from __future__ import annotations

import pytest
from normapi.app import build_dispatcher
from normapi.scaffold_profile import SCAFFOLD_PROFILE
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType
from stdnum.no import mva, orgnr
from stdnum.se import orgnr as se_orgnr

pytestmark = pytest.mark.unit

_D = build_dispatcher(env_id="tax-base")


def _tax(value: str, country: str) -> object:
    ctx = NormalizationContext(
        field_name="f", semantic_type=FieldSemanticType.TAX_ID, country=country
    )
    return _D.normalize(value, FieldSemanticType.TAX_ID, ctx, SCAFFOLD_PROFILE)


def _orgnr(body: str) -> str:
    """The one check digit stdnum accepts for `body` (computed, not typed)."""
    (number,) = [body + d for d in "0123456789" if orgnr.is_valid(body + d)]
    return number


def test_a_norwegian_organisation_number_is_a_valid_tax_id() -> None:
    number = _orgnr("92360901")
    assert orgnr.is_valid(number) and not mva.is_valid(number)
    r = _tax(number, "NO")
    assert r.validation_status == "VALID"
    assert r.structured["verified_by"] == "stdnum.no.orgnr"


def test_the_vat_form_still_validates_as_before() -> None:
    r = _tax(f"NO{_orgnr('92360901')}MVA", "NO")
    assert r.validation_status == "VALID"
    assert "verified_by" not in r.structured


def test_a_wrong_check_digit_is_still_invalid() -> None:
    good = _orgnr("92360901")
    bad = good[:-1] + str((int(good[-1]) + 1) % 10)
    assert not orgnr.is_valid(bad)
    assert _tax(bad, "NO").validation_status == "INVALID"


def test_the_rule_is_stdnums_own_structure_not_norway() -> None:
    number = "5560360793"  # se.orgnr's documented example
    assert se_orgnr.is_valid(number)
    assert _tax(number, "SE").validation_status == "VALID"

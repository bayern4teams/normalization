"""Cultural safety — Source.txt §76 — consolidated cross-cutting proof.

§76 names six specific assumptions this project must never make, each
already enforced by a real normalizer (built and unit-tested individually
in M3/M4). This module doesn't add new behavior — it demonstrates all six
together, in one place, against real normalizer output, so the guarantee
is auditable as a single cross-cutting statement rather than scattered
facts a reader has to piece together from six different test files.

    "first token is always first name"       -> TestFirstTokenIsNotAssumedGivenName
    "last token is always surname"           -> TestLastTokenIsNotAssumedSurname
    "address order is universal"             -> TestAddressComponentsAreLabelNotPositionBased
    "country can be inferred from postal
     code alone"                             -> TestCountryIsNotInferredFromPostcodeAlone
    "company suffix always indicates
     jurisdiction"                           -> TestCompanySuffixIsOnlyAHint
    "email provider rules apply universally" -> TestEmailProviderRulesAreNotApplied

"When uncertain: mark ambiguity" is the shared mechanism behind the first
four: each one either returns `NormalizationStatus.AMBIGUOUS` or leaves a
field `None`/unresolved rather than silently guessing.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from normalizers.address import AddressNormalizer
from normalizers.company import CompanyNormalizer
from normalizers.email import EmailNormalizer
from normalizers.name import NameNormalizer
from normalizers.postcode import PostcodeNormalizer
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType, NormalizationStatus
from normdict.loader import DictionaryLoader

_DICT_ROOT = Path(__file__).parents[2] / "data" / "dictionaries"


class _FakeLibpostalParser:
    def __init__(self, canned: dict[str, list[tuple[str, str]]]) -> None:
        self._canned = canned

    def parse(self, address: str) -> list[tuple[str, str]]:
        return self._canned.get(address, [])


@pytest.mark.unit
class TestFirstTokenIsNotAssumedGivenName:
    def test_two_token_name_is_marked_ambiguous_not_guessed(self) -> None:
        normalizer = NameNormalizer(DictionaryLoader(_DICT_ROOT))
        ctx = NormalizationContext(field_name="name", semantic_type=FieldSemanticType.PERSON_NAME)

        result = normalizer.normalize("Smith John", ctx)

        assert result.normalization_status is NormalizationStatus.AMBIGUOUS
        # NOT silently resolved to given_name="Smith" (first token)
        assert result.structured["given_name"] is None


@pytest.mark.unit
class TestLastTokenIsNotAssumedSurname:
    def test_two_token_name_offers_both_orderings_as_candidates(self) -> None:
        normalizer = NameNormalizer(DictionaryLoader(_DICT_ROOT))
        ctx = NormalizationContext(field_name="name", semantic_type=FieldSemanticType.PERSON_NAME)

        result = normalizer.normalize("Smith John", ctx)

        # NOT silently resolved to family_name="John" (last token) — both
        # readings are offered as candidates, neither asserted as fact.
        assert result.structured["family_name"] is None
        candidates = result.structured["candidates"]
        assert {"given_name": "Smith", "family_name": "John"} in candidates
        assert {"given_name": "John", "family_name": "Smith"} in candidates


@pytest.mark.unit
class TestAddressComponentsAreLabelNotPositionBased:
    def test_postcode_first_address_still_parses_postcode_correctly(self) -> None:
        """A libpostal-style parse where the postcode is the FIRST token
        (as in Japanese addresses) must still land in the `postcode`
        component — proving components are assembled by the parser's
        real per-token label, never by fixed positional order."""
        address = "100-0001 Chiyoda Tokyo"
        canned = {
            address: [
                ("100-0001", "postcode"),
                ("chiyoda", "city_district"),
                ("tokyo", "city"),
            ]
        }
        normalizer = AddressNormalizer(_FakeLibpostalParser(canned))
        ctx = NormalizationContext(field_name="address", semantic_type=FieldSemanticType.ADDRESS)

        result = normalizer.normalize(address, ctx)

        assert result.structured["postcode"] == "100-0001"
        assert result.structured["city"] == "tokyo"


@pytest.mark.unit
class TestCountryIsNotInferredFromPostcodeAlone:
    def test_bare_postcode_without_country_context_stays_ambiguous(self) -> None:
        normalizer = PostcodeNormalizer()
        ctx = NormalizationContext(field_name="zip", semantic_type=FieldSemanticType.POSTCODE)

        # "90210" is a plausible postcode in several countries — no
        # country context means no country can honestly be inferred.
        result = normalizer.normalize("90210", ctx)

        assert result.normalization_status is NormalizationStatus.AMBIGUOUS
        assert result.structured["country"] is None


@pytest.mark.unit
class TestCompanySuffixIsOnlyAHint:
    def test_multi_country_suffix_gets_no_jurisdiction_hint(self) -> None:
        normalizer = CompanyNormalizer(DictionaryLoader(_DICT_ROOT))
        ctx = NormalizationContext(
            field_name="company", semantic_type=FieldSemanticType.COMPANY_NAME
        )

        # "SA" is used by France, Spain, Switzerland, and others — never
        # collapsed to a single asserted jurisdiction.
        result = normalizer.normalize("Foo Bar SA", ctx)

        assert result.structured["jurisdiction_hint"] is None

    def test_unambiguous_suffix_is_still_only_a_hint_field_not_a_fact_field(self) -> None:
        normalizer = CompanyNormalizer(DictionaryLoader(_DICT_ROOT))
        ctx = NormalizationContext(
            field_name="company", semantic_type=FieldSemanticType.COMPANY_NAME
        )

        result = normalizer.normalize("Müller GmbH", ctx)

        assert result.structured["jurisdiction_hint"] == "DE"
        assert "jurisdiction" not in result.structured  # only the hedged "_hint" key exists


@pytest.mark.unit
class TestEmailProviderRulesAreNotApplied:
    def test_gmail_style_dots_in_local_part_are_preserved_not_stripped(self) -> None:
        """Gmail treats 'a.b.c@gmail.com' and 'abc@gmail.com' as the same
        inbox, but that is a Gmail-specific convention, not a universal
        email rule (§39/§4.5) — this project must not silently apply it."""
        normalizer = EmailNormalizer()
        ctx = NormalizationContext(field_name="email", semantic_type=FieldSemanticType.EMAIL)

        result = normalizer.normalize("a.b.c@gmail.com", ctx)

        assert result.structured["local_part"] == "a.b.c"  # dots NOT removed
        assert result.comparison is not None
        assert "a.b.c" in result.comparison

"""Unit tests for AddressNormalizer — Source.txt §29-§32, §76.

Uses a fake `LibpostalParser` test double (no Docker/network needed) with
canned parses for the exact input strings each test exercises — real
end-to-end behavior against the live libpostal sidecar is proven
separately in tests/integration/test_address_normalizer_integration.py.
"""

from __future__ import annotations

import pyarrow as pa
import pytest
from normalizers.address import AddressNormalizer, LibpostalUnavailableError
from normcore.context import NormalizationContext
from normcore.enums import (
    FieldSemanticType,
    MissingKind,
    NormalizationStatus,
    QualityFlag,
    Reversibility,
)


class FakeLibpostalParser:
    """canned[address] -> list[(value, label)], matching
    LibpostalClient.parse()'s real return shape exactly."""

    def __init__(self, canned: dict[str, list[tuple[str, str]]], *, always_fail: bool = False):
        self._canned = canned
        self._always_fail = always_fail
        self.call_count = 0

    def parse(self, address: str) -> list[tuple[str, str]]:
        self.call_count += 1
        if self._always_fail:
            raise LibpostalUnavailableError("simulated sidecar outage")
        return self._canned.get(address, [])


_BAKER_ST = "10-12 Baker St., London, W1U 3BW, UK"
_BAKER_ST_PARSE: list[tuple[str, str]] = [
    ("10-12", "house_number"),
    ("baker st.", "road"),
    ("london", "city"),
    ("w1u 3bw", "postcode"),
    ("uk", "country"),
]

_PENNSYLVANIA_AVE = "1600 Pennsylvania Avenue NW, Washington, DC 20500, USA"
_PENNSYLVANIA_AVE_PARSE: list[tuple[str, str]] = [
    ("1600", "house_number"),
    ("pennsylvania avenue nw", "road"),
    ("washington", "city"),
    ("dc", "state"),
    ("20500", "postcode"),
    ("usa", "country"),
]


def _ctx(*, country: str | None = None) -> NormalizationContext:
    return NormalizationContext(
        field_name="address", semantic_type=FieldSemanticType.ADDRESS, country=country
    )


@pytest.mark.unit
class TestProtocolShape:
    def test_supported_types(self) -> None:
        normalizer = AddressNormalizer(FakeLibpostalParser({}))
        assert normalizer.supported_types == frozenset({FieldSemanticType.ADDRESS})

    def test_version(self) -> None:
        normalizer = AddressNormalizer(FakeLibpostalParser({}))
        assert normalizer.version().name == "AddressNormalizer"


@pytest.mark.unit
class TestMissingValues:
    def test_none(self) -> None:
        normalizer = AddressNormalizer(FakeLibpostalParser({}))
        result = normalizer.normalize(None, _ctx())
        assert result.original_kind is MissingKind.NULL

    def test_empty(self) -> None:
        normalizer = AddressNormalizer(FakeLibpostalParser({}))
        result = normalizer.normalize("", _ctx())
        assert result.original_kind is MissingKind.EMPTY_STRING


@pytest.mark.unit
class TestSuccessfulParse:
    def test_house_number_range_survives(self) -> None:
        """Source.txt §109's own worked example — "10-12" must not
        become "1012"."""
        parser = FakeLibpostalParser({_BAKER_ST: _BAKER_ST_PARSE})
        normalizer = AddressNormalizer(parser)
        result = normalizer.normalize(_BAKER_ST, _ctx())
        assert result.structured["house_number"] == "10-12"
        assert result.normalization_status is NormalizationStatus.PARSED

    def test_display_is_full_cleaned_address_not_reconstructed(self) -> None:
        """§30: display/comparison never collapse to one lossy string —
        display keeps the full original text, comparison is built
        separately from components."""
        parser = FakeLibpostalParser({_BAKER_ST: _BAKER_ST_PARSE})
        normalizer = AddressNormalizer(parser)
        result = normalizer.normalize(_BAKER_ST, _ctx())
        assert result.display == _BAKER_ST

    def test_comparison_built_from_component_values_not_labels(self) -> None:
        parser = FakeLibpostalParser({_BAKER_ST: _BAKER_ST_PARSE})
        normalizer = AddressNormalizer(parser)
        result = normalizer.normalize(_BAKER_ST, _ctx())
        assert result.comparison is not None
        assert "house_number" not in result.comparison  # a label, not a value
        assert "10-12" in result.comparison
        assert "baker st." in result.comparison

    def test_all_named_components_present(self) -> None:
        parser = FakeLibpostalParser({_PENNSYLVANIA_AVE: _PENNSYLVANIA_AVE_PARSE})
        normalizer = AddressNormalizer(parser)
        result = normalizer.normalize(_PENNSYLVANIA_AVE, _ctx())
        for key in ("house_number", "road", "city", "state", "postcode", "country"):
            assert key in result.structured

    def test_original_never_overwritten(self) -> None:
        parser = FakeLibpostalParser({_BAKER_ST: _BAKER_ST_PARSE})
        normalizer = AddressNormalizer(parser)
        result = normalizer.normalize(_BAKER_ST, _ctx())
        assert result.original == _BAKER_ST


@pytest.mark.unit
class TestPostalCodeValidation:
    def test_valid_uk_postcode(self) -> None:
        parser = FakeLibpostalParser({_BAKER_ST: _BAKER_ST_PARSE})
        normalizer = AddressNormalizer(parser)
        result = normalizer.normalize(_BAKER_ST, _ctx())
        assert result.structured["postcode_valid"] is True

    def test_valid_us_postcode(self) -> None:
        parser = FakeLibpostalParser({_PENNSYLVANIA_AVE: _PENNSYLVANIA_AVE_PARSE})
        normalizer = AddressNormalizer(parser)
        result = normalizer.normalize(_PENNSYLVANIA_AVE, _ctx())
        assert result.structured["postcode_valid"] is True

    def test_invalid_postcode_for_country(self) -> None:
        bad_parse = [
            ("999-999", "postcode"),
            ("uk", "country"),
            ("some place", "road"),
        ]
        parser = FakeLibpostalParser({"bad": bad_parse})
        normalizer = AddressNormalizer(parser)
        result = normalizer.normalize("bad", _ctx())
        assert result.structured["postcode_valid"] is False

    def test_no_country_leaves_postcode_unchecked(self) -> None:
        parse_no_country = [("w1u 3bw", "postcode"), ("some road", "road")]
        parser = FakeLibpostalParser({"addr": parse_no_country})
        normalizer = AddressNormalizer(parser)
        result = normalizer.normalize("addr", _ctx())
        assert "postcode_valid" not in result.structured

    def test_context_country_used_when_libpostal_omits_it(self) -> None:
        parse_no_country = [("w1u 3bw", "postcode"), ("baker st", "road")]
        parser = FakeLibpostalParser({"addr": parse_no_country})
        normalizer = AddressNormalizer(parser)
        result = normalizer.normalize("addr", _ctx(country="GB"))
        assert result.structured["postcode_valid"] is True


@pytest.mark.unit
class TestPartialParseAndFallback:
    def test_empty_parse_result_flags_partial(self) -> None:
        parser = FakeLibpostalParser({"gibberish": []})
        normalizer = AddressNormalizer(parser)
        result = normalizer.normalize("gibberish", _ctx())
        assert QualityFlag.ADDRESS_PARSE_PARTIAL in result.flags
        assert result.normalization_status is NormalizationStatus.PARTIAL

    def test_sidecar_unavailable_falls_back_gracefully(self) -> None:
        """§68: one malformed/unreachable dependency must never crash
        the run — and §29's circuit breaker + PARSER_FALLBACK requirement."""
        parser = FakeLibpostalParser({}, always_fail=True)
        normalizer = AddressNormalizer(parser)
        result = normalizer.normalize("123 Main St", _ctx())
        assert QualityFlag.PARSER_FALLBACK in result.flags
        assert QualityFlag.ADDRESS_PARSE_PARTIAL in result.flags
        assert result.display == "123 Main St"
        assert result.errors != []

    def test_circuit_breaker_opens_after_threshold(self) -> None:
        parser = FakeLibpostalParser({}, always_fail=True)
        normalizer = AddressNormalizer(parser)
        for _ in range(5):
            normalizer.normalize("123 Main St", _ctx())
        # After the circuit opens, no further HTTP calls should be made —
        # the breaker short-circuits locally instead of hammering a known-
        # down sidecar.
        assert parser.call_count < 5

    def test_validate_partial_parse_is_invalid(self) -> None:
        parser = FakeLibpostalParser({"gibberish": []})
        normalizer = AddressNormalizer(parser)
        outcome = normalizer.validate("gibberish", _ctx())
        assert outcome.is_valid is False


@pytest.mark.unit
class TestExactFieldsOnFullSuccess:
    """A real mutmut run (M12) found 49 surviving mutants in
    `AddressNormalizer.normalize` alone, mostly literal constants
    (confidence values, empty-list defaults, comparison operators) that
    the field-by-field checks above never pinned down exactly."""

    def test_complete_parse_every_field(self) -> None:
        parse = [
            ("10", "house_number"),
            ("main st", "road"),
            ("springfield", "city"),
            ("some category", "category"),
            ("a place", "near"),
            ("", "unit"),
        ]
        parser = FakeLibpostalParser({"addr": parse})
        normalizer = AddressNormalizer(parser)
        result = normalizer.normalize("addr", _ctx())

        assert result.original == "addr"
        assert result.display == "addr"
        # category/near labels and blank values are excluded from
        # comparison, but NOT filtered out of structured (additive).
        assert result.comparison == "10 main st springfield"
        assert result.search == result.comparison
        assert result.structured == {
            "house_number": "10",
            "road": "main st",
            "city": "springfield",
            "category": "some category",
            "near": "a place",
            "unit": "",
        }
        assert result.flags == []
        assert result.validation_status == "VALID"
        assert result.normalization_status is NormalizationStatus.PARSED
        assert result.confidence == 1.0
        assert result.errors == []
        assert result.lossiness is Reversibility.PARTIALLY_REVERSIBLE
        assert result.profile_version == ""
        assert result.env_id == ""
        assert result.trace[-1].library == "libpostal"
        assert result.trace[-1].library_version == "1.1.4"
        assert result.trace[-1].changed is True
        assert result.trace[-1].reversibility is Reversibility.PARTIALLY_REVERSIBLE

    def test_missing_city_only_is_partial_with_0_7_confidence(self) -> None:
        parse = [("10", "house_number"), ("main st", "road")]
        parser = FakeLibpostalParser({"addr": parse})
        result = AddressNormalizer(parser).normalize("addr", _ctx())
        assert result.flags == [QualityFlag.ADDRESS_PARSE_PARTIAL]
        assert result.validation_status == "PARTIAL"
        assert result.normalization_status is NormalizationStatus.PARTIAL
        assert result.confidence == 0.7

    def test_missing_road_only_is_also_partial(self) -> None:
        """The flag condition is `not road OR not city` — road missing
        alone must trip it exactly like city missing alone."""
        parse = [("10", "house_number"), ("springfield", "city")]
        parser = FakeLibpostalParser({"addr": parse})
        result = AddressNormalizer(parser).normalize("addr", _ctx())
        assert result.flags == [QualityFlag.ADDRESS_PARSE_PARTIAL]
        assert result.confidence == 0.7

    def test_invalid_postcode_with_complete_parse_is_not_flagged_partial(self) -> None:
        """postcode_valid=False alone does not add ADDRESS_PARSE_PARTIAL
        — only missing road/city does. confidence still drops to 0.6, but
        validation_status stays VALID since it derives from `flags`, not
        from postcode validity directly (an existing, real quirk of this
        function's logic worth pinning down exactly)."""
        parse = [
            ("10", "house_number"),
            ("main st", "road"),
            ("springfield", "city"),
            ("999-999", "postcode"),
            ("uk", "country"),
        ]
        parser = FakeLibpostalParser({"addr": parse})
        result = AddressNormalizer(parser).normalize("addr", _ctx())
        assert result.flags == []
        assert result.validation_status == "VALID"
        assert result.normalization_status is NormalizationStatus.PARSED
        assert result.confidence == 0.6
        assert result.structured["postcode_valid"] is False

    def test_invalid_postcode_and_partial_parse_confidence_is_clamped_to_0_6(self) -> None:
        """Both conditions active: confidence starts at 0.6 (postcode
        invalid) then `min(confidence, 0.7)` for the partial-parse flag
        — 0.6 stays 0.6, proving the clamp is a min, not an overwrite."""
        parse = [
            ("10", "house_number"),
            ("main st", "road"),
            ("999-999", "postcode"),
            ("uk", "country"),
        ]
        parser = FakeLibpostalParser({"addr": parse})
        result = AddressNormalizer(parser).normalize("addr", _ctx())
        assert result.flags == [QualityFlag.ADDRESS_PARSE_PARTIAL]
        assert result.confidence == 0.6
        assert result.validation_status == "PARTIAL"


@pytest.mark.unit
class TestExactFieldsOnFallbackAndMissing:
    def test_fallback_every_field(self) -> None:
        parser = FakeLibpostalParser({}, always_fail=True)
        result = AddressNormalizer(parser).normalize("123 Main St", _ctx())

        assert result.original == "123 Main St"
        assert result.display == "123 Main St"
        assert result.comparison is None
        assert result.search is None
        assert result.structured == {}
        assert result.validation_status == "PARTIAL"
        assert result.normalization_status is NormalizationStatus.PARTIAL
        assert result.confidence == 0.3
        assert result.flags == [QualityFlag.ADDRESS_PARSE_PARTIAL, QualityFlag.PARSER_FALLBACK]
        assert result.errors == ["simulated sidecar outage"]
        assert result.lossiness is Reversibility.LOSSLESS
        assert result.profile_version == ""
        assert result.env_id == ""
        # The fallback trace is unicode-cleanup steps only — the parse
        # step is appended AFTER the fallback branch would have
        # returned, so it must never claim a libpostal parse happened.
        assert all(step.library != "libpostal" for step in result.trace)

    def test_missing_none_every_field(self) -> None:
        result = AddressNormalizer(FakeLibpostalParser({})).normalize(None, _ctx())
        assert result.original is None
        assert result.original_kind is MissingKind.NULL
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.validation_status == "MISSING"
        assert result.confidence == 1.0
        assert result.display is None
        assert result.errors == []
        assert result.profile_version == ""
        assert result.env_id == ""

    def test_missing_empty_every_field(self) -> None:
        result = AddressNormalizer(FakeLibpostalParser({})).normalize("", _ctx())
        assert result.original == ""
        assert result.original_kind is MissingKind.EMPTY_STRING
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.validation_status == "MISSING"
        assert result.confidence == 1.0

    def test_circuit_open_call_carries_the_real_value_and_reason(self) -> None:
        """Once the circuit is actually open (not just mid-failure), the
        fallback for THAT call must still carry the real `original`/
        `display` for the value being normalized right now, and the
        exact reason text — not the value from whichever call tripped
        the breaker earlier."""
        parser = FakeLibpostalParser({}, always_fail=True)
        normalizer = AddressNormalizer(parser)
        for _ in range(3):
            normalizer.normalize("123 Main St", _ctx())
        assert parser.call_count == 3  # breaker now open

        result = normalizer.normalize("456 Oak Ave", _ctx())
        assert parser.call_count == 3  # no new call while open
        assert result.original == "456 Oak Ave"
        assert result.display == "456 Oak Ave"
        assert result.errors == ["circuit breaker open"]


@pytest.mark.unit
class TestLocaleSensitiveComparison:
    def test_turkish_locale_uses_dotless_i_casefold(self) -> None:
        """`comparison` is built via `text_ops.casefold(..., ctx.locale)`
        — Turkish casefolding of 'I' differs from the locale-agnostic
        default (U+0131 dotless-i vs U+0069 dotted-i), verified against
        the real ICU casefold implementation before writing this
        assertion."""
        parse = [("istanbul rd", "road"), ("ISTANBUL", "city")]
        parser = FakeLibpostalParser({"addr": parse})
        ctx_tr = NormalizationContext(
            field_name="address", semantic_type=FieldSemanticType.ADDRESS, locale="tr"
        )
        result = AddressNormalizer(parser).normalize("addr", ctx_tr)
        dotless_i = chr(0x0131)  # RUF001: avoid the ambiguous glyph literally in source
        assert result.comparison == f"istanbul rd {dotless_i}stanbul"

    def test_no_locale_uses_default_casefold(self) -> None:
        parse = [("istanbul rd", "road"), ("ISTANBUL", "city")]
        parser = FakeLibpostalParser({"addr": parse})
        result = AddressNormalizer(parser).normalize("addr", _ctx())
        assert result.comparison == "istanbul rd istanbul"


@pytest.mark.unit
class TestBatchAndInverse:
    def test_normalize_batch_matches_scalar(self) -> None:
        parser = FakeLibpostalParser(
            {_BAKER_ST: _BAKER_ST_PARSE, _PENNSYLVANIA_AVE: _PENNSYLVANIA_AVE_PARSE}
        )
        normalizer = AddressNormalizer(parser)
        ctx = _ctx()
        values = [_BAKER_ST, _PENNSYLVANIA_AVE]
        batch = normalizer.normalize_batch(pa.array(values, type=pa.large_string()), ctx)
        displays = batch.field("display").to_pylist()
        assert displays == [normalizer.normalize(v, ctx).display for v in values]

    def test_inverse_parse_step_returns_none(self) -> None:
        normalizer = AddressNormalizer(FakeLibpostalParser({}))
        assert normalizer.inverse("address.libpostal_parse", "10-12 Baker St") is None

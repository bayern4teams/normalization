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
from normcore.enums import FieldSemanticType, MissingKind, NormalizationStatus, QualityFlag


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

"""Unit tests for URLNormalizer — Source.txt §42, §99."""

from __future__ import annotations

import pytest
from normalizers.url import URLNormalizer
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType, MissingKind, NormalizationStatus, QualityFlag


@pytest.fixture
def normalizer() -> URLNormalizer:
    return URLNormalizer()


def _ctx() -> NormalizationContext:
    return NormalizationContext(field_name="u", semantic_type=FieldSemanticType.URL)


@pytest.mark.unit
class TestProtocolShape:
    def test_supported_types(self, normalizer: URLNormalizer) -> None:
        assert normalizer.supported_types == frozenset({FieldSemanticType.URL})

    def test_version(self, normalizer: URLNormalizer) -> None:
        assert normalizer.version().name == "URLNormalizer"


@pytest.mark.unit
class TestMissingValues:
    def test_none(self, normalizer: URLNormalizer) -> None:
        result = normalizer.normalize(None, _ctx())
        assert result.original_kind is MissingKind.NULL

    def test_empty(self, normalizer: URLNormalizer) -> None:
        result = normalizer.normalize("", _ctx())
        assert result.original_kind is MissingKind.EMPTY_STRING


@pytest.mark.unit
class TestSchemeAndHost:
    def test_scheme_lowercased(self, normalizer: URLNormalizer) -> None:
        result = normalizer.normalize("HTTP://example.com/", _ctx())
        assert result.display is not None
        assert result.display.startswith("http://")

    def test_host_lowercased(self, normalizer: URLNormalizer) -> None:
        result = normalizer.normalize("http://EXAMPLE.com/", _ctx())
        assert result.structured["host"] == "example.com"

    def test_missing_scheme_or_host_is_invalid(self, normalizer: URLNormalizer) -> None:
        result = normalizer.normalize("not a url", _ctx())
        assert result.normalization_status is NormalizationStatus.INVALID


@pytest.mark.unit
class TestDefaultPortRemoval:
    def test_http_default_port_removed(self, normalizer: URLNormalizer) -> None:
        result = normalizer.normalize("http://example.com:80/", _ctx())
        assert result.display is not None
        assert ":80" not in result.display

    def test_https_default_port_removed(self, normalizer: URLNormalizer) -> None:
        result = normalizer.normalize("https://example.com:443/", _ctx())
        assert result.display is not None
        assert ":443" not in result.display

    def test_non_default_port_kept(self, normalizer: URLNormalizer) -> None:
        result = normalizer.normalize("http://example.com:8080/", _ctx())
        assert result.display is not None
        assert ":8080" in result.display


@pytest.mark.unit
class TestPercentEncodingNormalization:
    def test_unreserved_char_decoded(self, normalizer: URLNormalizer) -> None:
        """Source.txt §42: percent-encoding normalized "where safe" — '~'
        (0x7E) is RFC 3986 unreserved, always safe to decode."""
        result = normalizer.normalize("https://example.com/a%7Eb", _ctx())
        assert result.display is not None
        assert "%7E" not in result.display
        assert "~" in result.display

    def test_reserved_char_stays_encoded(self, normalizer: URLNormalizer) -> None:
        """'/' (0x2F) is reserved — decoding it inside a path segment would
        change the URL's structure, so it must stay encoded."""
        result = normalizer.normalize("https://example.com/a%2Fb", _ctx())
        assert result.display is not None
        assert "%2F" in result.display

    def test_hex_digits_uppercased(self, normalizer: URLNormalizer) -> None:
        result = normalizer.normalize("https://example.com/a%2fb", _ctx())
        assert result.display is not None
        assert "%2F" in result.display
        assert "%2f" not in result.display


@pytest.mark.unit
class TestIdnNormalization:
    def test_unicode_host_converted_to_punycode(self, normalizer: URLNormalizer) -> None:
        result = normalizer.normalize("https://münchen.de/", _ctx())
        assert result.structured["host"].startswith("xn--")
        assert result.structured["is_idn"] is True

    def test_ascii_host_not_marked_idn(self, normalizer: URLNormalizer) -> None:
        result = normalizer.normalize("https://example.com/", _ctx())
        assert result.structured["is_idn"] is False


@pytest.mark.unit
class TestTrailingSlashPolicy:
    def test_root_path_equivalent_in_comparison(self, normalizer: URLNormalizer) -> None:
        with_slash = normalizer.normalize("https://example.com/", _ctx())
        without_slash = normalizer.normalize("https://example.com", _ctx())
        assert with_slash.comparison == without_slash.comparison

    def test_non_root_trailing_slash_never_stripped_from_display(
        self, normalizer: URLNormalizer
    ) -> None:
        result = normalizer.normalize("https://example.com/path/", _ctx())
        assert result.display is not None
        assert result.display.endswith("/path/")


@pytest.mark.unit
class TestTrackingParams:
    def test_tracking_param_detected_but_not_removed(self, normalizer: URLNormalizer) -> None:
        result = normalizer.normalize("https://example.com/?utm_source=x&y=1", _ctx())
        assert result.structured["tracking_params_detected"] == ["utm_source"]
        assert result.display is not None
        assert "utm_source=x" in result.display  # never silently stripped
        assert QualityFlag.POTENTIAL_COLLISION in result.flags

    def test_no_tracking_params_no_flag(self, normalizer: URLNormalizer) -> None:
        result = normalizer.normalize("https://example.com/?y=1", _ctx())
        assert result.structured["tracking_params_detected"] == []
        assert QualityFlag.POTENTIAL_COLLISION not in result.flags


@pytest.mark.unit
class TestFragmentPreserved:
    def test_fragment_kept(self, normalizer: URLNormalizer) -> None:
        result = normalizer.normalize("https://example.com/#section", _ctx())
        assert result.display is not None
        assert result.display.endswith("#section")


@pytest.mark.unit
class TestOriginalNeverMutated:
    def test_original_field_is_raw_input(self, normalizer: URLNormalizer) -> None:
        raw = "HTTP://Example.COM:80/Path/"
        result = normalizer.normalize(raw, _ctx())
        assert result.original == raw

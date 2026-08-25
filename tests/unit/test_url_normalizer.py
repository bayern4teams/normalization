"""Unit tests for URLNormalizer — Source.txt §42, §99.

Assertions check every field `normalize()` sets for each real code path
(not just one field per case) — found via a real mutmut run (M12) that
this function alone had 53 surviving mutants, most of them literal
constants (confidence values, empty-string defaults, comparison
operators) no existing assertion actually pinned down.

Also covers a real bug found while designing these tests (not a
mutation-coverage gap): `parts.port` is a lazy `urllib.parse` property
that raises `ValueError` for a malformed port ("http://host:abc/") only
when accessed — `normalize()` used to access it *outside* the
try/except that catches `urlsplit()`'s own errors, so a single
malformed port crashed the whole call uncaught instead of producing the
INVALID result this normalizer exists to give it. Fixed in
normalizers/url.py alongside these tests; `test_malformed_port_is_invalid_not_a_crash`
is the regression test.
"""

from __future__ import annotations

import pytest
from normalizers.url import URLNormalizer
from normcore.context import NormalizationContext
from normcore.enums import (
    FieldSemanticType,
    MissingKind,
    NormalizationStatus,
    QualityFlag,
    Reversibility,
)


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
        assert result.original is None
        assert result.original_kind is MissingKind.NULL
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.validation_status == "MISSING"
        assert result.confidence == 1.0
        assert result.display is None
        assert result.errors == []
        assert result.warnings == []
        assert result.profile_version == ""
        assert result.env_id == ""

    def test_empty(self, normalizer: URLNormalizer) -> None:
        result = normalizer.normalize("", _ctx())
        assert result.original == ""
        assert result.original_kind is MissingKind.EMPTY_STRING
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.validation_status == "MISSING"
        assert result.confidence == 1.0

    def test_whitespace_only_is_treated_as_empty(self, normalizer: URLNormalizer) -> None:
        result = normalizer.normalize("   ", _ctx())
        assert result.original_kind is MissingKind.EMPTY_STRING


@pytest.mark.unit
class TestInvalidUrls:
    def test_malformed_port_is_invalid_not_a_crash(self, normalizer: URLNormalizer) -> None:
        """Regression test: `parts.port` used to be accessed outside the
        try/except that catches urlsplit()'s own ValueErrors, so this
        raised uncaught instead of returning an INVALID result. Verified
        the crash was real (not theoretical) before fixing."""
        result = normalizer.normalize("http://example.com:abc/", _ctx())
        assert result.normalization_status is NormalizationStatus.INVALID
        assert result.validation_status == "INVALID"
        assert result.original == "http://example.com:abc/"
        assert result.display == "http://example.com:abc/"
        assert result.comparison is None
        assert result.structured == {}
        assert result.confidence == 0.0
        assert result.errors == ["Port could not be cast to integer value as 'abc'"]
        assert result.warnings == []
        assert result.flags == []
        assert len(result.trace) == 1
        assert result.trace[0].changed is False
        assert result.lossiness is Reversibility.LOSSLESS
        assert result.profile_version == ""
        assert result.env_id == ""

    def test_malformed_ipv6_is_invalid(self, normalizer: URLNormalizer) -> None:
        result = normalizer.normalize("http://[::1/path", _ctx())
        assert result.normalization_status is NormalizationStatus.INVALID
        assert result.errors == ["Invalid IPv6 URL"]
        assert result.confidence == 0.0

    def test_missing_scheme_is_invalid(self, normalizer: URLNormalizer) -> None:
        result = normalizer.normalize("example.com/path", _ctx())
        assert result.normalization_status is NormalizationStatus.INVALID
        assert result.validation_status == "INVALID"
        assert result.original == "example.com/path"
        assert result.display == "example.com/path"
        assert result.errors == ["not an absolute URL (missing scheme or host)"]
        assert result.confidence == 0.0
        assert result.structured == {}
        assert len(result.trace) == 1
        assert result.trace[0].changed is False
        assert result.lossiness is Reversibility.LOSSLESS
        assert result.profile_version == ""
        assert result.env_id == ""

    def test_scheme_without_netloc_is_invalid(self, normalizer: URLNormalizer) -> None:
        result = normalizer.normalize("mailto:foo@example.com", _ctx())
        assert result.normalization_status is NormalizationStatus.INVALID
        assert result.errors == ["not an absolute URL (missing scheme or host)"]

    def test_not_a_url_at_all_is_invalid(self, normalizer: URLNormalizer) -> None:
        result = normalizer.normalize("not a url", _ctx())
        assert result.normalization_status is NormalizationStatus.INVALID


@pytest.mark.unit
class TestSchemeAndHost:
    def test_scheme_lowercased(self, normalizer: URLNormalizer) -> None:
        result = normalizer.normalize("HTTP://example.com/", _ctx())
        assert result.display == "http://example.com/"
        assert result.structured["scheme"] == "http"

    def test_host_lowercased(self, normalizer: URLNormalizer) -> None:
        result = normalizer.normalize("http://EXAMPLE.com/", _ctx())
        assert result.structured["host"] == "example.com"
        assert result.display == "http://example.com/"


@pytest.mark.unit
class TestDefaultPortRemoval:
    def test_http_default_port_removed(self, normalizer: URLNormalizer) -> None:
        result = normalizer.normalize("http://example.com:80/", _ctx())
        assert result.display == "http://example.com/"
        assert result.comparison == "http://example.com"
        assert result.structured["port"] == 80

    def test_https_default_port_removed(self, normalizer: URLNormalizer) -> None:
        result = normalizer.normalize("https://example.com:443/", _ctx())
        assert result.display == "https://example.com/"
        assert result.structured["port"] == 443

    def test_non_default_port_kept(self, normalizer: URLNormalizer) -> None:
        result = normalizer.normalize("http://example.com:8080/", _ctx())
        assert result.display == "http://example.com:8080/"
        assert result.comparison == "http://example.com:8080"
        assert result.structured["port"] == 8080


@pytest.mark.unit
class TestPercentEncodingNormalization:
    def test_unreserved_char_decoded(self, normalizer: URLNormalizer) -> None:
        """Source.txt §42: percent-encoding normalized "where safe" — '~'
        (0x7E) is RFC 3986 unreserved, always safe to decode."""
        result = normalizer.normalize("https://example.com/a%7Eb", _ctx())
        assert result.display == "https://example.com/a~b"
        assert result.structured["path"] == "/a~b"

    def test_reserved_char_stays_encoded(self, normalizer: URLNormalizer) -> None:
        """'/' (0x2F) is reserved — decoding it inside a path segment would
        change the URL's structure, so it must stay encoded."""
        result = normalizer.normalize("https://example.com/a%2Fb", _ctx())
        assert result.display == "https://example.com/a%2Fb"
        assert result.structured["path"] == "/a%2Fb"

    def test_hex_digits_uppercased(self, normalizer: URLNormalizer) -> None:
        result = normalizer.normalize("https://example.com/a%2fb", _ctx())
        assert result.display == "https://example.com/a%2Fb"


@pytest.mark.unit
class TestIdnNormalization:
    def test_unicode_host_converted_to_punycode(self, normalizer: URLNormalizer) -> None:
        result = normalizer.normalize("https://münchen.de/", _ctx())
        assert result.structured["host"] == "xn--mnchen-3ya.de"
        assert result.structured["is_idn"] is True
        assert result.display == "https://xn--mnchen-3ya.de/"
        assert result.confidence == 1.0
        assert result.flags == []
        assert result.warnings == []

    def test_ascii_host_not_marked_idn(self, normalizer: URLNormalizer) -> None:
        result = normalizer.normalize("https://example.com/", _ctx())
        assert result.structured["is_idn"] is False

    def test_invalid_idna_label_falls_back_with_diagnostics(
        self, normalizer: URLNormalizer
    ) -> None:
        """A non-ASCII host label that fails real `idna.encode()` (a
        disallowed codepoint, verified live) is left as-is rather than
        raising — but must be flagged, not silently treated as fully
        successful."""
        result = normalizer.normalize("https://\U0001f600example.de/path", _ctx())
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.validation_status == "VALID"
        assert result.structured["is_idn"] is False
        assert result.confidence == 0.7
        assert QualityFlag.PARSER_FALLBACK in result.flags
        assert len(result.warnings) == 1
        assert "is not valid IDNA" in result.warnings[0]


@pytest.mark.unit
class TestTrailingSlashPolicy:
    def test_root_path_equivalent_in_comparison(self, normalizer: URLNormalizer) -> None:
        with_slash = normalizer.normalize("https://example.com/", _ctx())
        without_slash = normalizer.normalize("https://example.com", _ctx())
        assert with_slash.comparison == without_slash.comparison == "https://example.com"
        assert with_slash.display == "https://example.com/"
        assert without_slash.display == "https://example.com"
        assert without_slash.structured["path"] == ""

    def test_non_root_trailing_slash_never_stripped_from_display(
        self, normalizer: URLNormalizer
    ) -> None:
        result = normalizer.normalize("https://example.com/path/", _ctx())
        assert result.display == "https://example.com/path/"
        assert result.comparison == "https://example.com/path/"


@pytest.mark.unit
class TestTrackingParams:
    def test_tracking_param_detected_but_not_removed(self, normalizer: URLNormalizer) -> None:
        result = normalizer.normalize("https://example.com/?utm_source=x&y=1", _ctx())
        assert result.structured["tracking_params_detected"] == ["utm_source"]
        assert result.display is not None
        assert "utm_source=x" in result.display  # never silently stripped
        assert QualityFlag.POTENTIAL_COLLISION in result.flags
        assert result.warnings == [
            "query contains known tracking parameters ['utm_source'] "
            "(not removed — §42 forbids stripping query parameters blindly)"
        ]

    def test_no_tracking_params_no_flag(self, normalizer: URLNormalizer) -> None:
        result = normalizer.normalize("https://example.com/?y=1", _ctx())
        assert result.structured["tracking_params_detected"] == []
        assert QualityFlag.POTENTIAL_COLLISION not in result.flags
        assert result.warnings == []


@pytest.mark.unit
class TestUserinfo:
    def test_username_without_password_has_no_colon(self, normalizer: URLNormalizer) -> None:
        result = normalizer.normalize("http://user@example.com/", _ctx())
        assert result.display == "http://user@example.com/"
        userinfo = result.display.removeprefix("http://").split("@")[0]
        assert userinfo == "user"

    def test_empty_host_with_userinfo_present_falls_back_to_empty_host(
        self, normalizer: URLNormalizer
    ) -> None:
        """`parts.hostname` is `None` here (netloc is just "user@", no
        actual host) — `_normalize_host` must fall back to the empty
        string, not swallow the missing host into a fabricated one, and
        `is_idn`'s own `parts.hostname or ""` must agree with it."""
        result = normalizer.normalize("http://user@/path", _ctx())
        assert result.display == "http://user@/path"
        assert result.structured == {
            "scheme": "http",
            "host": "",
            "port": None,
            "path": "/path",
            "query": "",
            "fragment": "",
            "is_idn": False,
            "tracking_params_detected": [],
        }
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.confidence == 1.0
        assert result.warnings == []


@pytest.mark.unit
class TestFragmentPreserved:
    def test_fragment_kept(self, normalizer: URLNormalizer) -> None:
        result = normalizer.normalize("https://example.com/#section", _ctx())
        assert result.display == "https://example.com/#section"
        assert result.comparison == "https://example.com#section"
        assert result.structured["fragment"] == "section"


@pytest.mark.unit
class TestOriginalNeverMutated:
    def test_original_field_is_raw_input(self, normalizer: URLNormalizer) -> None:
        raw = "HTTP://Example.COM:80/Path/"
        result = normalizer.normalize(raw, _ctx())
        assert result.original == raw


@pytest.mark.unit
class TestFullyPopulatedValidResult:
    def test_every_field_on_a_representative_valid_url(self, normalizer: URLNormalizer) -> None:
        """One case exercising userinfo+password+default-port-removal+
        percent-decoding+tracking-param+fragment together, asserting
        every NormalizedValue field's exact value against real library
        output (verified live before writing this assertion)."""
        raw = "HTTP://user:pass@EXAMPLE.com:80/a%7Eb%2Fc?utm_source=x&y=1#frag"
        result = normalizer.normalize(raw, _ctx())

        assert result.original == raw
        assert result.display == "http://user:pass@example.com/a~b%2Fc?utm_source=x&y=1#frag"
        assert result.comparison == result.display
        assert result.search == result.display
        assert result.structured == {
            "scheme": "http",
            "host": "example.com",
            "port": 80,
            "path": "/a~b%2Fc",
            "query": "utm_source=x&y=1",
            "fragment": "frag",
            "is_idn": False,
            "tracking_params_detected": ["utm_source"],
        }
        assert result.validation_status == "VALID"
        assert result.normalization_status is NormalizationStatus.NORMALIZED
        assert result.confidence == 1.0
        assert result.flags == [QualityFlag.POTENTIAL_COLLISION]
        assert result.errors == []
        assert len(result.warnings) == 1
        assert len(result.trace) == 1
        assert result.trace[0].changed is True
        assert result.trace[0].library == "idna/urllib.parse"
        assert result.lossiness is Reversibility.PARTIALLY_REVERSIBLE
        assert result.profile_version == ""
        assert result.env_id == ""

"""URLNormalizer — Source.txt §42, §99 (closes a gap: §99 lists
URLNormalizer among the required adapters but no M2-M5 milestone
registered `FieldSemanticType.URL`, so it silently fell through to
`PassthroughNormalizer`).

Implements exactly the operations §42 lists, and nothing beyond them:

- scheme normalization (lowercased)
- host lowercasing
- default port removal (":80" for http, ":443" for https)
- percent-encoding normalization "where safe" (RFC 3986 §2.3: decode only
  unreserved characters, uppercase remaining hex digits) — applied
  uniformly to path/query/fragment since this transform is safe
  *regardless* of component by construction, not a per-component guess
- IDN normalization (punycode via the `idna` package, RFC 5891)
- fragment policy: preserved verbatim, never stripped
- trailing-slash policy: a bare root path ("/") is treated as equivalent
  to no path in `comparison`/`search`, but `display` never removes a
  trailing slash from a non-root path (§42 forbids stripping query
  parameters blindly, and by the same logic path segments are never
  silently dropped)
- tracking-parameter policy: NEVER strips query parameters (§42's
  explicit prohibition) — known tracking parameter names are flagged in
  `structured.tracking_params_detected` for a caller/profile to act on,
  purely diagnostic, no silent removal

- registrable domain (D9): `registrable_domain`, `public_suffix`,
  `is_private_suffix` (PSL PRIVATE section, so a hosting-provider suffix is
  told apart from an ICANN one) and `registrable_domain_reason`, computed
  from the A-label host by `publicsuffixlist` against the Public Suffix List
  snapshot bundled in the package. The library has no fetch code on its
  import/query path, so network access is off by construction. Snapshot: PSL
  VERSION 2026-09-30_20-56-07_UTC (publicsuffixlist 1.0.2.20261003, whose
  version carries the snapshot date); it moves with the pinned package,
  which is in `FINGERPRINTED_PACKAGES`, so a PSL update changes `env_id`.
  IP literals, single labels, unlisted suffixes and a host that is itself a
  public suffix give `registrable_domain = None` with a reason, never "the
  last two labels".

URL standard: this module follows RFC 3986 (generic syntax via
`urllib.parse`) with IDNA 2008 (RFC 5891, the `idna` package) for hosts. It
is NOT the WHATWG URL Standard: there is no UTS #46 mapping, no backslash or
special-scheme host parsing and no IPv4 number-form canonicalisation. This is
a statement of what the code already does; behaviour is unchanged.

Per-field configuration (which of these to apply, custom tracking-param
lists) is not wired through `NormalizationContext` — the same disclosed
gap carried across every M2-M5 normalizer (profile-driven per-field
config isn't threaded into `Normalizer.normalize()` yet).
"""

from __future__ import annotations

import ipaddress
import re
from typing import TYPE_CHECKING
from urllib.parse import SplitResult, urlsplit, urlunsplit

import blake3
import idna
import pyarrow as pa
from normcore.context import NormalizationContext
from normcore.enums import (
    FieldSemanticType,
    MissingKind,
    NormalizationStatus,
    QualityFlag,
    Reversibility,
)
from normcore.models import NormalizedValue
from normcore.pii import character_class_mask, content_hash
from normcore.rules import ComponentVersionInfo, ExplanationText, ValidationOutcome
from normcore.trace import TraceStep

# upstream ships no py.typed/stubs (re-check at milestone gates)
from publicsuffixlist import PublicSuffixList  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Sequence

    from normcore.interfaces import ComponentVersion, Explanation, StepSpec, ValidationResult

_VERSION = "0.1.0"

# A bare host states no scheme. It is parsed under each of these so the host
# and registrable domain (which it does state) are reported, and the URL
# itself is AMBIGUOUS between them: picking https was a guess (PART1 N3).
_BARE_HOST_SCHEMES = ("http", "https")


def _looks_like_bare_host(value: str) -> bool:
    """Is this a hostname someone wrote without a scheme?

    Real website columns are full of `www.example.com` — a perfectly
    valid site address that `urlsplit` reports as a bare *path* with no
    scheme and no host, which used to make it INVALID. Measured on a real
    1.27M-row website column: 1,227,979 of 1,266,268 values (97%) were
    rejected this way.

    Deliberately conservative, and deliberately not a TLD list (which
    would need perpetual updating). Requires: no whitespace, at least two
    dot-separated labels, all non-empty, and a final label that is purely
    alphabetic and at least two characters. That accepts `example.com`
    and `example.com/path`, and rejects `3.14`, `192.168.1.1` and
    `hello world`. A syntactically host-shaped non-host like
    `notes.txt` does slip through — it is indistinguishable from a real
    hostname without a TLD list, and the result is still flagged and
    reported as an assumption rather than presented as fact.
    """
    host = value.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    if not host or any(c.isspace() for c in host):
        return False
    labels = host.rsplit("@", 1)[-1].split(".")
    if len(labels) < 2 or not all(labels):
        return False
    tld = labels[-1].split(":", 1)[0]  # drop any :port
    return len(tld) >= 2 and tld.isalpha()


# Offline by construction: the snapshot is read from the package, and the
# library's updater is a separate module that is never imported here.
# `accept_unknown=False`: a suffix the list does not carry is not guessed.
# The ICANN-only view exists to tell the PRIVATE section apart: a host is
# under a private suffix exactly when the two views disagree on its suffix.
# ponytail: the PSL snapshot is the one bundled in the pinned package; a newer
# suffix is unknown (-> None, never guessed) until the dependency is bumped,
# which moves env_id. Upgrade path: a scheduled dependency bump, never a fetch.
_PSL = PublicSuffixList(accept_unknown=False)
_PSL_ICANN = PublicSuffixList(accept_unknown=False, only_icann=True)


# LDH labels (RFC 1123) plus "_", which DNS carries in service names.
_HOST_CHARS = re.compile(r"[a-z0-9._-]+")


def _registrable(host: str, *, idn_ok: bool) -> dict[str, object]:
    """Registrable domain of an A-label `host`, or None with a reason."""
    none: dict[str, object] = {
        "registrable_domain": None,
        "public_suffix": None,
        "is_private_suffix": None,
    }
    if not host:
        return {**none, "registrable_domain_reason": "no host"}
    if not idn_ok:
        return {**none, "registrable_domain_reason": "host is not valid IDNA"}
    if not _HOST_CHARS.fullmatch(host):
        return {
            **none,
            "registrable_domain_reason": "host has characters a domain name cannot carry",
        }
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return {**none, "registrable_domain_reason": "host is an IP address"}
    suffix = _PSL.publicsuffix(host)
    if suffix is None:
        why = (
            "single-label host has no public suffix"
            if "." not in host
            else "host's suffix is not in the Public Suffix List"
        )
        return {**none, "registrable_domain_reason": why}
    registrable = _PSL.privatesuffix(host)
    return {
        "registrable_domain": registrable,
        "public_suffix": suffix,
        "is_private_suffix": suffix != _PSL_ICANN.publicsuffix(host),
        "registrable_domain_reason": (None if registrable else "host is itself a public suffix"),
    }


_PARSE_PARAMS_HASH = blake3.blake3(b"{}").hexdigest()

_DEFAULT_PORTS = {"http": "80", "https": "443", "ftp": "21"}
_RECOGNIZED_SCHEMES = frozenset({"http", "https", "ftp"})

# RFC 3986 §2.3 unreserved characters — the only ones it is ever safe to
# percent-decode without changing meaning, regardless of URL component.
_UNRESERVED = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")

# Curated, not exhaustive (this project's established "curated subset,
# extend on evidence" policy for every lookup table) — purely diagnostic,
# never used to remove anything.
_KNOWN_TRACKING_PARAMS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "gclid",
        "fbclid",
        "msclkid",
        "mc_cid",
        "mc_eid",
        "igshid",
    }
)


class _StaticStepSpec:
    def __init__(self, step_id: str, operation: str, reversibility: Reversibility, lossy: bool):
        self.step_id = step_id
        self.operation = operation
        self.claimed_reversibility = reversibility
        self.lossy = lossy


_NORMALIZE_STEP = _StaticStepSpec(
    "url.normalize", "url.normalize", Reversibility.PARTIALLY_REVERSIBLE, False
)
_STATIC_STEPS: tuple[_StaticStepSpec, ...] = (_NORMALIZE_STEP,)


class URLNormalizer:
    name = "URLNormalizer"
    supported_types = frozenset({FieldSemanticType.URL})

    def can_handle(self, field_type: FieldSemanticType, ctx: NormalizationContext) -> bool:
        return field_type in self.supported_types

    def normalize(self, value: str | None, ctx: NormalizationContext) -> NormalizedValue:
        if value is None:
            return _missing(None, MissingKind.NULL, ctx)
        if value.strip() == "":
            return _missing(value, MissingKind.EMPTY_STRING, ctx)

        cleaned = value.strip()
        try:
            parts = urlsplit(cleaned)
        except ValueError as exc:
            return _invalid(value, ctx, reason=str(exc))

        # No scheme AND no host means urlsplit found only a path — either
        # genuine garbage, or a bare hostname written without a scheme.
        # Try the repair before rejecting; `_looks_like_bare_host` is what
        # keeps this from turning arbitrary text into a URL.
        #
        # Requiring an absent scheme matters: `mailto:a@b.com` also has an
        # empty netloc, and its "b.com" IS host-shaped, so testing the
        # netloc alone rewrote it to `https://mailto:a@b.com`. Caught by
        # running the case, not by reading the code. The cost of this
        # stricter test is that `example.com:8080` (which urlsplit reads
        # as scheme "example.com") is not repaired — it stays INVALID
        # exactly as it was before, so nothing regresses.
        scheme_assumed = False
        if not parts.scheme and not parts.netloc and _looks_like_bare_host(cleaned):
            candidate = f"{_BARE_HOST_SCHEMES[-1]}://{cleaned}"
            try:
                repaired_parts = urlsplit(candidate)
            except ValueError:
                repaired_parts = None
            if repaired_parts is not None and repaired_parts.netloc:
                cleaned, parts, scheme_assumed = candidate, repaired_parts, True

        if not parts.scheme or not parts.netloc:
            return _invalid(value, ctx, reason="not an absolute URL (missing scheme or host)")

        scheme = parts.scheme.lower()
        flags: list[QualityFlag] = []
        warnings: list[str] = []
        if scheme_assumed:
            # Flagged as before, so type detection still does not count a
            # bare host as clean evidence that a column holds URLs.
            flags.append(QualityFlag.PARSER_FALLBACK)
            warnings.append("no scheme in input: http and https are both readings")

        host, idn_ok = _normalize_host(parts.hostname or "")
        if not idn_ok:
            flags.append(QualityFlag.PARSER_FALLBACK)
            warnings.append(f"host label in {parts.hostname!r} is not valid IDNA; left as-is")

        userinfo = ""
        if parts.username:
            password_part = f":{parts.password}" if parts.password else ""
            userinfo = f"{parts.username}{password_part}@"
        port = _normalize_port(scheme, parts.port)
        netloc = f"{userinfo}{host}{port}"

        path = _normalize_percent_encoding(parts.path)
        query = _normalize_percent_encoding(parts.query)
        fragment = _normalize_percent_encoding(parts.fragment)

        display = urlunsplit(SplitResult(scheme, netloc, path, query, fragment))

        comparison_path = "" if path == "/" else path
        comparison = urlunsplit(SplitResult(scheme, netloc, comparison_path, query, fragment))

        tracking_params = sorted(_detect_tracking_params(query))
        if tracking_params:
            flags.append(QualityFlag.POTENTIAL_COLLISION)
            warnings.append(
                f"query contains known tracking parameters {tracking_params} "
                "(not removed — §42 forbids stripping query parameters blindly)"
            )

        structured = {
            "scheme": scheme,
            "host": host,
            "port": parts.port,
            "path": path,
            "query": query,
            "fragment": fragment,
            "is_idn": host != (parts.hostname or "").lower(),
            "tracking_params_detected": tracking_params,
            "scheme_assumed": scheme_assumed,
            **_registrable(host, idn_ok=idn_ok),
        }

        if scheme_assumed:
            return NormalizedValue(
                original=value,
                display=value.strip(),
                structured={
                    **structured,
                    "scheme": None,
                    "candidates": [
                        {
                            "scheme": candidate,
                            "url": urlunsplit(
                                SplitResult(
                                    candidate,
                                    f"{userinfo}{host}{_normalize_port(candidate, parts.port)}",
                                    path,
                                    query,
                                    fragment,
                                )
                            ),
                        }
                        for candidate in _BARE_HOST_SCHEMES
                    ],
                },
                validation_status="AMBIGUOUS",
                normalization_status=NormalizationStatus.AMBIGUOUS,
                confidence=0.5,
                flags=flags,
                warnings=warnings,
                trace=[_normalize_trace_step(value, changed=False)],
                lossiness=Reversibility.LOSSLESS,
                profile_version="",
                env_id="",
                semantic_type=ctx.semantic_type,
                context_hash=ctx.context_hash,
            )

        return NormalizedValue(
            original=value,
            display=display,
            comparison=comparison,
            search=comparison,
            structured=structured,
            validation_status="VALID",
            normalization_status=NormalizationStatus.NORMALIZED,
            confidence=1.0 if idn_ok else 0.7,
            flags=flags,
            warnings=warnings,
            trace=[_normalize_trace_step(value, changed=(display != cleaned))],
            lossiness=Reversibility.PARTIALLY_REVERSIBLE,
            profile_version="",
            env_id="",
            semantic_type=ctx.semantic_type,
            context_hash=ctx.context_hash,
        )

    def normalize_batch(self, values: pa.Array, ctx: NormalizationContext) -> pa.StructArray:
        results = [self.normalize(v, ctx) for v in values.to_pylist()]
        return pa.StructArray.from_arrays(
            [
                pa.array([r.original for r in results], type=pa.large_string()),
                pa.array([r.display for r in results], type=pa.large_string()),
                pa.array([r.comparison for r in results], type=pa.large_string()),
                pa.array([r.normalization_status.value for r in results], type=pa.large_string()),
            ],
            names=["original", "display", "comparison", "status"],
        )

    def validate(self, value: str | None, ctx: NormalizationContext) -> ValidationResult:
        result = self.normalize(value, ctx)
        if result.original_kind is not None:
            return ValidationOutcome(
                is_valid=False, status="MISSING", reason=result.original_kind.value
            )
        # A bare host is a URL whose scheme is unstated, not a non-URL.
        is_valid = result.normalization_status in (
            NormalizationStatus.NORMALIZED,
            NormalizationStatus.AMBIGUOUS,
        )
        return ValidationOutcome(
            is_valid=is_valid,
            status=result.validation_status or "UNKNOWN",
            reason=None if is_valid else "not a valid absolute URL",
        )

    def explain(self, result: NormalizedValue) -> Explanation:
        if result.normalization_status is NormalizationStatus.INVALID:
            return ExplanationText(
                plain_language="Not a valid absolute URL.",
                technical=f"errors={result.errors}",
            )
        return ExplanationText(
            plain_language=f"Normalized to {result.display}.",
            technical=f"structured={result.structured}",
        )

    def version(self) -> ComponentVersion:
        return ComponentVersionInfo(name=self.name, version=_VERSION)

    def steps(self) -> Sequence[StepSpec]:
        return _STATIC_STEPS

    def inverse(self, step_id: str, value: str) -> str | None:
        return None


def _normalize_host(hostname: str) -> tuple[str, bool]:
    if not hostname:
        return "", True
    lowered = hostname.lower()
    if lowered.isascii():
        return lowered, True
    labels = lowered.split(".")
    encoded_labels = []
    ok = True
    for label in labels:
        try:
            encoded_labels.append(idna.encode(label).decode("ascii"))
        except idna.IDNAError:
            encoded_labels.append(label)
            ok = False
    return ".".join(encoded_labels), ok


def _normalize_port(scheme: str, port: int | None) -> str:
    if port is None:
        return ""
    if _DEFAULT_PORTS.get(scheme) == str(port):
        return ""
    return f":{port}"


def _normalize_percent_encoding(component: str) -> str:
    """RFC 3986 §2.3: decode %XX sequences that represent an unreserved
    character back to the literal character, and uppercase the hex
    digits of any %XX sequence left encoded — this is the one
    percent-encoding transform that never changes a URL's meaning."""
    if "%" not in component:
        return component

    result: list[str] = []
    i = 0
    length = len(component)
    while i < length:
        ch = component[i]
        if ch == "%" and i + 2 < length and _is_hex(component[i + 1]) and _is_hex(component[i + 2]):
            hex_digits = component[i + 1 : i + 3]
            code_point = int(hex_digits, 16)
            decoded_char = chr(code_point)
            if decoded_char in _UNRESERVED:
                result.append(decoded_char)
            else:
                result.append(f"%{hex_digits.upper()}")
            i += 3
        else:
            result.append(ch)
            i += 1
    return "".join(result)


def _is_hex(ch: str) -> bool:
    return ch in "0123456789abcdefABCDEF"


def _detect_tracking_params(query: str) -> set[str]:
    if not query:
        return set()
    found: set[str] = set()
    for pair in query.split("&"):
        key = pair.split("=", 1)[0]
        if key in _KNOWN_TRACKING_PARAMS:
            found.add(key)
    return found


def _invalid(value: str, ctx: NormalizationContext, *, reason: str) -> NormalizedValue:
    return NormalizedValue(
        original=value,
        display=value,
        normalization_status=NormalizationStatus.INVALID,
        validation_status="INVALID",
        confidence=0.0,
        errors=[reason],
        structured={},
        trace=[_normalize_trace_step(value, changed=False)],
        lossiness=Reversibility.LOSSLESS,
        profile_version="",
        env_id="",
        semantic_type=ctx.semantic_type,
        context_hash=ctx.context_hash,
    )


def _missing(value: str | None, kind: MissingKind, ctx: NormalizationContext) -> NormalizedValue:
    return NormalizedValue(
        original=value,
        original_kind=kind,
        normalization_status=NormalizationStatus.NORMALIZED,
        validation_status="MISSING",
        confidence=1.0,
        profile_version="",
        env_id="",
        semantic_type=ctx.semantic_type,
        context_hash=ctx.context_hash,
    )


def _normalize_trace_step(value: str, *, changed: bool) -> TraceStep:
    return TraceStep(
        step_order=1,
        rule_id="url.normalize",
        operation="url.normalize",
        params_hash=_PARSE_PARAMS_HASH,
        input_hash=content_hash(value),
        output_hash=content_hash(value),
        input_mask=character_class_mask(value),
        output_mask=character_class_mask(value),
        changed=changed,
        lossy=False,
        reversibility=Reversibility.PARTIALLY_REVERSIBLE,
        library="idna/urllib.parse",
        library_version=str(idna.__version__),
    )

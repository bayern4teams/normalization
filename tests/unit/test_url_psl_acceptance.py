"""Independent acceptance checks for D9 (registrable domain from the Public Suffix List).

Derived from docs/plans/DEFECTS_IMPLEMENTATION_PLAN.md section 9 (D9 *Accept*), section 2.4 and
docs/improvement-report.md D9 / Part 2 "URL", not from the implementation. Target contract:

* URL normalizer `structured` gains, additively, `registrable_domain` (str | None),
  `public_suffix` (str | None), `is_private_suffix` (bool | None) and
  `registrable_domain_reason` (non-empty str, present when `registrable_domain` is None).
* Computed from a PSL library with a pinned snapshot and no network by construction
  (`tldextract` with fetching disabled, or `publicsuffixlist`), registered in
  `normexec.env_fingerprint.FINGERPRINTED_PACKAGES`.
* IP literals, localhost, single labels, unlisted suffixes, a bare public suffix:
  registrable_domain None with a reason, never the last two labels.
* IDN: one declared form is computed, the other must give the consistent answer.
* Every pre-existing output is byte-identical: `_BEFORE_D9` below was produced by running the
  URL normalizer BEFORE any D9 change, on branch feat/defects-fixes, 2026-10-05.

Nothing here lists suffixes by hand to compute an answer: expected values come from the shared
fixture table (`tests/defects/fixtures_phase1.py`, verified against publicsuffix.org) plus two
wildcard-rule probes (`*.ck`, `!www.ck`) that a hand-written two-level table cannot satisfy.
"""

from __future__ import annotations

import ast
import socket
import subprocess
import sys
import textwrap
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version
from pathlib import Path
from typing import Any

import pytest
from normalizers.url import URLNormalizer
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType, NormalizationStatus
from normexec.env_fingerprint import FINGERPRINTED_PACKAGES
from publicsuffixlist import PublicSuffixList  # type: ignore[import-untyped]

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # tests/ holds the `defects` package
from defects.fixtures_phase1 import (
    D9_CASES,
    UrlCase,
    naive_registrable_domain,
    registrable_answers,
)

pytestmark = pytest.mark.unit

_NEW_KEYS = frozenset(
    {"registrable_domain", "public_suffix", "is_private_suffix", "registrable_domain_reason"}
)
_PSL_PACKAGES = ("tldextract", "publicsuffixlist")  # either is acceptable (plan 9 D9)
_URL_SRC = Path(__file__).resolve().parents[2] / "packages/normalizers/src/normalizers/url.py"
_CASE_IDS = [c.id for c in D9_CASES]


def _run(url: str) -> Any:
    ctx = NormalizationContext(field_name="u", semantic_type=FieldSemanticType.URL)
    return URLNormalizer().normalize(url, ctx)


def _punycode(domain: str) -> str:
    return domain.encode("idna").decode("ascii")


# Full URLNormalizer output for 14 inputs, captured by running the current (pre-D9) code.
# `structured` is compared after removing the four new D9 keys.
_BEFORE_D9: dict[str, dict[str, Any]] = {
    "https://a.co.uk/": {
        "display": "https://a.co.uk/",
        "comparison": "https://a.co.uk",
        "search": "https://a.co.uk",
        "structured": {
            "scheme": "https",
            "host": "a.co.uk",
            "port": None,
            "path": "/",
            "query": "",
            "fragment": "",
            "is_idn": False,
            "tracking_params_detected": [],
            "scheme_assumed": False,
        },
        "normalization_status": "NORMALIZED",
        "validation_status": "VALID",
        "confidence": 1.0,
        "flags": [],
        "warnings": [],
    },
    "HTTP://EXAMPLE.com:80/Path%7e/x?utm_source=a&b=%7e#Frag": {
        "display": "http://example.com/Path~/x?utm_source=a&b=~#Frag",
        "comparison": "http://example.com/Path~/x?utm_source=a&b=~#Frag",
        "search": "http://example.com/Path~/x?utm_source=a&b=~#Frag",
        "structured": {
            "scheme": "http",
            "host": "example.com",
            "port": 80,
            "path": "/Path~/x",
            "query": "utm_source=a&b=~",
            "fragment": "Frag",
            "is_idn": False,
            "tracking_params_detected": ["utm_source"],
            "scheme_assumed": False,
        },
        "normalization_status": "NORMALIZED",
        "validation_status": "VALID",
        "confidence": 1.0,
        "flags": ["POTENTIAL_COLLISION"],
        "warnings": [
            "query contains "
            "known tracking "
            "parameters "
            "['utm_source'] (not "
            "removed — §42 "
            "forbids stripping "
            "query parameters "
            "blindly)"
        ],
    },
    "https://b.a.co.uk/x": {
        "display": "https://b.a.co.uk/x",
        "comparison": "https://b.a.co.uk/x",
        "search": "https://b.a.co.uk/x",
        "structured": {
            "scheme": "https",
            "host": "b.a.co.uk",
            "port": None,
            "path": "/x",
            "query": "",
            "fragment": "",
            "is_idn": False,
            "tracking_params_detected": [],
            "scheme_assumed": False,
        },
        "normalization_status": "NORMALIZED",
        "validation_status": "VALID",
        "confidence": 1.0,
        "flags": [],
        "warnings": [],
    },
    "https://x.github.io/": {
        "display": "https://x.github.io/",
        "comparison": "https://x.github.io",
        "search": "https://x.github.io",
        "structured": {
            "scheme": "https",
            "host": "x.github.io",
            "port": None,
            "path": "/",
            "query": "",
            "fragment": "",
            "is_idn": False,
            "tracking_params_detected": [],
            "scheme_assumed": False,
        },
        "normalization_status": "NORMALIZED",
        "validation_status": "VALID",
        "confidence": 1.0,
        "flags": [],
        "warnings": [],
    },
    "https://例え.jp/": {
        "display": "https://xn--r8jz45g.jp/",
        "comparison": "https://xn--r8jz45g.jp",
        "search": "https://xn--r8jz45g.jp",
        "structured": {
            "scheme": "https",
            "host": "xn--r8jz45g.jp",
            "port": None,
            "path": "/",
            "query": "",
            "fragment": "",
            "is_idn": True,
            "tracking_params_detected": [],
            "scheme_assumed": False,
        },
        "normalization_status": "NORMALIZED",
        "validation_status": "VALID",
        "confidence": 1.0,
        "flags": [],
        "warnings": [],
    },
    "https://xn--r8jz45g.jp/": {
        "display": "https://xn--r8jz45g.jp/",
        "comparison": "https://xn--r8jz45g.jp",
        "search": "https://xn--r8jz45g.jp",
        "structured": {
            "scheme": "https",
            "host": "xn--r8jz45g.jp",
            "port": None,
            "path": "/",
            "query": "",
            "fragment": "",
            "is_idn": False,
            "tracking_params_detected": [],
            "scheme_assumed": False,
        },
        "normalization_status": "NORMALIZED",
        "validation_status": "VALID",
        "confidence": 1.0,
        "flags": [],
        "warnings": [],
    },
    "http://192.0.2.1/": {
        "display": "http://192.0.2.1/",
        "comparison": "http://192.0.2.1",
        "search": "http://192.0.2.1",
        "structured": {
            "scheme": "http",
            "host": "192.0.2.1",
            "port": None,
            "path": "/",
            "query": "",
            "fragment": "",
            "is_idn": False,
            "tracking_params_detected": [],
            "scheme_assumed": False,
        },
        "normalization_status": "NORMALIZED",
        "validation_status": "VALID",
        "confidence": 1.0,
        "flags": [],
        "warnings": [],
    },
    "http://[2001:db8::1]/": {
        "display": "http://2001:db8::1/",
        "comparison": "http://2001:db8::1",
        "search": "http://2001:db8::1",
        "structured": {
            "scheme": "http",
            "host": "2001:db8::1",
            "port": None,
            "path": "/",
            "query": "",
            "fragment": "",
            "is_idn": False,
            "tracking_params_detected": [],
            "scheme_assumed": False,
        },
        "normalization_status": "NORMALIZED",
        "validation_status": "VALID",
        "confidence": 1.0,
        "flags": [],
        "warnings": [],
    },
    "http://localhost:8080/": {
        "display": "http://localhost:8080/",
        "comparison": "http://localhost:8080",
        "search": "http://localhost:8080",
        "structured": {
            "scheme": "http",
            "host": "localhost",
            "port": 8080,
            "path": "/",
            "query": "",
            "fragment": "",
            "is_idn": False,
            "tracking_params_detected": [],
            "scheme_assumed": False,
        },
        "normalization_status": "NORMALIZED",
        "validation_status": "VALID",
        "confidence": 1.0,
        "flags": [],
        "warnings": [],
    },
    "http://foo.notatld/": {
        "display": "http://foo.notatld/",
        "comparison": "http://foo.notatld",
        "search": "http://foo.notatld",
        "structured": {
            "scheme": "http",
            "host": "foo.notatld",
            "port": None,
            "path": "/",
            "query": "",
            "fragment": "",
            "is_idn": False,
            "tracking_params_detected": [],
            "scheme_assumed": False,
        },
        "normalization_status": "NORMALIZED",
        "validation_status": "VALID",
        "confidence": 1.0,
        "flags": [],
        "warnings": [],
    },
    "example.com/path": {
        "display": "https://example.com/path",
        "comparison": "https://example.com/path",
        "search": "https://example.com/path",
        "structured": {
            "scheme": "https",
            "host": "example.com",
            "port": None,
            "path": "/path",
            "query": "",
            "fragment": "",
            "is_idn": False,
            "tracking_params_detected": [],
            "scheme_assumed": True,
        },
        "normalization_status": "NORMALIZED",
        "validation_status": "VALID",
        "confidence": 0.8,
        "flags": ["PARSER_FALLBACK"],
        "warnings": ["no scheme in input; assumed 'https' for a bare hostname"],
    },
    "not a url": {
        "display": "not a url",
        "comparison": None,
        "search": None,
        "structured": {},
        "normalization_status": "INVALID",
        "validation_status": "INVALID",
        "confidence": 0.0,
        "flags": [],
        "warnings": [],
    },
    "https://user:pw@www.Example.org:443/a/b/?q=1": {
        "display": "https://user:pw@www.example.org/a/b/?q=1",
        "comparison": "https://user:pw@www.example.org/a/b/?q=1",
        "search": "https://user:pw@www.example.org/a/b/?q=1",
        "structured": {
            "scheme": "https",
            "host": "www.example.org",
            "port": 443,
            "path": "/a/b/",
            "query": "q=1",
            "fragment": "",
            "is_idn": False,
            "tracking_params_detected": [],
            "scheme_assumed": False,
        },
        "normalization_status": "NORMALIZED",
        "validation_status": "VALID",
        "confidence": 1.0,
        "flags": [],
        "warnings": [],
    },
    "ftp://files.example.com:21/x": {
        "display": "ftp://files.example.com/x",
        "comparison": "ftp://files.example.com/x",
        "search": "ftp://files.example.com/x",
        "structured": {
            "scheme": "ftp",
            "host": "files.example.com",
            "port": 21,
            "path": "/x",
            "query": "",
            "fragment": "",
            "is_idn": False,
            "tracking_params_detected": [],
            "scheme_assumed": False,
        },
        "normalization_status": "NORMALIZED",
        "validation_status": "VALID",
        "confidence": 1.0,
        "flags": [],
        "warnings": [],
    },
}


# --------------------------------------------------------------------------- the fixture table


@pytest.mark.parametrize("case", D9_CASES, ids=_CASE_IDS)
def test_table_registrable_domain(case: UrlCase) -> None:
    s = _run(case.url).structured
    assert "registrable_domain" in s, "D9 key missing (no PSL computation yet)"
    assert s["registrable_domain"] in registrable_answers(case), s
    assert s["public_suffix"] == case.public_suffix, s
    assert s["is_private_suffix"] is case.is_private_suffix, s
    if case.registrable_domain is None:
        assert s["registrable_domain_reason"].strip(), "None must carry a reason"
        assert isinstance(s["registrable_domain_reason"], str)


def test_private_section_is_distinguished_from_icann() -> None:
    """x.github.io (PRIVATE) and a.co.uk (ICANN): only the flag tells them apart."""
    gh, uk = _run("https://x.github.io/").structured, _run("https://a.co.uk/").structured
    assert gh["is_private_suffix"] is True and uk["is_private_suffix"] is False
    assert gh["registrable_domain"] == "x.github.io" and uk["registrable_domain"] == "a.co.uk"


def test_idn_both_forms_consistent() -> None:
    """例え.jp and xn--r8jz45g.jp (one declared, one tested) agree on the registrable domain."""
    uni, alabel = (_run(c.url).structured for c in D9_CASES if c.id.startswith("d9-idn"))
    assert uni["registrable_domain"] and alabel["registrable_domain"]
    assert _punycode(uni["registrable_domain"]) == _punycode(alabel["registrable_domain"])
    assert uni["public_suffix"] == alabel["public_suffix"] == "jp"
    assert uni["is_private_suffix"] is alabel["is_private_suffix"] is False


def test_naive_last_two_labels_is_exposed_by_the_table() -> None:
    """The naive rule is wrong on >= 5 cases; the normalizer never agrees with it there."""
    exposed = [
        c for c in D9_CASES if naive_registrable_domain(c.host) not in registrable_answers(c)
    ]
    assert {c.id for c in exposed} >= {
        "d9-co-uk",
        "d9-sub-co-uk",
        "d9-github-io",
        "d9-ipv4",
        "d9-unlisted-tld",
    }
    for c in exposed:
        got = _run(c.url).structured.get("registrable_domain", "<absent>")
        assert got in registrable_answers(c), (c.id, got)
        assert got != naive_registrable_domain(c.host), (c.id, "equals the naive answer")


def test_wildcard_and_exception_rules() -> None:
    """`*.ck` makes b.ck a suffix; `!www.ck` makes www.ck registrable (not 'two labels')."""
    a = _run("http://a.b.ck/").structured
    assert (a["registrable_domain"], a["public_suffix"]) == ("a.b.ck", "b.ck")
    w = _run("http://www.ck/").structured
    assert (w["registrable_domain"], w["public_suffix"]) == ("www.ck", "ck")


# --------------------------------------------------------------------------- never-guess


@pytest.mark.parametrize(
    "url",
    [
        "http://intranet/",  # single label
        "http://localhost/",
        "http://127.0.0.1:8000/",
        "http://[::1]/",
        "http://a.b.c.notatld/",  # unlisted suffix, deep: still not the last two labels
        "http://co.uk/",  # the host IS a public suffix: nothing is registrable
        "http://github.io/",  # a PRIVATE suffix itself
    ],
)
def test_undecidable_hosts_give_none_with_reason(url: str) -> None:
    r = _run(url)
    s = r.structured
    assert s["registrable_domain"] is None, s
    assert (
        isinstance(s["registrable_domain_reason"], str) and s["registrable_domain_reason"].strip()
    )
    assert (
        r.normalization_status is NormalizationStatus.NORMALIZED
    )  # the URL is fine; only the claim abstains
    assert s["is_private_suffix"] in (None, False, True)  # never raises; truthiness not asserted


def test_precision_not_invented_for_bare_suffix_hosts() -> None:
    """Stating only a suffix must not be 'completed' into a registrable domain or an extra label."""
    s = _run("http://co.uk/").structured
    assert s["registrable_domain"] is None
    assert s["public_suffix"] in (None, "co.uk")  # never an invented label
    assert s["host"] == "co.uk"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://user:pw@WWW.B.A.CO.UK:8443/p?q=1#f", "a.co.uk"),  # userinfo, port, case
        ("b.a.co.uk/x", "a.co.uk"),  # scheme assumed
        ("https://例え.jp:443/", "例え.jp"),
    ],
)
def test_computed_from_host_only(url: str, expected: str) -> None:
    s = _run(url).structured
    assert _punycode(s["registrable_domain"]) == _punycode(expected), s


def test_invalid_url_gets_no_invented_registrable_domain() -> None:
    r = _run("not a url")
    assert r.normalization_status is NormalizationStatus.INVALID
    assert r.structured.get("registrable_domain") is None


# --------------------------------------------------------------------------- no network


def _block_sockets(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    attempts: list[str] = []

    def deny(name: str) -> Any:
        def _f(*a: Any, **k: Any) -> Any:
            attempts.append(name)
            raise OSError(f"network blocked by test: {name}")

        return _f

    monkeypatch.setattr(socket, "socket", deny("socket"))
    monkeypatch.setattr(socket, "create_connection", deny("create_connection"))
    monkeypatch.setattr(socket, "getaddrinfo", deny("getaddrinfo"))
    return attempts


def test_works_with_sockets_blocked_and_never_tries(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = _block_sockets(monkeypatch)
    for c in D9_CASES:
        s = _run(c.url).structured
        assert s["registrable_domain"] in registrable_answers(c), (c.id, s)
        assert s["public_suffix"] == c.public_suffix
    assert attempts == [], f"the PSL path touched the network: {attempts}"


def test_fresh_process_import_and_first_call_never_touch_network() -> None:
    """Lazy-fetch libraries fetch on FIRST use in a new process; in-process tests miss that."""
    code = textwrap.dedent(
        """
        import socket, sys
        hits = []
        def deny(*a, **k):
            hits.append(1)
            raise OSError("blocked")
        socket.socket = deny
        socket.create_connection = deny
        socket.getaddrinfo = deny
        from normalizers.url import URLNormalizer
        from normcore.context import NormalizationContext
        from normcore.enums import FieldSemanticType
        ctx = NormalizationContext(field_name="u", semantic_type=FieldSemanticType.URL)
        s = URLNormalizer().normalize("https://b.a.co.uk/x", ctx).structured
        assert s["registrable_domain"] == "a.co.uk", s
        assert s["public_suffix"] == "co.uk", s
        assert not hits, "network attempted"
        print("OK")
        """
    )
    p = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120, check=False
    )
    assert p.returncode == 0 and "OK" in p.stdout, (p.stdout, p.stderr[-1500:])


# --------------------------------------------------------------------------- fingerprint, 2.4


def test_psl_library_is_fingerprinted_and_installed() -> None:
    chosen = [p for p in _PSL_PACKAGES if p in FINGERPRINTED_PACKAGES]
    assert chosen, (
        f"none of {_PSL_PACKAGES} in FINGERPRINTED_PACKAGES: a PSL update would not move env_id"
    )
    for p in chosen:
        try:
            assert pkg_version(p)
        except PackageNotFoundError:  # pragma: no cover
            pytest.fail(f"{p} is fingerprinted but not installed")


def test_fingerprinted_library_is_the_one_url_py_uses() -> None:
    src = _URL_SRC.read_text(encoding="utf-8")
    chosen = [p for p in _PSL_PACKAGES if p in FINGERPRINTED_PACKAGES]
    assert chosen
    assert any(p in src for p in chosen), "url.py does not import the fingerprinted PSL library"


def _str_collections(src: str) -> set[tuple[str, ...]]:
    out: set[tuple[str, ...]] = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            vals = tuple(e.value for e in node.elts if isinstance(e, ast.Constant))
            if len(vals) >= 3 and all(isinstance(v, str) for v in vals):
                out.add(tuple(map(str, vals)))
    return out


def test_no_suffix_literals_in_url_py() -> None:
    """Section 2.4 grep: url.py holds no list of >=3 string literals naming a public suffix (a
    TLD/suffix table) and no fixture value; the PSL library is the only source of suffix data.
    History-free on purpose: CI's shallow checkout has no `main` to diff against."""
    psl = PublicSuffixList(accept_unknown=False)
    src = _URL_SRC.read_text(encoding="utf-8")
    tables = [
        c for c in _str_collections(src) if any(psl.is_public(v.strip(".").lower()) for v in c)
    ]
    assert not tables, f"public-suffix list literal(s) in url.py: {tables[:3]}"
    for needle in ("co.uk", "github.io", "notatld", '"jp"', '"uk"', "'jp'", "'uk'"):
        assert needle not in src, f"literal {needle!r} in url.py (fixture value copied into code)"


# --------------------------------------------------------------------------- additive only


@pytest.mark.parametrize("url", list(_BEFORE_D9), ids=range(len(_BEFORE_D9)))
def test_existing_output_is_byte_identical(url: str) -> None:
    before = _BEFORE_D9[url]
    r = _run(url)
    assert r.display == before["display"]
    assert r.comparison == before["comparison"]
    assert r.search == before["search"]
    assert r.normalization_status.name == before["normalization_status"]
    assert r.validation_status == before["validation_status"]
    assert r.confidence == before["confidence"]
    assert sorted(f.name for f in r.flags) == before["flags"]
    assert list(r.warnings) == before["warnings"]
    assert {k: v for k, v in r.structured.items() if k not in _NEW_KEYS} == before["structured"]


def test_new_keys_are_additive_and_typed() -> None:
    """The three always-present keys have the contract types; nothing outside the four is added."""
    for url in ("https://a.co.uk/", "http://localhost/"):
        s = _run(url).structured
        extra = set(s) - set(_BEFORE_D9[url]["structured"] if url in _BEFORE_D9 else s)
        assert extra <= _NEW_KEYS, extra
        assert {"registrable_domain", "public_suffix", "is_private_suffix"} <= set(s)
        assert s["registrable_domain"] is None or isinstance(s["registrable_domain"], str)
        assert s["public_suffix"] is None or isinstance(s["public_suffix"], str)
        assert s["is_private_suffix"] is None or isinstance(s["is_private_suffix"], bool)

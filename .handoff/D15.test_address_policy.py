"""D15 acceptance, part 1: the address table and the target checks.

Derived BEFORE the implementation from docs/improvement-report.md (D15) and
docs/plans/ROUND2_IMPLEMENTATION_PLAN.md (2.4, 2.6, 9). Expected classes come from the RFCs named
next to each row and from this file's own calculation over `ipaddress.ip_network` values, never from
running the code under test.

Assumed names (see D15.acceptance.md):
  normapi.address_policy.classify(addr: str) -> bool        True = allowed
  normapi.address_policy.check_caller(peer: str | None) -> bool   True = caller allowed
  normapi.address_policy.resolve_and_check(host: str) -> str      the checked IP literal to connect to;
                                                    raises AddressPolicyError on any refusal
  normapi.address_policy.AddressPolicyError(Exception)
"""

from __future__ import annotations

import ipaddress
import os
import random
import re
import socket
from pathlib import Path

import pytest



def _policy():
    try:
        import normapi.address_policy as mod
    except ImportError as exc:  # the missing behaviour, reported as such
        pytest.fail(f"normapi.address_policy does not exist yet: {exc}")
    return mod


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "packages" / "normapi" / "src" / "normapi"

# (address, allowed, why). The reason column is the RFC / registry that makes the row true.
TABLE = [
    # allowed ----------------------------------------------------------------------------
    ("127.0.0.1", True, "RFC 1122 s3.2.1.3 loopback 127.0.0.0/8"),
    ("127.255.255.254", True, "last-but-one of 127.0.0.0/8"),
    ("::1", True, "RFC 4291 s2.5.3 loopback"),
    ("10.0.0.1", True, "RFC 1918 10.0.0.0/8"),
    ("10.255.255.255", True, "last address of 10/8"),
    ("172.16.0.1", True, "RFC 1918 172.16.0.0/12 first"),
    ("172.31.255.255", True, "RFC 1918 172.16.0.0/12 last"),
    ("192.168.0.1", True, "RFC 1918 192.168.0.0/16"),
    ("192.168.255.255", True, "last of 192.168/16"),
    ("fc00::1", True, "RFC 4193 fc00::/7 first block"),
    ("fd12:3456:789a::1", True, "RFC 4193 fd00::/8 half of fc00::/7"),
    ("fdff:ffff:ffff:ffff:ffff:ffff:ffff:ffff", True, "last of fc00::/7"),
    ("::ffff:10.0.0.1", True, "RFC 4291 s2.5.5.2 mapped; unwraps to 10/8"),
    ("::ffff:127.0.0.1", True, "mapped loopback"),
    ("::ffff:192.168.1.1", True, "mapped RFC 1918"),
    # refused ----------------------------------------------------------------------------
    ("100.64.0.1", False, "RFC 6598 shared address space 100.64.0.0/10 (R14)"),
    ("100.127.255.255", False, "last of 100.64.0.0/10"),
    ("169.254.1.1", False, "RFC 3927 link-local 169.254.0.0/16"),
    ("fe80::1", False, "RFC 4291 link-local fe80::/10, not in the allowed set of R9"),
    ("198.18.0.1", False, "RFC 2544 benchmarking 198.18.0.0/15"),
    ("198.19.255.255", False, "last of 198.18.0.0/15"),
    ("192.0.2.1", False, "RFC 5737 TEST-NET-1 192.0.2.0/24"),
    ("198.51.100.1", False, "RFC 5737 TEST-NET-2"),
    ("203.0.113.1", False, "RFC 5737 TEST-NET-3"),
    ("2001:db8::1", False, "RFC 3849 documentation 2001:db8::/32"),
    ("8.8.8.8", False, "public"),
    ("1.1.1.1", False, "public"),
    ("2001:4860:4860::8888", False, "public IPv6"),
    ("0.0.0.0", False, "RFC 1122 'this host'; binds/connects to anything"),
    ("::", False, "RFC 4291 unspecified"),
    ("255.255.255.255", False, "RFC 919 limited broadcast"),
    ("224.0.0.1", False, "RFC 5771 multicast 224.0.0.0/4"),
    ("239.255.255.250", False, "multicast"),
    ("ff02::1", False, "RFC 4291 multicast ff00::/8"),
    ("::ffff:8.8.8.8", False, "mapped public address unwraps to public"),
    ("::ffff:100.64.0.1", False, "mapped CGNAT unwraps to refused"),
    ("::ffff:0.0.0.0", False, "mapped unspecified"),
    # just outside each allowed block (boundary rows) ------------------------------------
    ("172.15.255.255", False, "one below 172.16.0.0/12"),
    ("172.32.0.0", False, "one above 172.16.0.0/12"),
    ("192.167.255.255", False, "one below 192.168/16"),
    ("192.169.0.0", False, "one above 192.168/16"),
    ("9.255.255.255", False, "one below 10/8"),
    ("11.0.0.0", False, "one above 10/8"),
    ("126.255.255.255", False, "one below 127/8"),
    ("128.0.0.0", False, "one above 127/8"),
    ("fbff:ffff:ffff:ffff:ffff:ffff:ffff:ffff", False, "one below fc00::/7"),
    ("fe00::", False, "one above fc00::/7"),
    # never-guess: forms a lenient parser (inet_aton, urllib) would turn into 127.0.0.1 -------
    ("2130706433", False, "decimal IPv4 form of 127.0.0.1"),
    ("0177.0.0.1", False, "octal IPv4 form of 127.0.0.1"),
    ("0x7f.1", False, "hex / short IPv4 form of 127.0.0.1"),
    ("0x7f000001", False, "hex IPv4 form of 127.0.0.1"),
    ("127.1", False, "short IPv4 form"),
    ("127.0.1", False, "short IPv4 form"),
    ("010.0.0.1", False, "leading zero: octal (8.0.0.1) or decimal (10.0.0.1)? undecidable"),
    ("012.1.1.1", False, "octal or decimal? undecidable"),
    ("167772161", False, "decimal form of 10.0.0.1"),
    ("0xa.0.0.1", False, "hex octet form of 10.0.0.1"),
    (" 127.0.0.1", False, "leading blank"),
    ("127.0.0.1 ", False, "trailing blank"),
    ("127.0.0.1\n", False, "trailing newline"),
    ("127.0.0.1.", False, "trailing dot"),
    ("localhost", False, "a name is not a literal; classify never resolves"),
    ("", False, "empty"),
    ("not-an-address", False, "garbage"),
    ("10.0.0.256", False, "octet out of range"),
    ("[::1]", False, "bracketed form is a URL piece, not an address"),
    ("::1%lo", False, "zone id: not decidable by the table"),
    ("10.0.0.1/8", False, "a network is not an address"),
]


@pytest.mark.parametrize(("addr", "allowed", "why"), TABLE, ids=[row[0] or "<empty>" for row in TABLE])
def test_fixed_address_table(addr: str, allowed: bool, why: str) -> None:
    assert _policy().classify(addr) is allowed, f"{addr!r}: expected allowed={allowed} ({why})"


# --- the test's own calculation: an oracle built from RFC networks, compared on boundaries and a
# seeded sample. This guards against `is_private` drift (plan 2.6) without trusting the table alone.
_RFC_ALLOWED = [
    ipaddress.ip_network(n)
    for n in (
        "127.0.0.0/8",  # RFC 1122
        "::1/128",  # RFC 4291
        "10.0.0.0/8",  # RFC 1918
        "172.16.0.0/12",  # RFC 1918
        "192.168.0.0/16",  # RFC 1918
        "fc00::/7",  # RFC 4193
    )
]


def _oracle(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    return any(addr.version == n.version and addr in n for n in _RFC_ALLOWED)


def test_boundaries_of_every_allowed_network_match_the_oracle() -> None:
    policy = _policy()
    for net in _RFC_ALLOWED:
        first, last = net.network_address, net.broadcast_address
        for value in (int(first) - 1, int(first), int(last), int(last) + 1):
            cls = type(first)
            if not 0 <= value < 2 ** (32 if net.version == 4 else 128):
                continue
            addr = cls(value)
            assert policy.classify(str(addr)) is _oracle(addr), f"{addr} (edge of {net})"


def test_seeded_sample_matches_the_oracle() -> None:
    seed = int(os.environ.get("D15_SEED", "20261027"))
    print(f"D15 sample seed={seed}")  # L6: printed so a failure can be reproduced
    rng = random.Random(seed)
    policy = _policy()
    candidates: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for _ in range(2000):
        candidates.append(ipaddress.IPv4Address(rng.getrandbits(32)))
        candidates.append(ipaddress.IPv6Address(rng.getrandbits(128)))
    for net in _RFC_ALLOWED:  # random members of each allowed block
        for _ in range(100):
            candidates.append(type(net.network_address)(int(net.network_address) + rng.randrange(net.num_addresses)))
    for _ in range(300):  # mapped forms of random IPv4 and of members of the IPv4 allowed blocks
        v4 = ipaddress.IPv4Address(rng.getrandbits(32))
        candidates.append(ipaddress.IPv6Address(f"::ffff:{v4}"))
    for addr in candidates:
        assert policy.classify(str(addr)) is _oracle(addr), f"{addr} (seed {seed})"


# --- the plan 2.4 grep, runnable over the policy module (the diff-wide command is in the .md) ----
def _policy_source() -> str:
    path = SRC / "address_policy.py"
    assert path.exists(), "packages/normapi/src/normapi/address_policy.py does not exist yet"
    return path.read_text(encoding="utf-8")


def test_no_is_private_anywhere_in_normapi() -> None:
    """Report D15 fix 7 / plan 2.6: `is_private`, `is_global`, `is_reserved` changed across Python
    versions and are wrong for documentation and benchmark ranges."""
    _policy_source()  # the module must exist, otherwise the negative case below is vacuous
    hits = [
        f"{p.relative_to(ROOT)}:{n}: {line.strip()}"
        for p in SRC.rglob("*.py")
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if re.search(r"\.is_(private|global|reserved)\b", line) and not line.lstrip().startswith("#")
    ]
    assert not hits, hits


def test_every_network_literal_is_named_by_an_rfc() -> None:
    """Plan 2.4: an address range typed by hand needs a named source next to it."""
    lines = _policy_source().splitlines()
    cidr = re.compile(r"\d{1,3}(?:\.\d{1,3}){3}/\d{1,2}|[0-9a-fA-F:]{2,}::?[0-9a-fA-F:]*/\d{1,3}")
    unnamed = []
    for i, line in enumerate(lines):
        if cidr.search(line) and not line.lstrip().startswith(('"""', "'''")):
            window = "\n".join(lines[max(0, i - 2) : i + 1])
            if "RFC" not in window and "rfc" not in window:
                unnamed.append(f"{i + 1}: {line.strip()}")
    assert not unnamed, unnamed


def test_allowed_set_uses_ipaddress_networks() -> None:
    assert "ip_network" in _policy_source()


# --- caller check -----------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("peer", "allowed"),
    [
        ("127.0.0.1", True),
        ("::1", True),
        ("192.168.1.20", True),
        ("172.17.0.1", True),  # Docker bridge gateway, RFC 1918 (R9)
        ("fd00::5", True),
        ("8.8.8.8", False),
        ("100.64.0.9", False),  # CGNAT refused unless a deployer setting adds it (R14)
        ("169.254.0.1", False),
        ("203.0.113.9", False),
        ("0.0.0.0", False),
        # never-guess: a peer that is not an IP literal is refused (the plan 2.6 'testclient' trap)
        ("testclient", False),
        ("", False),
        (None, False),
        ("2130706433", False),
    ],
)
def test_check_caller(peer: str | None, allowed: bool) -> None:
    assert _policy().check_caller(peer) is allowed


# --- database targets: one refusal per kind -----------------------------------------------------
def _fake_dns(monkeypatch: pytest.MonkeyPatch, mapping: dict[str, list[str]]) -> list[str]:
    """Replace socket.getaddrinfo (a boundary we do not own, rule L5). Returns the list of names asked."""
    asked: list[str] = []

    def fake(host, port=None, *args, **kwargs):
        asked.append(host)
        if host not in mapping:
            raise socket.gaierror(socket.EAI_NONAME, "unknown")
        out = []
        for ip in mapping[host]:
            fam = socket.AF_INET6 if ":" in ip else socket.AF_INET
            sockaddr = (ip, port or 0, 0, 0) if fam == socket.AF_INET6 else (ip, port or 0)
            out.append((fam, socket.SOCK_STREAM, 6, "", sockaddr))
        return out

    monkeypatch.setattr(socket, "getaddrinfo", fake)
    return asked


def _unwrap(text: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    addr = ipaddress.ip_address(text)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        return addr.ipv4_mapped
    return addr


@pytest.mark.parametrize("host", ["10.1.2.3", "127.0.0.1", "192.168.5.5", "::1", "fd00::9", "::ffff:10.0.0.1"])
def test_allowed_literal_target_is_returned_as_the_checked_address(
    host: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked = _fake_dns(monkeypatch, {})
    got = _policy().resolve_and_check(host)
    assert _unwrap(got) == _unwrap(host)
    assert asked == [], "a literal address must not be resolved"


@pytest.mark.parametrize(
    "host",
    [
        "8.8.8.8",  # public IP
        "2001:4860:4860::8888",  # public IPv6
        "100.64.0.1",  # CGNAT
        "0.0.0.0",
        "2130706433",  # decimal form: refused, not decoded
        "0177.0.0.1",
        "0x7f.1",
        "/var/run/postgresql",  # unix-socket path (libpq: a host starting with / is a socket dir)
        "/tmp",
        "@abstract",  # libpq abstract socket form
        "host1,host2",  # multi-host string
        "10.0.0.1,10.0.0.2",  # comma host made only of allowed literals is still refused
        "10.0.0.1,8.8.8.8",
        "10.0.0.1,",
        ",10.0.0.1",
        "",
        " ",
    ],
)
def test_refused_target_kinds(host: str, monkeypatch: pytest.MonkeyPatch) -> None:
    policy = _policy()
    _fake_dns(monkeypatch, {})  # nothing resolves; a refusal must not depend on DNS luck
    with pytest.raises(policy.AddressPolicyError):
        policy.resolve_and_check(host)


def test_hostname_with_any_public_address_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """R15: resolve and require EVERY address to be allowed."""
    policy = _policy()
    _fake_dns(
        monkeypatch,
        {
            "mixed.example": ["10.0.0.5", "8.8.8.8"],
            "mixed-last.example": ["8.8.8.8", "10.0.0.5"],
            "mixed6.example": ["fd00::1", "2001:4860:4860::8888"],
            "mapped-public.example": ["10.0.0.5", "::ffff:8.8.8.8"],
            "cgnat.example": ["10.0.0.5", "100.64.0.1"],
        },
    )
    for name in ("mixed.example", "mixed-last.example", "mixed6.example", "mapped-public.example", "cgnat.example"):
        with pytest.raises(policy.AddressPolicyError):
            policy.resolve_and_check(name)


def test_hostname_with_only_allowed_addresses_is_accepted_and_pinned(monkeypatch: pytest.MonkeyPatch) -> None:
    policy = _policy()
    _fake_dns(monkeypatch, {"db.lan": ["10.0.0.5", "192.168.1.9", "fd00::7"], "localhost": ["127.0.0.1", "::1"]})
    got = policy.resolve_and_check("db.lan")
    assert got in {"10.0.0.5", "192.168.1.9", "fd00::7"}  # the address to hand to libpq as hostaddr
    assert policy.resolve_and_check("localhost") in {"127.0.0.1", "::1"}


def test_never_guess_unresolvable_or_empty_resolution_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """A name that does not resolve, or resolves to nothing, is undecidable: refuse, never allow."""
    policy = _policy()
    _fake_dns(monkeypatch, {"empty.example": []})
    for name in ("nxdomain.example", "empty.example"):
        with pytest.raises(policy.AddressPolicyError):
            policy.resolve_and_check(name)


def test_dns_rebinding_between_two_calls_is_caught_on_each_use(monkeypatch: pytest.MonkeyPatch) -> None:
    """'Check both when a connection is saved and each time it is used': the answer is not cached
    across calls. First answer private, second public -> the second call must refuse."""
    policy = _policy()
    answers = iter([["10.0.0.5"], ["8.8.8.8"]])

    def fake(host, port=None, *a, **k):
        ip = next(answers)[0]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port or 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake)
    assert policy.resolve_and_check("flip.example") == "10.0.0.5"
    with pytest.raises(policy.AddressPolicyError):
        policy.resolve_and_check("flip.example")

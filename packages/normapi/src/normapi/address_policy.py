"""Local-network-only address policy (ADR-022, report D15).

One allowed set, built from explicit ``ipaddress.ip_network`` values named by their RFCs. The
``is_private`` family is never used: its list changed across Python versions and it calls
documentation and benchmark ranges private. Parsing is strict (never guess): decimal, octal, hex
and short IPv4 forms, zones, prefixes, brackets and blanks are refused, and ``::ffff:a.b.c.d`` is
unwrapped to the IPv4 address before the check.
"""

from __future__ import annotations

import ipaddress
import os
import re
import socket

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

# The allowed set. Each network carries the RFC that defines it.
_BUILTIN_NETWORKS = (
    ipaddress.ip_network("127.0.0.0/8"),  # RFC 1122 s3.2.1.3 (loopback), listed in RFC 5735
    ipaddress.ip_network("::1/128"),  # RFC 4291 s2.5.3 (IPv6 loopback)
    ipaddress.ip_network("10.0.0.0/8"),  # RFC 1918 (private use)
    ipaddress.ip_network("172.16.0.0/12"),  # RFC 1918 (private use)
    ipaddress.ip_network("192.168.0.0/16"),  # RFC 1918 (private use)
    ipaddress.ip_network("fc00::/7"),  # RFC 4193 (IPv6 unique local)
)

_ENV_EXTRA = "NORM_ALLOWED_NETWORKS"
_LITERAL_CHARS = re.compile(r"[0-9A-Fa-f:.]+", re.ASCII)
_HOSTNAME = re.compile(r"[A-Za-z0-9_.-]+", re.ASCII)
# A last label that is all digits or 0x-hex is an IPv4 form a lenient resolver (inet_aton) would
# decode; refuse it instead of letting the name resolver decide.
_NUMERIC_LABEL = re.compile(r"[0-9]+|0[xX][0-9A-Fa-f]*", re.ASCII)


class AddressPolicyError(Exception):
    """A caller, host or database target is outside the allowed local network.

    Fix: use a loopback, RFC 1918 or fc00::/7 address, or ask the deployer to add the range to
    ``NORM_ALLOWED_NETWORKS`` (comma-separated CIDRs).
    """


def allowed_networks() -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    """The built-in networks plus the deployer's ``NORM_ALLOWED_NETWORKS`` (R14), read on each call.

    A bad entry raises ``ValueError``; it is never skipped, so a typo cannot silently narrow or
    widen the set.
    """
    extra = os.environ.get(_ENV_EXTRA, "").strip()
    if not extra:
        return _BUILTIN_NETWORKS
    return _BUILTIN_NETWORKS + tuple(_parse_network(item.strip()) for item in extra.split(","))


def _parse_network(entry: str) -> ipaddress.IPv4Network | ipaddress.IPv6Network:
    try:
        return ipaddress.ip_network(entry, strict=True)
    except ValueError as exc:
        raise ValueError(
            f"{_ENV_EXTRA} entry {entry!r} is not a network: {exc}. "
            "Fix: use comma-separated CIDRs with no host bits set."
        ) from exc


def _parse(addr: str) -> IPAddress | None:
    """Strict literal parse, or None. Mapped IPv6 is unwrapped to its IPv4 address."""
    if not _LITERAL_CHARS.fullmatch(addr):  # blanks, zones, prefixes, brackets, names, empty
        return None
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def _allowed(ip: IPAddress) -> bool:
    return any(ip.version == net.version and ip in net for net in allowed_networks())


def classify(addr: str) -> bool:
    """True if ``addr`` is a strict IP literal inside the allowed set. Never resolves."""
    ip = _parse(addr)
    return ip is not None and _allowed(ip)


def check_caller(peer: str | None) -> bool:
    """True if the ASGI peer is an allowed IP literal. Non-IP peers ("testclient") are refused."""
    return peer is not None and classify(peer)


def checked_addresses(host: str) -> list[str]:
    """Return every checked IP literal ``host`` stands for, the one to connect to first, or raise.

    Literals are not resolved. A host name is resolved on every call (no cache, so a DNS rebind
    between two uses is caught) and EVERY address it returns must be allowed (R15).
    """
    ip = _parse(host)
    if ip is not None:
        if not _allowed(ip):
            raise AddressPolicyError(f"address {host!r} is outside the allowed local network")
        return [str(ip)]
    name = host.removesuffix(".")
    if (
        not _HOSTNAME.fullmatch(name)
        or ":" in name
        or _NUMERIC_LABEL.fullmatch(name.rsplit(".", 1)[-1])
    ):
        raise AddressPolicyError(
            f"host {host!r} is not an IP address or a plain host name "
            "(socket paths, several hosts and decimal, octal, hex or short IPv4 forms are refused)"
        )
    try:
        infos = socket.getaddrinfo(name, None, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise AddressPolicyError(f"host {host!r} did not resolve: {exc}") from exc
    answers = [_parse(str(info[4][0])) for info in infos]
    if not answers:
        raise AddressPolicyError(f"host {host!r} resolved to no address")
    for found in answers:
        if found is None or not _allowed(found):
            raise AddressPolicyError(f"host {host!r} resolves outside the allowed local network")
    return [str(found) for found in answers]


def resolve_and_check(host: str) -> str:
    """Return the checked IP literal to connect to (libpq ``hostaddr``), or raise."""
    return checked_addresses(host)[0]

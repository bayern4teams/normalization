"""D9 attack-time checks (verifier-written): an independent PSL algorithm over the bundled
list cross-checks the normalizer on every rule, so a hand-picked table cannot hide a guess."""

from __future__ import annotations

import os

import pytest
from normalizers.url import URLNormalizer
from test_url_normalizer import _ctx

pytestmark = pytest.mark.unit

# C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
import publicsuffixlist  # noqa: E402


def _load() -> tuple[list[tuple[str, bool]], ...]:
    path = os.path.join(os.path.dirname(publicsuffixlist.__file__), "public_suffix_list.dat")
    rules: list[tuple[str, bool]] = []
    icann = False
    # C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
    for raw in open(path, encoding="utf-8"):  # noqa: SIM115
        line = raw.strip()
        if "BEGIN ICANN DOMAINS" in line:
            icann = True
        elif "END ICANN DOMAINS" in line:
            icann = False
        elif line and not line.startswith("//"):
            rules.append((line.split()[0], icann))
    return (rules,)


def _a(label: str) -> str | None:
    try:
        return label.encode("idna").decode("ascii") if label != "*" else "*"
    except UnicodeError:
        return None


def _suffix(host: str, rules: set[str]) -> str | None:
    labels = host.split(".")
    best: int | None = None
    for i in range(len(labels)):
        cand = ".".join(labels[i:])
        wild = ".".join(["*", *labels[i + 1 :]]) if i + 1 < len(labels) + 0 else None
        if "!" + cand in rules:
            return ".".join(labels[i + 1 :]) or None
        if cand in rules or (wild and wild in rules):
            best = len(labels) - i if best is None or len(labels) - i > best else best
    return ".".join(labels[len(labels) - best :]) if best else None


def _expected(host: str, all_rules: set[str], icann_rules: set[str]):
    suf = _suffix(host, all_rules)
    if suf is None:
        return (None, None, None)
    n = len(suf.split("."))
    labels = host.split(".")
    dom = ".".join(labels[-(n + 1) :]) if len(labels) > n else None
    return (dom, suf, suf != _suffix(host, icann_rules))


def test_every_psl_rule_agrees_with_independent_algorithm() -> None:
    (rules,) = _load()
    alln: set[str] = set()
    icn: set[str] = set()
    for r, is_icann in rules:
        parts = [
            _a(p) if not r.startswith("!") or i else _a(p[1:]) for i, p in enumerate(r.split("."))
        ]
        # C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
        if any(p is None for p in parts):
            continue
        enc = ".".join(parts)  # type: ignore[arg-type]
        if r.startswith("!"):
            enc = "!" + enc
        alln.add(enc)
        if is_icann:
            icn.add(enc)
    norm = URLNormalizer()
    checked = bad = 0
    msgs = []
    sample = [r for r in alln if not r.startswith("!")]
    sample += ["!" + r[1:] for r in alln if r.startswith("!")]
    for enc in sample:
        base = enc.lstrip("!").replace("*", "wild")
        for host in (base, "zz." + base, "yy.zz." + base):
            exp = _expected(host, alln, icn)
            s = norm.normalize(f"https://{host}/", _ctx()).structured
            got = (s["registrable_domain"], s["public_suffix"], s["is_private_suffix"])
            checked += 1
            if got != exp:
                bad += 1
                if len(msgs) < 15:
                    msgs.append((host, got, exp))
    assert checked > 15000
    assert not bad, msgs


@pytest.mark.parametrize(
    ("value", "domain"),
    [
        ("https://a.co.uk./x", "a.co.uk"),
        ("https://A.CO.UK/", "a.co.uk"),
        ("https://MÜNCHEN.DE/", "xn--mnchen-3ya.de"),
        ("https://xn--mnchen-3ya.de/", "xn--mnchen-3ya.de"),
        ("https://user@a.co.uk@b.com/", "b.com"),
    ],
)
def test_case_dot_idn_userinfo(value: str, domain: str) -> None:
    assert URLNormalizer().normalize(value, _ctx()).structured["registrable_domain"] == domain


@pytest.mark.parametrize(
    "value",
    [
        "http://[2001:db8::1]/",
        "http://[::ffff:1.2.3.4]/",
        "http://1.2.3.4/",
        "http://127.1/",
        "http://2130706433/",
        "http://0x7f.1/",
        "http://a.example.invalid/",
        "http://a..co.uk/",
        "http://.co.uk/",
    ],
)
def test_never_guess_ip_and_malformed(value: str) -> None:
    s = URLNormalizer().normalize(value, _ctx()).structured
    assert s["registrable_domain"] is None and s["registrable_domain_reason"]
    assert s["public_suffix"] is None and s["is_private_suffix"] is None


def test_idempotent_on_structured_domain() -> None:
    n = URLNormalizer()
    for v in ["https://b.a.co.uk/x", "https://x.github.io/", "https://例え.jp/"]:
        d = n.normalize(v, _ctx()).structured["registrable_domain"]
        again = n.normalize(f"https://{d}/", _ctx()).structured["registrable_domain"]
        assert again == d

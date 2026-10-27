"""D15 attack probes. Run: uv run --python 3.12 python .handoff/D15.attack_probe.py
Prints one line per probe: OK (policy held) or LEAK/BUG. Not collected by pytest."""
import os, socket, sys
from unittest import mock

from normapi import address_policy as ap

res = []
def rec(kind, name, detail=""):
    res.append((kind, name, detail)); print(kind, name, detail)

# 1. classify: nothing outside the allowed set may pass
bad = ["::ffff:8.8.8.8", "::ffff:808:808", "::8.8.8.8", "::127.0.0.1", "::10.0.0.1", "2002:7f00:1::",
       "2002:a00:1::", "64:ff9b::7f00:1", "64:ff9b::a00:1", "::ffff:0:127.0.0.1", "::ffff:127.0.0.1%lo",
       "fe80::1%eth0", "fe80::1", "[::1]", "[127.0.0.1]", "127.0.0.1.", "127.0.0.1\n", "127.0.0.1\x00",
       "127.0.0.1 ", " 127.0.0.1", "\t10.0.0.1", "10.0.0.1/8", "0", "0.0.0.0", "127.1", "127.0.1", "2130706433",
       "0x7f.0.0.1", "0177.0.0.1", "017700000001", "٠.٠.٠.١", "１２７.０.０.１", "１27.0.0.1",
       "LOCALHOST", "localhost", "localhost.", "::FFFF:8.8.8.8", "::1%1", "::1\n", "::ffff:127.0.0.1\n",
       "100.64.0.1", "169.254.169.254", "192.0.0.1", "198.18.0.1", "224.0.0.1", "255.255.255.255",
       "fec0::1", "::", "::2", "1::", "fb00::1", "fe00::1", "2001:db8::1"]
for a in bad:
    if ap.classify(a):
        rec("LEAK", "classify", repr(a))
good_but_forms = {"::ffff:127.0.0.1": True, "::FFFF:10.1.2.3": True, "FC00::1": True, "::1": True, "0:0:0:0:0:0:0:1": True, "172.31.255.255": True}
for a, want in good_but_forms.items():
    if ap.classify(a) != want:
        rec("BUG", "classify-positive", repr(a))
# leading zeros
for a in ["010.0.0.1", "10.00.0.1", "127.000.000.001", "08.0.0.1"]:
    rec("INFO", "leading-zero-literal", f"{a!r} -> {ap.classify(a)}")

# 2. resolve_and_check for names/literals
def refuse(h):
    try:
        r = ap.resolve_and_check(h)
        rec("LEAK", "resolve_and_check", f"{h!r} -> {r}")
    except ap.AddressPolicyError:
        pass
    except Exception as e:
        rec("BUG", "resolve_and_check raised non-policy", f"{h!r} {type(e).__name__}: {e}")
for h in ["8.8.8.8", "0", "127.1", "0x7f.1", "localhost\n", "local host", "localhost\x00.evil", "a,b", "[::1]", "::1%lo",
          "/var/run/postgresql", "@abstract", "", " ", "1.1.1.1.", "127.0.0.1:5432", "host:5432", "localhost,8.8.8.8",
          "٠", "localhost。", "ｌｏｃａｌｈｏｓｔ", "127.0.0.1\n", "10.0.0.1/8", "0x7f000001", "2130706433", "017700000001",
          "1e1", "..", ".", "localhost..", "-", "_", "a" * 300]:
    with mock.patch.object(socket, "getaddrinfo", side_effect=AssertionError("must not resolve")) as m:
        refuse(h)

# 3. hostname answers
def fake(answers):
    return lambda *a, **k: [(socket.AF_INET6 if ":" in x else socket.AF_INET, socket.SOCK_STREAM, 6, "", (x, 0)) for x in answers]
for answers in [["8.8.8.8"], ["127.0.0.1", "8.8.8.8"], ["8.8.8.8", "127.0.0.1"], ["fe80::1%eth0"], ["::ffff:8.8.8.8"],
                ["::1", "2001:4860::1"], ["100.64.0.1"], []]:
    with mock.patch.object(socket, "getaddrinfo", fake(answers)):
        refuse("db.internal")
with mock.patch.object(socket, "getaddrinfo", fake(["10.0.0.5", "::ffff:10.0.0.6"])):
    rec("INFO", "mixed allowed answers", ap.resolve_and_check("db.internal"))

# 4. env var handling
for val in ["garbage", "10.0.0.0/8,", "8.8.8.8/8", "100.64.0.0/10,bogus", "0.0.0.0/0", "1.2.3.4/24"]:
    os.environ["NORM_ALLOWED_NETWORKS"] = val
    try:
        n = ap.allowed_networks()
        rec("INFO", "env-accepted", f"{val!r} -> extra={[str(x) for x in n[6:]]}")
    except ValueError as e:
        rec("OK", "env-refused", f"{val!r}: {e}")
os.environ.pop("NORM_ALLOWED_NETWORKS")

# 5. engine_from_dsn with '://' in password
from normio.connectors.postgres_destination import build_postgres_dsn, engine_from_dsn
dsn = build_postgres_dsn("127.0.0.1", 5432, "u", "pa://ss", "db", hostaddr="127.0.0.1")
try:
    e = engine_from_dsn(dsn)
    rec("INFO", "engine_from_dsn password with ://", f"built {e.url!r}")
except Exception as ex:
    rec("BUG", "engine_from_dsn password containing '://' breaks", f"{type(ex).__name__}: {str(ex)[:100]}")
for pw in ["postgresql://evil@8.8.8.8/x", "x"]:
    dsn = build_postgres_dsn("127.0.0.1", 5432, "u", pw, "db", hostaddr="127.0.0.1")
    try:
        e = engine_from_dsn(dsn); rec("INFO", "engine pw", f"{pw!r} {e.url!r}")
    except Exception as ex:
        rec("BUG", "engine pw", f"{pw!r} {type(ex).__name__}")
print("DONE", sum(1 for r in res if r[0] in ("LEAK",)), "leaks", sum(1 for r in res if r[0]=="BUG"), "bugs")

"""D15 acceptance, part 2: the app (caller + Host), the DSN, and compose.yaml.

Derived from docs/improvement-report.md (D15 fix 1, 2, 3, 5, 6) and the plan (2.6, 9, decision Q-B).
Assumed names (see D15.acceptance.md):
  normapi.app.create_app() -> FastAPI           (named in the report; no-argument call assumed)
  normapi.clone_executor.build_postgres_dsn(host, port, username, password, database, hostaddr=None) -> str
A refused caller or Host answers HTTP 400 or 403 (Starlette's TrustedHostMiddleware answers 400).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
REFUSED = (400, 403)


@pytest.fixture
def make_client(monkeypatch: pytest.MonkeyPatch):
    from starlette.testclient import TestClient

    from normapi.app import create_app

    app = create_app()

    def make(peer: tuple[str, int] | None, host: str = "localhost"):
        kwargs = {"base_url": f"http://{host}"}
        if peer is not None:
            kwargs["client"] = peer
        return TestClient(app, **kwargs)

    return make


# --- caller address ------------------------------------------------------------------------------
@pytest.mark.parametrize("peer", ["8.8.8.8", "100.64.0.9", "169.254.1.1", "203.0.113.5", "2001:4860:4860::8888"])
def test_refused_caller_address(make_client, peer: str) -> None:
    resp = make_client((peer, 50000)).get("/openapi.json")
    assert resp.status_code in REFUSED, f"{peer}: {resp.status_code}"


@pytest.mark.parametrize("peer", ["127.0.0.1", "::1", "10.1.2.3", "172.18.0.1", "192.168.1.50", "fd00::5"])
def test_accepted_caller_with_allowed_host(make_client, peer: str) -> None:
    resp = make_client((peer, 50000), host="localhost").get("/openapi.json")
    assert resp.status_code not in REFUSED and resp.status_code < 500, f"{peer}: {resp.status_code}"


def test_never_guess_default_testclient_peer_is_refused(make_client) -> None:
    """Plan 2.6: Starlette reports the peer as the string 'testclient'. It is not an IP: refuse."""
    resp = make_client(None).get("/openapi.json")
    assert resp.status_code in REFUSED


def test_x_forwarded_for_is_ignored_in_both_directions(make_client) -> None:
    """R17: no proxy. A public peer cannot claim to be loopback, a loopback peer cannot be demoted."""
    public = make_client(("8.8.8.8", 50000)).get("/openapi.json", headers={"X-Forwarded-For": "127.0.0.1"})
    assert public.status_code in REFUSED
    public2 = make_client(("8.8.8.8", 50000)).get(
        "/openapi.json", headers={"X-Forwarded-For": "10.0.0.1, 127.0.0.1", "Forwarded": "for=127.0.0.1"}
    )
    assert public2.status_code in REFUSED
    local = make_client(("127.0.0.1", 50000)).get("/openapi.json", headers={"X-Forwarded-For": "8.8.8.8"})
    assert local.status_code not in REFUSED and local.status_code < 500


# --- Host header (the DNS-rebinding defence) ---------------------------------------------------------
@pytest.mark.parametrize(
    "host",
    ["evil.example.com", "attacker.example:8080", "localhost.evil.com", "evillocalhost", "8.8.8.8", "127.0.0.1.evil.com"],
)
def test_refused_host_header_from_a_loopback_caller(make_client, host: str) -> None:
    """A rebinding page reaches us FROM this machine, so the peer is allowed; only Host can refuse it."""
    resp = make_client(("127.0.0.1", 50000), host=host).get("/openapi.json")
    assert resp.status_code in REFUSED, f"Host {host}: {resp.status_code}"


@pytest.mark.parametrize("host", ["localhost", "localhost:8080", "127.0.0.1", "127.0.0.1:8080"])
def test_accepted_host_header(make_client, host: str) -> None:
    resp = make_client(("127.0.0.1", 50000), host=host).get("/openapi.json")
    assert resp.status_code not in REFUSED and resp.status_code < 500, f"Host {host}: {resp.status_code}"


# --- DSN ----------------------------------------------------------------------------------------
NASTY_PASSWORDS = [
    "p@ss",
    "a/b",
    "x,y",
    "q?z=1",
    "p@ss/w,rd?sslmode=disable&host=8.8.8.8",
    "has space",
    "quote'and\"dq",
    "back\\slash",
    "pct%40",
    "#frag",
    "=eq=",
]


@pytest.mark.parametrize("password", NASTY_PASSWORDS)
def test_dsn_round_trip_keeps_every_field_exact(password: str) -> None:
    from psycopg.conninfo import conninfo_to_dict

    from normapi.clone_executor import build_postgres_dsn

    dsn = build_postgres_dsn("10.0.0.5", 5432, "us@er", password, "db/name?x", hostaddr="10.0.0.5")
    parts = conninfo_to_dict(dsn)  # psycopg's own parser is the independent oracle
    assert parts["password"] == password
    assert parts["user"] == "us@er"
    assert parts["dbname"] == "db/name?x"
    assert parts["host"] == "10.0.0.5"
    assert parts["hostaddr"] == "10.0.0.5"
    assert str(parts["port"]) == "5432"
    assert set(parts) <= {"host", "hostaddr", "port", "user", "password", "dbname"}, f"smuggled options: {parts}"


def test_dsn_password_cannot_redirect_the_host() -> None:
    """The injection the report names: `@`, `/`, `,`, `?` in a password must not change the server."""
    from psycopg.conninfo import conninfo_to_dict

    from normapi.clone_executor import build_postgres_dsn

    parts = conninfo_to_dict(build_postgres_dsn("10.0.0.5", 5432, "u", "x@8.8.8.8:5432/evil?host=8.8.8.8", "d"))
    assert parts["host"] == "10.0.0.5"
    assert "," not in parts["host"]


def test_no_hand_built_postgres_url_f_string_remains() -> None:
    """Negative case that fails on the old code: the f-string `postgresql://{username}:{password}@...`."""
    pat = re.compile(r"""f["']postgres(?:ql)?://""")
    hits = [
        f"{p.relative_to(ROOT)}:{n}"
        for p in (ROOT / "packages" / "normapi" / "src").rglob("*.py")
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if pat.search(line)
    ]
    assert not hits, hits


# --- compose.yaml, read as YAML -------------------------------------------------------------------
def _published(compose: dict) -> list[tuple[str, str | None]]:
    """(service, host-address-part or None) for every published port, short or long syntax."""
    out: list[tuple[str, str | None]] = []
    for name, svc in (compose.get("services") or {}).items():
        for port in svc.get("ports") or []:
            if isinstance(port, dict):
                out.append((name, port.get("host_ip")))
                continue
            text = re.sub(r"\$\{[^}]*\}", "VAR", str(port))  # ${NORM_BIND_ADDR:?msg} contains ':'
            fields = text.split(":")
            # "host_ip:host:container" (3 fields) has an address; "host:container" or "container" has none
            out.append((name, str(port).split(":")[0] if len(fields) >= 3 else None))
            if len(fields) >= 3:
                out[-1] = (name, "VAR" if fields[0] == "VAR" else fields[0])
    return out


def _compose_problems(compose: dict) -> list[str]:
    problems = []
    published = _published(compose)
    if not published:
        problems.append("no published ports found (parser or file broken)")
    for service, addr in published:
        if service == "api":
            if addr != "VAR":
                problems.append(f"api must bind a ${{...}} LAN variable, got {addr!r}")
        elif addr != "127.0.0.1":
            problems.append(f"{service} must bind 127.0.0.1, got {addr!r}")
    for service, svc in (compose.get("services") or {}).items():
        env = svc.get("environment") or {}
        items = env.items() if isinstance(env, dict) else (e.split("=", 1) + [""] for e in env)
        for key, val in items:
            if key == "NORM_SECRET_KEY":
                value = str(val if val is not None else "")
                if not value.startswith("${"):
                    problems.append(f"{service}: NORM_SECRET_KEY is a literal value")
    return problems


def test_compose_binds_every_port_and_commits_no_secret() -> None:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    assert _compose_problems(compose) == []


def test_compose_checker_fails_on_the_pre_change_file() -> None:
    """The checker itself is proven against the file as it was before D15 (the parent of the lane C
    commit d823ba8): it must report problems there, so a green check above means something."""
    done = subprocess.run(
        ["git", "show", "d823ba8^:compose.yaml"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, f"need full history (git fetch --unshallow): {done.stderr}"
    old = done.stdout
    problems = _compose_problems(yaml.safe_load(old))
    assert any("must bind" in p for p in problems), problems
    assert any("NORM_SECRET_KEY is a literal" in p for p in problems), problems


def test_env_example_documents_the_two_variables_and_env_is_ignored() -> None:
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert re.search(r"^NORM_SECRET_KEY=", example, re.M)
    assert re.search(r"^NORM_BIND_ADDR=", example, re.M)
    assert not re.search(r"^NORM_SECRET_KEY=[A-Za-z0-9_\-]{43}=$", example, re.M), "a real Fernet key is committed"
    assert re.search(r"^/?\.env$", (ROOT / ".gitignore").read_text(encoding="utf-8"), re.M)

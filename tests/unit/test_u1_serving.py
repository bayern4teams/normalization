"""U1 acceptance (derive), serving half: one port, built UI + local /docs assets, offline.

Source: docs/improvement-report.md U1 ("The build is served by the API itself, so there is one
port and no CORS"; "Offline. No CDN, no web fonts, no telemetry. FastAPI's default /docs loads
Swagger from a CDN; serve those assets locally"; "The other pages go (R19)"); plan 9 (U1),
2.4, 2.9 (the Playwright specs of dropped pages are deleted, Q14); ADR-023. Written before any
U1 implementation existed.

Run:

    ( ulimit -v 16777216; uv run pytest -p no:cacheprovider --import-mode=importlib -q \
        tests/unit/test_u1_serving.py )

Tests that read ui/dist need the build first (`npm --prefix ui ci && npm --prefix ui run build`).
A missing ui/dist is a FAILURE, not a skip (AGENTS.md C5): the item delivers a built UI.
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

import pytest
import yaml
from fastapi.testclient import TestClient
from normapi.app import create_app

ROOT = Path(__file__).resolve().parents[2]

UI = ROOT / "ui"
DIST = UI / "dist"
ALLOWED_PEER = ("127.0.0.1", 50000)
# LEAD: if app.py reads the UI directory from an environment variable, name it here; the tests
# then point it at ui/dist. None = app.py finds ui/dist itself from the repository layout.
UI_DIST_ENV: str | None = None

# Hosts that fetch code, fonts or measurements. The deny list is a courtesy for the message; the
# rule is stronger: NO absolute http(s) URL at all in index.html, CSS and /docs HTML, and in JS
# only the non-fetched identifiers named in JS_NOT_FETCHED.
TELEMETRY_OR_CDN = (
    "fonts.googleapis.com", "fonts.gstatic.com", "cdn.jsdelivr.net", "unpkg.com",
    "cdnjs.cloudflare.com", "cdn.tailwindcss.com", "code.jquery.com", "googletagmanager.com",
    "google-analytics.com", "sentry.io", "posthog.com", "segment.com", "mixpanel.com",
    "amplitude.com", "plausible.io", "hotjar.com", "fullstory.com", "datadoghq.com",
    "fastapi.tiangolo.com", "use.typekit.net", "api.mantine.dev",
)  # fmt: skip
# Hosts that appear in a JS bundle as identifiers or message text but are never fetched:
# XML namespace URIs, React's error link, and (lead, 2026-10-28; a new test of this round) the
# message text of react-router and Mantine plus react-router's dummy base `http://localhost`:
# text in the bundle, never fetched (checked in the built bundle).
JS_NOT_FETCHED = (
    "www.w3.org",
    "react.dev",
    "reactrouter.com",
    "mantine.dev",
    "localhost",
    "github.com",
)

# Telemetry packages that must not be in the dependency lock.
TELEMETRY_PACKAGES = (
    "posthog", "@sentry", "mixpanel", "amplitude", "@segment", "analytics-node", "hotjar",
    "logrocket", "fullstory", "@datadog", "plausible", "@vercel/analytics", "react-ga",
    "web-vitals",
)  # fmt: skip

URL_RE = re.compile(r"""(?:https?:)?//[A-Za-z0-9.-]+\.[A-Za-z]{2,}[^\s"'<>)]*""")
ABS_RE = re.compile(r"https?://([A-Za-z0-9.-]+)", re.I)


def _client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    if UI_DIST_ENV:
        monkeypatch.setenv(UI_DIST_ENV, str(DIST))
    app = create_app(dictionaries_dir=tmp_path / "d", custom_dictionaries_dir=tmp_path / "c")
    return TestClient(app, client=ALLOWED_PEER, base_url="http://localhost")


def _need_dist() -> None:
    assert (DIST / "index.html").is_file(), (
        "ui/dist/index.html is missing: build the UI first "
        "(npm --prefix ui ci && npm --prefix ui run build)"
    )


class _Refs(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.refs: list[tuple[str, str, str]] = []  # (tag, attr, value)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for k, v in attrs:
            if k in ("src", "href", "action", "data", "poster", "srcset") and v:
                self.refs.append((tag, k, v))


def _refs(html: str) -> list[tuple[str, str, str]]:
    p = _Refs()
    p.feed(html)
    return p.refs


def _local_assets(html: str) -> list[str]:
    out = []
    for tag, attr, v in _refs(html):
        if tag in ("script", "link", "img") and not v.startswith("#"):
            assert not urlparse(v).netloc and not v.startswith("//"), f"external {tag} {attr}={v}"
            out.append(v)
    return out


# =========================================================================== one port, no CORS
@pytest.mark.unit
def test_api_serves_the_built_ui_and_every_asset_it_references(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Report U1: "The build is served by the API itself". `GET /` returns ui/dist/index.html and
    each script/stylesheet/icon it references is served by the same app (200, not HTML)."""
    _need_dist()
    c = _client(monkeypatch, tmp_path)
    r = c.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert r.content == (DIST / "index.html").read_bytes()
    assets = _local_assets(r.text)
    assert any(a.endswith(".js") for a in assets), "index.html references no script"
    for a in assets:
        got = c.get(a if a.startswith("/") else "/" + a)
        assert got.status_code == 200, a
        assert got.content, a
        assert not got.headers["content-type"].startswith("text/html"), (
            f"{a} came back as HTML (the index fallback), not as the asset"
        )
        assert got.content == (DIST / a.lstrip("/")).read_bytes(), a


@pytest.mark.unit
def test_api_routes_are_not_shadowed_by_the_ui(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Mounting the UI at the root must not swallow the API: JSON stays JSON, a missing API path
    is still a 404 JSON error (never the index page)."""
    _need_dist()
    c = _client(monkeypatch, tmp_path)
    assert isinstance(c.get("/openapi.json").json()["paths"], dict)
    assert (
        c.get("/normalization/connections").headers["content-type"].startswith("application/json")
    )
    miss = c.get("/normalization/no-such-route")
    assert miss.status_code == 404
    assert "<html" not in miss.text.lower()


@pytest.mark.unit
@pytest.mark.parametrize(
    "origin", ["http://localhost:5173", "http://127.0.0.1:4173", "http://evil.example"]
)
def test_no_cors_headers_at_all(
    origin: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """ADR-023 "so there is no CORS": the UI and API share one origin, so no response carries an
    Access-Control-* header, for a simple request or a preflight, for any Origin.
    Negative on old code: create_app lists localhost:5173/4173 and answers them with
    access-control-allow-origin (measured on the old app before this file was committed)."""
    c = _client(monkeypatch, tmp_path)
    simple = c.get("/openapi.json", headers={"Origin": origin})
    pre = c.options(
        "/openapi.json",
        headers={"Origin": origin, "Access-Control-Request-Method": "POST"},
    )
    for r in (simple, pre):
        bad = {k: v for k, v in r.headers.items() if k.lower().startswith("access-control-")}
        assert not bad, bad


# =========================================================================== /docs is local
@pytest.mark.unit
def test_redoc_is_off_or_local(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """FastAPI's /redoc also loads a CDN script and Google Fonts. The report names /docs only;
    its Offline rule ("no CDN, no web fonts") covers the app. Either route is disabled (404) or
    local-only. LEAD: drop this test if you rule /redoc out of scope (state it in the ADR)."""
    c = _client(monkeypatch, tmp_path)
    r = c.get("/redoc")
    if r.status_code == 404:
        return
    assert r.status_code == 200
    assert not URL_RE.findall(r.text), URL_RE.findall(r.text)


# =========================================================================== ui/dist is offline
def _dist_files() -> list[Path]:
    _need_dist()
    return [p for p in DIST.rglob("*") if p.is_file()]


@pytest.mark.unit
def test_dist_index_html_references_only_local_assets() -> None:
    _need_dist()
    html = (DIST / "index.html").read_text(encoding="utf-8")
    assert not URL_RE.findall(html), URL_RE.findall(html)
    _local_assets(html)
    # no preconnect / dns-prefetch / prefetch hints to anywhere
    assert not re.search(r'rel=["\']?(preconnect|dns-prefetch|prefetch)', html)


@pytest.mark.unit
def test_dist_has_no_cdn_font_or_telemetry_url_in_any_file() -> None:
    """Every file under ui/dist: none names a CDN/font/telemetry host; CSS has no absolute URL and
    no remote @font-face; JS has an absolute http(s) host only from JS_NOT_FETCHED; no font file
    is fetched from outside (a bundled woff2 is fine, a remote one is not)."""
    for p in _dist_files():
        if p.suffix not in {".html", ".css", ".js", ".mjs", ".json", ".svg", ".map", ".txt"}:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        rel = p.relative_to(DIST)
        for host in TELEMETRY_OR_CDN:
            assert host not in text, f"{rel}: names {host}"
        if p.suffix in {".html", ".css"}:
            assert not URL_RE.findall(text), f"{rel}: {URL_RE.findall(text)}"
        if p.suffix in {".js", ".mjs"}:
            hosts = {h.lower() for h in ABS_RE.findall(text)}
            stray = {
                h for h in hosts if not any(h == a or h.endswith("." + a) for a in JS_NOT_FETCHED)
            }
            assert not stray, f"{rel}: absolute URL hosts {sorted(stray)}"
        if p.suffix == ".css":
            for m in re.finditer(r"url\(\s*['\"]?([^'\")]+)", text):
                assert not re.match(r"(https?:)?//", m.group(1)), f"{rel}: {m.group(1)}"


# =========================================================================== dependencies, build
def _package() -> dict:
    return json.loads((UI / "package.json").read_text())


@pytest.mark.unit
def test_mantine_is_a_dependency_with_an_exact_version() -> None:
    """Report U1 / ADR-023 / plan Q7: @mantine/core and @mantine/hooks, EXACT versions (no ^, ~,
    range or tag). Negative on old code: neither is in package.json."""
    deps = _package().get("dependencies", {})
    for name in ("@mantine/core", "@mantine/hooks"):
        assert name in deps, f"{name} missing from ui/package.json dependencies"
        assert re.fullmatch(r"\d+\.\d+\.\d+", deps[name]), f"{name}: {deps[name]!r} is not exact"
    lock = json.loads((UI / "package-lock.json").read_text())["packages"]
    for name in ("@mantine/core", "@mantine/hooks"):
        assert lock[f"node_modules/{name}"]["version"] == deps[name]


@pytest.mark.unit
def test_no_telemetry_package_in_the_dependency_lock() -> None:
    lock = json.loads((UI / "package-lock.json").read_text())["packages"]
    names = [k.removeprefix("node_modules/") for k in lock if k]
    hits = [n for n in names if n.startswith(TELEMETRY_PACKAGES)]
    assert not hits, hits


@pytest.mark.unit
def test_dockerfile_builds_the_ui_into_the_api_image_and_compose_adds_no_second_port() -> None:
    """ADR-023 Consequences: "ui/ builds into the API image". One port: compose has no UI service.
    (Unverified-live: the docker build itself.)"""
    text = (ROOT / "packages/normapi/Dockerfile").read_text()
    assert "npm ci" in text and "npm run build" in text
    assert re.search(r"COPY\s+--from=\S+\s+\S*dist", text), "no COPY --from=<ui stage> .../dist"
    services = yaml.safe_load((ROOT / "compose.yaml").read_text())["services"]
    assert not [s for s in services if s in {"ui", "web", "frontend", "nginx"}], list(services)


# =========================================================================== five screens only
OLD_PAGE_FILES = (  # report U1 "The other pages go (R19)" + their detail pages + the mode switch
    "OverviewPage", "ProfilesPage", "ProfileDetailPage", "FieldsPage", "FieldDetailPage",
    "RulesPage", "PreviewPage", "WarningsPage", "CollisionsPage", "DictionariesPage",
    "SettingsPage",
)  # fmt: skip
DROPPED_ROUTES = (
    "overview", "profiles", "fields", "rules", "preview", "warnings", "collisions",
    "dictionaries", "settings",
)  # fmt: skip


@pytest.mark.unit
def test_dropped_pages_and_the_mode_switch_are_gone_from_ui_src() -> None:
    """Negative on old code: all of these files exist today (report: 18 page files)."""
    still = [n for n in OLD_PAGE_FILES if list((UI / "src").rglob(f"{n}.tsx"))]
    assert not still, f"dropped pages still in ui/src: {still}"
    assert not list((UI / "src").rglob("ModeContext.*")), "the mode switch context is still there"
    src = "\n".join(p.read_text() for p in (UI / "src").rglob("*.ts*"))
    assert not re.search(r"ModeContext|useMode\b|ModeProvider", src)


@pytest.mark.unit
def test_pages_outside_the_five_screens_are_not_rebuilt() -> None:
    """Report U1 table + ADR-023 ("Pages not in the list above are not rebuilt"). The old Runs,
    Run detail and Comparison pages are not among Connections / New clone / Jobs / Review /
    Quality (the old Clone job pages are the Jobs and New clone screens). LEAD: the report does
    not name these three explicitly; rule on it, and drop this test if you keep them."""
    names = {p.name for p in (UI / "src").rglob("*.tsx")}
    legacy = {"RunsPage.tsx", "RunDetailPage.tsx", "ComparisonPage.tsx"}
    assert not (names & legacy), f"not among the five screens: {sorted(names & legacy)}"


@pytest.mark.unit
def test_playwright_specs_of_dropped_pages_are_deleted_and_none_visits_a_dropped_route() -> None:
    """Plan 2.9 (Q14): the specs of the dropped pages are deleted. Negative on old code: four of
    the five current specs visit only dropped pages, and smoke.spec.ts visits overview/settings."""
    for gone in ("dictionaries.spec.ts", "preview.spec.ts", "profiles-and-runs.spec.ts",
                 "type-detection.spec.ts"):  # fmt: skip
        assert not (UI / "e2e" / gone).exists(), f"{gone} tests only dropped pages"
    for spec in (UI / "e2e").glob("*.spec.ts"):
        text = spec.read_text()
        hit = re.findall(r"goto\([^)]*/(" + "|".join(DROPPED_ROUTES) + r")\b", text)
        assert not hit, f"{spec.name} visits a dropped page: {hit}"
        assert "mode switch" not in text.lower()
        assert not re.search(r"\boverview\b", text, re.I), f"{spec.name} still tests the overview"
    # and the five screens have specs (the names are the report's table)
    specs = "\n".join(p.read_text().lower() for p in (UI / "e2e").glob("*.spec.ts"))
    for screen in ("connections", "new clone", "jobs", "review", "quality"):
        assert screen in specs, f"no Playwright spec mentions the {screen!r} screen"

"""PARKED, not in testpaths: U1 acceptance "/docs served locally" (report U1, Offline).
Unmet: the Swagger assets need `swagger-ui-dist`, a dependency outside plan 2.10 (Q7 names only
Mantine). /docs is switched off meanwhile (ADR-023). Owner decides; if yes, move back to
tests/unit/test_u1_serving.py (it needs `_client`, `_local_assets`, URL_RE, TELEMETRY_OR_CDN there).
"""

@pytest.mark.unit
def test_docs_html_has_no_external_url_and_its_assets_are_served_locally(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Report U1 "Offline": /docs loads Swagger from a CDN by default (and its favicon from
    fastapi.tiangolo.com). Negative on old code: both are in the old HTML."""
    c = _client(monkeypatch, tmp_path)
    r = c.get("/docs")
    assert r.status_code == 200
    external = URL_RE.findall(r.text)
    assert not external, f"external URL in /docs HTML: {external}"
    for host in TELEMETRY_OR_CDN:
        assert host not in r.text
    assets = _local_assets(r.text)
    scripts = [a for a in assets if a.endswith(".js")]
    sheets = [a for a in assets if a.endswith(".css")]
    assert scripts and sheets, "/docs must reference a local script and a local stylesheet"
    for a in scripts + sheets + [x for x in assets if x not in scripts + sheets]:
        got = c.get(a if a.startswith("/") else "/" + a)
        assert got.status_code == 200, a
        assert got.content, a
        assert not got.headers["content-type"].startswith("text/html"), a
    bundle = next(a for a in scripts if "bundle" in a)  # swagger-ui-bundle.js by its own name
    assert b"SwaggerUIBundle" in c.get(bundle).content
    css = c.get(sheets[0]).text
    assert ".swagger-ui" in css
    assert "@import" not in css



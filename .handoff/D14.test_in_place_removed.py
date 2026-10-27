"""D14 acceptance (derive): in-place mode is removed; the origin is always read-only.

Written from docs/improvement-report.md D14, plan 2.4 / 2.9 / 9 and the 2026-10-27 amendments of
ADR-013 and ADR-017 ("every clone writes a separate copy, and the schema refuses an `in_place`
field"). No implementation was read. Run with importlib mode (the file name contains a dot):

    ( ulimit -v 16777216; uv run pytest -p no:cacheprovider --import-mode=importlib -q \
        .handoff/D14.test_in_place_removed.py )

When implementing, move this file to tests/unit/ (for example test_d14_in_place_removed.py).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from normapi.app import create_app
from normapi.dependencies import get_connections
from normapi.schemas import CloneJobCreateRequest
from normio.connectors import ClickHouseDestination, PostgresDestination
from pydantic import ValidationError

from normapi import clone_executor, secrets

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())
NORMAPI_SRC = ROOT / "packages" / "normapi" / "src" / "normapi"

# The only statuses a refusal may use: malformed (400), conflict (409), unprocessable (422).
REFUSAL_STATUSES = (400, 409, 422)

VALID_BODY: dict[str, Any] = {
    "source_connection_id": "conn-src",
    "source_database": "shop",
    "destination_connection_id": "conn-dst",
    "destination_database": "shop_clone",
}


def _body(**extra: Any) -> dict[str, Any]:
    return {**VALID_BODY, **extra}


# ---------------------------------------------------------------------------
# (1) The schema refuses an `in_place` field, whatever its value.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_valid_body_is_accepted_without_in_place() -> None:
    """Positive control: the refusal below is about `in_place`, not about the rest of the body."""
    request = CloneJobCreateRequest.model_validate(VALID_BODY)
    assert request.destination_connection_id == "conn-dst"
    assert request.destination_database == "shop_clone"


@pytest.mark.unit
@pytest.mark.parametrize("value", [True, False, None, 0, 1, "true", "", {}])
def test_schema_refuses_in_place_with_any_value(value: object) -> None:
    """Old behaviour: `in_place` was a field (False was the default) and pydantic ignores unknown
    fields, so a removed field would be accepted and silently dropped. The report says the schema
    refuses it: the error must name `in_place`, not some other field."""
    with pytest.raises(ValidationError) as caught:
        CloneJobCreateRequest.model_validate(_body(in_place=value))
    locations = [error["loc"] for error in caught.value.errors()]
    assert ("in_place",) in locations
    assert {error["type"] for error in caught.value.errors() if error["loc"] == ("in_place",)} == {
        "extra_forbidden"
    }


@pytest.mark.unit
def test_schema_refuses_in_place_without_destination() -> None:
    """The old opt-in shape (`in_place` and no destination) must not slip through."""
    body = {
        "source_connection_id": "conn-src",
        "source_database": "shop",
        "in_place": True,
    }
    with pytest.raises(ValidationError):
        CloneJobCreateRequest.model_validate(body)


@pytest.mark.unit
def test_schema_has_no_in_place_field_and_no_in_place_validator() -> None:
    assert "in_place" not in CloneJobCreateRequest.model_fields
    validators = CloneJobCreateRequest.__pydantic_decorators__.model_validators
    assert not [name for name in validators if "in_place" in name.lower()]


@pytest.mark.unit
def test_destination_is_required_not_optional() -> None:
    """The report removes 'the empty-destination case': the destination is always given, so the
    fields have no empty default (interpretation: see D14.acceptance.md)."""
    fields = CloneJobCreateRequest.model_fields
    assert fields["destination_connection_id"].is_required()
    assert fields["destination_database"].is_required()
    for missing in ("destination_connection_id", "destination_database"):
        body = {k: v for k, v in VALID_BODY.items() if k != missing}
        with pytest.raises(ValidationError):
            CloneJobCreateRequest.model_validate(body)
    for empty in ("destination_connection_id", "destination_database"):
        with pytest.raises(ValidationError):
            CloneJobCreateRequest.model_validate(_body(**{empty: ""}))


@pytest.mark.unit
def test_openapi_schema_has_no_in_place_property() -> None:
    client = TestClient(create_app(), client=("127.0.0.1", 50000), base_url="http://localhost")
    schema = client.get("/openapi.json").json()
    component = schema["components"]["schemas"]["CloneJobCreateRequest"]
    assert "in_place" not in component["properties"]
    assert component.get("additionalProperties") is False


class _FakePersistence:
    """Boundary stand-in for the metadata database (the one thing the route needs besides the
    origin): one saved connection per id, and a record of every job written."""

    def __init__(self) -> None:
        self.created_jobs: list[dict[str, Any]] = []

    def get_connection(self, connection_id: str) -> dict[str, Any]:
        # Port 1 on loopback: passes the address policy, and nothing listens there, so a request
        # that reaches the origin or the destination fails with a server error, not a refusal.
        return {
            "connection_id": connection_id,
            "engine": "postgres",
            "host": "127.0.0.1",
            "port": 1,
            "username": "u",
            "encrypted_password": secrets.encrypt("p"),
            "created_at": "2026-01-01T00:00:00Z",
        }

    def create_clone_job(self, job_id: str, data: dict[str, Any]) -> None:
        self.created_jobs.append(data)

    def save_clone_job(self, job_id: str, data: dict[str, Any]) -> None:
        self.created_jobs.append(data)


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, _FakePersistence]:
    monkeypatch.setenv("NORM_SECRET_KEY", Fernet.generate_key().decode())
    app = create_app()
    fake = _FakePersistence()
    app.dependency_overrides[get_connections] = lambda: fake
    client = TestClient(
        app,
        client=("127.0.0.1", 50000),
        base_url="http://localhost",
        raise_server_exceptions=False,
    )
    return client, fake


@pytest.mark.unit
@pytest.mark.parametrize("value", [True, False])
def test_route_refuses_in_place_before_touching_any_database(
    api: tuple[TestClient, _FakePersistence], value: bool
) -> None:
    client, fake = api
    response = client.post("/normalization/clone-jobs", json=_body(in_place=value))
    assert response.status_code == REFUSAL_STATUSES[-1]
    assert any("in_place" in error["loc"] for error in response.json()["detail"])
    assert fake.created_jobs == []


# ---------------------------------------------------------------------------
# (2) No writer is ever built from a source connection; the swap machinery is gone.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_clone_executor_has_no_staging_name() -> None:
    assert not hasattr(clone_executor, "staging_name")
    tree = ast.parse((NORMAPI_SRC / "clone_executor.py").read_text(encoding="utf-8"))
    defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "staging_name" not in defined


@pytest.mark.unit
@pytest.mark.parametrize("writer", [PostgresDestination, ClickHouseDestination])
def test_destination_writers_have_no_swap_table(writer: type) -> None:
    assert not hasattr(writer, "swap_table")


def _normapi_modules() -> list[Path]:
    return sorted(NORMAPI_SRC.rglob("*.py"))


def _mentions_source(node: ast.AST) -> bool:
    """True when an expression names a source: a variable, attribute or string key."""
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and "source" in child.id.lower():
            return True
        if isinstance(child, ast.Attribute) and "source" in child.attr.lower():
            return True
        is_text = isinstance(child, ast.Constant) and isinstance(child.value, str)
        if is_text and "source" in child.value.lower():
            return True
    return False


def _assigned_values(tree: ast.AST) -> list[tuple[str, int, ast.AST]]:
    found: list[tuple[str, int, ast.AST]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    found.append((target.id, node.lineno, node.value))
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.value is not None
        ):
            found.append((node.target.id, node.lineno, node.value))
    return found


@pytest.mark.unit
def test_no_destination_variable_is_derived_from_a_source() -> None:
    """Old code: `destination_connection_id = request["source_connection_id"] if in_place else
    request["destination_connection_id"]`, a destination that is the source. A name that says
    "dest" must never be assigned from an expression that mentions a source."""
    offenders: list[str] = []
    for path in _normapi_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for name, line, value in _assigned_values(tree):
            if "dest" in name.lower() and _mentions_source(value):
                offenders.append(f"{path.name}:{line} {name} = {ast.unparse(value)[:80]}")
    assert offenders == []


@pytest.mark.unit
def test_destination_writer_is_never_built_from_a_source_connection() -> None:
    """Structural: every `build_destination_writer(x)` call passes a name whose every assignment
    in the module is free of anything called "source". The check must also find the calls, so it
    cannot pass by looking at nothing."""
    calls = 0
    for path in _normapi_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assignments = _assigned_values(tree)
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and ast.unparse(node.func).endswith("build_destination_writer")
            ):
                continue
            calls += 1
            assert node.args, f"{path.name}:{node.lineno} passes no connection"
            argument = node.args[0]
            assert not _mentions_source(argument), f"{path.name}:{node.lineno} passes a source"
            if isinstance(argument, ast.Name):
                origins = [v for n, _, v in assignments if n == argument.id]
                assert origins, f"{path.name}:{node.lineno} {argument.id} has no assignment"
                for value in origins:
                    assert not _mentions_source(value), (
                        f"{path.name}:{node.lineno} {argument.id} = {ast.unparse(value)}"
                    )
    assert calls >= 1


@pytest.mark.unit
def test_swap_machinery_text_is_gone_from_packages() -> None:
    """`staging_name`, `swap_table` and the ClickHouse `EXCHANGE TABLES` statement went with the
    feature (report D14 'What goes')."""
    pattern = re.compile(r"staging_name|swap_table|EXCHANGE\s+TABLES", re.IGNORECASE)
    hits = [
        f"{path.relative_to(ROOT)}:{number}"
        for path in sorted((ROOT / "packages").glob("*/src/**/*.py"))
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line)
    ]
    assert hits == []


# ---------------------------------------------------------------------------
# (3) Plan 2.4 grep: the feature name is absent from sources and the three user docs.
# ---------------------------------------------------------------------------

FEATURE_NAME = re.compile(r"in[\s_-]?place", re.IGNORECASE)

# Different meanings of the words, checked by reading each hit at the parent commit:
#   "replaced in place (decision #7)"   a DDL column replaced by its typed column
#   "in place of"                       "instead of"
#   "object in place" / "mutated in place" / "one chunk, in place"   Python object mutation
#   "replicates schema in place"        "on the spot"; no connection to the removed mode
BENIGN = (
    re.compile(r"replaced in place \(decision #7\)"),
    re.compile(r"\bin place of\b"),
    re.compile(r"\bobject in place\b"),
    re.compile(r"never mutated in place"),
    re.compile(r"across one chunk, in place"),
    re.compile(r"replicates schema in place"),
)

# The one sentence that names the removed field because it describes the refusal (ADR-013 and
# ADR-017 amendments use the same words).
REFUSAL_SENTENCE = re.compile(r"schema refuses an `in_place` field")

DOCS = ("README.md", "ARCHITECTURE.md", "GLOSSARY.md")


def _scanned_files() -> list[Path]:
    files = [ROOT / name for name in DOCS]
    for pattern in ("packages/*/src/**/*", "ui/src/**/*"):
        files += [p for p in ROOT.glob(pattern) if p.is_file() and p.suffix != ".pyc"]
    return sorted(files)


@pytest.mark.unit
def test_in_place_feature_name_is_absent() -> None:
    hits: list[str] = []
    for path in _scanned_files():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not FEATURE_NAME.search(line):
                continue
            if any(pattern.search(line) for pattern in BENIGN):
                continue
            if path.name == "ARCHITECTURE.md" and REFUSAL_SENTENCE.search(line):
                continue
            hits.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()[:100]}")
    assert hits == []


@pytest.mark.unit
def test_refusal_sentence_allowance_is_narrow() -> None:
    """The allowance above must not hide the feature: at most that one sentence per document and
    only in ARCHITECTURE.md; README.md and GLOSSARY.md never name the field."""
    for name in ("README.md", "GLOSSARY.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "in_place" not in text
        assert not re.search(r"in[\s-]place (mode|clone)", text, re.IGNORECASE)
    architecture = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert architecture.count("in_place") <= 1
    assert not re.search(r"in[\s-]place (mode|clone)", architecture, re.IGNORECASE)


@pytest.mark.unit
def test_in_place_grep_would_catch_the_old_text() -> None:
    """The scanner bites: it flags the removed feature's own wording."""
    for old in (
        "in_place: bool = False",
        "In-place mode (`in_place`, off by default) replaces the origin's tables",
        "An in-place clone writes into the origin database",
        "In in-place mode the destination is the origin",
    ):
        assert FEATURE_NAME.search(old)
        assert not any(pattern.search(old) for pattern in BENIGN)


# ---------------------------------------------------------------------------
# (4) Never guess: a destination that is provably the origin is refused.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_same_connection_and_same_database_is_refused(
    api: tuple[TestClient, _FakePersistence],
) -> None:
    """ADR-013 / ADR-017: 'every clone writes a separate copy'. A destination with the same saved
    connection and the same database name is the origin itself. Which layer refuses is not stated
    anywhere, so any of 400 / 409 / 422 counts; a server error (the old code tries to connect) or
    a created job does not."""
    client, fake = api
    body = _body(destination_connection_id="conn-src", destination_database="shop")
    response = client.post("/normalization/clone-jobs", json=body)
    assert response.status_code in REFUSAL_STATUSES
    assert fake.created_jobs == []


@pytest.mark.unit
def test_same_connection_with_another_database_is_not_a_schema_error() -> None:
    """Control: a second database on the same server is a separate copy, so the rule is about
    identity, not about sharing a connection."""
    request = CloneJobCreateRequest.model_validate(
        _body(destination_connection_id="conn-src", destination_database="shop_clone")
    )
    assert request.destination_connection_id == request.source_connection_id


@pytest.mark.unit
def test_same_database_name_on_another_connection_is_not_guessed_to_be_the_origin() -> None:
    """Never guess: two saved connections may or may not point at one server, and the schema
    cannot tell. Only provable identity (same id, same database) is refused."""
    request = CloneJobCreateRequest.model_validate(
        _body(destination_connection_id="conn-dst", destination_database="shop")
    )
    assert request.destination_database == request.source_database

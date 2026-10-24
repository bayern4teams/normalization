"""D3 acceptance: OpenLineage events at job boundaries (report D3, plan 9 "D3").

Written from the report's Evidence/Fix text, the plan (2.4, 4, 9 "D3") and the
OpenLineage spec only; the implementation did not exist when this was written.

The seam is the existing Phase 2 entry point, `clone_executor._run_phase2`,
run on a SQLite-backed `PgPersistence` with fake source and destination
connectors (the way the D1 acceptance drives `_normalize_table`). Everything
is observed from outside:

* over HTTP: `GET /normalization/clone-jobs/{id}/lineage`,
* from the metadata database: the `normalization_lineage_events` table, read
  with raw SQL and decoded by introspection (the column layout is not assumed),
* from the destination fake: the columns a table really received.

What is assumed of the implementation is listed in `.handoff/D3.acceptance.md`
(git history: `git log -- .handoff/`).

Payloads are validated against the OpenLineage JSON Schemas vendored under
`tests/defects/openlineage_spec/` (core spec 2-0-2 plus the facet schemas, Apache
2.0, notice kept). `jsonschema` is not a dependency of this repository, so a
small validator for the keywords those schemas use lives here; it is
self-tested below, so a validator that accepted everything would fail.
"""

from __future__ import annotations

import ast
import copy
import datetime as dt
import json
import re
import socket
import subprocess
import threading
import time
import urllib.request
import uuid
from collections import Counter
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import urlparse

import pytest
import sqlalchemy as sa
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from normapi.app import build_dispatcher, build_normalizer_registry, create_app
from normapi.clone_executor import plan_one_table
from normapi.dependencies import get_connections
from normapi.pg_persistence import PgPersistence
from normapi.scaffold_profile import SCAFFOLD_PROFILE
from normcore.enums import FieldSemanticType
from normio.connector import ColumnInfo

from normapi import clone_executor, lineage

REPO = Path(__file__).resolve().parents[2]
LINEAGE_PY = REPO / "packages/normapi/src/normapi/lineage.py"
SPEC_DIR = REPO / "tests/defects/openlineage_spec"
SPEC_VERSION = "2-0-2"
CORE_ID = f"https://openlineage.io/spec/{SPEC_VERSION}/OpenLineage.json"
FACET_PREFIX = "https://openlineage.io/spec/facets/"
EVENTS_TABLE = "normalization_lineage_events"

# --------------------------------------------------------------------------- planted data
SRC_DB, DST_DB = "srcdb_d3", "dstdb_d3"
SRC_HOST, DST_HOST = "src-host.d3.invalid", "dst-host.d3.invalid"
USERNAME = "svc_d3_reader"
PASSWORD = "Zq9!planted-pw-d3"
TABLE_A, TABLE_B = "customers", "orders"
ODD_COLUMN = "Größe (m²)"  # non-ASCII, spaces, parentheses
NOTE_CELL = "private-note-d3-4471"  # a cell value: lineage is metadata, never data
PHONE_CELL = "+1 650-253-0000"
PROFILE_VERSION = SCAFFOLD_PROFILE.version

# Which source columns carry which semantic type, per table. `note` and the odd
# column have none configured: they must be mapped, with no invented transformation.
FIELD_CONFIGS: dict[str, dict[str, str]] = {
    TABLE_A: {
        "phone": FieldSemanticType.PHONE.value,
        "country": FieldSemanticType.COUNTRY.value,
        "note": "",
    },
    TABLE_B: {
        "amount": FieldSemanticType.MONEY.value,
        "ship_country": FieldSemanticType.COUNTRY.value,
    },
}
COLUMNS: dict[str, list[str]] = {
    TABLE_A: ["id", "phone", "country", "note"],
    TABLE_B: ["order_id", "amount", "ship_country", ODD_COLUMN],
}
PRIMARY_KEY = {TABLE_A: ["id"], TABLE_B: ["order_id"]}
ROWS: dict[str, list[dict[str, Any]]] = {
    TABLE_A: [
        {"id": 1, "phone": PHONE_CELL, "country": "United States", "note": NOTE_CELL},
        {"id": 2, "phone": "", "country": "Germany", "note": None},
    ],
    TABLE_B: [
        {"order_id": 10, "amount": "12.50 USD", "ship_country": "France", ODD_COLUMN: "7"},
        {"order_id": 11, "amount": "3,00 EUR", "ship_country": None, ODD_COLUMN: None},
    ],
}


# --------------------------------------------------------------------------- fakes
class _Batch:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def to_pylist(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self._rows)


class _Source:
    """Fake source. After `armed`, any read is a failure: used to prove that a
    lineage answer needs no row scan."""

    def __init__(self, data: dict[str, list[dict[str, Any]]]) -> None:
        self.data = data
        self.reads = 0
        self.armed = False

    def list_tables(self) -> list[str]:
        return list(self.data)

    def read_table(self, table: str, *args: Any, **kwargs: Any) -> Any:
        assert not self.armed, "a source read happened after the job: a row scan"
        self.reads += 1
        rows = [{"source_row_key": f"{table}:{i}", **row} for i, row in enumerate(self.data[table])]
        if rows:
            yield _Batch(rows)

    def get_columns(self, table: str) -> list[ColumnInfo]:
        return [ColumnInfo(name=c, native_type="text") for c in COLUMNS[table]]

    def get_primary_key(self, table: str) -> list[str]:
        return list(PRIMARY_KEY[table])

    def close(self) -> None:
        pass


class _Dest:
    def __init__(self, fail_on: dict[str, BaseException] | None = None) -> None:
        self.inserted: dict[str, list[dict[str, Any]]] = {}
        self.fail_on = fail_on or {}

    def bulk_insert(self, database: str, table: str, rows: list[dict[str, Any]], **kw: Any) -> None:
        if table in self.fail_on:
            raise self.fail_on[table]
        self.inserted.setdefault(table, []).extend(copy.deepcopy(rows))

    def close(self) -> None:
        pass


# --------------------------------------------------------------------------- harness
class _Env:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.dsn = f"sqlite:///{tmp_path}/m.db"
        self.persistence = PgPersistence(self.dsn)
        self.persistence.ensure_schema()
        self.mp = monkeypatch
        self.src_conn = self.persistence.save_connection(
            "src-conn",
            engine="postgres",
            host=SRC_HOST,
            port=5432,
            username=USERNAME,
            password=PASSWORD,
        )
        self.dst_conn = self.persistence.save_connection(
            "dst-conn",
            engine="postgres",
            host=DST_HOST,
            port=5432,
            username=USERNAME,
            password=PASSWORD,
        )
        app = create_app(
            dictionaries_dir=tmp_path / "dicts", custom_dictionaries_dir=tmp_path / "custom"
        )
        app.dependency_overrides[get_connections] = lambda: self.persistence
        self.client = TestClient(app)
        self.dispatcher = build_dispatcher(env_id="env-d3")
        self.source = _Source(copy.deepcopy(ROWS))
        self.dests: list[_Dest] = []
        self.n = 0
        monkeypatch.setattr(clone_executor, "_make_pool", lambda env_id: None)
        monkeypatch.delenv("NORM_OPENLINEAGE_URL", raising=False)

    def new_job(
        self,
        tables: list[str] | None = None,
        data: dict[str, list[dict[str, Any]]] | None = None,
    ) -> str:
        self.n += 1
        job_id = str(uuid.uuid4())
        tables = tables or [TABLE_A, TABLE_B]
        if data is not None:
            self.source = _Source(data)
        job: dict[str, Any] = {
            "job_id": job_id,
            "status": "RUNNING",
            "source_connection_id": "src-conn",
            "source_database": SRC_DB,
            "source_schema": None,
            "destination_connection_id": "dst-conn",
            "destination_database": DST_DB,
            "tables": tables,
            "field_configs": {t: dict(FIELD_CONFIGS[t]) for t in tables},
            "inferred_field_configs": {},
            "typed_destination_columns": False,
            "country": None,
            "locale": None,
            "max_new_null_rate": None,
            "cross_table_entity_key": None,
            "in_place": False,
            "progress": {
                "current_table": None,
                "tables_completed": [],
                "rows_done": 0,
                "checkpoints": {},
            },
            "error": None,
        }
        # what `verify_and_create_schema` records at Phase 1
        job["destination_plan"] = {}
        for table in tables:
            plan = plan_one_table(self.source, "postgres", table, job)
            job["destination_plan"][table] = {
                k: plan[k] for k in ("typed_columns", "currency_columns", "code_columns")
            }
        self.persistence.create_clone_job(job_id, job)
        return job_id

    def run(
        self,
        job_id: str,
        *,
        fail_on: dict[str, BaseException] | None = None,
    ) -> _Dest:
        dest = _Dest(fail_on)
        self.dests.append(dest)
        self.mp.setattr(
            clone_executor, "build_source_connector", lambda conn, db, schema=None: self.source
        )
        self.mp.setattr(clone_executor, "build_destination_writer", lambda conn: dest)
        clone_executor._run_phase2(self.persistence, self.dispatcher, None, job_id)
        return dest

    def job(self, job_id: str) -> dict[str, Any]:
        job = self.persistence.get_clone_job(job_id)
        assert job is not None
        return job

    def lineage(self, job_id: str) -> list[dict[str, Any]]:
        resp = self.client.get(f"/normalization/clone-jobs/{job_id}/lineage")
        assert resp.status_code == 200, resp.text
        return as_events(resp.json())

    def stored(self, dsn: str | None = None) -> tuple[list[dict[str, Any]], str]:
        """(events, raw text of every cell) from the metadata DB, read with raw SQL."""
        engine = sa.create_engine(dsn or self.dsn)
        with engine.begin() as conn:
            rows = conn.execute(sa.text(f"SELECT * FROM {EVENTS_TABLE}")).mappings().all()
        events: list[dict[str, Any]] = []
        raw: list[str] = []
        for row in rows:
            for value in row.values():
                raw.append(value if isinstance(value, str) else json.dumps(value, default=str))
                event = _decode_event(value)
                if event is not None:
                    events.append(event)
        return events, "\n".join(raw)


@pytest.fixture(autouse=True)
def secret_key(monkeypatch: pytest.MonkeyPatch) -> str:
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("NORM_SECRET_KEY", key)
    return key


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, secret_key: str) -> _Env:
    return _Env(tmp_path, monkeypatch)


# --------------------------------------------------------------------------- event helpers
def _decode_event(value: Any) -> dict[str, Any] | None:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    if isinstance(value, dict) and "eventType" in value:
        return value
    if isinstance(value, dict):  # an envelope such as {"event": {...}}
        for inner in value.values():
            found = _decode_event(inner)
            if found is not None:
                return found
    return None


def as_events(body: Any) -> list[dict[str, Any]]:
    """The route may return a bare list or an object wrapping one list of events."""
    if isinstance(body, dict):
        lists = [v for v in body.values() if isinstance(v, list)]
        assert len(lists) == 1, f"cannot find the event list in {sorted(body)}"
        body = lists[0]
    assert isinstance(body, list)
    events = [e for e in (_decode_event(x) for x in body) if e is not None]
    assert len(events) == len(body), "every element of the response must be an OpenLineage event"
    return events


def _tail(name: str) -> str:
    return re.split(r"[./:]", name)[-1]


def _ds(ds: dict[str, Any]) -> str:
    return f"{ds['namespace']}|{ds['name']}"


def table_of(event: dict[str, Any]) -> str | None:
    for key in ("outputs", "inputs"):
        for ds in event.get(key) or []:
            return _tail(ds["name"])
    return None


def of_table(events: list[dict[str, Any]], table: str) -> list[dict[str, Any]]:
    return [e for e in events if table_of(e) == table]


def kinds(events: list[dict[str, Any]]) -> Counter[str]:
    return Counter(e["eventType"] for e in events)


def facets_of(ds: dict[str, Any]) -> dict[str, Any]:
    return dict(ds.get("facets") or {})


def column_lineage(event: dict[str, Any]) -> dict[str, Any]:
    outputs = event.get("outputs") or []
    assert len(outputs) == 1, f"one output dataset (the destination table) expected: {outputs}"
    facet = facets_of(outputs[0]).get("columnLineage")
    assert facet is not None, (
        "no `columnLineage` in outputs[0].facets (the OpenLineage dataset-facet slot)"
    )
    fields = facet["fields"]
    assert isinstance(fields, dict)
    return fields


def dest_columns(env: _Env, job_id: str, dest: _Dest, table: str) -> set[str]:
    """Every column the destination really received, plus what the plan says it will
    get even for a table with no rows. Ground truth, not the implementation's idea."""
    cols = {k for row in dest.inserted.get(table, []) for k in row}
    plan = env.job(job_id)["destination_plan"][table]
    cols |= set(plan["currency_columns"].values()) | set(plan["code_columns"].values())
    cols |= set(COLUMNS[table])
    return cols


def source_of(env: _Env, job_id: str, table: str, column: str) -> str:
    """The source column a destination column derives from: itself, or the column a
    companion is a projection of (taken from the job's own recorded plan)."""
    plan = env.job(job_id)["destination_plan"][table]
    for mapping in (plan["currency_columns"], plan["code_columns"]):
        for base, companion in mapping.items():
            if companion == column:
                return str(base)
    return column


def semantic_type_of(table: str, source_column: str) -> str | None:
    return FIELD_CONFIGS[table].get(source_column) or None


def description_strings(entry: dict[str, Any]) -> list[str]:
    """Every string in a columnLineage field entry that is not an input identity."""
    out: list[str] = []

    def walk(node: Any, skip: bool) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, skip or key in {"namespace", "name", "field"})
        elif isinstance(node, list):
            for value in node:
                walk(value, skip)
        elif isinstance(node, str) and not skip:
            out.append(node)

    walk(entry, False)
    return out


def has_token(text: str, token: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9]){re.escape(token)}(?![A-Za-z0-9])", text, re.I) is not None


# --------------------------------------------------------------------------- the spec validator
class _Spec:
    """Just enough JSON Schema (2020-12) for the vendored OpenLineage documents:
    $ref (local and cross-document), allOf/anyOf/oneOf/not, type, enum, format,
    properties, required, additionalProperties, items."""

    def __init__(self) -> None:
        self.docs: dict[str, dict[str, Any]] = {}
        for path in sorted(SPEC_DIR.rglob("*.json")):
            doc = json.loads(path.read_text(encoding="utf-8"))
            self.docs[doc["$id"]] = doc

    def resolve(self, ref: str, base: str) -> tuple[dict[str, Any], str]:
        url, _, fragment = ref.partition("#")
        doc_id = url or base
        if doc_id not in self.docs:
            msg = f"schema {doc_id} is not vendored under tests/defects/openlineage_spec"
            raise KeyError(msg)
        node: Any = self.docs[doc_id]
        for part in [p for p in fragment.split("/") if p]:
            node = node[part.replace("~1", "/").replace("~0", "~")]
        return node, doc_id

    @staticmethod
    def _is_type(value: Any, name: str) -> bool:
        return {
            "object": isinstance(value, dict),
            "array": isinstance(value, list),
            "string": isinstance(value, str),
            "boolean": isinstance(value, bool),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
            "null": value is None,
        }[name]

    @staticmethod
    def _format_ok(value: str, fmt: str) -> bool:
        try:
            if fmt == "date-time":
                return dt.datetime.fromisoformat(value).tzinfo is not None
            if fmt == "uuid":
                uuid.UUID(value)
                return True
            if fmt == "uri":
                parsed = urlparse(value)
                return bool(parsed.scheme and (parsed.netloc or parsed.path))
        except ValueError:
            return False
        return True

    # C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
    def errors(  # noqa: PLR0912 - one branch per JSON Schema keyword
        self, inst: Any, schema: dict[str, Any], doc: str, path: str = "$"
    ) -> list[str]:
        out: list[str] = []
        if "$ref" in schema:
            sub, sub_doc = self.resolve(schema["$ref"], doc)
            out += self.errors(inst, sub, sub_doc, path)
        for sub in schema.get("allOf", []):
            out += self.errors(inst, sub, doc, path)
        if "anyOf" in schema and not any(
            not self.errors(inst, s, doc, path) for s in schema["anyOf"]
        ):
            out.append(f"{path}: matches no anyOf branch")
        if "oneOf" in schema:
            hits = sum(not self.errors(inst, s, doc, path) for s in schema["oneOf"])
            if hits != 1:
                out.append(f"{path}: matches {hits} oneOf branches")
        if "not" in schema and not self.errors(inst, schema["not"], doc, path):
            out.append(f"{path}: matches a `not` schema")
        types = schema.get("type")
        if types is not None:
            names = [types] if isinstance(types, str) else types
            if not any(self._is_type(inst, n) for n in names):
                return [*out, f"{path}: expected {names}, got {type(inst).__name__}"]
        if "enum" in schema and inst not in schema["enum"]:
            out.append(f"{path}: {inst!r} not in {schema['enum']}")
        if (
            isinstance(inst, str)
            and "format" in schema
            and not self._format_ok(inst, schema["format"])
        ):
            out.append(f"{path}: {inst!r} is not a {schema['format']}")
        if isinstance(inst, dict):
            out += [f"{path}: missing {k!r}" for k in schema.get("required", []) if k not in inst]
            props = schema.get("properties", {})
            extra = schema.get("additionalProperties")
            for key, value in inst.items():
                if key in props:
                    out += self.errors(value, props[key], doc, f"{path}.{key}")
                elif isinstance(extra, dict):
                    out += self.errors(value, extra, doc, f"{path}.{key}")
                elif extra is False:
                    out.append(f"{path}: unexpected {key!r}")
        if isinstance(inst, list) and "items" in schema:
            for i, value in enumerate(inst):
                out += self.errors(value, schema["items"], doc, f"{path}[{i}]")
        return out

    def validate_event(self, event: dict[str, Any]) -> list[str]:
        out = self.errors(event, {"$ref": f"{CORE_ID}#/$defs/RunEvent"}, CORE_ID)
        schema_url = str(event.get("schemaURL", ""))
        if not schema_url.startswith(
            f"https://openlineage.io/spec/{SPEC_VERSION}/OpenLineage.json"
        ):
            out.append(f"schemaURL {schema_url!r} is not the pinned core spec {SPEC_VERSION}")
        slots: list[tuple[str, dict[str, Any]]] = [
            ("run.facets", (event.get("run") or {}).get("facets") or {}),
            ("job.facets", (event.get("job") or {}).get("facets") or {}),
        ]
        for side in ("inputs", "outputs"):
            for i, ds in enumerate(event.get(side) or []):
                for slot in ("facets", "inputFacets", "outputFacets"):
                    slots.append((f"{side}[{i}].{slot}", ds.get(slot) or {}))
        for where, facets in slots:
            for key, facet in facets.items():
                out += self._facet_errors(f"{where}.{key}", key, facet)
        return out

    def _facet_errors(self, where: str, key: str, facet: Any) -> list[str]:
        if not isinstance(facet, dict):
            return [f"{where}: a facet must be an object"]
        base = str(facet.get("_schemaURL", "")).split("#")[0]
        if not base.startswith(FACET_PREFIX):
            # a custom facet: it must still be a BaseFacet (_producer, _schemaURL)
            return self.errors(facet, {"$ref": f"{CORE_ID}#/$defs/BaseFacet"}, CORE_ID, where)
        if base not in self.docs:
            return [
                f"{where}: facet schema {base} is not vendored (tests/defects/openlineage_spec)"
            ]
        root = self.docs[base]
        if key not in root.get("properties", {}):
            return [f"{where}: key {key!r} is not what {base} defines"]
        return self.errors({key: facet}, root, base, where)


@pytest.fixture(scope="module")
def spec() -> _Spec:
    return _Spec()


def assert_valid(spec: _Spec, events: list[dict[str, Any]]) -> None:
    assert events, "no events to validate"
    problems = [f"{e.get('eventType')}: {p}" for e in events for p in spec.validate_event(e)]
    assert not problems, "\n".join(problems[:10])


# --------------------------------------------------------------------------- secrets
def secret_needles(env: _Env, key: str) -> dict[str, str]:
    stored = env.persistence.get_connection("src-conn")
    assert stored is not None
    return {
        "password": PASSWORD,
        "stored ciphertext": str(stored["encrypted_password"]),
        "username": USERNAME,
        "NORM_SECRET_KEY": key,
    }


_USERINFO_URL = re.compile(r"[a-z][a-z0-9+.-]*://[^/@\s\"']*:[^/@\s\"']*@", re.I)


def assert_no_secrets(text: str, env: _Env, key: str) -> None:
    for what, needle in secret_needles(env, key).items():
        assert needle not in text, f"{what} leaked into lineage"
    assert not _USERINFO_URL.search(text), "a user:password@host URL leaked into lineage"


# =========================================================================== tests
@pytest.mark.unit
class TestRunEventsPerJobAndTable:
    def test_start_and_complete_per_table_with_source_input_and_destination_output(
        self, env: _Env
    ) -> None:
        job_id = env.new_job()
        env.run(job_id)
        assert env.job(job_id)["status"] == "COMPLETED"
        events = env.lineage(job_id)
        for table in (TABLE_A, TABLE_B):
            mine = of_table(events, table)
            assert kinds(mine) == {"START": 1, "COMPLETE": 1}, kinds(mine)
            start = next(e for e in mine if e["eventType"] == "START")
            done = next(e for e in mine if e["eventType"] == "COMPLETE")
            assert start["run"]["runId"] == done["run"]["runId"]
            assert dt.datetime.fromisoformat(start["eventTime"]) <= dt.datetime.fromisoformat(
                done["eventTime"]
            )
            for event in mine:
                assert len(event["inputs"]) == 1 and len(event["outputs"]) == 1
                src, out = _ds(event["inputs"][0]), _ds(event["outputs"][0])
                assert SRC_DB in src and _tail(event["inputs"][0]["name"]) == table, src
                assert DST_DB in out and _tail(event["outputs"][0]["name"]) == table, out
                assert DST_DB not in src and SRC_DB not in out, "input/output not told apart"
        assert {table_of(e) for e in events} == {TABLE_A, TABLE_B}, "an event for no table"
        run_ids = {e["run"]["runId"] for e in events}
        assert len(run_ids) == 2, "one run per (job, table)"

    def test_every_event_belongs_to_its_job_and_two_jobs_do_not_mix(self, env: _Env) -> None:
        first, second = env.new_job(), env.new_job()
        env.run(first)
        env.run(second)
        for mine, other in ((first, second), (second, first)):
            events = env.lineage(mine)
            assert len(events) == 4
            for event in events:
                text = json.dumps(event)
                assert mine in text, "an event that does not say which clone job it is from"
                assert other not in text
        assert {e["run"]["runId"] for e in env.lineage(first)}.isdisjoint(
            e["run"]["runId"] for e in env.lineage(second)
        )

    def test_a_table_with_no_rows_still_gets_start_and_complete_with_lineage(
        self, env: _Env
    ) -> None:
        empty = {TABLE_A: [], TABLE_B: copy.deepcopy(ROWS[TABLE_B])}
        job_id = env.new_job(data=empty)
        dest = env.run(job_id)
        events = env.lineage(job_id)
        mine = of_table(events, TABLE_A)
        assert kinds(mine) == {"START": 1, "COMPLETE": 1}
        complete = next(e for e in mine if e["eventType"] == "COMPLETE")
        # no rows were scanned, so the columns come from the plan, not from data
        assert set(column_lineage(complete)) == dest_columns(env, job_id, dest, TABLE_A)


@pytest.mark.unit
class TestColumnLineage:
    def _complete(self, env: _Env) -> tuple[str, _Dest, list[dict[str, Any]]]:
        job_id = env.new_job()
        dest = env.run(job_id)
        events = [e for e in env.lineage(job_id) if e["eventType"] == "COMPLETE"]
        assert len(events) == 2
        return job_id, dest, events

    def test_every_destination_column_including_companions_is_in_the_facet(self, env: _Env) -> None:
        job_id, dest, events = self._complete(env)
        for table in (TABLE_A, TABLE_B):
            cols = dest_columns(env, job_id, dest, table)
            plan = env.job(job_id)["destination_plan"][table]
            companions = set(plan["currency_columns"].values()) | set(plan["code_columns"].values())
            assert companions, "harness: the fixture must produce companion columns"
            assert companions <= {k for r in dest.inserted[table] for k in r}, "harness"
            event = next(e for e in events if table_of(e) == table)
            fields = column_lineage(event)
            assert set(fields) == cols, (
                f"missing {sorted(cols - set(fields))}, invented {sorted(set(fields) - cols)}"
            )

    def test_each_column_maps_to_exactly_its_source_column(self, env: _Env) -> None:
        job_id, _dest, events = self._complete(env)
        for table in (TABLE_A, TABLE_B):
            event = next(e for e in events if table_of(e) == table)
            input_ds = event["inputs"][0]
            for column, entry in column_lineage(event).items():
                fields = entry["inputFields"]
                assert len(fields) == 1, f"{table}.{column}: one source field, got {fields}"
                assert fields[0]["namespace"] == input_ds["namespace"]
                assert fields[0]["name"] == input_ds["name"]
                assert fields[0]["field"] == source_of(env, job_id, table, column)

    def test_configured_columns_carry_normalizer_semantic_type_and_profile_version(
        self, env: _Env
    ) -> None:
        job_id, _dest, events = self._complete(env)
        registry = build_normalizer_registry()
        checked = 0
        for table in (TABLE_A, TABLE_B):
            event = next(e for e in events if table_of(e) == table)
            for column, entry in column_lineage(event).items():
                source_col = source_of(env, job_id, table, column)
                semantic = semantic_type_of(table, source_col)
                if semantic is None:
                    continue
                text = " | ".join(description_strings(entry))
                normalizer = registry.require(FieldSemanticType(semantic)).name
                where = f"{table}.{column}: {text!r}"
                assert normalizer in text, f"normalizer name {normalizer} missing: {where}"
                assert has_token(text, semantic), f"semantic type {semantic} missing: {where}"
                assert has_token(text, PROFILE_VERSION), f"profile_version missing: {where}"
                checked += 1
        assert (
            checked == 8
        )  # phone, phone_code, country, country_code, amount, amount_currency, ...

    def test_the_profile_version_is_read_not_hard_coded(
        self, env: _Env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        original = SCAFFOLD_PROFILE.version
        probe = "v7d3probe"
        object.__setattr__(SCAFFOLD_PROFILE, "version", probe)
        try:
            job_id = env.new_job()
            env.run(job_id)
        finally:
            object.__setattr__(SCAFFOLD_PROFILE, "version", original)
        complete = next(e for e in env.lineage(job_id) if e["eventType"] == "COMPLETE")
        text = json.dumps(column_lineage(complete))
        assert probe in text and original not in re.sub(r"v7d3probe", "", text)

    def test_never_guess_an_unconfigured_column_is_mapped_without_an_invented_transformation(
        self, env: _Env
    ) -> None:
        _job_id, _dest, events = self._complete(env)
        registry = build_normalizer_registry()
        forbidden = {f.value for f in FieldSemanticType}
        forbidden |= {n.name for f in FieldSemanticType if (n := registry.get(f)) is not None}
        seen = 0
        for table, column in ((TABLE_A, "note"), (TABLE_B, ODD_COLUMN)):
            event = next(e for e in events if table_of(e) == table)
            entry = column_lineage(event)[column]  # it IS mapped (a KeyError is a failure)
            assert [f["field"] for f in entry["inputFields"]] == [column]
            text = " | ".join(description_strings(entry))
            for word in sorted(forbidden):
                assert not has_token(text, word), f"{column}: invented {word!r}: {text!r}"
            assert not has_token(text, PROFILE_VERSION), f"{column}: no profile applied: {text!r}"
            seen += 1
        assert seen == 2

    def test_no_cell_value_appears_in_any_event(self, env: _Env) -> None:
        job_id = env.new_job()
        env.run(job_id)
        text = json.dumps(env.lineage(job_id))
        for cell in (NOTE_CELL, PHONE_CELL, "12.50", "Germany"):
            assert cell not in text, "lineage is metadata: a source value leaked"


@pytest.mark.unit
class TestPayloadsValidateAgainstTheVendoredSpec:
    def test_vendored_spec_is_pinned_and_licensed(self, spec: _Spec) -> None:
        assert CORE_ID in spec.docs
        assert (SPEC_DIR / "LICENSE").read_text().lstrip().startswith("Apache License")
        notice = (SPEC_DIR / "NOTICE.md").read_text()
        assert "Apache" in notice and SPEC_VERSION in notice
        assert f"{FACET_PREFIX}1-2-0/ColumnLineageDatasetFacet.json" in spec.docs

    def test_validator_rejects_what_the_spec_forbids(self, spec: _Spec) -> None:
        good = {
            "eventType": "COMPLETE",
            "eventTime": "2026-01-01T00:00:00+00:00",
            "producer": "https://example.test/normalization",
            "schemaURL": f"{CORE_ID}#/$defs/RunEvent",
            "run": {"runId": str(uuid.uuid4())},
            "job": {"namespace": "n", "name": "j"},
            "inputs": [{"namespace": "n", "name": "in"}],
            "outputs": [
                {
                    "namespace": "n",
                    "name": "out",
                    "facets": {
                        "columnLineage": {
                            "_producer": "https://example.test/normalization",
                            "_schemaURL": f"{FACET_PREFIX}1-2-0/ColumnLineageDatasetFacet.json",
                            "fields": {
                                "c": {
                                    "inputFields": [{"namespace": "n", "name": "in", "field": "c"}]
                                }
                            },
                        }
                    },
                }
            ],
        }
        assert spec.validate_event(good) == []

        def mutated(edit: Any) -> dict[str, Any]:
            event = copy.deepcopy(good)
            edit(event)
            return event

        bad = {
            "no run": mutated(lambda e: e.pop("run")),
            "bad eventType": mutated(lambda e: e.update(eventType="COMPLETED")),
            "bad runId": mutated(lambda e: e["run"].update(runId="not-a-uuid")),
            "no eventTime": mutated(lambda e: e.pop("eventTime")),
            "naive time": mutated(lambda e: e.update(eventTime="2026-01-01T00:00:00")),
            "no producer": mutated(lambda e: e.pop("producer")),
            "dataset without name": mutated(lambda e: e["inputs"][0].pop("name")),
            "wrong core version": mutated(
                lambda e: e.update(schemaURL="https://openlineage.io/spec/1-0-5/OpenLineage.json")
            ),
            "fields missing": mutated(
                lambda e: e["outputs"][0]["facets"]["columnLineage"].pop("fields")
            ),
            "inputFields missing": mutated(
                lambda e: e["outputs"][0]["facets"]["columnLineage"]["fields"]["c"].pop(
                    "inputFields"
                )
            ),
            "input field without field": mutated(
                lambda e: e["outputs"][0]["facets"]["columnLineage"]["fields"]["c"]["inputFields"][
                    0
                ].pop("field")
            ),
            "transformation without type": mutated(
                lambda e: e["outputs"][0]["facets"]["columnLineage"]["fields"]["c"]["inputFields"][
                    0
                ].update(transformations=[{"description": "x"}])
            ),
            "facet without _producer": mutated(
                lambda e: e["outputs"][0]["facets"]["columnLineage"].pop("_producer")
            ),
            "facet under the wrong key": mutated(
                lambda e: e["outputs"][0]["facets"].update(
                    notColumnLineage=e["outputs"][0]["facets"].pop("columnLineage")
                )
            ),
            "unvendored facet schema": mutated(
                lambda e: e["outputs"][0]["facets"]["columnLineage"].update(
                    _schemaURL=f"{FACET_PREFIX}9-9-9/ColumnLineageDatasetFacet.json"
                )
            ),
        }
        for name, event in bad.items():
            assert spec.validate_event(event), f"validator accepted: {name}"

    def test_every_event_of_every_kind_validates(self, env: _Env, spec: _Spec) -> None:
        ok = env.new_job()
        env.run(ok)
        failed = env.new_job()
        env.run(failed, fail_on={TABLE_B: RuntimeError("boom")})
        events = env.lineage(ok) + env.lineage(failed)
        assert {"START", "COMPLETE", "FAIL"} <= set(kinds(events))
        assert_valid(spec, events)

    def test_the_columnlineage_facet_is_a_spec_dataset_facet_on_the_output(
        self, env: _Env, spec: _Spec
    ) -> None:
        job_id = env.new_job()
        env.run(job_id)
        for event in env.lineage(job_id):
            if event["eventType"] != "COMPLETE":
                continue
            facet = facets_of(event["outputs"][0])["columnLineage"]
            assert facet["_schemaURL"].startswith(FACET_PREFIX)
            assert "ColumnLineageDatasetFacet.json" in facet["_schemaURL"]
            assert not spec.errors(
                {"columnLineage": facet},
                spec.docs[facet["_schemaURL"].split("#")[0]],
                facet["_schemaURL"].split("#")[0],
            )

    def test_stored_payloads_validate_too(self, env: _Env, spec: _Spec) -> None:
        job_id = env.new_job()
        env.run(job_id)
        events, _ = env.stored()
        assert_valid(spec, events)


@pytest.mark.unit
class TestEventsAreDurableAndReadableOverHttp:
    def test_the_table_exists_in_the_metadata_schema(self, env: _Env) -> None:
        assert EVENTS_TABLE in sa.inspect(sa.create_engine(env.dsn)).get_table_names()

    def test_stored_rows_equal_what_the_route_returns_and_survive_a_new_connection(
        self, env: _Env
    ) -> None:
        job_id = env.new_job()
        env.run(job_id)
        routed = env.lineage(job_id)
        stored, _ = env.stored()
        reopened = PgPersistence(env.dsn)  # a new process would do exactly this
        assert reopened.get_clone_job(job_id) is not None
        again, _ = env.stored()

        def canon(events: list[dict[str, Any]]) -> list[str]:
            return sorted(json.dumps(e, sort_keys=True) for e in events)

        assert len(stored) == 4
        assert canon(stored) == canon(routed) == canon(again)

    def test_events_are_stored_before_the_job_is_over_not_only_at_the_end(self, env: _Env) -> None:
        """A killed process must leave a START behind: durability is the point (Q13)."""
        job_id = env.new_job()
        with pytest.raises(KeyboardInterrupt):
            env.run(job_id, fail_on={TABLE_B: KeyboardInterrupt()})
        stored, _ = env.stored()
        assert kinds(of_table(stored, TABLE_A)) == {"START": 1, "COMPLETE": 1}
        assert kinds(of_table(stored, TABLE_B))["START"] == 1
        assert kinds(of_table(stored, TABLE_B))["COMPLETE"] == 0

    def test_route_edges(self, env: _Env) -> None:
        resp = env.client.get(f"/normalization/clone-jobs/{uuid.uuid4()}/lineage")
        assert resp.status_code == 404
        never_started = env.new_job()
        resp = env.client.get(f"/normalization/clone-jobs/{never_started}/lineage")
        assert resp.status_code == 200
        assert env.lineage(never_started) == []
        paths = env.client.get("/openapi.json").json()["paths"]
        assert "/normalization/clone-jobs/{job_id}/lineage" in paths
        assert "get" in paths["/normalization/clone-jobs/{job_id}/lineage"]


@pytest.mark.unit
class TestNoSecretsInAnyPayload:
    def test_a_connection_holding_a_password_leaks_nothing(
        self, env: _Env, secret_key: str
    ) -> None:
        job_id = env.new_job()
        env.run(job_id)
        routed = json.dumps(env.lineage(job_id))
        _, raw = env.stored()
        assert env.persistence.get_connection("src-conn") is not None
        assert raw, "harness: stored rows must be readable"
        for text in (routed, raw):
            assert_no_secrets(text, env, secret_key)

    def test_a_failure_message_that_echoes_the_credentials_does_not_reach_the_payload(
        self, env: _Env, secret_key: str
    ) -> None:  # C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
        cipher = str(env.persistence.get_connection("dst-conn")["encrypted_password"])  # type: ignore[index]
        boom = RuntimeError(
            f"password authentication failed for user {USERNAME!r}: "
            f"postgresql://{USERNAME}:{PASSWORD}@{DST_HOST}:5432/{DST_DB} ({cipher})"
        )
        job_id = env.new_job()
        env.run(job_id, fail_on={TABLE_B: boom})
        events = env.lineage(job_id)
        assert kinds(of_table(events, TABLE_B))["FAIL"] == 1
        _, raw = env.stored()
        for text in (json.dumps(events), raw):
            assert_no_secrets(text, env, secret_key)
            assert cipher not in text


@pytest.mark.unit
class TestFailEvent:
    def test_a_failing_table_gets_fail_not_complete_and_earlier_tables_keep_their_complete(
        self, env: _Env
    ) -> None:
        job_id = env.new_job()
        env.run(job_id, fail_on={TABLE_B: RuntimeError("disk full")})
        assert env.job(job_id)["status"] == "FAILED"
        events = env.lineage(job_id)
        assert kinds(of_table(events, TABLE_A)) == {"START": 1, "COMPLETE": 1}
        mine = of_table(events, TABLE_B)
        assert kinds(mine) == {"START": 1, "FAIL": 1}, kinds(mine)
        start = next(e for e in mine if e["eventType"] == "START")
        fail = next(e for e in mine if e["eventType"] == "FAIL")
        assert start["run"]["runId"] == fail["run"]["runId"]
        assert len(fail["inputs"]) == 1 and len(fail["outputs"]) == 1
        assert _tail(fail["inputs"][0]["name"]) == TABLE_B

    def test_the_old_behaviour_a_failed_job_leaves_a_trace_in_lineage(self, env: _Env) -> None:
        """Negative case: on today's code a failed job records nothing outside its job blob."""
        job_id = env.new_job()
        env.run(job_id, fail_on={TABLE_A: RuntimeError("boom")})
        assert env.job(job_id)["status"] == "FAILED"
        events = env.lineage(job_id)
        assert [e["eventType"] for e in events].count("FAIL") == 1
        assert [e["eventType"] for e in events].count("COMPLETE") == 0
        assert not of_table(events, TABLE_B), "a table never reached must not get events"


@pytest.mark.unit
class TestResumeNeverEmitsASecondComplete:
    def test_resume_after_a_crash(self, env: _Env) -> None:
        job_id = env.new_job()
        with pytest.raises(KeyboardInterrupt):  # not an Exception: the job stays RUNNING
            env.run(job_id, fail_on={TABLE_B: KeyboardInterrupt()})
        assert env.job(job_id)["status"] == "RUNNING"
        env.run(job_id)  # the same job, resumed
        assert env.job(job_id)["status"] == "COMPLETED"
        events = env.lineage(job_id)
        assert kinds(of_table(events, TABLE_A)) == {"START": 1, "COMPLETE": 1}, (
            "a table finished before the crash is skipped on resume and must not be re-announced"
        )
        assert kinds(of_table(events, TABLE_B))["COMPLETE"] == 1
        assert kinds(events)["COMPLETE"] == 2
        for run_id in {e["run"]["runId"] for e in events}:
            mine = [e["eventType"] for e in events if e["run"]["runId"] == run_id]
            assert mine.count("START") <= 1
            assert sum(mine.count(t) for t in ("COMPLETE", "FAIL", "ABORT")) <= 1

    def test_rerunning_a_finished_job_emits_nothing(self, env: _Env) -> None:
        job_id = env.new_job()
        env.run(job_id)
        before, _ = env.stored()
        env.run(job_id)  # every table is in tables_completed
        after, _ = env.stored()
        assert len(before) == 4
        assert [json.dumps(e, sort_keys=True) for e in after] == [
            json.dumps(e, sort_keys=True) for e in before
        ]

    def test_resume_after_a_failed_table_still_has_one_complete_per_table(self, env: _Env) -> None:
        job_id = env.new_job()
        env.run(job_id, fail_on={TABLE_B: RuntimeError("transient")})
        job = env.job(job_id)
        job["status"] = "RUNNING"  # what start/claim does for a retried job
        env.persistence.save_clone_job(job_id, job)
        env.run(job_id)
        events = env.lineage(job_id)
        assert kinds(of_table(events, TABLE_A)) == {"START": 1, "COMPLETE": 1}
        assert kinds(of_table(events, TABLE_B))["COMPLETE"] == 1


class _Capture(BaseHTTPRequestHandler):
    status = 200
    bodies: ClassVar[list[bytes]] = []

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        type(self).bodies.append(self.rfile.read(length))
        self.send_response(type(self).status)
        self.end_headers()

    def log_message(self, *args: Any) -> None:
        pass


def _serve(status: int) -> tuple[ThreadingHTTPServer, type[_Capture]]:
    handler = type("Handler", (_Capture,), {"status": status, "bodies": []})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, handler


@pytest.mark.unit
class TestForwarding:
    @pytest.mark.parametrize(
        "url",
        ["http://127.0.0.1:1/api/v1/lineage", "not a url at all", "http://[::1"],
        ids=["connection-refused", "malformed", "bad-ipv6"],
    )
    def test_an_unusable_url_never_fails_the_job_and_events_are_still_stored(
        self, env: _Env, monkeypatch: pytest.MonkeyPatch, url: str
    ) -> None:
        monkeypatch.setenv("NORM_OPENLINEAGE_URL", url)
        job_id = env.new_job()
        env.run(job_id)
        job = env.job(job_id)
        assert job["status"] == "COMPLETED", job.get("error")
        assert len(env.lineage(job_id)) == 4

    def test_a_server_error_never_fails_the_job(
        self, env: _Env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        server, handler = _serve(500)
        try:
            monkeypatch.setenv(
                "NORM_OPENLINEAGE_URL", f"http://127.0.0.1:{server.server_port}/api/v1/lineage"
            )
            job_id = env.new_job()
            env.run(job_id)
            assert env.job(job_id)["status"] == "COMPLETED"
            assert len(env.lineage(job_id)) == 4
            assert handler.bodies, "it should at least have tried"
        finally:
            server.shutdown()

    def test_events_are_forwarded_when_the_url_is_set_and_they_equal_the_stored_ones(
        self, env: _Env, monkeypatch: pytest.MonkeyPatch, secret_key: str, spec: _Spec
    ) -> None:
        server, handler = _serve(200)
        try:
            monkeypatch.setenv(
                "NORM_OPENLINEAGE_URL", f"http://127.0.0.1:{server.server_port}/api/v1/lineage"
            )
            job_id = env.new_job()
            env.run(job_id)
            deadline = time.monotonic() + 10
            while len(handler.bodies) < 4 and time.monotonic() < deadline:
                time.sleep(0.05)
        finally:
            server.shutdown()
        sent = [json.loads(b) for b in handler.bodies]
        assert_valid(spec, sent)
        assert sorted(json.dumps(e, sort_keys=True) for e in sent) == sorted(
            json.dumps(e, sort_keys=True) for e in env.lineage(job_id)
        )
        assert_no_secrets(b"\n".join(handler.bodies).decode(), env, secret_key)

    def test_with_the_variable_unset_no_connection_is_attempted(
        self, env: _Env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def no_network(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("a network connection was attempted without NORM_OPENLINEAGE_URL")

        monkeypatch.setattr(socket.socket, "connect", no_network)
        job_id = env.new_job()
        env.run(job_id)
        assert env.job(job_id)["status"] == "COMPLETED"
        assert len(env.lineage(job_id)) == 4


@pytest.mark.unit
class TestWhichSourceColumnsProducedThisColumnWithoutScanningRows:
    def test_answered_from_stored_events_alone(
        self, env: _Env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        job_id = env.new_job()
        dest = env.run(job_id)
        reads_during_job = env.source.reads
        assert reads_during_job > 0

        # From here on any touch of a connector, a row or the error table is a failure.
        env.source.armed = True

        def forbidden(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("the lineage question must not open a connector")

        monkeypatch.setattr(clone_executor, "build_source_connector", forbidden)
        monkeypatch.setattr(clone_executor, "build_destination_writer", forbidden)
        monkeypatch.setattr(PgPersistence, "load_clone_job_errors_page", forbidden)
        monkeypatch.setattr(PgPersistence, "load_execution_all_rows", forbidden)

        events = env.lineage(job_id)

        def answer(table: str, destination_column: str) -> set[tuple[str, str]]:
            complete = [e for e in events if e["eventType"] == "COMPLETE" and table_of(e) == table]
            assert len(complete) == 1
            entry = column_lineage(complete[0])[destination_column]
            return {(_tail(f["name"]), f["field"]) for f in entry["inputFields"]}

        expected = 0
        for table in (TABLE_A, TABLE_B):
            for column in sorted(dest_columns(env, job_id, dest, table)):
                assert answer(table, column) == {(table, source_of(env, job_id, table, column))}
                expected += 1
        assert expected == 12, "6 per table: 4 source columns + 2 companions"
        assert env.source.reads == reads_during_job


# --------------------------------------------------------------------------- 2.4 grep
_COLLECTION_MIN = 5
_DICT_MIN = 3
_INT_MIN = 10
_HTTP = {status.value for status in HTTPStatus}  # a status code is not a threshold
_EXEMPT_WINDOW = 4  # a `ponytail:` note on the line or up to this many lines above


def _added_line_numbers(path: Path) -> set[int] | None:
    if not path.exists():
        return None
    rel = str(path.relative_to(REPO))
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", rel], cwd=REPO, capture_output=True, check=False
    )
    total = len(path.read_text(encoding="utf-8").splitlines())
    if tracked.returncode != 0:
        return set(range(1, total + 1))
    diff = subprocess.run(
        ["git", "diff", "main", "--unified=0", "--", rel],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    added: set[int] = set()
    for hunk in re.finditer(r"^@@ -\S+ \+(\d+)(?:,(\d+))? @@", diff, re.M):
        start, count = int(hunk.group(1)), int(hunk.group(2) or 1)
        added.update(range(start, start + count))
    return added or set(range(1, total + 1))


def literal_violations(source: str, added: set[int], forbidden_strings: set[str]) -> list[str]:
    """No hand-written table, no threshold, no value copied from a fixture or from the
    registries in non-test code, on the added lines."""
    lines = source.splitlines()
    tree = ast.parse(source)
    docstrings = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
    }

    def exempt(lineno: int) -> bool:
        window = lines[max(0, lineno - 1 - _EXEMPT_WINDOW) : lineno]
        return any("ponytail:" in line for line in window)

    out: list[str] = []
    for node in ast.walk(tree):
        lineno = getattr(node, "lineno", None)
        if lineno is None or lineno not in added or exempt(lineno):
            continue
        if isinstance(node, ast.Dict) and len(node.keys) >= _DICT_MIN:
            # a table is constants mapped to constants; an event being built is not
            plain = (ast.Constant, ast.Attribute)
            if all(isinstance(k, plain) for k in node.keys) and all(
                isinstance(v, plain) for v in node.values
            ):
                out.append(f"{lineno}: dict literal of {len(node.keys)} constant entries")
        elif isinstance(node, (ast.List, ast.Set, ast.Tuple)) and len(node.elts) >= _COLLECTION_MIN:
            if all(isinstance(e, ast.Constant) for e in node.elts):
                out.append(f"{lineno}: literal collection of {len(node.elts)} constants")
        elif isinstance(node, ast.Constant):
            if id(node) in docstrings:
                continue
            if isinstance(node.value, bool):
                continue
            if (
                isinstance(node.value, int)
                and abs(node.value) >= _INT_MIN
                and node.value not in _HTTP
            ):
                out.append(f"{lineno}: threshold literal {node.value}")
            if isinstance(node.value, str) and node.value in forbidden_strings:
                out.append(f"{lineno}: {node.value!r} duplicates a registry/fixture value")
    return out


def _forbidden_strings() -> set[str]:
    registry = build_normalizer_registry()
    names = {f.value for f in FieldSemanticType}
    names |= {n.name for f in FieldSemanticType if (n := registry.get(f)) is not None}
    names |= {clone_executor._CURRENCY_SUFFIX, clone_executor._CODE_SUFFIX}
    names |= {c for cols in COLUMNS.values() for c in cols if len(c) > 3} | {TABLE_A, TABLE_B}
    names |= {SRC_DB, DST_DB, NOTE_CELL, PHONE_CELL}
    return names


@pytest.mark.unit
class TestSection24:
    def test_the_grep_itself_catches_planted_violations(self) -> None:
        bad = (
            "NORM = {'PHONE': 'PhoneNormalizer', 'DATE': 'DateN', 'M': 'MoneyN'}\n"
            "EVENT = {'a': x, 'b': y, 'c': z}\n"
            "SUFFIX = '_currency'\n"
            "LIMIT = 4096\n"
            "OK = {'a': 1}\n"
            "WORDS = ['a', 'b', 'c', 'd', 'e']\n"
            "# ponytail: ceiling named\n"
            "PERMITTED = 777\n"
        )
        found = literal_violations(bad, set(range(1, 9)), {"PHONE", "_currency"})
        text = "\n".join(found)
        assert "dict literal" in text and "'_currency'" in text and "4096" in text
        assert "'PHONE'" in text and "literal collection" in text
        assert "777" not in text, "a ponytail: note exempts the line below it"
        assert "'a': 1" not in text
        assert not any(line.startswith("2:") for line in found), "an event dict is not a table"

    def test_lineage_py_has_no_hand_written_tables_or_copied_values(self) -> None:
        added = _added_line_numbers(LINEAGE_PY)
        assert added is not None, f"{LINEAGE_PY.relative_to(REPO)} does not exist yet"
        found = literal_violations(
            LINEAGE_PY.read_text(encoding="utf-8"), added, _forbidden_strings()
        )
        assert not found, "\n".join(found)

    def test_lineage_py_derives_the_normalizer_and_companions_instead_of_listing_them(
        self,
    ) -> None:
        assert LINEAGE_PY.exists(), f"{LINEAGE_PY.relative_to(REPO)} does not exist yet"
        source = LINEAGE_PY.read_text(encoding="utf-8")
        for suffix in (clone_executor._CURRENCY_SUFFIX, clone_executor._CODE_SUFFIX):
            assert f'"{suffix}"' not in source and f"'{suffix}'" not in source, (
                f"companion suffix {suffix!r} re-typed: take the mapping from the job's "
                "destination_plan (currency_columns/code_columns) or the executor's constant"
            )

    def test_no_new_runtime_dependency_unless_the_lead_approved_it(self) -> None:
        diff = subprocess.run(
            ["git", "diff", "main", "--unified=0", "--", "pyproject.toml", "uv.lock"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        added = [line for line in diff.splitlines() if line.startswith("+")]
        assert not [line for line in added if "openlineage" in line.lower()], (
            "report D3: the default is no new dependency; openlineage-python only if it passes "
            "check_licenses.py and removes more code than it adds (lead decision)"
        )


# --------------------------------------------------------------------------- attack round (D3)
class _SwapDest(_Dest):
    def swap_table(self, database: str, table: str, staging: str) -> None:
        self.inserted.setdefault("__swapped__", []).append({"table": table, "staging": staging})


def _mark(env: _Env, job_id: str, **changes: Any) -> None:
    job = env.job(job_id)
    job.update(changes)
    env.persistence.save_clone_job(job_id, job)


@pytest.mark.unit
class TestAttackShapes:
    def test_in_place_output_is_the_final_table_not_the_staging_name(self, env: _Env) -> None:
        job_id = env.new_job()
        _mark(env, job_id, in_place=True)
        env.mp.setattr(clone_executor, "build_source_connector", lambda c, d, s=None: env.source)
        dest = _SwapDest()
        env.mp.setattr(clone_executor, "build_destination_writer", lambda conn: dest)
        clone_executor._run_phase2(env.persistence, env.dispatcher, None, job_id)
        assert env.job(job_id)["status"] == "COMPLETED", env.job(job_id)["error"]
        for event in env.lineage(job_id):
            assert clone_executor.staging_name("x")[1:] not in event["outputs"][0]["name"]
            assert event["outputs"][0]["name"].endswith(f"{DST_DB}.{table_of(event)}")

    def test_typed_destination_runs_and_validates(self, env: _Env, spec: _Spec) -> None:
        job_id = env.new_job()
        _mark(env, job_id, typed_destination_columns=True)
        env.run(job_id)
        assert env.job(job_id)["status"] == "COMPLETED", env.job(job_id)["error"]
        assert_valid(spec, env.lineage(job_id))

    def test_source_schema_is_in_the_input_name_only(self, env: _Env) -> None:
        job_id = env.new_job()
        _mark(env, job_id, source_schema="sales")
        env.run(job_id)
        for e in env.lineage(job_id):
            assert e["inputs"][0]["name"] == f"{SRC_DB}.sales.{table_of(e)}"
            assert e["outputs"][0]["name"] == f"{DST_DB}.{table_of(e)}"

    def test_dots_quotes_unicode_in_table_and_column_names(
        self, env: _Env, spec: _Spec, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        table, column = "ta.b\"le'é;--", "co.l\"é'name"
        monkeypatch.setitem(COLUMNS, table, ["id", column])
        monkeypatch.setitem(PRIMARY_KEY, table, ["id"])
        monkeypatch.setitem(FIELD_CONFIGS, table, {column: "PHONE"})
        data = {table: [{"id": 1, column: "+1 650-253-0000"}]}
        job_id = env.new_job(tables=[table], data=data)
        env.run(job_id)
        assert env.job(job_id)["status"] == "COMPLETED", env.job(job_id)["error"]
        events = env.lineage(job_id)
        assert len(events) == 2
        assert_valid(spec, events)
        assert column in column_lineage(events[-1])
        assert events[-1]["outputs"][0]["name"].endswith(table)

    def test_a_configured_column_the_source_no_longer_has_is_not_invented(self, env: _Env) -> None:
        job_id = env.new_job()
        job = env.job(job_id)
        job["field_configs"][TABLE_A]["vanished"] = "EMAIL"
        env.persistence.save_clone_job(job_id, job)
        env.run(job_id)
        events = of_table(env.lineage(job_id), TABLE_A)
        done = [e for e in events if e["eventType"] == "COMPLETE"]
        if (
            env.job(job_id)["status"] == "FAILED"
        ):  # the executor itself rejects it: a FAIL, no COMPLETE
            assert kinds(events) == {"START": 1, "FAIL": 1}
        else:
            assert "vanished" not in column_lineage(done[0])

    def test_a_companion_of_a_vanished_base_column_is_not_claimed(self, env: _Env) -> None:
        # destination_plan names a MONEY base the source lacks: the companion
        # would point at a source field that does not exist.
        job_id = env.new_job()
        job = env.job(job_id)
        job["destination_plan"][TABLE_A]["currency_columns"] = {"gone": "gone_currency"}
        env.persistence.save_clone_job(job_id, job)
        env.run(job_id)
        done = of_table([e for e in env.lineage(job_id) if e["eventType"] == "COMPLETE"], TABLE_A)
        fields = column_lineage(done[0])
        if "gone_currency" in fields:
            src = {f["field"] for f in fields["gone_currency"]["inputFields"]}
            assert src <= set(COLUMNS[TABLE_A]), f"lineage claims nonexistent source column {src}"


@pytest.mark.unit
class TestAttackFailurePaths:
    def test_failure_before_the_first_table_leaves_a_trace_in_the_job_not_phantom_events(
        self, env: _Env
    ) -> None:
        job_id = env.new_job()
        _mark(env, job_id, cross_table_entity_key="id")

        def boom(*a: Any, **k: Any) -> Any:
            raise RuntimeError("entity map exploded")

        env.mp.setattr(clone_executor, "_build_entity_country_map", boom)
        env.run(job_id)
        assert env.job(job_id)["status"] == "FAILED"
        assert env.lineage(job_id) == []  # documented gap: no run existed yet

    def test_get_columns_raising_on_the_second_table_leaves_a_dangling_nothing(
        self, env: _Env
    ) -> None:
        job_id = env.new_job()
        real = env.source.get_columns

        def flaky(table: str) -> Any:
            if table == TABLE_B:
                raise RuntimeError("catalog gone")
            return real(table)

        # C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
        env.source.get_columns = flaky  # type: ignore[method-assign]
        env.run(job_id)
        assert env.job(job_id)["status"] == "FAILED"
        events = env.lineage(job_id)
        assert kinds(of_table(events, TABLE_A)) == {"START": 1, "COMPLETE": 1}
        # The failing table has no FAIL: it never had a START either.
        assert of_table(events, TABLE_B) == []

    def test_if_the_store_cannot_write_the_job_fails_closed(
        self, env: _Env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        job_id = env.new_job()

        def deny(*a: Any, **k: Any) -> None:
            raise RuntimeError("metadata db down")

        monkeypatch.setattr(env.persistence, "save_lineage_event", deny)
        env.run(job_id)
        job = env.job(job_id)
        assert job["status"] == "FAILED"
        assert "metadata db down" in job["error"]

    def test_a_failed_store_of_FAIL_does_not_hide_the_original_error(
        self, env: _Env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        job_id = env.new_job()
        real = env.persistence.save_lineage_event

        def fail_only(job: str, table: str, event: dict[str, Any]) -> None:
            if event["eventType"] == "FAIL":
                raise RuntimeError("metadata db down")
            real(job, table, event)

        monkeypatch.setattr(env.persistence, "save_lineage_event", fail_only)
        env.run(job_id, fail_on={TABLE_A: RuntimeError("the real cause: disk full")})
        err = env.job(job_id)["error"]
        assert "disk full" in err, f"the job's error lost the real cause: {err!r}"

    def test_a_store_failure_at_COMPLETE_must_not_strand_a_finished_table_without_COMPLETE(
        self, env: _Env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        job_id = env.new_job()
        real = env.persistence.save_lineage_event
        state = {"deny": True}

        def flaky(job: str, table: str, event: dict[str, Any]) -> None:
            if event["eventType"] == "COMPLETE" and state["deny"]:
                state["deny"] = False
                raise RuntimeError("blip")
            real(job, table, event)

        monkeypatch.setattr(env.persistence, "save_lineage_event", flaky)
        env.run(job_id)
        assert env.job(job_id)["status"] == "FAILED"
        _mark(env, job_id, status="RUNNING", error=None)  # operator retries
        env.run(job_id)
        events = env.lineage(job_id)
        assert kinds(of_table(events, TABLE_A))["COMPLETE"] == 1, (
            "table A is checkpointed done, so it is skipped on resume, and its "
            "START will never get a COMPLETE: the audit trail has a permanent hole"
        )

    def test_a_crash_between_checkpoint_and_COMPLETE_is_repaired_on_resume(
        self, env: _Env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        job_id = env.new_job()
        real = env.persistence.save_lineage_event
        state = {"deny": True}

        def die(job: str, table: str, event: dict[str, Any]) -> None:
            if event["eventType"] == "COMPLETE" and state["deny"]:
                state["deny"] = False
                raise KeyboardInterrupt
            real(job, table, event)

        monkeypatch.setattr(env.persistence, "save_lineage_event", die)
        with pytest.raises(KeyboardInterrupt):
            env.run(job_id)
        env.run(job_id)
        assert kinds(of_table(env.lineage(job_id), TABLE_A))["COMPLETE"] == 1


@pytest.mark.unit
class TestAttackOrderingAndForwarding:
    def test_identical_event_times_still_list_start_before_its_terminal(
        self, env: _Env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _Frozen(dt.datetime):
            @classmethod
            def now(cls, tz: Any = None) -> Any:
                return dt.datetime(2026, 1, 1, tzinfo=dt.UTC)

        class _Shim:
            UTC = dt.UTC
            datetime = _Frozen

        monkeypatch.setattr(lineage, "dt", _Shim)
        job_id = env.new_job(tables=[TABLE_A])
        env.run(job_id)
        # Simulate a heap whose physical order is COMPLETE first (as after a vacuum / update).
        with env.persistence._engine.begin() as conn:
            conn.execute(sa.text(f"DELETE FROM {EVENTS_TABLE} WHERE event_type='START'"))
        events = env.lineage(job_id)
        assert [e["eventType"] for e in events] == ["COMPLETE"]
        env.persistence.save_lineage_event(job_id, TABLE_A, {**events[0], "eventType": "START"})
        order = [e["eventType"] for e in env.lineage(job_id)]
        assert order == ["START", "COMPLETE"], f"ties order by insertion luck: {order}"

    def test_a_hanging_endpoint_costs_bounded_time(
        self, env: _Env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(50)
        monkeypatch.setenv("NORM_OPENLINEAGE_URL", f"http://127.0.0.1:{srv.getsockname()[1]}/x")
        monkeypatch.setenv("NO_PROXY", "127.0.0.1")
        job_id = env.new_job(tables=[TABLE_A])
        t0 = time.monotonic()
        env.run(job_id)
        took = time.monotonic() - t0
        srv.close()
        assert env.job(job_id)["status"] == "COMPLETED"
        assert took < 15, f"a hanging collector stalled the job {took:.1f}s for one table"

    def test_userinfo_in_the_url_leaks_into_no_log_and_no_payload(
        self, env: _Env, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        server, handler = _serve(200)
        try:
            monkeypatch.setenv("NO_PROXY", "127.0.0.1")
            monkeypatch.setenv(
                "NORM_OPENLINEAGE_URL",
                f"http://urluser:urlpw-9z@127.0.0.1:{server.server_port}/api/v1/lineage",
            )
            job_id = env.new_job(tables=[TABLE_A])
            with caplog.at_level("DEBUG"):
                env.run(job_id)
        finally:
            server.shutdown()
        assert env.job(job_id)["status"] == "COMPLETED"
        assert "urlpw-9z" not in caplog.text and "urluser" not in caplog.text
        assert "urlpw-9z" not in b"".join(handler.bodies).decode()
        assert "urlpw-9z" not in json.dumps(env.lineage(job_id))

    @pytest.mark.parametrize("url", ["file:///etc/passwd", "FILE:///etc/hosts", "ftp://x/y"])
    def test_non_http_urls_are_not_opened(
        self, env: _Env, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, url: str
    ) -> None:
        opened: list[Any] = []
        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: opened.append(a))
        monkeypatch.setenv("NORM_OPENLINEAGE_URL", url)
        job_id = env.new_job(tables=[TABLE_A])
        env.run(job_id)
        assert opened == []
        assert env.job(job_id)["status"] == "COMPLETED"

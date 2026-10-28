"""U1 acceptance (derive), API half: the raw value lives in the review route only.

Source: docs/improvement-report.md "U1 - Replace the UI" (bullets "Review distinct values,
not rows", "No pre-selected reading", "Speed", "The raw value is shown in the review screen
only"), owner decisions R18, R22, R23; plan 2.4, 2.6 (test client address), 9 (U1); ADR-023.
Written before any U1 implementation existed. Existing code was read only to build fixtures
(how a queue entry gets into the metadata store: the same executor path production uses).

Run (the file name contains a dot, so use importlib mode):

    ( ulimit -v 16777216; uv run pytest -p no:cacheprovider --import-mode=importlib -q \
        .handoff/U1.test_review_route.py )

When implementing, move the file to tests/unit/ (rename, e.g. test_u1_review_route.py).

THE LEAD SETS THE TWO ROUTE CONSTANTS BELOW. They are the only guess-free way to write this
before the route exists: the report says "the review route" but names no path.

Expected values: planted by this file (occurrence counts, raw strings) or computed from the
calendar (the two readings of an ambiguous dd/mm/yyyy), never copied from running the route.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import logging
import re
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from normapi.adjudication import Adjudication  # noqa: E402
from normapi.app import build_dispatcher, create_app  # noqa: E402
from normapi.clone_executor import _normalize_table  # noqa: E402
from normapi.dependencies import get_connections  # noqa: E402
from normapi.pg_persistence import PgPersistence  # noqa: E402
from normapi.scaffold_profile import SCAFFOLD_PROFILE  # noqa: E402
from normexec.planner import DistinctValuePlanner  # noqa: E402

# =========================================================================== LEAD: set these
# GET: the whole pending queue, raw values and candidate readings, no paging parameters.
REVIEW_LIST_ROUTE = "/normalization/adjudication/review"
# GET: one entry by its queue key (the same `key` the existing queue uses).
REVIEW_ENTRY_ROUTE = "/normalization/adjudication/review/{key}"
# =========================================================================== end LEAD

QUEUE_ROUTE = "/normalization/adjudication/queue"  # existing route, ADR-018
TABLE = "t"
ALLOWED_PEER = ("127.0.0.1", 50000)  # ADR-022: loopback is always allowed (plan 2.6)
PAGE_BUDGET_S = 1.0  # NN/g response-time limit for a page (report U1 "Speed")

# Planted by this file. Dates dd/mm/yyyy with both parts <= 12 and different have exactly two
# readings (DMY and MDY); the readings are calendar arithmetic, not an output of the code.
RAW_A, RAW_B, RAW_C = "01/02/2024", "03/04/2023", "11/12/1999"
PLANTED = {RAW_C: 9, RAW_A: 5, RAW_B: 3}  # occurrences, deliberately not in insertion order
RAW_MONEY = "1,234"  # no locale: stays ambiguous (AGENTS.md section 4); its error row is a surface


def _readings(raw: str) -> set[str]:
    a, b, y = (int(p) for p in raw.split("/"))
    return {dt.date(y, b, a).isoformat(), dt.date(y, a, b).isoformat()}


# --------------------------------------------------------------------------- harness
class _Batch:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def to_pylist(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self._rows)


class _Source:
    def __init__(self, batches: list[list[dict[str, Any]]]) -> None:
        self.batches = batches

    def read_table(self, table: str, *args: Any, **kwargs: Any) -> Iterator[_Batch]:
        for rows in self.batches:
            yield _Batch(rows)

    def get_columns(self, table: str) -> list[Any]:
        return []

    def get_primary_key(self, table: str) -> list[str]:
        return []


class _Dest:
    def __init__(self) -> None:
        self.inserted: list[dict[str, Any]] = []

    def bulk_insert(self, database: str, table: str, rows: list[dict[str, Any]], **kw: Any) -> None:
        self.inserted.extend(copy.deepcopy(rows))


class Env:
    def __init__(self, tmp_path: Path) -> None:
        self.persistence = PgPersistence(f"sqlite:///{tmp_path}/m.db")
        self.persistence.ensure_schema()
        app = create_app(
            dictionaries_dir=tmp_path / "dicts", custom_dictionaries_dir=tmp_path / "custom"
        )
        app.dependency_overrides[get_connections] = lambda: self.persistence
        self.client = TestClient(app, client=ALLOWED_PEER, base_url="http://localhost")
        self.n = 0
        self.dest = _Dest()

    def run(self, rows: list[dict[str, Any]], cfg: dict[str, str], block: int = 125) -> str:
        """One executor pass, the production path (`_normalize_table`)."""
        self.n += 1
        job_id = f"job-{self.n}"
        batches = [rows[i : i + block] for i in range(0, len(rows), block)] or [[]]
        job = {
            "status": "completed",
            "source_connection_id": "src-1",
            "destination_connection_id": "dst-1",
            "source_identity": "postgres://src:5432/db",
            "destination_database": "dest",
            "field_configs": {TABLE: cfg},
            "progress": {
                "checkpoints": {},
                "rows_done": 0,
                "current_table": None,
                "insert_block_rows": {TABLE: block},
            },
            "country": None,
            "locale": None,
        }
        self.persistence.create_clone_job(job_id, job)
        self.dest = _Dest()
        _normalize_table(
            TABLE,
            job=job,
            job_id=job_id,
            source=_Source(batches),
            dest=self.dest,
            source_engine="postgres",
            persistence=self.persistence,
            planner=DistinctValuePlanner(build_dispatcher(env_id="env-1"), None),
            pool=None,
            progress=job["progress"],
            entity_countries={},
            adjudication=Adjudication(self.persistence, SCAFFOLD_PROFILE),
        )
        return job_id

    def key_of(self, original: str) -> str:
        _, rows = self.persistence.list_queue(
            semantic_type=None, decided=None, limit=100000, offset=0
        )
        hits = [r for r in rows if r["original"] == original]
        assert len(hits) == 1, hits
        return str(hits[0]["key"])


def _rows(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"source_row_key": f"{TABLE}:{i}", **cells} for i, cells in enumerate(values)]


@pytest.fixture
def env(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> Env:
    caplog.set_level(logging.DEBUG)  # the seeding run is inside the log capture
    return Env(tmp_path)


@pytest.fixture
def seeded(env: Env) -> tuple[Env, str]:
    """Three distinct ambiguous dates with planted counts, one ambiguous MONEY value."""
    values: list[dict[str, Any]] = []
    for raw, n in PLANTED.items():
        values += [{"d": raw, "m": None}] * n
    values.append({"d": None, "m": RAW_MONEY})
    job_id = env.run(_rows(values), {"d": "DATE", "m": "MONEY"})
    return env, job_id


# --------------------------------------------------------------------------- JSON helpers
def _walk(node: Any) -> Iterator[Any]:
    yield node
    if isinstance(node, dict):
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def _leaves(node: Any) -> list[str]:
    return [n for n in _walk(node) if isinstance(n, str)]


def _entries(body: Any) -> list[dict[str, Any]]:
    """Queue entries = JSON objects that carry `occurrences` (the field the report names)."""
    return [n for n in _walk(body) if isinstance(n, dict) and "occurrences" in n]


def _entry_for(body: Any, raw: str) -> dict[str, Any]:
    hits = [e for e in _entries(body) if raw in _leaves(e)]
    assert len(hits) == 1, f"expected exactly one entry holding the raw value {raw!r}, got {hits}"
    return hits[0]


def _has_reading(entry: dict[str, Any], iso: str) -> bool:
    """A candidate reading is present as the ISO string, or as a day/month/year object."""
    y, m, d = (int(p) for p in iso.split("-"))
    for n in _walk(entry):
        if n == iso:
            return True
        if isinstance(n, dict) and {"year", "month", "day"} <= n.keys():
            try:
                if (int(n["year"]), int(n["month"]), int(n["day"])) == (y, m, d):
                    return True
            except (TypeError, ValueError):
                continue
    return False


def _unmasked_candidate_dicts(body: Any) -> list[dict[str, Any]]:
    """Any {year, month, day} object whose three values are still digits: an unmasked reading."""
    out = []
    for n in _walk(body):
        if (
            isinstance(n, dict)
            and {"year", "month", "day"} <= n.keys()
            and all(
                isinstance(n[k], (str, int)) and re.fullmatch(r"\d+", str(n[k]))
                for k in ("year", "month", "day")
            )
        ):
            out.append(n)
    return out


def _forms(raw: str) -> set[str]:
    """The raw value as it could appear in a body: plain, JSON-escaped, URL-escaped."""
    return {raw, json.dumps(raw)[1:-1], quote(raw, safe=""), raw.replace("/", "\\/")}


def _assert_masked(text: str, what: str) -> None:
    for raw in (*PLANTED, RAW_MONEY):
        for form in _forms(raw):
            assert form not in text, f"{what}: raw value {raw!r} leaked as {form!r}"
    body: Any
    try:
        body = json.loads(text)
    except ValueError:
        return
    assert not _unmasked_candidate_dicts(body), f"{what}: an unmasked candidate reading leaked"
    leaves = set(_leaves(body))
    for raw in PLANTED:
        assert not (_readings(raw) & leaves), f"{what}: a candidate reading leaked as ISO date"


# =========================================================================== review route
@pytest.mark.unit
def test_review_list_returns_every_raw_value_and_its_candidate_readings(
    seeded: tuple[Env, str],
) -> None:
    """R23: the review route carries the raw value and the candidate readings, unmasked.
    Negative on old code: the route does not exist (404); the old queue route masks both."""
    env, _ = seeded
    r = env.client.get(REVIEW_LIST_ROUTE)
    assert r.status_code == 200, r.text
    body = r.json()
    for raw, n in PLANTED.items():
        e = _entry_for(body, raw)
        assert e["occurrences"] == n
        for iso in _readings(raw):
            assert _has_reading(e, iso), f"reading {iso} of {raw} missing from {e}"
    assert _entry_for(body, RAW_MONEY)["occurrences"] == 1


@pytest.mark.unit
def test_review_entry_route_returns_the_raw_value_and_readings(seeded: tuple[Env, str]) -> None:
    env, _ = seeded
    key = env.key_of(RAW_A)
    r = env.client.get(REVIEW_ENTRY_ROUTE.format(key=key))
    assert r.status_code == 200, r.text
    e = _entry_for(r.json(), RAW_A)
    assert e["occurrences"] == PLANTED[RAW_A]
    assert all(_has_reading(e, iso) for iso in _readings(RAW_A))


@pytest.mark.unit
def test_review_list_is_ordered_by_occurrences_descending(seeded: tuple[Env, str]) -> None:
    """Report U1: "Order the queue by occurrences" (most first: one answer settles most rows)."""
    env, _ = seeded
    r = env.client.get(REVIEW_LIST_ROUTE)
    assert r.status_code == 200, r.text
    counts = [e["occurrences"] for e in _entries(r.json())]
    assert counts == sorted(counts, reverse=True)
    assert counts[:3] == [9, 5, 3]  # the planted order, whatever the insertion order was


@pytest.mark.unit
def test_review_list_is_one_unpaged_response_within_the_page_budget(env: Env) -> None:
    """R22: hundreds of distinct values, "a plain list; no server paging". 250 distinct ambiguous
    dates (both parts <= 12 and different: 132 per year) must all come back from one call with
    no parameters; the API half of the 1 s page budget must hold."""
    pairs = [(a, b) for a in range(1, 13) for b in range(1, 13) if a != b]
    raws = [f"{a:02d}/{b:02d}/{y}" for y in (2000, 2001) for a, b in pairs][:250]
    assert len(set(raws)) == 250
    env.run(_rows([{"d": raw} for raw in raws]), {"d": "DATE"})
    env.client.get(REVIEW_LIST_ROUTE)  # warm-up; the budget is for a normal call
    t0 = time.perf_counter()
    r = env.client.get(REVIEW_LIST_ROUTE)
    elapsed = time.perf_counter() - t0
    assert r.status_code == 200, r.text
    got = _entries(r.json())
    assert len(got) == 250, f"server paging: {len(got)} of 250 entries"
    assert {raw for e in got for raw in _leaves(e) if raw in raws} == set(raws)
    assert elapsed < PAGE_BUDGET_S, f"{elapsed:.3f}s for 250 entries (budget {PAGE_BUDGET_S}s)"


@pytest.mark.unit
def test_never_guess_review_route_selects_no_reading_and_writes_nothing(
    seeded: tuple[Env, str],
) -> None:
    """R18 "no reading pre-selected": an ambiguous date shows >= 2 readings, none marked as picked;
    a GET writes no verdict and the value stays ambiguous on the next run (ADR-018, AGENTS.md)."""
    env, _ = seeded
    r = env.client.get(REVIEW_LIST_ROUTE)
    assert r.status_code == 200, r.text
    e = _entry_for(r.json(), RAW_A)
    assert sum(1 for iso in _readings(RAW_A) if _has_reading(e, iso)) == 2
    picks = {
        "selected", "preselected", "pre_selected", "suggested", "suggestion", "recommended",
        "recommendation", "default", "preferred", "best", "chosen", "pick", "picked",
        "most_likely", "top_candidate",
    }  # fmt: skip
    keys = {k.lower() for n in _walk(r.json()) if isinstance(n, dict) for k in n}
    assert not (keys & picks), f"a field names a picked reading: {keys & picks}"
    # the read changed nothing
    for key in (env.key_of(RAW_A), env.key_of(RAW_B)):
        assert env.persistence.list_verdicts(key) == []
    env.client.get(REVIEW_ENTRY_ROUTE.format(key=env.key_of(RAW_A)))
    assert env.persistence.list_verdicts(env.key_of(RAW_A)) == []
    # and a second run, with no person having decided, still hands back the original string
    env.run(_rows([{"d": RAW_A}]), {"d": "DATE"})
    assert [row["d"] for row in env.dest.inserted] == [RAW_A]


# =========================================================================== masking, per surface
# Each surface is one test case. A masking test is vacuous unless the raw value is retrievable
# somewhere, so every case first demands that the review route returns it: they fail on the old
# code for the missing review route, and bite once the route exists.
SURFACES = [
    "queue_list",
    "queue_entry",
    "job_detail",
    "job_quality",
    "job_errors",
    "job_lineage",
    "job_plan",
    "verdict_response",
    "verdict_error_422",
    "trace",
    "logs",
]


@pytest.mark.unit
@pytest.mark.parametrize("surface", SURFACES)
def test_every_other_surface_stays_masked(
    surface: str, seeded: tuple[Env, str], caplog: pytest.LogCaptureFixture
) -> None:
    env, job_id = seeded
    review = env.client.get(REVIEW_LIST_ROUTE)
    assert review.status_code == 200 and RAW_A in review.text, (
        "precondition: the review route returns the raw value"
    )
    key_a = env.key_of(RAW_A)
    base = "/normalization"
    if surface == "queue_list":
        r = env.client.get(QUEUE_ROUTE)
    elif surface == "queue_entry":
        r = env.client.get(f"{QUEUE_ROUTE}/{key_a}")
    elif surface == "job_detail":
        r = env.client.get(f"{base}/clone-jobs/{job_id}")
    elif surface == "job_quality":
        r = env.client.get(f"{base}/clone-jobs/{job_id}/quality")
    elif surface == "job_errors":
        r = env.client.get(f"{base}/clone-jobs/{job_id}/errors")
    elif surface == "job_lineage":
        r = env.client.get(f"{base}/clone-jobs/{job_id}/lineage")
    elif surface == "job_plan":
        r = env.client.get(f"{base}/clone-jobs/{job_id}/plan")
    elif surface == "verdict_response":
        r = env.client.post(
            f"{QUEUE_ROUTE}/{key_a}/verdicts",
            json={
                "decided_value": sorted(_readings(RAW_A))[0],
                "decided_by": "human:alice",
                "rationale": "checked the source",
            },
        )
        assert r.status_code == 201, r.text
    elif surface == "verdict_error_422":
        # an answer that is itself not a clean value is refused with an error report
        r = env.client.post(
            f"{QUEUE_ROUTE}/{key_a}/verdicts",
            json={
                "decided_value": "not a date at all",
                "decided_by": "human:alice",
                "rationale": "checked the source",
            },
        )
        assert r.status_code == 422, r.text
    elif surface == "trace":
        # A normalization result's trace embeds values only as hash + mask (pii.safe_preview).
        r = env.client.post(
            f"{base}/field-test",
            json={"field_name": "d", "semantic_type": "DATE", "value": RAW_A},
        )
        assert r.status_code == 200, r.text
        trace = r.json()["trace"]
        assert trace, "the date.parse step must be in the trace"
        _assert_masked(json.dumps(trace), "trace")
        return
    else:  # logs: the seeding run, the review reads, a verdict and every GET above
        for url in (
            f"{QUEUE_ROUTE}",
            f"{QUEUE_ROUTE}/{key_a}",
            f"{base}/clone-jobs/{job_id}",
            f"{base}/clone-jobs/{job_id}/quality",
            f"{base}/clone-jobs/{job_id}/errors",
            f"{base}/clone-jobs/{job_id}/lineage",
            REVIEW_LIST_ROUTE,
            REVIEW_ENTRY_ROUTE.format(key=key_a),
        ):
            env.client.get(url)
        env.client.post(
            f"{QUEUE_ROUTE}/{key_a}/verdicts",
            json={"decided_value": "x", "decided_by": "human:alice", "rationale": "r"},
        )
        text = "\n".join(
            [rec.getMessage() + "\n" + (rec.exc_text or "") for rec in caplog.records]
            + [str(getattr(rec, "args", "")) for rec in caplog.records]
        )
        assert caplog.records, "no log record captured: the capture is not wired"
        _assert_masked(text, "logs")
        return
    _assert_masked(r.text, surface)


@pytest.mark.unit
def test_unknown_review_key_error_report_is_masked(seeded: tuple[Env, str]) -> None:
    """The review route's own error report must not echo a stored raw value either."""
    env, _ = seeded
    assert RAW_A in env.client.get(REVIEW_LIST_ROUTE).text, "precondition: route exists"
    r = env.client.get(REVIEW_ENTRY_ROUTE.format(key="no-such-key"))
    assert r.status_code == 404
    _assert_masked(r.text, "review 404")


@pytest.mark.unit
def test_review_route_is_unreachable_from_a_public_peer(seeded: tuple[Env, str]) -> None:
    """ADR-023 limit: the review route "relies on ADR-022's local-network-only policy". A public
    peer must be refused (400/403) before any raw value leaves."""
    env, _ = seeded
    assert env.client.get(REVIEW_LIST_ROUTE).status_code == 200, "precondition: route exists"
    app = env.client.app
    outsider = TestClient(app, client=("8.8.8.8", 50000), base_url="http://localhost")  # type: ignore[arg-type]
    r = outsider.get(REVIEW_LIST_ROUTE)
    assert r.status_code in (400, 403)
    for raw in PLANTED:
        assert raw not in r.text

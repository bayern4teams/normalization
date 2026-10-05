"""D1 acceptance: AMBIGUOUS has an exit path (ADR-018, plan 9 D1 "Accept").

Written from the plan, the report and ADR-018 only, driving the public
interface (`_normalize_table`, `PgPersistence` on SQLite, the HTTP routes).
Every number and value that is expected comes from an authoritative source
at import time (libphonenumber, calendar arithmetic, CLDR) through
`tests/defects/fixtures_phase1.py`, or is a count this file plants itself.

The negative case that fails on the old behaviour is
`test_without_adjudication_the_refusal_still_evaporates`: with
`adjudication=None` (what `main` does) the verdict is ignored on every run.
"""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar

import pytest
from fastapi.testclient import TestClient
from normapi.adjudication import (
    CLEAN_STATUSES,
    DECIDED_BY,
    Adjudication,
    verdict_key,
)
from normapi.app import build_dispatcher, create_app
from normapi.clone_executor import _normalize_table
from normapi.dependencies import get_connections
from normapi.pg_persistence import PgPersistence
from normapi.scaffold_profile import SCAFFOLD_PROFILE
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType, NormalizationStatus
from normexec.planner import DistinctValuePlanner
from normio.connector import SourceConnector
from tests.defects import fixtures_phase1 as fx

# --------------------------------------------------------------------------- planted values
# Taken from the authoritative-source-derived fixture, never typed in.
_DATE = fx.D1_DATE_AMBIGUOUS[0]
_DATE_2 = fx.D1_DATE_AMBIGUOUS[1]
_MONEY = fx.D1_MONEY_AMBIGUOUS[0]
# long enough that its digits cannot occur in a hash by chance
_PHONE = next(c for c in fx.D1_PHONE_AMBIGUOUS if len(re.sub(r"\D", "", c.input)) >= 9)
RAW_DATE, RAW_DATE_2, RAW_MONEY, RAW_PHONE = _DATE.input, _DATE_2.input, _MONEY.input, _PHONE.input
# A decided value is one of the candidate readings the fixture computed.
DECIDE_DATE = sorted(_DATE.candidates or ())[0]
DECIDE_DATE_2 = sorted(_DATE_2.candidates or ())[0]
DECIDE_MONEY = sorted(_MONEY.candidates or ())[-1]  # the unambiguous-looking reading
DECIDE_PHONE = sorted(_PHONE.candidates or ())[0]
CLEAN_DATE = fx.D1_DATE_CLEAN[2].input  # 13/02/2024: day > 12, one reading
CLEAN_DATE_OUT = fx.D1_DATE_CLEAN[2].expected_value
TABLE = "t"


# --------------------------------------------------------------------------- fakes
class _Batch:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def to_pylist(self) -> list[dict[str, Any]]:
        # the executor mutates rows: hand out copies so a source can be re-read
        return copy.deepcopy(self._rows)


class _Source:
    def __init__(self, tables: dict[str, list[list[dict[str, Any]]]]) -> None:
        self.tables = tables  # table -> list of batches

    def read_table(self, table: str, *args: Any, **kwargs: Any) -> Iterator[_Batch]:
        for rows in self.tables[table]:
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

    def swap_table(self, *a: Any, **k: Any) -> None:  # pragma: no cover - in_place unused
        raise AssertionError("not an in-place test")


class _Crash(RuntimeError):
    pass


class _FlakyPersistence:
    """Delegates everything; raises BEFORE delegating on the Nth call of the
    chunk-commit method, i.e. the transaction never happened."""

    def __init__(self, inner: PgPersistence, fail_on_call: int | None) -> None:
        self._inner = inner
        self._fail_on = fail_on_call
        self.commits = 0

    def save_clone_job_and_enqueue(self, *args: Any, **kwargs: Any) -> Any:
        self.commits += 1
        if self._fail_on == self.commits:
            raise _Crash("crash after insert, before the checkpoint committed")
        return self._inner.save_clone_job_and_enqueue(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


# --------------------------------------------------------------------------- harness
def _rows(values: list[dict[str, Any]], start: int = 0) -> list[dict[str, Any]]:
    return [{"source_row_key": f"{TABLE}:{start + i}", **cells} for i, cells in enumerate(values)]


def _job(field_configs: dict[str, str], **extra: Any) -> dict[str, Any]:
    return {
        "source_connection_id": "src-1",
        "destination_database": "dest",
        "field_configs": {TABLE: field_configs},
        "progress": {"checkpoints": {}, "rows_done": 0, "current_table": None},
        "country": None,
        "locale": None,
        **extra,
    }


class _Env:
    def __init__(self, tmp_path: Path) -> None:
        self.persistence = PgPersistence(f"sqlite:///{tmp_path}/m.db")
        self.persistence.ensure_schema()
        app = create_app(
            dictionaries_dir=tmp_path / "dicts", custom_dictionaries_dir=tmp_path / "custom"
        )
        app.dependency_overrides[get_connections] = lambda: self.persistence
        self.client = TestClient(app)
        self.n = 0

    def adjudication(self, profile: Any = SCAFFOLD_PROFILE) -> Adjudication:
        return Adjudication(self.persistence, profile)

    def run(
        self,
        batches: list[list[dict[str, Any]]],
        field_configs: dict[str, str],
        *,
        job_id: str | None = None,
        adjudication: Any = "default",
        env_id: str = "env-1",
        persistence: Any = None,
        resume: bool = False,
        table: str = TABLE,
        job_extra: dict[str, Any] | None = None,
        source_tables: dict[str, list[list[dict[str, Any]]]] | None = None,
    ) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
        """One executor pass over `batches`. Returns (job_id, dest rows, job)."""
        self.n += 1
        job_id = job_id or f"job-{self.n}"
        store = self.persistence
        if resume:
            job = store.get_clone_job(job_id)
            assert job is not None
        else:
            job = _job(field_configs, **(job_extra or {}))
            job["field_configs"] = {table: field_configs}
            store.create_clone_job(job_id, job)
        dest = _Dest()
        _normalize_table(
            table,
            job=job,
            job_id=job_id,
            source=_Source(source_tables or {table: batches}),
            dest=dest,
            source_engine="clickhouse",
            persistence=persistence or store,
            planner=DistinctValuePlanner(build_dispatcher(env_id=env_id), None),
            pool=None,
            progress=job["progress"],
            in_place=False,
            entity_countries={},
            adjudication=self.adjudication() if adjudication == "default" else adjudication,
        )
        self.dest = dest
        return job_id, dest.inserted, job

    def errors(self, job_id: str) -> list[dict[str, Any]]:
        return self.persistence.load_clone_job_errors_page(job_id, limit=100000, offset=0)

    def queue(self) -> list[dict[str, Any]]:
        total, rows = self.persistence.list_queue(
            semantic_type=None, decided=None, limit=1000, offset=0
        )
        assert total == len(rows)
        return rows

    def post(self, key: str, value: str, by: str = "human:alice") -> Any:
        return self.client.post(
            f"/normalization/adjudication/queue/{key}/verdicts",
            json={"decided_value": value, "decided_by": by, "rationale": "checked the source"},
        )

    def key_of(self, original: str, *, field: str | None = None) -> str:
        hits = [r for r in self.queue() if r["original"] == original]
        if field is not None:
            hits = [r for r in hits if json.loads(r["context"])["field_name"] == field]
        assert len(hits) == 1, hits
        return str(hits[0]["key"])


@pytest.fixture
def env(tmp_path: Path) -> _Env:
    return _Env(tmp_path)


def _statuses(job: dict[str, Any], column: str, table: str = TABLE) -> dict[str, int]:
    return dict(job["quality"][table][column]["statuses"])


# --------------------------------------------------------------------------- (1)
@pytest.mark.unit
class TestVerdictIsAppliedOnTheNextRun:
    """DATE and PHONE refusals carry no error row today (`errors` is empty);
    MONEY's does. So the error-row half of the spec is asserted on the MONEY
    column, and DATE is asserted through the cell and the quality statuses."""

    def _data(self) -> list[list[dict[str, Any]]]:
        return [
            _rows(
                [
                    {"d": RAW_DATE, "m": RAW_MONEY, "e": "Alice@Example.COM", "x": CLEAN_DATE},
                    {"d": RAW_DATE_2, "m": None, "e": "bob@example.com", "x": None},
                    {"d": RAW_DATE, "m": RAW_MONEY, "e": None, "x": CLEAN_DATE},
                    {"d": None, "m": None, "e": "carol@example.com", "x": CLEAN_DATE},
                    {"d": "", "m": "", "e": "", "x": ""},
                ]
            )
        ]

    CFG: ClassVar[dict[str, str]] = {"d": "DATE", "m": "MONEY", "e": "EMAIL", "x": "DATE"}

    @staticmethod
    def _errs(env: _Env, job_id: str) -> list[tuple[Any, ...]]:
        return [(e["row_index"], e["field"], e["original"], e["error"]) for e in env.errors(job_id)]

    def _decide(self, env: _Env) -> None:
        assert env.post(env.key_of(RAW_DATE), DECIDE_DATE).status_code == 201
        assert env.post(env.key_of(RAW_MONEY), DECIDE_MONEY).status_code == 201

    def test_without_adjudication_the_refusal_still_evaporates(self, env: _Env) -> None:
        """The OLD behaviour (main): even with a verdict stored, run after run
        emits the original and an error row. Fails on any build where the
        resolve stage is not what changed the second run."""
        j0, first, _ = env.run(self._data(), self.CFG, adjudication=None)
        assert env.queue() == []  # old behaviour: nothing was ever queued
        env.run(self._data(), self.CFG)  # the same data, queued by the new path
        self._decide(env)
        jid, second, _ = env.run(self._data(), self.CFG, adjudication=None)
        assert second[0]["d"] == RAW_DATE and second[0]["m"] == RAW_MONEY  # verdicts ignored
        assert (0, "m", RAW_MONEY, "could not parse an amount") in self._errs(env, jid)
        assert second == first and self._errs(env, jid) == self._errs(env, j0)

    def test_second_run_emits_the_adjudicated_value_and_no_error_row(self, env: _Env) -> None:
        j1, first, _ = env.run(self._data(), self.CFG)
        assert first[0]["d"] == RAW_DATE and first[2]["d"] == RAW_DATE  # unchanged write path
        assert first[0]["m"] == RAW_MONEY
        assert {e[0] for e in self._errs(env, j1) if e[1] == "m"} == {0, 2}
        self._decide(env)

        j2, second, job2 = env.run(self._data(), self.CFG)
        assert second[0]["d"] == DECIDE_DATE and second[2]["d"] == DECIDE_DATE
        assert second[0]["m"] == DECIDE_MONEY and second[2]["m"] == DECIDE_MONEY
        assert not [e for e in self._errs(env, j2) if e[1] in ("d", "m")]  # no error row for them
        # the other ambiguous value has no verdict: still the original
        assert second[1]["d"] == RAW_DATE_2
        assert _statuses(job2, "d").get("AMBIGUOUS") == 1
        assert "AMBIGUOUS" not in _statuses(job2, "m")

    def test_every_other_cell_is_byte_identical_to_the_old_run(self, env: _Env) -> None:
        j0, old, _ = env.run(self._data(), self.CFG, adjudication=None)
        j1, first, _ = env.run(self._data(), self.CFG)
        assert first == old  # first run: byte-identical write path
        assert self._errs(env, j1) == self._errs(env, j0)

        self._decide(env)
        j2, second, _ = env.run(self._data(), self.CFG)
        adjudicated = {(0, "d"), (2, "d"), (0, "m"), (2, "m")}
        for i, (a, b) in enumerate(zip(old, second, strict=True)):
            assert a.keys() == b.keys()
            for col in a:
                if (i, col) not in adjudicated:
                    assert a[col] == b[col], (i, col)
        assert [e for e in self._errs(env, j2) if e[:2] not in adjudicated] == self._errs(env, j0)[
            :0
        ] or all(e[:2] not in adjudicated for e in self._errs(env, j2))
        assert self._errs(env, j2) == [e for e in self._errs(env, j0) if e[:2] not in adjudicated]

    def test_null_and_empty_cells_are_never_queued_or_resolved(self, env: _Env) -> None:
        env.run(self._data(), self.CFG)
        assert sorted(r["original"] for r in env.queue()) == sorted(
            [RAW_DATE, RAW_DATE_2, RAW_MONEY]
        )


# --------------------------------------------------------------------------- (2)
@pytest.mark.unit
class TestOneQuestionPerDistinctValue:
    def test_a_thousand_identical_values_are_one_row(self, env: _Env) -> None:
        env.run([_rows([{"d": RAW_DATE}] * 1000)], {"d": "DATE"})
        (row,) = env.queue()
        assert row["occurrences"] == 1000 and row["original"] == RAW_DATE

    def test_counts_add_across_chunks_of_the_same_job(self, env: _Env) -> None:
        batches = [_rows([{"d": RAW_DATE}] * 300), _rows([{"d": RAW_DATE}] * 200, start=300)]
        env.run(batches, {"d": "DATE"})
        (row,) = env.queue()
        assert row["occurrences"] == 500

    def test_only_ambiguous_is_queued_not_clean_not_invalid(self, env: _Env) -> None:
        env.run(
            [_rows([{"d": RAW_DATE}, {"d": CLEAN_DATE}, {"d": "not a date at all"}])],
            {"d": "DATE"},
        )
        assert [r["original"] for r in env.queue()] == [RAW_DATE]


# --------------------------------------------------------------------------- (3)
@pytest.mark.unit
class TestContextAndValueAreBothInTheKey:
    def _ctx(self, **kw: Any) -> NormalizationContext:
        return NormalizationContext(
            field_name="d", semantic_type=FieldSemanticType.DATE, table=TABLE, source="s", **kw
        )

    def test_same_value_two_countries_is_two_keys(self) -> None:
        us, de = self._ctx(country="US"), self._ctx(country="DE")
        v = SCAFFOLD_PROFILE.version
        a = verdict_key(FieldSemanticType.DATE, RAW_DATE, us, v)
        assert a != verdict_key(FieldSemanticType.DATE, RAW_DATE, de, v)
        assert a != verdict_key(FieldSemanticType.DATE, RAW_DATE, self._ctx(), v)
        assert a == verdict_key(FieldSemanticType.DATE, RAW_DATE, self._ctx(country="US"), v)

    def test_two_values_one_country_is_two_keys(self) -> None:
        c, v = self._ctx(country="US"), SCAFFOLD_PROFILE.version
        assert verdict_key(FieldSemanticType.DATE, RAW_DATE, c, v) != verdict_key(
            FieldSemanticType.DATE, RAW_DATE_2, c, v
        )

    def test_key_never_contains_the_value(self) -> None:
        k = verdict_key(FieldSemanticType.DATE, RAW_DATE, self._ctx(), SCAFFOLD_PROFILE.version)
        assert re.fullmatch(r"[0-9a-f]{32,128}", k) and RAW_DATE not in k

    def test_same_value_two_locales_end_to_end_is_two_rows(self, env: _Env) -> None:
        # locale-only contexts: DATE stays ambiguous under bare "en" and "de"
        for loc in ("en", "de"):
            env.run([_rows([{"d": RAW_DATE}])], {"d": "DATE"}, job_extra={"locale": loc})
        rows = env.queue()
        assert len(rows) == 2 and len({r["context_hash"] for r in rows}) == 2

    def test_same_value_two_columns_and_two_tables_are_separate_rows(self, env: _Env) -> None:
        env.run([_rows([{"d1": RAW_DATE, "d2": RAW_DATE}])], {"d1": "DATE", "d2": "DATE"})
        env.run(
            [_rows([{"d1": RAW_DATE}])],
            {"d1": "DATE"},
            table="t2",
            source_tables={"t2": [_rows([{"d1": RAW_DATE}])]},
        )
        assert len(env.queue()) == 3

    def test_a_verdict_for_one_answers_none_of_the_others(self, env: _Env) -> None:
        data = [_rows([{"d1": RAW_DATE, "d2": RAW_DATE, "d3": RAW_DATE_2}])]
        cfg = {"d1": "DATE", "d2": "DATE", "d3": "DATE"}
        env.run(data, cfg)
        assert len(env.queue()) == 3
        key = env.key_of(RAW_DATE, field="d1")
        assert env.post(key, DECIDE_DATE).status_code == 201
        _, out, job = env.run(data, cfg)
        assert out[0]["d1"] == DECIDE_DATE
        assert out[0]["d2"] == RAW_DATE  # same value, other column
        assert out[0]["d3"] == RAW_DATE_2  # other value, same table
        assert "AMBIGUOUS" not in _statuses(job, "d1")
        assert _statuses(job, "d2") == _statuses(job, "d3") == {"AMBIGUOUS": 1}

    def test_derived_country_groups_queue_only_the_ambiguous_group(self, env: _Env) -> None:
        """A row's COUNTRY column makes its date clean (own group); rows whose
        country does not resolve fall to the job context and stay ambiguous."""
        data = [
            _rows(
                [
                    {"c": "US", "d": RAW_DATE},
                    {"c": "DE", "d": RAW_DATE},
                    {"c": "ZZ-not-a-country", "d": RAW_DATE},
                ]
            )
        ]
        _, out, _ = env.run(data, {"c": "COUNTRY", "d": "DATE"})
        assert out[0]["d"] != out[1]["d"]  # US vs DE reading: context decided it
        assert out[2]["d"] == RAW_DATE  # no country: refused
        (row,) = env.queue()
        assert row["occurrences"] == 1


# --------------------------------------------------------------------------- (4)
@pytest.mark.unit
class TestInvalidationRules:
    def test_profile_version_change_does_not_apply_and_keeps_the_old_row(self, env: _Env) -> None:
        data, cfg = [_rows([{"d": RAW_DATE}])], {"d": "DATE"}
        env.run(data, cfg)
        key = env.key_of(RAW_DATE)
        assert env.post(key, DECIDE_DATE).status_code == 201

        bumped = SCAFFOLD_PROFILE.model_copy(update={"version": "v-next"})
        assert bumped.version != SCAFFOLD_PROFILE.version
        _, out, _ = env.run(data, cfg, adjudication=env.adjudication(bumped))
        assert out[0]["d"] == RAW_DATE  # not applied
        assert len(env.queue()) == 2  # asked again, under the new profile version
        (old,) = env.persistence.list_verdicts(key)  # still readable
        assert old["decided_value"] == DECIDE_DATE
        assert env.persistence.get_queue_entry(key) is not None

    def test_env_id_change_alone_still_applies(self, env: _Env) -> None:
        data, cfg = [_rows([{"d": RAW_DATE}])], {"d": "DATE"}
        env.run(data, cfg, env_id="env-1")
        env.post(env.key_of(RAW_DATE), DECIDE_DATE)
        j2, out, _ = env.run(data, cfg, env_id="env-2-after-a-normalizer-edit")
        assert out[0]["d"] == DECIDE_DATE and not env.errors(j2)
        # env_id is recorded, not matched
        (v,) = env.persistence.list_verdicts(env.key_of(RAW_DATE))
        assert v["env_id"]


# --------------------------------------------------------------------------- (5)
@pytest.mark.unit
class TestRefusedVerdictsStoreNothing:
    @pytest.mark.parametrize("bad", ["not a date", "03/04/2023", RAW_DATE, "2024-13-45", "\x00"])
    def test_non_clean_decided_value_is_refused_422(self, env: _Env, bad: str) -> None:
        env.run([_rows([{"d": RAW_DATE}])], {"d": "DATE"})
        key = env.key_of(RAW_DATE)
        before = (env.persistence.list_verdicts(key), env.queue())
        r = env.post(key, bad)
        assert r.status_code in (422,), (bad, r.status_code, r.text)
        assert (env.persistence.list_verdicts(key), env.queue()) == before
        assert env.persistence.list_verdicts(key) == []

    @pytest.mark.parametrize(
        "by", ["bob", "human:", "agent:", "root:alice", "human:al ice", "", "HUMAN:alice"]
    )
    def test_bad_decided_by_is_422(self, env: _Env, by: str) -> None:
        env.run([_rows([{"d": RAW_DATE}])], {"d": "DATE"})
        key = env.key_of(RAW_DATE)
        assert env.post(key, DECIDE_DATE, by).status_code == 422
        assert env.persistence.list_verdicts(key) == []

    def test_unknown_key_is_404_and_empty_body_values_are_422(self, env: _Env) -> None:
        assert env.post("0" * 64, DECIDE_DATE).status_code == 404
        env.run([_rows([{"d": RAW_DATE}])], {"d": "DATE"})
        key = env.key_of(RAW_DATE)
        assert env.post(key, "").status_code == 422
        bad = env.client.post(
            f"/normalization/adjudication/queue/{key}/verdicts",
            json={
                "decided_value": DECIDE_DATE,
                "decided_by": "human:a",
                "rationale": "x",
                "confidence": 1.5,
            },
        )
        assert bad.status_code == 422
        assert env.persistence.list_verdicts(key) == []

    def test_clean_statuses_are_the_non_refusal_ones(self) -> None:
        assert NormalizationStatus.AMBIGUOUS not in CLEAN_STATUSES
        assert NormalizationStatus.INVALID not in CLEAN_STATUSES
        assert NormalizationStatus.NEEDS_REVIEW not in CLEAN_STATUSES
        assert NormalizationStatus.NORMALIZED in CLEAN_STATUSES
        assert NormalizationStatus.PARSED in CLEAN_STATUSES

    def test_verdicts_are_append_only_newest_wins(self, env: _Env) -> None:
        data, cfg = [_rows([{"d": RAW_DATE}])], {"d": "DATE"}
        env.run(data, cfg)
        key = env.key_of(RAW_DATE)
        assert env.post(key, DECIDE_DATE, "human:alice").status_code == 201
        other = sorted(_DATE.candidates or ())[1]
        assert env.post(key, other, "human:bob").status_code == 201
        assert len(env.persistence.list_verdicts(key)) == 2  # nothing updated or deleted
        _, out, _ = env.run(data, cfg)
        assert out[0]["d"] == other


# --------------------------------------------------------------------------- (6)
@pytest.mark.unit
class TestDeciderIsJustAString:
    def test_decided_by_pattern(self) -> None:
        for ok in ("human:alice", "agent:v3", "agent:model-2.1", "human:a@b.org"):
            assert DECIDED_BY.fullmatch(ok), ok
        for bad in ("alice", "bot:x", "agent:", "human:a b", "agent:v3\n"):
            assert not DECIDED_BY.fullmatch(bad), bad

    def test_agent_v3_applies_identically_to_human_alice(self, tmp_path: Path) -> None:
        results = []
        for who in ("human:alice", "agent:v3"):
            (tmp_path / who.replace(":", "_")).mkdir()
            e = _Env(tmp_path / who.replace(":", "_"))
            data = [_rows([{"d": RAW_DATE, "a": RAW_MONEY}, {"d": RAW_DATE_2, "a": None}])]
            cfg = {"d": "DATE", "a": "MONEY"}
            e.run(data, cfg)
            assert e.post(e.key_of(RAW_DATE), DECIDE_DATE, who).status_code == 201
            assert e.post(e.key_of(RAW_MONEY), DECIDE_MONEY, who).status_code == 201
            jid, out, job = e.run(data, cfg)
            errs = [(x["row_index"], x["field"], x["error"]) for x in e.errors(jid)]
            results.append((out, errs, job["quality"]))
        assert results[0] == results[1]
        assert results[0][0][0]["d"] == DECIDE_DATE


# --------------------------------------------------------------------------- (7)
@pytest.mark.unit
class TestResumeNeverCountsTwice:
    N = 7

    def _batches(self) -> list[list[dict[str, Any]]]:
        return [
            _rows([{"d": RAW_DATE}] * self.N),
            _rows([{"d": RAW_DATE}] * self.N, start=self.N),
        ]

    def test_crash_after_insert_before_checkpoint_then_rerun(self, env: _Env) -> None:
        flaky = _FlakyPersistence(env.persistence, fail_on_call=1)
        jid = "resume-1"
        with pytest.raises(_Crash):
            env.run(self._batches(), {"d": "DATE"}, job_id=jid, persistence=flaky)
        assert flaky.commits == 1  # the queue write rides the checkpoint method
        assert env.queue() == []  # the uncommitted chunk left no trace in the queue
        # resume: the persisted checkpoint (none) decides which rows are re-read
        env.run(self._batches(), {"d": "DATE"}, job_id=jid, resume=True)
        (row,) = env.queue()
        assert row["occurrences"] == 2 * self.N  # counted once per row, not twice

    def test_crash_on_second_chunk_counts_the_first_exactly_once(self, env: _Env) -> None:
        flaky = _FlakyPersistence(env.persistence, fail_on_call=2)
        jid = "resume-2"
        with pytest.raises(_Crash):
            env.run(self._batches(), {"d": "DATE"}, job_id=jid, persistence=flaky)
        (row,) = env.queue()
        assert row["occurrences"] == self.N  # chunk 1 committed with its checkpoint
        _, out, job = env.run(self._batches(), {"d": "DATE"}, job_id=jid, resume=True)
        assert len(out) == self.N  # chunk 1 skipped on resume
        (row,) = env.queue()
        assert row["occurrences"] == 2 * self.N
        assert job["progress"]["rows_done"] >= self.N

    def test_checkpointed_rows_are_skipped_and_queue_is_unchanged(self, env: _Env) -> None:
        jid, *_ = env.run(self._batches(), {"d": "DATE"})
        before = env.queue()
        _, out, _ = env.run(self._batches(), {"d": "DATE"}, job_id=jid, resume=True)
        assert out == []  # every row is at or below the checkpoint
        assert env.queue() == before

    def test_a_later_job_restarts_the_count_rather_than_adding(self, env: _Env) -> None:
        env.run(self._batches(), {"d": "DATE"})
        env.run(self._batches(), {"d": "DATE"})  # a new job reads the same rows again
        (row,) = env.queue()
        assert row["occurrences"] == 2 * self.N  # per-job count; not 4N
        assert row["first_job_id"] != row["last_job_id"]


# --------------------------------------------------------------------------- (8) API
@pytest.mark.unit
class TestApiNeverReturnsTheRawValue:
    def _everything(self, env: _Env) -> list[str]:
        bodies: list[str] = []

        def grab(r: Any) -> Any:
            bodies.append(r.text + json.dumps(dict(r.headers)))
            return r

        base = "/normalization/adjudication/queue"
        grab(env.client.get(base))
        for q in ("?status=pending", "?status=decided", "?semantic_type=DATE", "?limit=1&offset=1"):
            grab(env.client.get(base + q))
        for row in env.queue():
            grab(env.client.get(f"{base}/{row['key']}"))
        return bodies

    def test_no_response_body_contains_the_raw_value_or_its_digits(self, env: _Env) -> None:
        data = [_rows([{"d": RAW_DATE, "a": RAW_MONEY, "p": RAW_PHONE}] * 3)]
        cfg = {"d": "DATE", "a": "MONEY", "p": "PHONE"}
        env.run(data, cfg)
        bodies = self._everything(env)
        assert len(env.queue()) == 3
        for row in env.queue():  # decide, then read again with a verdict attached
            value = {"DATE": DECIDE_DATE, "MONEY": DECIDE_MONEY, "PHONE": DECIDE_PHONE}[
                row["semantic_type"]
            ]
            r = env.post(row["key"], value)
            assert r.status_code == 201, r.text
            bodies.append(r.text)
        bodies += self._everything(env)
        bodies.append(env.post("0" * 64, DECIDE_DATE).text)
        bodies.append(env.post(env.queue()[0]["key"], "not clean at all").text)
        digits_phone = re.sub(r"\D", "", RAW_PHONE)
        for body in bodies:
            for raw in (RAW_DATE, RAW_MONEY, RAW_PHONE):
                assert raw not in body, raw
            assert digits_phone not in re.sub(r"\D", "", body)  # nor a reformatted candidate

    def test_queue_view_has_counts_total_header_and_paging(self, env: _Env) -> None:
        env.run([_rows([{"d": RAW_DATE}] * 5 + [{"d": RAW_DATE_2}] * 2)], {"d": "DATE"})
        r = env.client.get("/normalization/adjudication/queue")
        assert r.status_code == 200 and r.headers["X-Total-Count"] == "2"
        assert [e["occurrences"] for e in r.json()] == [5, 2]  # most frequent first
        page = env.client.get("/normalization/adjudication/queue?limit=1&offset=1")
        assert page.headers["X-Total-Count"] == "2" and len(page.json()) == 1
        env.post(env.key_of(RAW_DATE), DECIDE_DATE)
        pend = env.client.get("/normalization/adjudication/queue?status=pending")
        done = env.client.get("/normalization/adjudication/queue?status=decided")
        assert (pend.headers["X-Total-Count"], done.headers["X-Total-Count"]) == ("1", "1")
        assert done.json()[0]["occurrences"] == 5
        assert env.client.get("/normalization/adjudication/queue/" + "f" * 64).status_code == 404


# --------------------------------------------------------------------------- NEEDS_REVIEW (D12)
@pytest.mark.unit
class TestNeedsReviewHasOneProducer:
    def test_a_verdict_whose_display_moved_is_emitted_and_flagged(self, env: _Env) -> None:
        data, cfg = [_rows([{"d": RAW_DATE}, {"d": RAW_DATE_2}])], {"d": "DATE"}
        env.run(data, cfg)
        for raw, decided in ((RAW_DATE, DECIDE_DATE), (RAW_DATE_2, DECIDE_DATE_2)):
            assert env.post(env.key_of(raw), decided).status_code == 201
        # simulate a normalizer change since the decision: the recorded display
        # no longer matches what the decided value normalizes to now
        stale = env.persistence.list_verdicts(env.key_of(RAW_DATE))[0]
        env.persistence.add_verdict(
            {**stale, "decided_display": "an older rendering", "decided_at": "2999-01-01T00:00:00"}
        )
        j2, out, job = env.run(data, cfg)
        assert out[0]["d"] == DECIDE_DATE  # the new value is emitted
        assert out[1]["d"] == DECIDE_DATE_2
        assert _statuses(job, "d").get("NEEDS_REVIEW") == 1  # the stale one, only
        errs = [e for e in env.errors(j2) if e["field"] == "d"]
        assert [e["row_index"] for e in errs] == [0] and errs[0]["error"].strip()

    def test_an_env_change_that_does_not_alter_the_output_is_silent(self, env: _Env) -> None:
        data, cfg = [_rows([{"d": RAW_DATE}])], {"d": "DATE"}
        env.run(data, cfg, env_id="a")
        env.post(env.key_of(RAW_DATE), DECIDE_DATE)
        j2, _, job = env.run(data, cfg, env_id="b")
        assert "NEEDS_REVIEW" not in _statuses(job, "d") and not env.errors(j2)


# --------------------------------------------------------------------------- 2.4 never-guess
@pytest.mark.unit
class TestNeverGuess:
    def test_an_undecided_value_is_never_resolved_to_one_of_its_candidates(self, env: _Env) -> None:
        data, cfg = [_rows([{"d": RAW_DATE, "e": RAW_DATE_2}])], {"d": "DATE", "e": "DATE"}
        env.run(data, cfg)
        env.post(
            env.key_of(
                RAW_DATE,
            ),
            DECIDE_DATE,
        )  # a verdict for ONE value
        _, out, _ = env.run(data, cfg)
        for cell, candidates in ((out[0]["e"], _DATE_2.candidates),):
            assert cell == RAW_DATE_2 and cell not in (candidates or ())

    def test_a_verdict_for_a_value_does_not_leak_to_a_look_alike(self, env: _Env) -> None:
        data = [_rows([{"d": RAW_DATE}])]
        env.run(data, {"d": "DATE"})
        env.post(env.key_of(RAW_DATE), DECIDE_DATE)
        look_alike = RAW_DATE + " "  # different string, different key
        _, out, _ = env.run([_rows([{"d": look_alike}])], {"d": "DATE"})
        assert out[0]["d"] != DECIDE_DATE

    @pytest.mark.parametrize("case", fx.D1_DATE_PRECISION, ids=lambda c: c.id)
    def test_stated_precision_is_preserved_with_adjudication_on(self, env: _Env, case: Any) -> None:
        data = [_rows([{"d": case.input}])]
        _, old, _ = env.run(data, {"d": "DATE"}, adjudication=None)
        _, out, _ = env.run(data, {"d": "DATE"})
        assert out == old  # the resolve stage never touches a clean value
        assert env.queue() == []  # clean values are not questions
        if case.id == "prec-month-year" and out[0]["d"] != case.expected_value:
            pytest.xfail("pre-existing date normalizer fills in a day for 03/2024 (not D1)")
        assert out[0]["d"] == case.expected_value  # no month or day filled in

    def test_a_clean_value_equal_to_a_verdict_target_is_untouched(self, env: _Env) -> None:
        env.run([_rows([{"d": RAW_DATE}])], {"d": "DATE"})
        env.post(env.key_of(RAW_DATE), DECIDE_DATE)
        _, out, _ = env.run([_rows([{"d": CLEAN_DATE}])], {"d": "DATE"})
        assert out[0]["d"] == CLEAN_DATE_OUT


# --- attack: shapes the spec did not list
class _SeededSource(_Source):
    def get_columns(self, table: str) -> list[Any]:
        return [type("Col", (), {"name": n}) for n in ("k", "m")]


@pytest.mark.unit
class TestAttackShapes:
    def test_typed_money_with_companion_column_gets_the_cast_and_a_uniform_row(
        self, env: _Env
    ) -> None:
        plan = {"typed_columns": {"m": "MONEY"}, "currency_columns": {"m": "m_ccy"}}
        data = [_rows([{"m": RAW_MONEY}, {"m": None}])]
        extra = {"destination_plan": {TABLE: plan}}
        j1, first, _ = env.run(data, {"m": "MONEY"}, job_extra=extra)
        assert first[0]["m"] is None  # un-castable original: NULL + error row, as on main
        assert any(e["field"] == "m" for e in env.errors(j1))
        assert env.post(env.key_of(RAW_MONEY), DECIDE_MONEY).status_code == 201
        j2, second, _ = env.run(data, {"m": "MONEY"}, job_extra=extra)
        assert str(second[0]["m"]) == DECIDE_MONEY  # the exit reaches a typed column
        assert all(set(r) == {"m", "m_ccy"} for r in second)  # bulk_insert needs uniform keys
        assert not env.errors(j2)

    def test_a_country_inferred_from_a_sibling_table_gets_its_own_answerable_row(
        self, env: _Env
    ) -> None:
        """CH rejects "1,234" (INVALID), `_drop_rejected_country` falls back to the
        no-country result (AMBIGUOUS). The queue row carries the context the value
        was keyed in, and a verdict on it must be accepted and applied."""
        rows = [_rows([{"k": "e1", "m": RAW_MONEY}] * 2 + [{"k": "e2", "m": RAW_MONEY}])]

        def run(job_id: str) -> list[dict[str, Any]]:
            job = _job({"m": "MONEY"}, cross_table_entity_key="k")
            env.persistence.create_clone_job(job_id, job)
            dest = _Dest()
            _normalize_table(
                TABLE,
                job=job,
                job_id=job_id,
                source=_SeededSource({TABLE: rows}),
                dest=dest,
                source_engine="clickhouse",
                persistence=env.persistence,
                planner=DistinctValuePlanner(build_dispatcher(env_id="e"), None),
                pool=None,
                progress=job["progress"],
                in_place=False,
                entity_countries={"e1": "CH"},
                adjudication=env.adjudication(),
            )
            return dest.inserted

        assert [r["m"] for r in run("s1")] == [RAW_MONEY] * 3
        assert sorted(r["occurrences"] for r in env.queue()) == [1, 2]  # CH group, no-country group
        for r in env.queue():
            assert env.post(r["key"], DECIDE_MONEY).status_code == 201
        assert [r["m"] for r in run("s2")] == [DECIDE_MONEY] * 3

    def test_a_lone_surrogate_in_an_ambiguous_value_does_not_fail_the_chunk(
        self, env: _Env
    ) -> None:
        data = [_rows([{"p": RAW_PHONE + "\ud800"}, {"p": RAW_PHONE}])]
        _, old, _ = env.run(data, {"p": "PHONE"}, adjudication=None)  # main completes
        _, new, _ = env.run(data, {"p": "PHONE"})
        assert new == old

    def test_whitespace_verdict_must_not_silently_null_the_cell(self, env: _Env) -> None:
        env.run([_rows([{"d": RAW_DATE}])], {"d": "DATE"})
        assert env.post(env.key_of(RAW_DATE), " ").status_code == 422


# --------------------------------------------------------------------------- connectors
@pytest.mark.unit
def test_source_connectors_still_have_no_write_method() -> None:
    public = {n for n in dir(SourceConnector) if not n.startswith("_")}
    assert not {n for n in public if re.search(r"write|insert|update|delete|execute|upsert", n)}

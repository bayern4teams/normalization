"""Reproducers for the bugs the public-data benchmarks found
(docs/benchmarks/REPORT.md §7), one class per bug. Each failed on main
before its fix. The live counterparts, against real Postgres and
ClickHouse, are in tests/integration/test_robustness_live.py.
"""

from __future__ import annotations

import decimal
import json
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

import pyarrow as pa
import pytest
import sqlalchemy as sa
from cryptography.fernet import Fernet
from normalizers.phone import PhoneNormalizer
from normapi.app import build_dispatcher, build_normalizer_registry
from normapi.clone_executor import _normalize_table
from normapi.pg_persistence import PgPersistence
from normapi.schemas import CloneJobCreateRequest
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType, NormalizationStatus
from normexec.planner import DistinctValuePlanner
from normio.connector import ColumnInfo
from normio.connectors.clickhouse_destination import ClickHouseDestination
from normio.connectors.postgres_destination import PostgresDestination

from normapi import clone_executor
from normio import storage_types

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit


def _open(item: str) -> pytest.MarkDecorator:
    """Reproducer of a bug not fixed yet at this commit (removed by its fix)."""
    return pytest.mark.xfail(strict=True, reason=f"fix/robustness item {item}")


_ROOT = Path(__file__).resolve().parents[2]
_NOT_UNIT = ("-q", "-m", "not unit", "tests/unit")


# --- shared fakes -----------------------------------------------------------


class _Batch:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def to_pylist(self) -> list[dict[str, Any]]:
        return [{**r, "source_row_key": f"t:{i}"} for i, r in enumerate(self._rows)]


class _Source:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def read_table(self, *a: Any, **k: Any) -> Iterator[_Batch]:
        yield _Batch(self._rows)

    def get_columns(self, table: str) -> list[Any]:
        return []

    def get_primary_key(self, table: str) -> list[str]:
        return []


class _Dest:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def bulk_insert(self, database: str, table: str, rows: list[Any], **kw: Any) -> None:
        self.rows.extend(rows)


def _reject_nul_like_postgres(engine: sa.Engine) -> None:
    """SQLite stores NUL; Postgres text refuses it. Make the test store refuse
    it the same way, at the same point (the INSERT)."""

    @sa.event.listens_for(engine, "before_cursor_execute")
    def _reject(_c: Any, _cur: Any, _stmt: str, params: Any, _ctx: Any, many: bool) -> None:
        for p in params if many else [params]:
            values = p.values() if isinstance(p, dict) else p
            if any(isinstance(v, str) and "\x00" in v for v in values):
                msg = "PostgreSQL text fields cannot contain NUL (0x00) bytes"
                raise ValueError(msg)


def _store(tmp_path: Path) -> PgPersistence:
    store = PgPersistence(f"sqlite:///{tmp_path}/m.db")
    store.ensure_schema()
    _reject_nul_like_postgres(store._engine)
    return store


def _run_table(
    store: PgPersistence,
    rows: list[dict[str, Any]],
    field_configs: dict[str, str],
    typed: dict[str, str] | None = None,
    engine: str = "postgres",
) -> _Dest:
    job: dict[str, Any] = {
        "source_connection_id": "s",
        "destination_database": "d",
        "field_configs": {"t": field_configs},
        "destination_plan": {"t": {"typed_columns": typed or {}}},
        "progress": {"checkpoints": {}, "rows_done": 0, "current_table": None},
        "country": None,
        "locale": None,
    }
    store.create_clone_job("j", job)
    dest = _Dest()
    _normalize_table(
        "t",
        job=job,
        job_id="j",
        source=_Source(rows),
        dest=dest,
        source_engine=engine,
        persistence=store,
        planner=DistinctValuePlanner(build_dispatcher(env_id="e"), None),
        pool=None,
        progress=job["progress"],
        in_place=False,
        entity_countries={},
        adjudication=None,
    )
    return dest


def _errors(store: PgPersistence) -> list[dict[str, Any]]:
    return store.load_clone_job_errors_page("j", limit=100, offset=0)


# --- 1. D1 NUL ---------------------------------------------------------------


class TestNulInAPersistedValue:
    def test_the_job_continues_and_the_error_row_keeps_the_original(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        raw = "1,234\x00"
        dest = _run_table(store, [{"amt": raw}, {"amt": "x"}], {"amt": "MONEY"})
        assert len(dest.rows) == 2
        by_original = {e["original"]: e for e in _errors(store)}
        stored = json.dumps(raw)
        assert stored in by_original, by_original
        assert json.loads(stored) == raw  # recoverable, byte for byte
        assert "NUL" in by_original[stored]["error"]

    def test_the_queue_accepts_a_nul_original(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.create_clone_job("j", {})
        item = {
            "key": "k",
            "semantic_type": "MONEY",
            "context_hash": "c",
            "profile_version": "p",
            "context": "{}",
            "original": "1,234\x00",
            "detail": json.dumps({"errors": ["ambiguous"]}),
            "occurrences": 1,
        }
        store.save_clone_job_and_enqueue("j", {}, [item])
        entry = store.get_queue_entry("k")
        assert entry is not None
        assert json.loads(entry["original"]) == "1,234\x00"
        assert json.loads(entry["detail"])["original_encoding"] == "json"

    def test_a_value_without_nul_is_stored_unchanged(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        _run_table(store, [{"amt": "x"}], {"amt": "MONEY"})
        assert [e["original"] for e in _errors(store)] == ["x"]


# --- 2. D5 silent truncation --------------------------------------------------


class TestNoSilentFractionLoss:
    @pytest.mark.parametrize("engine", ["postgres", "clickhouse"])
    @pytest.mark.parametrize("text", ["12.34565", "0.00005", "0.0000000005"])
    def test_money_with_more_decimals_than_the_column_is_null_plus_error(
        self, engine: str, text: str
    ) -> None:
        cast, error = storage_types.coerce("MONEY", text, engine)
        assert cast is None
        assert error is not None

    def test_clickhouse_numeric_past_its_scale_is_null_plus_error(self) -> None:
        cast, error = storage_types.coerce("NUMERIC", "0.0000000005", "clickhouse")
        assert cast is None
        assert error is not None

    def test_postgres_unbounded_numeric_keeps_every_digit(self) -> None:
        cast, error = storage_types.coerce("NUMERIC", "0.0000000005", "postgres")
        assert error is None
        assert cast == decimal.Decimal("0.0000000005")

    @pytest.mark.parametrize("engine", ["postgres", "clickhouse"])
    def test_trailing_zeros_past_the_scale_lose_nothing(self, engine: str) -> None:
        cast, error = storage_types.coerce("MONEY", "12.3400000", engine)
        assert error is None
        assert cast == decimal.Decimal("12.34")


# --- 3. autodetect default off ------------------------------------------------


class _DetectSource:
    """The three columns autodetect corrupted on real data."""

    columns: ClassVar[dict[str, list[str]]] = {
        "siren": [str(300000000 + i * 7919) for i in range(50)],
        "state": ["al", "ak", "az", "ca", "ny"] * 10,
        "marital_status": ["S", "M"] * 25,
    }

    def list_tables(self) -> list[str]:
        return ["t"]

    def get_primary_key(self, table: str) -> list[str]:
        return []

    def get_columns(self, table: str) -> list[ColumnInfo]:
        return [ColumnInfo(name=c, native_type="text") for c in self.columns]

    def read_table(self, table: str, *, columns: list[str], batch_size: int = 200) -> Any:
        yield pa.RecordBatch.from_arrays(
            [pa.array(self.columns[c]) for c in columns], names=list(columns)
        )

    def close(self) -> None:
        pass


class TestAutodetectIsOffByDefault:
    @pytest.fixture
    def store(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> PgPersistence:
        monkeypatch.setenv("NORM_SECRET_KEY", Fernet.generate_key().decode())
        monkeypatch.setattr(clone_executor, "build_source_connector", lambda *a: _DetectSource())
        store = PgPersistence(f"sqlite:///{tmp_path}/m.db")
        store.ensure_schema()
        store.save_connection(
            "src", engine="postgres", host="h", port=1, username="u", password="p"
        )
        return store

    def _create(self, store: PgPersistence, **extra: Any) -> dict[str, Any]:
        request = CloneJobCreateRequest(
            source_connection_id="src",
            source_database="db",
            destination_connection_id="src",
            destination_database="out",
            country="FR",
            locale="fr-FR",
            **extra,
        ).model_dump(mode="json")
        return clone_executor.create_clone_job(
            store, request=request, registry=build_normalizer_registry()
        )

    def test_the_request_default_is_off(self) -> None:
        assert CloneJobCreateRequest.model_fields["autodetect_field_types"].default is False

    def test_nothing_is_applied_but_every_column_gets_a_suggestion(
        self, store: PgPersistence
    ) -> None:
        job = self._create(store)
        assert job["field_configs"] == {}
        assert job["inferred_field_configs"] == {}
        suggested = job["suggested_field_types"]["t"]
        for column in ("siren", "state", "marital_status"):
            if column not in suggested:
                continue  # no candidate at all is also not a write
            s = suggested[column]
            assert set(s) >= {"semantic_type", "validated_share", "sampled"}
            assert 0.0 <= s["validated_share"] <= 1.0
            assert s["sampled"] == len(_DetectSource.columns[column])

    def test_opting_in_per_job_applies_the_suggestions(self, store: PgPersistence) -> None:
        job = self._create(store, autodetect_field_types=True)
        assert job["field_configs"] == job["inferred_field_configs"]

    def test_the_plan_shows_the_suggestion_next_to_each_column(
        self, store: PgPersistence, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        job = self._create(store)
        monkeypatch.setattr(
            clone_executor,
            "plan_one_table",
            lambda *a: {
                "semantic_types": {},
                "columns": _DetectSource().get_columns("t"),
                "currency_columns": {},
                "code_columns": {},
                "column_overrides": {},
                "key_columns": [],
                "table_engine": None,
                "extra_columns": {},
            },
        )
        plan = clone_executor.plan_job(store, job["job_id"])
        columns = {c["column"]: c for c in plan["tables"][0]["columns"]}
        for column, suggestion in job["suggested_field_types"]["t"].items():
            assert columns[column]["suggestion"] == suggestion
            assert columns[column]["semantic_type"] is None


# --- 4. identifiers -------------------------------------------------------------

_HOSTILE_NAMES = ["organisasjonsform.kode", "zip code", "x-y", "p:q", "50%", 'qu"ote', "b`t"]


class TestHostileIdentifiers:
    def test_postgres_destination_creates_and_inserts_any_column_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            PostgresDestination, "_dsn", lambda self, db: f"sqlite:///{tmp_path}/{db}.db"
        )
        dest = PostgresDestination("h", 1, "u", "p")
        cols = [ColumnInfo(name=n, native_type="TEXT") for n in _HOSTILE_NAMES]
        dest.create_table("d", 'ta"ble.x', cols, primary_key=[_HOSTILE_NAMES[0]])
        rows = [{n: f"{i}-{n}" for n in _HOSTILE_NAMES} for i in range(3)]
        dest.bulk_insert("d", 'ta"ble.x', rows, primary_key=[_HOSTILE_NAMES[0]])
        dest.bulk_insert("d", 'ta"ble.x', rows, primary_key=[_HOSTILE_NAMES[0]])  # resume: no-op
        with sa.create_engine(f"sqlite:///{tmp_path}/d.db").connect() as conn:
            got = conn.execute(sa.text('SELECT * FROM "ta""ble.x"')).mappings().all()
        assert [dict(r) for r in got] == rows

    def test_clickhouse_destination_escapes_backticks(self) -> None:
        sent: list[str] = []

        class _Client:
            def command(self, sql: str) -> None:
                sent.append(sql)

        dest = ClickHouseDestination("h", 1, "u", "p")
        dest._clients["d"] = _Client()
        cols = [ColumnInfo(name=n, native_type="String") for n in _HOSTILE_NAMES]
        dest.create_table("d", "t`x", cols, order_by=["b`t"])
        ddl = sent[0]
        assert "`b\\`t`" in ddl
        assert "`t\\`x`" in ddl
        assert ddl.count("`") % 2 == ddl.count("\\`") % 2  # every unescaped backtick is paired

    def test_create_database_sql_quotes_the_name(self) -> None:
        assert clone_executor.create_database_sql('my"db') == 'CREATE DATABASE "my""db";'


# --- 6. smaller items -------------------------------------------------------------


class TestNonTextSourceValues:
    @_open("6 (Decimal / UTF-8)")
    def test_a_decimal_source_value_normalizes_instead_of_crashing(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        dest = _run_table(
            store, [{"total": decimal.Decimal("1.98")}], {"total": "MONEY"}, {"total": "MONEY"}
        )
        assert dest.rows[0]["total"] == decimal.Decimal("1.98")

    @_open("6 (Decimal / UTF-8)")
    def test_invalid_utf8_is_kept_as_is_with_an_error_row(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        raw = b"12.50\xed\xa0\x80"
        dest = _run_table(store, [{"amt": raw}, {"amt": b"7.00"}], {"amt": "MONEY"})
        assert dest.rows[0]["amt"] == raw  # the cell keeps the source bytes
        assert dest.rows[1]["amt"] == "7.00"
        (error,) = _errors(store)
        assert "UTF-8" in error["error"]
        assert error["original"] == raw.decode("utf-8", "backslashreplace")


class TestPhoneLettersAreNotDigits:
    @pytest.mark.parametrize(
        "value",
        ["3342938xxx", "334-293-8xxx", "+1 334 293 8XXX", "(334) 293-ABCD", "1-800-FLOWERS"],
    )
    @_open("6 (phone letters)")
    def test_letters_never_become_a_confident_number(self, value: str) -> None:
        ctx = NormalizationContext(
            field_name="p", semantic_type=FieldSemanticType.PHONE, country="US"
        )
        result = PhoneNormalizer().normalize(value, ctx)
        assert result.normalization_status is NormalizationStatus.AMBIGUOUS
        assert result.display == value

    @pytest.mark.parametrize("value", ["(334) 293-8123", "334-293-8123 x45", "+1 334 293 8123"])
    def test_digit_numbers_still_parse(self, value: str) -> None:
        ctx = NormalizationContext(
            field_name="p", semantic_type=FieldSemanticType.PHONE, country="US"
        )
        result = PhoneNormalizer().normalize(value, ctx)
        assert result.normalization_status is NormalizationStatus.PARSED


# --- 7. CI gap ---------------------------------------------------------------------


class TestEveryUnitTestIsSelectedByCi:
    @_open("7 (CI gap)")
    def test_nothing_under_tests_unit_lacks_the_unit_marker(self) -> None:
        out = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", *_NOT_UNIT],
            cwd=_ROOT,
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        selected = [line for line in out.splitlines() if "::" in line]
        assert selected == [], f"{len(selected)} tests escape ci-fast, e.g. {selected[:3]}"

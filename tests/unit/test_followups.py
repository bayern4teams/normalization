"""Reproducers for the follow-ups to fix/robustness (docs/benchmarks/REPORT.md
§9 "Remaining failures" and "Logged, not fixed"), one class per item. Each
failed on main before its fix. Live counterparts (real Postgres and
ClickHouse) are in tests/integration/test_followups_live.py.
"""

from __future__ import annotations

import re
import shlex
import string
import subprocess
import sys
import tempfile
from collections import namedtuple
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pyarrow as pa
import pytest
import yaml
from normapi.app import build_dispatcher
from normapi.clone_executor import _normalize_table
from normapi.pg_persistence import PgPersistence
from normapi.scaffold_profile import SCAFFOLD_PROFILE
from normcli.cli import main as normcli_main
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType, NormalizationStatus
from normexec.planner import DistinctValuePlanner
from normio.connectors import ClickHouseConnector
from normio.connectors.clickhouse_destination import ClickHouseDestination

from normalizers import text_ops

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]


# --- shared fakes -----------------------------------------------------------


def _batches(n_rows: int, batch: int, values: list[str]) -> list[pa.RecordBatch]:
    """Offsets 0..n_rows-1 in arrival order, cut at `batch`, like a source."""
    out = []
    for start in range(0, n_rows, batch):
        offsets = range(start, min(start + batch, n_rows))
        out.append(
            pa.RecordBatch.from_pydict(
                {
                    "id": [str(i) for i in offsets],
                    "amt": [values[i % len(values)] for i in offsets],
                    "source_row_key": [f"t:{i}" for i in offsets],
                }
            )
        )
    return out


class _Source:
    def __init__(self, batches: list[pa.RecordBatch]) -> None:
        self._batches = batches

    def read_table(self, *a: Any, **k: Any) -> Iterator[pa.RecordBatch]:
        yield from self._batches

    def get_columns(self, table: str) -> list[Any]:
        return []

    def get_primary_key(self, table: str) -> list[str]:
        return []


class _Dest:
    """Keeps what was inserted. `primary_key` on: a re-sent row is dropped,
    as Postgres' ON CONFLICT on the primary key does."""

    def __init__(self, *, primary_key: bool = False) -> None:
        self.inserts: list[int] = []
        self.rows: list[dict[str, Any]] = []
        self.truncated = 0
        self._primary_key = primary_key

    def bulk_insert(self, database: str, table: str, rows: list[Any], **kw: Any) -> None:
        self.inserts.append(len(rows))
        seen = {r["id"] for r in self.rows} if self._primary_key else set()
        self.rows.extend(r for r in rows if r["id"] not in seen)

    def truncate_table(self, database: str, table: str) -> None:
        self.truncated += 1
        self.rows.clear()


def _store(tmp_path: Path) -> PgPersistence:
    store = PgPersistence(f"sqlite:///{tmp_path}/m.db")
    store.ensure_schema()
    return store


def _job(block_rows: int = 2000) -> dict[str, Any]:
    return {
        "source_connection_id": "s",
        "source_identity": "postgres://s:5432/db",
        "destination_database": "d",
        "field_configs": {"t": {"amt": "MONEY"}},
        "destination_plan": {"t": {"typed_columns": {}}},
        "progress": {
            "checkpoints": {},
            "rows_done": 0,
            "current_table": None,
            "insert_block_rows": {"t": block_rows},
        },
        "country": "US",
        "locale": "en-US",
    }


def _run(
    store: Any, job: dict[str, Any], source: _Source, dest: _Dest, engine: str = "clickhouse"
) -> None:
    _normalize_table(
        "t",
        job=job,
        job_id="j",
        source=source,
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


# --- 1. ClickHouse insert blocks ---------------------------------------------


class _RecordingClient:
    def __init__(self) -> None:
        self.inserts: list[tuple[int, dict[str, Any]]] = []
        self.commands: list[str] = []

    def insert(self, table: str, data: list[Any], **kw: Any) -> None:
        self.inserts.append((len(data), kw.get("settings") or {}))

    def command(self, sql: str) -> None:
        self.commands.append(sql)


def _ch_dest() -> tuple[ClickHouseDestination, _RecordingClient]:
    dest = ClickHouseDestination("h", 1, "u", "p")
    client = _RecordingClient()
    dest._clients["d"] = client
    return dest, client


class TestClickHouseInsertBlocks:
    def test_rows_are_inserted_in_blocks_cut_at_offsets(self, tmp_path: Path) -> None:
        dest = _Dest()
        _run(_store(tmp_path), _job(8000), _Source(_batches(20000, 2000, ["1.00"])), dest)
        assert dest.inserts == [8000, 8000, 4000]

    def test_merge_tree_tables_merge_vertically(self) -> None:
        """A horizontal merge of small parts of a 110-column table peaked at
        562 MiB on ClickHouse 24.9; vertical, 14 MiB (REPORT.md §10)."""
        dest, client = _ch_dest()
        dest.create_table("d", "t", [], order_by=())
        assert "vertical_merge_algorithm_min_rows_to_activate = 0" in client.commands[0]


# --- 6. Low-cardinality columns are normalized once per job ------------------


class TestDistinctValuesAreRememberedAcrossChunks:
    def _calls(self, tmp_path: Path, values: list[str], rows: int) -> int:
        calls = 0
        dispatcher = build_dispatcher(env_id="e")
        real = dispatcher.normalize

        def counting(*a: Any, **k: Any) -> Any:
            nonlocal calls
            calls += 1
            return real(*a, **k)

        dispatcher.normalize = counting  # type: ignore[method-assign]
        job = _job()
        _normalize_table(
            "t",
            job=job,
            job_id="j",
            source=_Source(_batches(rows, 2000, values)),
            dest=_Dest(),
            source_engine="clickhouse",
            persistence=_store(tmp_path),
            planner=DistinctValuePlanner(dispatcher, None),
            pool=None,
            progress=job["progress"],
            in_place=False,
            entity_countries={},
            adjudication=None,
        )
        return calls

    def test_a_column_with_three_values_costs_three_calls_not_three_per_chunk(
        self, tmp_path: Path
    ) -> None:
        calls = self._calls(tmp_path, ["1.00", "2.00", "not money"], rows=20_000)
        # 3 values, plus the idempotence re-check of the 2 displays; was 5 per
        # chunk (50) before.
        assert calls <= 5

    def test_a_copied_context_hashes_its_own_fields(self) -> None:
        """Found by the memo: `model_copy` kept the cached hash, so the
        no-country retry of a cross-table country was keyed as the
        country context and served its result."""
        france = _ctx(FieldSemanticType.PHONE, "FR")
        assert france.context_hash  # cached now
        nowhere = france.model_copy(update={"country": None})
        assert nowhere.context_hash == _ctx(FieldSemanticType.PHONE, None).context_hash
        assert nowhere.context_hash != france.context_hash

    def test_a_high_cardinality_column_is_still_bounded(self, tmp_path: Path) -> None:
        dispatcher_values = [f"{i}.00" for i in range(6000)]
        calls = self._calls(tmp_path, dispatcher_values, rows=6000)
        assert calls >= 6000  # every value once at least: the memo never invents hits


# --- 2. A FAILED job resumes from its last committed block ---------------------


class _CrashOnSave:
    """The real store, except the n-th checkpoint save dies AFTER the
    destination insert it covers has committed: the worst place to crash."""

    def __init__(self, store: PgPersistence, crash_on: int) -> None:
        self._store = store
        self._left = crash_on

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._store, name)
        if name not in ("save_clone_job", "save_clone_job_and_enqueue"):
            return attr

        def save(*a: Any, **k: Any) -> Any:
            self._left -= 1
            if self._left == 0:
                msg = "killed"
                raise RuntimeError(msg)
            return attr(*a, **k)

        return save


class TestResumeAfterFailure:
    def _crash_then_resume(self, tmp_path: Path, engine: str, dest: _Dest) -> PgPersistence:
        store = _store(tmp_path)
        store.create_clone_job("j", _job())
        # every 3rd value is not money: an error row each, 2,000 of 6,000
        source = _Source(_batches(6000, 2000, ["1.00", "2.00", "not money"]))
        with pytest.raises(RuntimeError, match="killed"):
            _run(
                _CrashOnSave(store, crash_on=2),
                store.get_clone_job("j") or {},
                source,
                dest,
                engine,
            )
        _run(store, store.get_clone_job("j") or {}, source, dest, engine)
        assert sorted(int(r["id"]) for r in dest.rows) == list(range(6000))
        errors = store.load_clone_job_errors_page("j", limit=10_000, offset=0)
        assert sorted(e["row_index"] for e in errors) == list(range(2, 6000, 3))
        return store

    def test_postgres_resumes_after_its_last_committed_block(self, tmp_path: Path) -> None:
        """Crash after block 2's insert, before its checkpoint: block 2 is
        sent again and the primary key drops it; block 1 is not re-sent."""
        dest = _Dest(primary_key=True)
        self._crash_then_resume(tmp_path, "postgres", dest)
        assert dest.inserts == [2000, 2000, 2000, 2000] and dest.truncated == 0

    def test_clickhouse_starts_an_unfinished_table_over(self, tmp_path: Path) -> None:
        """A ClickHouse source does not arrive in the same order twice, so a
        skip by offset would skip the wrong rows: the table starts over."""
        dest = _Dest()
        store = self._crash_then_resume(tmp_path, "clickhouse", dest)
        assert dest.truncated == 1
        assert (store.get_clone_job("j") or {})["progress"]["rows_done"] == 6000

    def test_the_destination_can_empty_a_table(self) -> None:
        dest, client = _ch_dest()
        dest.truncate_table("d", "t")
        assert client.commands == ["TRUNCATE TABLE IF EXISTS `d`.`t`"]


# --- 3. Spool free space ------------------------------------------------------


class _SizeClient:
    def __init__(self, sizes: dict[str, int]) -> None:
        self._sizes = sizes

    def query(self, sql: str, parameters: Any = None) -> Any:
        return namedtuple("R", "result_rows")(list(self._sizes.items()))


def _ch_source(sizes: dict[str, int]) -> ClickHouseConnector:
    source = ClickHouseConnector.__new__(ClickHouseConnector)
    source._client = _SizeClient(sizes)
    source._database = "src"
    return source


class TestSpoolFreeSpace:
    def test_a_job_whose_largest_table_does_not_fit_fails_before_reading(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        usage = namedtuple("usage", "total used free")
        monkeypatch.setattr("shutil.disk_usage", lambda p: usage(10**9, 10**9 - 10**6, 10**6))
        with pytest.raises(OSError, match="TMPDIR") as exc:
            _ch_source({"big": 5 * 10**6, "small": 10}).check_spool_space(["big", "small"])
        assert tempfile.gettempdir() in str(exc.value)
        assert "big" in str(exc.value)

    def test_enough_space_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        usage = namedtuple("usage", "total used free")
        monkeypatch.setattr("shutil.disk_usage", lambda p: usage(10**9, 0, 10**9))
        _ch_source({"big": 5 * 10**6}).check_spool_space(["big"])


# --- 4. A letter among digits is never silently dropped -------------------------


def _ctx(semantic_type: FieldSemanticType, country: str | None) -> NormalizationContext:
    return NormalizationContext(
        field_name="f", semantic_type=semantic_type, country=country, include_trace=False
    )


_REFUSED = {
    NormalizationStatus.AMBIGUOUS,
    NormalizationStatus.INVALID,
    NormalizationStatus.FAILED,
    NormalizationStatus.NEEDS_REVIEW,
}

# Letters Unicode TR39 (via ICU's spoof checker) says read as a digit: the
# shape of a damaged digit. Derived, not listed by hand.
_checker = text_ops._get_spoof_checker()
_DIGIT_SKELETONS = {_checker.getSkeleton(0, str(d)) for d in range(10)}
_DIGIT_LIKE = [c for c in string.ascii_letters if _checker.getSkeleton(0, c) in _DIGIT_SKELETONS]

# One well-formed value per type that normalizes confidently, with the
# country it needs. Types with no digits to damage are not listed.
_SAMPLES: list[tuple[FieldSemanticType, str | None, str]] = [
    (FieldSemanticType.PHONE, "US", "3342938123"),
    (FieldSemanticType.PHONE, "US", "(334) 293-8123"),
    (FieldSemanticType.PHONE, None, "+44 20 7946 0958"),
    (FieldSemanticType.DATE, "US", "03/15/2024"),
    (FieldSemanticType.DATE, "US", "2024-03-15"),
    (FieldSemanticType.DATE, "US", "15 March 2024"),
    (FieldSemanticType.DATETIME, "US", "2024-03-15 12:34:56"),
    (FieldSemanticType.NUMERIC, "US", "1,234,567.89"),
    (FieldSemanticType.MONEY, "US", "1234.56 USD"),
    (FieldSemanticType.MONEY, "US", "$1,234.56"),
    (FieldSemanticType.POSTCODE, "US", "90210-1234"),
    (FieldSemanticType.TAX_ID, "US", "12-3456789"),
    (FieldSemanticType.UUID, None, "123e4567-e89b-12d3-a456-426614174000"),
    (FieldSemanticType.QUANTITY, None, "12 kg"),
]


class TestNoSilentCharacterDrop:
    def test_the_reported_value_is_ambiguous_and_keeps_the_original(self) -> None:
        dispatcher = build_dispatcher(env_id="e")
        ctx = _ctx(FieldSemanticType.PHONE, "US")
        result = dispatcher.normalize("33429381O23", FieldSemanticType.PHONE, ctx, SCAFFOLD_PROFILE)
        assert result.normalization_status is NormalizationStatus.AMBIGUOUS
        assert result.original == "33429381O23"

    def test_the_digit_like_letters_are_derived(self) -> None:
        assert set(_DIGIT_LIKE) >= {"O", "I", "l"}

    @pytest.mark.parametrize(("semantic_type", "country", "value"), _SAMPLES)
    def test_an_inserted_digit_like_letter_is_never_ignored(
        self, semantic_type: FieldSemanticType, country: str | None, value: str
    ) -> None:
        """Property: inserting a letter that looks like a digit anywhere
        inside a good value must not give back the same confident answer.
        That answer would mean the letter was dropped, and a damaged digit
        was guessed at."""
        dispatcher = build_dispatcher(env_id="e")
        ctx = _ctx(semantic_type, country)
        base = dispatcher.normalize(value, semantic_type, ctx, SCAFFOLD_PROFILE)
        assert base.normalization_status not in _REFUSED, base
        dropped = []
        for letter in _DIGIT_LIKE:
            for i in range(1, len(value)):
                damaged = value[:i] + letter + value[i:]
                r = dispatcher.normalize(damaged, semantic_type, ctx, SCAFFOLD_PROFILE)
                if r.normalization_status not in _REFUSED and r.comparison == base.comparison:
                    dropped.append(damaged)
        assert dropped == []

    @pytest.mark.parametrize("value", ["3342938a123", "3342938123 ok", "33429381O23"])
    def test_any_unread_letter_in_a_phone_number_is_ambiguous(self, value: str) -> None:
        dispatcher = build_dispatcher(env_id="e")
        ctx = _ctx(FieldSemanticType.PHONE, "US")
        r = dispatcher.normalize(value, FieldSemanticType.PHONE, ctx, SCAFFOLD_PROFILE)
        assert r.normalization_status is NormalizationStatus.AMBIGUOUS

    @pytest.mark.parametrize(
        "value", ["+1 334 293 8123 ext. 12", "334-293-8123 x12", "tel:+1-334-293-8123;ext=12"]
    )
    def test_a_phone_extension_still_parses(self, value: str) -> None:
        dispatcher = build_dispatcher(env_id="e")
        ctx = _ctx(FieldSemanticType.PHONE, "US")
        r = dispatcher.normalize(value, FieldSemanticType.PHONE, ctx, SCAFFOLD_PROFILE)
        assert r.normalization_status is NormalizationStatus.PARSED
        assert (r.structured or {})["extension"] == "12"

    @pytest.mark.parametrize("value", ["1234.56 foo USD", "1234.56 x USD", "1234.56O USD"])
    def test_an_unread_word_beside_a_currency_code_is_ambiguous(self, value: str) -> None:
        dispatcher = build_dispatcher(env_id="e")
        ctx = _ctx(FieldSemanticType.MONEY, "US")
        r = dispatcher.normalize(value, FieldSemanticType.MONEY, ctx, SCAFFOLD_PROFILE)
        assert r.normalization_status is NormalizationStatus.AMBIGUOUS

    @pytest.mark.parametrize("value", ["1234.56 USD", "1234.56 US dollar", "$10.5 Million"])
    def test_every_word_that_is_read_still_parses(self, value: str) -> None:
        dispatcher = build_dispatcher(env_id="e")
        ctx = _ctx(FieldSemanticType.MONEY, "US")
        r = dispatcher.normalize(value, FieldSemanticType.MONEY, ctx, SCAFFOLD_PROFILE)
        assert r.normalization_status is NormalizationStatus.NORMALIZED

    @pytest.mark.parametrize("value", ["15th March 2024", "on 15 March 2024", "Mar. 15th, 2024"])
    def test_ordinals_and_filler_words_in_dates_still_parse(self, value: str) -> None:
        dispatcher = build_dispatcher(env_id="e")
        ctx = _ctx(FieldSemanticType.DATE, "US")
        r = dispatcher.normalize(value, FieldSemanticType.DATE, ctx, SCAFFOLD_PROFILE)
        assert r.comparison == "2024-03-15"


# --- 5. Workflows that run on their own call commands that exist ------------------------------


def _triggered_run_lines() -> list[tuple[str, str]]:
    """`run:` lines of every workflow that starts on its own (a schedule, a
    push or a pull request), not only when someone dispatches it."""
    lines = []
    for path in sorted((_ROOT / ".github" / "workflows").glob("*.yml")):
        spec = yaml.safe_load(path.read_text())
        triggers = spec.get(True) or spec.get("on") or {}  # YAML 1.1 reads `on` as True
        if not {"schedule", "push", "pull_request"} & set(triggers):
            continue
        for job in spec["jobs"].values():
            for step in job.get("steps", []):
                text = re.sub(r"\\\n", " ", step.get("run", ""))
                lines += [(path.name, line) for line in text.splitlines()]
    return lines


# gate.yml (push to milestone/** only; last run 2026-08-29) and release.yml
# (tags) call normcli commands that were never built. Logged in REPORT.md §10,
# not fixed here; a ratchet, so building one or breaking another workflow
# both show up.
_KNOWN_MISSING = {("gate.yml", c) for c in ("bench-compare", "run", "diff", "sbom", "gate")} | {
    ("release.yml", "sbom")
}


class TestTriggeredWorkflowsCanRun:
    def test_every_normcli_command_they_call_exists(self) -> None:
        missing, seen = [], 0
        for name, line in _triggered_run_lines():
            for command in re.findall(r"-m normcli ([\w-]+)", line):
                seen += 1
                try:
                    normcli_main([command, "--help"])
                except SystemExit as exc:
                    if exc.code != 0:
                        missing.append((name, command))
        assert seen > 0  # the check is not vacuous
        assert set(missing) == _KNOWN_MISSING

    def test_every_pytest_option_they_pass_exists(self) -> None:
        help_text = subprocess.run(
            [sys.executable, "-m", "pytest", "--help"],
            capture_output=True,
            text=True,
            cwd=_ROOT,
            check=False,
        ).stdout
        missing, seen = [], 0
        for name, line in _triggered_run_lines():
            if "pytest" not in line:
                continue
            for token in shlex.split(line.split("||")[0]):
                option = token.split("=")[0]
                seen += option.startswith("--")
                if option.startswith("--") and option not in help_text:
                    missing.append((name, option))
        assert seen > 0  # the check is not vacuous
        assert missing == []


# --- found here: QUANTITY crashes, a date month taken from today ---------------


class TestQuantityNeverRaises:
    @pytest.mark.parametrize("base", ["12 kg", "3.5 m", "5 °C", "10 km/h", "2 ft"])
    def test_any_printable_character_anywhere_gives_a_result(self, base: str) -> None:
        """pint's unit parser raised AssertionError (`12# kg`, `12 kg*`) and
        tokenize.TokenError (`12" kg`) out of the normalizer, failing the job."""
        from normalizers.unit import UnitNormalizer  # noqa: PLC0415

        normalizer, ctx = UnitNormalizer(), _ctx(FieldSemanticType.QUANTITY, None)
        raised = []
        for ch in string.printable.strip() + " ":
            for i in range(len(base) + 1):
                value = base[:i] + ch + base[i:]
                try:
                    normalizer.normalize(value, ctx)
                except Exception as exc:
                    raised.append((value, type(exc).__name__))
        assert raised == []


class TestDateMonthIsStated:
    def test_a_letter_that_is_no_month_name_does_not_state_a_month(self) -> None:
        """`15 Z 2024` came back as 2024-<this month>-15: `Z` (a time zone to
        dateparser) counted as a month word, and the month came from today."""
        dispatcher = build_dispatcher(env_id="e")
        ctx = _ctx(FieldSemanticType.DATE, "US")
        r = dispatcher.normalize("15 Z 2024", FieldSemanticType.DATE, ctx, SCAFFOLD_PROFILE)
        assert r.normalization_status in _REFUSED or "-" not in (r.comparison or "")

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("15 March 2024", "2024-03-15"),
            ("Mar. 15th, 2024", "2024-03-15"),
            ("15 März 2024", "2024-03-15"),
            ("March 2024", "2024-03"),
        ],
    )
    def test_a_month_name_still_states_its_month(self, value: str, expected: str) -> None:
        dispatcher = build_dispatcher(env_id="e")
        ctx = _ctx(FieldSemanticType.DATE, "US")
        r = dispatcher.normalize(value, FieldSemanticType.DATE, ctx, SCAFFOLD_PROFILE)
        assert r.comparison == expected

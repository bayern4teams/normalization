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


class _DedupDest:
    """Keeps what was inserted; drops a re-sent block by its token, the way
    ClickHouse does with `insert_deduplication_token`."""

    def __init__(self, block_rows: int) -> None:
        self.block_rows = block_rows
        self.inserts: list[tuple[int, str | None]] = []
        self.rows: list[dict[str, Any]] = []
        self._tokens: set[str] = set()

    def insert_block_rows(self, database: str, sample: pa.RecordBatch) -> int:
        return self.block_rows

    def bulk_insert(
        self,
        database: str,
        table: str,
        rows: list[Any],
        *,
        dedup_token: str | None = None,
        **kw: Any,
    ) -> None:
        self.inserts.append((len(rows), dedup_token))
        if dedup_token is not None and dedup_token in self._tokens:
            return
        if dedup_token is not None:
            self._tokens.add(dedup_token)
        self.rows.extend(rows)


def _store(tmp_path: Path) -> PgPersistence:
    store = PgPersistence(f"sqlite:///{tmp_path}/m.db")
    store.ensure_schema()
    return store


def _job() -> dict[str, Any]:
    return {
        "source_connection_id": "s",
        "destination_database": "d",
        "field_configs": {"t": {"amt": "MONEY"}},
        "destination_plan": {"t": {"typed_columns": {}}},
        "progress": {"checkpoints": {}, "rows_done": 0, "current_table": None},
        "country": "US",
        "locale": "en-US",
    }


def _run(store: Any, job: dict[str, Any], source: _Source, dest: _DedupDest) -> None:
    _normalize_table(
        "t",
        job=job,
        job_id="j",
        source=source,
        dest=dest,
        source_engine="clickhouse",
        persistence=store,
        planner=DistinctValuePlanner(build_dispatcher(env_id="e"), None),
        pool=None,
        progress=job["progress"],
        in_place=False,
        entity_countries={},
        adjudication=None,
    )


# --- 1. ClickHouse insert blocks ---------------------------------------------


class _SettingsClient:
    """Answers the two settings reads `insert_block_rows` makes."""

    def __init__(self) -> None:
        self.inserts: list[tuple[int, dict[str, Any]]] = []
        self.commands: list[str] = []

    def query(self, sql: str, parameters: Any = None) -> Any:
        rows = {
            "vertical_merge_algorithm_min_rows_to_activate": "131072",
            "min_insert_block_size_bytes": "268402944",
        }
        return namedtuple("R", "result_rows")([(k, v) for k, v in rows.items() if k in sql])

    def insert(self, table: str, data: list[Any], **kw: Any) -> None:
        self.inserts.append((len(data), kw.get("settings") or {}))

    def command(self, sql: str) -> None:
        self.commands.append(sql)


def _ch_dest() -> tuple[ClickHouseDestination, _SettingsClient]:
    dest = ClickHouseDestination("h", 1, "u", "p")
    client = _SettingsClient()
    dest._clients["d"] = client
    return dest, client


class TestClickHouseInsertBlocks:
    def test_rows_are_inserted_in_destination_sized_blocks_cut_at_offsets(
        self, tmp_path: Path
    ) -> None:
        dest = _DedupDest(block_rows=8000)
        _run(_store(tmp_path), _job(), _Source(_batches(20000, 2000, ["1.00"])), dest)
        assert [n for n, _ in dest.inserts] == [8000, 8000, 4000]

    def test_the_block_reaches_the_vertical_merge_threshold_for_narrow_rows(self) -> None:
        dest, _ = _ch_dest()
        narrow = pa.RecordBatch.from_pydict({"a": list(range(2000))})
        assert dest.insert_block_rows("d", narrow) == 131072

    def test_the_block_stops_at_the_server_insert_block_bytes_for_wide_rows(self) -> None:
        dest, _ = _ch_dest()
        wide = pa.RecordBatch.from_pydict({"a": ["x" * 10_000] * 100})
        row_bytes = wide.nbytes // wide.num_rows
        assert dest.insert_block_rows("d", wide) == 268402944 // row_bytes


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


@pytest.mark.xfail(strict=True, reason="item 2 not fixed yet")
class TestResumeAfterFailure:
    def test_one_insert_per_block_carrying_its_dedup_token(self) -> None:
        dest, client = _ch_dest()
        dest.bulk_insert("d", "t", [{"a": i} for i in range(5000)], dedup_token="j:t:0-4999")
        assert client.inserts == [(5000, {"insert_deduplication_token": "j:t:0-4999"})]

    def test_merge_tree_tables_keep_a_dedup_window(self) -> None:
        dest, client = _ch_dest()
        dest.create_table("d", "t", [], order_by=())
        assert "non_replicated_deduplication_window" in client.commands[0]

    def test_a_crash_after_an_insert_resumes_without_duplicate_rows_or_errors(
        self, tmp_path: Path
    ) -> None:
        store = _store(tmp_path)
        store.create_clone_job("j", _job())
        # every 3rd value is not money: an error row each, 2,000 of 6,000
        source = _Source(_batches(6000, 2000, ["1.00", "2.00", "not money"]))
        dest = _DedupDest(block_rows=2000)
        with pytest.raises(RuntimeError, match="killed"):
            _run(_CrashOnSave(store, crash_on=2), store.get_clone_job("j") or {}, source, dest)
        _run(store, store.get_clone_job("j") or {}, source, dest)

        assert sorted(int(r["id"]) for r in dest.rows) == list(range(6000))
        errors = store.load_clone_job_errors_page("j", limit=10_000, offset=0)
        assert sorted(e["row_index"] for e in errors) == list(range(2, 6000, 3))


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


@pytest.mark.xfail(strict=True, reason="item 3 not fixed yet")
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


@pytest.mark.xfail(strict=False, reason="item 4 not fixed yet")
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


# --- 5. Scheduled workflows run commands that exist ------------------------------


def _scheduled_run_lines() -> list[tuple[str, str]]:
    lines = []
    for path in sorted((_ROOT / ".github" / "workflows").glob("*.yml")):
        spec = yaml.safe_load(path.read_text())
        triggers = spec.get(True) or spec.get("on") or {}  # YAML 1.1 reads `on` as True
        if "schedule" not in triggers:
            continue
        for job in spec["jobs"].values():
            for step in job.get("steps", []):
                text = re.sub(r"\\\n", " ", step.get("run", ""))
                lines += [(path.name, line) for line in text.splitlines()]
    return lines


@pytest.mark.xfail(strict=True, reason="item 5 not fixed yet")
class TestScheduledWorkflowsCanRun:
    def test_every_normcli_command_they_call_exists(self) -> None:
        missing = []
        for name, line in _scheduled_run_lines():
            for command in re.findall(r"-m normcli ([\w-]+)", line):
                try:
                    normcli_main([command, "--help"])
                except SystemExit as exc:
                    if exc.code != 0:
                        missing.append((name, command))
        assert missing == []

    def test_every_pytest_option_they_pass_exists(self) -> None:
        help_text = subprocess.run(
            [sys.executable, "-m", "pytest", "--help"],
            capture_output=True,
            text=True,
            cwd=_ROOT,
            check=False,
        ).stdout
        missing = []
        for name, line in _scheduled_run_lines():
            if "pytest" not in line:
                continue
            for token in shlex.split(line.split("||")[0]):
                option = token.split("=")[0]
                if option.startswith("--") and option not in help_text:
                    missing.append((name, option))
        assert missing == []

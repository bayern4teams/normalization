"""Unit tests for `normexec.destination_stream.stream_table_to_destination`
(the M19 full-row destination-writing chunk loop) — previously only
exercised end to end against real docker-compose infrastructure in the
`integration`/`e2e` CI jobs (17% unit coverage, found 2026-08-29 when
gate.yml's coverage-fail-under=80 gate actually ran for the first time).
`StreamingSourceConnector` and `DestinationConnector` are both plain
Protocols with no infra dependency of their own — the same fake-connector
technique `tests/unit/test_run_execution.py` already uses for `Dispatcher`
callers — so this exercises the module's real branching (typed NUMERIC/
DATE extraction, unmapped passthrough columns, warning/error/typed-parse
issue rows, resume/since/track_created_at) without any live database.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pyarrow as pa
import pytest
from normcore.models import NormalizedValue
from normexec.destination_stream import stream_table_to_destination
from normio.catalog import ColumnSpec

from normanalysis import RunRecorder
from normcore import (
    Dispatcher,
    FieldSemanticType,
    NormalizationProfile,
    NormalizationRun,
    NormalizationRunMetrics,
    NormalizationStatus,
    NormalizerRegistry,
    RunStatus,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from normcore.context import NormalizationContext
    from normcore.interfaces import ComponentVersion, Explanation, StepSpec, ValidationResult


class _FakeSourceConnector:
    """Serves pre-built pages, one per `read_chunk` call, then `None`.
    Records every call's kwargs so tests can assert `since`/`after_key`
    were threaded through correctly."""

    def __init__(self, pages: list[pa.RecordBatch]) -> None:
        self._pages = list(pages)
        self.calls: list[dict[str, object]] = []

    def read_chunk(
        self,
        table: str,
        *,
        key_columns: Sequence[str],
        columns: Sequence[str] | None = None,
        after_key: tuple[object, ...] | None = None,
        limit: int = 100_000,
        since: object | None = None,
    ) -> pa.RecordBatch | None:
        self.calls.append({"table": table, "after_key": after_key, "since": since})
        if not self._pages:
            return None
        return self._pages.pop(0)


class _FakeDestinationConnector:
    def __init__(self) -> None:
        self.batches: list[tuple[str, pa.RecordBatch]] = []
        self.side_batches: list[tuple[str, pa.RecordBatch]] = []

    def ensure_database(self) -> None:
        pass

    def ensure_table(self, table: str, *, columns: object, key_columns: object) -> None:
        pass

    def ensure_side_table(self, table: str) -> None:
        pass

    def insert_batch(self, table: str, batch: pa.RecordBatch) -> None:
        self.batches.append((table, batch))

    def insert_side_table_batch(self, table: str, batch: pa.RecordBatch) -> None:
        self.side_batches.append((table, batch))

    def close(self) -> None:
        pass


class _ScriptedNormalizer:
    """Returns a caller-scripted `NormalizedValue` per distinct input
    value — deterministic control over status/display/warnings/errors
    that no real normalizer offers, matching the `_AlwaysFailsNormalizer`
    test-double convention used elsewhere (test_dispatch.py,
    test_run_execution.py)."""

    name = "Scripted"
    supported_types = frozenset(
        {FieldSemanticType.NUMERIC, FieldSemanticType.DATE, FieldSemanticType.UNKNOWN}
    )

    def __init__(self, script: dict[str | None, NormalizedValue]) -> None:
        self._script = script

    def can_handle(self, field_type: FieldSemanticType, ctx: NormalizationContext) -> bool:
        return True

    def normalize(self, value: str | None, ctx: NormalizationContext) -> NormalizedValue:
        # KeyError on an unscripted value is a test bug, not silently
        # swallowed. context_hash/semantic_type are stamped from the real
        # ctx here (mirroring what every real normalizer does) rather than
        # baked into the script, since Dispatcher._finalize asserts the
        # returned context_hash matches the context actually passed in.
        scripted = self._script[value]
        return scripted.model_copy(
            update={"context_hash": ctx.context_hash, "semantic_type": ctx.semantic_type}
        )

    def validate(self, value: str | None, ctx: NormalizationContext) -> ValidationResult:
        raise NotImplementedError

    def explain(self, result: NormalizedValue) -> Explanation:
        raise NotImplementedError

    def version(self) -> ComponentVersion:
        raise NotImplementedError

    def steps(self) -> Sequence[StepSpec]:
        return []

    def inverse(self, step_id: str, value: str) -> None:
        return None


def _nv(
    *,
    original: str | None,
    display: str | None,
    status: NormalizationStatus,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
) -> NormalizedValue:
    return NormalizedValue(
        original=original,
        display=display,
        comparison=display,
        search=display,
        normalization_status=status,
        warnings=warnings or [],
        errors=errors or [],
        profile_version="",
        env_id="",
        semantic_type=FieldSemanticType.NUMERIC,
        context_hash="",
    )


def _profile() -> NormalizationProfile:
    return NormalizationProfile(
        id="p1", name="test", version="v1", created_at="t", updated_at="t", created_by="test"
    )


def _recorder() -> RunRecorder:
    run = NormalizationRun(
        id="r1",
        profile_id="p1",
        profile_version="v1",
        env_id="e" * 64,
        source_snapshot="s",
        started_at="t",
        status=RunStatus.PENDING,
        metrics=NormalizationRunMetrics(),
    )
    recorder = RunRecorder(run)
    recorder.start()
    return recorder


def _dispatcher(script: dict[str | None, NormalizedValue]) -> Dispatcher:
    registry = NormalizerRegistry()
    registry.register(_ScriptedNormalizer(script))
    return Dispatcher(registry, env_id="e" * 64)


def _batch(
    *, ids: list[str], country: list[str], amount: list[str | None], keys: list[str]
) -> pa.RecordBatch:
    return pa.RecordBatch.from_arrays(
        [
            pa.array(ids),
            pa.array(country),
            pa.array(amount),
            pa.array(keys),
        ],
        names=["id", "country", "amount", "source_row_key"],
    )


@pytest.mark.unit
class TestStreamTableToDestination:
    def test_two_chunks_writes_mapped_and_unmapped_columns(self) -> None:
        script: dict[str | None, NormalizedValue] = {
            "10": _nv(original="10", display="10.00", status=NormalizationStatus.NORMALIZED),
            "20": _nv(original="20", display="20.00", status=NormalizationStatus.NORMALIZED),
        }
        page1 = _batch(ids=["r1"], country=["US"], amount=["10"], keys=["t:1"])
        page2 = _batch(ids=["r2"], country=["FR"], amount=["20"], keys=["t:2"])
        source = _FakeSourceConnector([page1, page2])
        destination = _FakeDestinationConnector()
        committed: list[int] = []

        rows = stream_table_to_destination(
            source,
            run_id="r1",
            table="t",
            key_columns=["id"],
            source_columns=_columns(),
            column_semantic_types={"amount": FieldSemanticType.NUMERIC},
            field_ref_prefix="s.t.",
            profile=_profile(),
            dispatcher=_dispatcher(script),
            cache=None,
            recorder=_recorder(),
            destination=destination,
            destination_table="t",
            chunk_size=1,
            on_chunk_committed=lambda p: committed.append(p.rows_processed),
        )

        assert rows == 2
        assert committed == [1, 2]
        assert len(destination.batches) == 2
        first_table, first_batch = destination.batches[0]
        assert first_table == "t"
        assert first_batch.schema.names == ["id", "country", "amount"]
        assert first_batch.column("country").to_pylist() == ["US"]  # unmapped, passed through
        assert first_batch.column("amount").to_pylist() == [Decimal("10.000000000")]
        # No warnings/errors/parse failures -> no side-table rows at all.
        assert destination.side_batches == []

    def test_typed_column_parse_failure_writes_null_plus_issue_row(self) -> None:
        # normalization_status looks successful but display is not a real
        # decimal -- _typed_parse_issue_row's "successful status" branch.
        script: dict[str | None, NormalizedValue] = {
            "abc": _nv(original="abc", display="abc", status=NormalizationStatus.NORMALIZED),
        }
        page = _batch(ids=["r1"], country=["US"], amount=["abc"], keys=["t:1"])
        source = _FakeSourceConnector([page])
        destination = _FakeDestinationConnector()

        stream_table_to_destination(
            source,
            run_id="r1",
            table="t",
            key_columns=["id"],
            source_columns=_columns(),
            column_semantic_types={"amount": FieldSemanticType.NUMERIC},
            field_ref_prefix="s.t.",
            profile=_profile(),
            dispatcher=_dispatcher(script),
            cache=None,
            recorder=_recorder(),
            destination=destination,
            destination_table="t",
        )

        _, batch = destination.batches[0]
        assert batch.column("amount").to_pylist() == [None]
        assert len(destination.side_batches) == 1
        _, issues = destination.side_batches[0]
        rows = issues.to_pylist()
        assert len(rows) == 1
        assert rows[0]["code"] == "TYPED_COLUMN_PARSE_FAILED"
        assert "did not parse" in rows[0]["message"]

    def test_non_successful_status_writes_null_plus_issue_row(self) -> None:
        script: dict[str | None, NormalizedValue] = {
            "??": _nv(original="??", display=None, status=NormalizationStatus.AMBIGUOUS),
        }
        page = _batch(ids=["r1"], country=["US"], amount=["??"], keys=["t:1"])
        destination = _FakeDestinationConnector()

        stream_table_to_destination(
            _FakeSourceConnector([page]),
            run_id="r1",
            table="t",
            key_columns=["id"],
            source_columns=_columns(),
            column_semantic_types={"amount": FieldSemanticType.NUMERIC},
            field_ref_prefix="s.t.",
            profile=_profile(),
            dispatcher=_dispatcher(script),
            cache=None,
            recorder=_recorder(),
            destination=destination,
            destination_table="t",
        )

        _, issues = destination.side_batches[0]
        rows = issues.to_pylist()
        assert rows[0]["code"] == "TYPED_COLUMN_PARSE_FAILED"
        assert "normalization_status=AMBIGUOUS" in rows[0]["message"]

    def test_warning_and_error_produce_issue_rows_not_typed_parse_rows(self) -> None:
        script: dict[str | None, NormalizedValue] = {
            "w": _nv(
                original="w",
                display="1.00",
                status=NormalizationStatus.REPAIRED,
                warnings=["rounded"],
            ),
            "e": _nv(
                original="e",
                display=None,
                status=NormalizationStatus.FAILED,
                errors=["boom"],
            ),
        }
        page = _batch(
            ids=["r1", "r2"], country=["US", "US"], amount=["w", "e"], keys=["t:1", "t:2"]
        )
        destination = _FakeDestinationConnector()

        stream_table_to_destination(
            _FakeSourceConnector([page]),
            run_id="r1",
            table="t",
            key_columns=["id"],
            source_columns=_columns(),
            column_semantic_types={"amount": FieldSemanticType.NUMERIC},
            field_ref_prefix="s.t.",
            profile=_profile(),
            dispatcher=_dispatcher(script),
            cache=None,
            recorder=_recorder(),
            destination=destination,
            destination_table="t",
        )

        _, issues = destination.side_batches[0]
        rows = issues.to_pylist()
        codes = sorted(r["code"] for r in rows)
        # Exactly the warning + error rows -- no extra TYPED_COLUMN_PARSE_FAILED
        # row for "e" (had_warning_or_error already True skips that branch).
        assert codes == ["NORMALIZER_ERROR", "NORMALIZER_WARNING"]

    def test_since_and_after_key_threaded_through_and_resume_after_key_used_first(self) -> None:
        script: dict[str | None, NormalizedValue] = {
            "1": _nv(original="1", display="1.00", status=NormalizationStatus.NORMALIZED)
        }
        page1 = _batch(ids=["r1"], country=["US"], amount=["1"], keys=["t:1"])
        source = _FakeSourceConnector([page1])
        destination = _FakeDestinationConnector()

        stream_table_to_destination(
            source,
            run_id="r1",
            table="t",
            key_columns=["id"],
            source_columns=_columns(),
            column_semantic_types={"amount": FieldSemanticType.NUMERIC},
            field_ref_prefix="s.t.",
            profile=_profile(),
            dispatcher=_dispatcher(script),
            cache=None,
            recorder=_recorder(),
            destination=destination,
            destination_table="t",
            resume_after_key=("r0",),
            since="2026-01-01",
        )

        assert source.calls[0]["after_key"] == ("r0",)
        assert source.calls[0]["since"] == "2026-01-01"

    def test_track_created_at_computes_max_from_batch(self) -> None:
        script: dict[str | None, NormalizedValue] = {
            "1": _nv(original="1", display="1.00", status=NormalizationStatus.NORMALIZED)
        }
        page = pa.RecordBatch.from_arrays(
            [
                pa.array(["r1", "r2"]),
                pa.array(["US", "US"]),
                pa.array(["1", "1"]),
                pa.array(["t:1", "t:2"]),
                pa.array(["2026-01-01", "2026-06-01"]),
            ],
            names=["id", "country", "amount", "source_row_key", "created_at"],
        )
        destination = _FakeDestinationConnector()
        committed = []

        stream_table_to_destination(
            _FakeSourceConnector([page]),
            run_id="r1",
            table="t",
            key_columns=["id"],
            source_columns=_columns(),
            column_semantic_types={"amount": FieldSemanticType.NUMERIC},
            field_ref_prefix="s.t.",
            profile=_profile(),
            dispatcher=_dispatcher(script),
            cache=None,
            recorder=_recorder(),
            destination=destination,
            destination_table="t",
            track_created_at=True,
            on_chunk_committed=lambda p: committed.append(p.last_created_at),
        )

        assert committed == ["2026-06-01"]

    def test_date_semantic_type_extracts_via_extract_date(self) -> None:
        script: dict[str | None, NormalizedValue] = {
            "d": _nv(original="d", display="2026-03-05", status=NormalizationStatus.NORMALIZED),
        }
        page = pa.RecordBatch.from_arrays(
            [pa.array(["r1"]), pa.array(["US"]), pa.array(["d"]), pa.array(["t:1"])],
            names=["id", "country", "when", "source_row_key"],
        )
        destination = _FakeDestinationConnector()

        stream_table_to_destination(
            _FakeSourceConnector([page]),
            run_id="r1",
            table="t",
            key_columns=["id"],
            source_columns=_columns(name_amount="when"),
            column_semantic_types={"when": FieldSemanticType.DATE},
            field_ref_prefix="s.t.",
            profile=_profile(),
            dispatcher=_dispatcher(script),
            cache=None,
            recorder=_recorder(),
            destination=destination,
            destination_table="t",
        )

        _, batch = destination.batches[0]
        assert batch.column("when").to_pylist() == [date(2026, 3, 5)]

    def test_non_typed_mapped_column_writes_display_string(self) -> None:
        # semantic_type neither NUMERIC nor DATE -> the plain "else" branch
        # in _build_destination_batch: written as display, large_string.
        script: dict[str | None, NormalizedValue] = {
            "raw": _nv(
                original="raw", display="Cleaned Value", status=NormalizationStatus.NORMALIZED
            ),
        }
        page = pa.RecordBatch.from_arrays(
            [pa.array(["r1"]), pa.array(["US"]), pa.array(["raw"]), pa.array(["t:1"])],
            names=["id", "country", "amount", "source_row_key"],
        )
        destination = _FakeDestinationConnector()

        stream_table_to_destination(
            _FakeSourceConnector([page]),
            run_id="r1",
            table="t",
            key_columns=["id"],
            source_columns=_columns(),
            column_semantic_types={"amount": FieldSemanticType.UNKNOWN},
            field_ref_prefix="s.t.",
            profile=_profile(),
            dispatcher=_dispatcher(script),
            cache=None,
            recorder=_recorder(),
            destination=destination,
            destination_table="t",
        )

        _, batch = destination.batches[0]
        assert batch.column("amount").to_pylist() == ["Cleaned Value"]
        assert batch.schema.field("amount").type == pa.large_string()


def _columns(name_amount: str = "amount") -> list[ColumnSpec]:
    return [
        ColumnSpec(name="id", type="string", nullable=False, is_primary_key=True),
        ColumnSpec(name="country", type="string", nullable=True, is_primary_key=False),
        ColumnSpec(name=name_amount, type="string", nullable=True, is_primary_key=False),
    ]

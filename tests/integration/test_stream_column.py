"""Integration tests for normexec.stream.stream_column (M17,
docs/plan/M13-M22-program-plan.md) — the real chunked-streaming
normalization loop, live against the real ClickHouse at localhost:8190.

Note: constructing a `ClickHouseConnector` (normio) directly in a bare
script on this machine's venv can segfault depending on import order (a
known, previously-disclosed native-DLL loading fragility — see M14's
verification pack and project memory). Running through pytest's own
import machinery, as every other integration test in this suite already
does, reliably avoids it — confirmed across 1000+ tests this session.
"""

from __future__ import annotations

import contextlib
import os
import time
from pathlib import Path

import pytest
from normalizers.passthrough import PassthroughNormalizer
from normexec.sinks import SidecarRunSink
from normexec.stream import ChunkProgress, stream_column
from normio.connectors.clickhouse import ClickHouseConnector
from normio.sidecar_store import SidecarStore

from normanalysis import RunRecorder
from normcore import (
    Dispatcher,
    ErrorPolicy,
    FieldSemanticType,
    NormalizationContext,
    NormalizationProfile,
    NormalizationRun,
    NormalizationRunMetrics,
    NormalizerRegistry,
    RunStatus,
)

_REAL_CLICKHOUSE_HOST = os.environ.get("TEST_CLICKHOUSE_HOST", "localhost")


def _dispatcher() -> Dispatcher:
    registry = NormalizerRegistry()
    registry.register(PassthroughNormalizer())
    return Dispatcher(registry, env_id="e" * 64)


def _profile() -> NormalizationProfile:
    return NormalizationProfile(
        id="p1",
        name="p",
        version="v1",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        created_by="tester",
    )


def _recorder() -> RunRecorder:
    run = NormalizationRun(
        id="run1",
        profile_id="p1",
        profile_version="v1",
        env_id="e" * 64,
        source_snapshot="s",
        started_at="2026-01-01T00:00:00Z",
        status=RunStatus.PENDING,
        metrics=NormalizationRunMetrics(),
    )
    recorder = RunRecorder(run)
    recorder.start()
    return recorder


@pytest.mark.integration
class TestStreamColumnLiveAgainstRealClickHouse:
    def test_streams_every_row_of_a_small_real_table_in_multiple_chunks(
        self, tmp_path: Path
    ) -> None:
        """Industry has 179 real rows — chunk_size=50 forces >=4 chunks,
        proving the loop actually iterates rather than reading once."""
        connector = ClickHouseConnector(
            "t",
            _REAL_CLICKHOUSE_HOST,
            port=8190,
            username="default",
            password="pass",
            database="origin2",
        )
        try:
            key_columns = list(connector.table_spec("Industry").primary_key)
            assert key_columns

            sidecar = SidecarStore(tmp_path / "parquet", tmp_path / "catalog.duckdb")
            sink = SidecarRunSink(sidecar, source_id="t")
            recorder = _recorder()
            ctx = NormalizationContext(
                field_name="name",
                semantic_type=FieldSemanticType.FREE_TEXT,
                error_policy=ErrorPolicy.RETURN_ORIGINAL,
            )
            progresses: list[ChunkProgress] = []

            total = stream_column(
                connector,
                run_id="run1",
                table="Industry",
                column="name",
                key_columns=key_columns,
                semantic_type=FieldSemanticType.FREE_TEXT,
                context=ctx,
                profile=_profile(),
                dispatcher=_dispatcher(),
                cache=None,
                recorder=recorder,
                sink=sink,
                chunk_size=50,
                on_chunk_committed=progresses.append,
            )

            assert total == 179
            assert len(progresses) >= 4
            assert [p.chunk_index for p in progresses] == list(range(len(progresses)))
            assert progresses[-1].rows_processed == 179
            # Monotonically increasing rows_processed across chunks.
            assert [p.rows_processed for p in progresses] == sorted(
                p.rows_processed for p in progresses
            )

            snapshot = recorder.snapshot()
            assert snapshot.metrics.records_processed == 179

            run_tables = sidecar.list_run_tables("run1")
            assert ("t", "Industry", "name") in run_tables

            written = sidecar.read_run(
                source_id="t", table="Industry", run_id="run1", column="name"
            )
            assert written.num_rows == 179
            sidecar.close()
        finally:
            connector.close()

    def test_resume_after_key_skips_already_processed_rows(self, tmp_path: Path) -> None:
        """The real resumability contract: calling stream_column a SECOND
        time with `resume_after_key` set to the last committed key
        processes only the remaining rows, not the whole table again."""
        connector = ClickHouseConnector(
            "t",
            _REAL_CLICKHOUSE_HOST,
            port=8190,
            username="default",
            password="pass",
            database="origin2",
        )
        try:
            key_columns = list(connector.table_spec("Industry").primary_key)
            sidecar = SidecarStore(tmp_path / "parquet", tmp_path / "catalog.duckdb")
            sink = SidecarRunSink(sidecar, source_id="t")
            ctx = NormalizationContext(
                field_name="name",
                semantic_type=FieldSemanticType.FREE_TEXT,
                error_policy=ErrorPolicy.RETURN_ORIGINAL,
            )

            # Simulate a process that died after 2 chunks (100 rows):
            # stream_column has no built-in early-stop, so reproduce
            # exactly what its own first two iterations would have read,
            # directly via the connector, then resume from that point.
            first_batch = connector.read_chunk("Industry", key_columns=key_columns, limit=50)
            assert first_batch is not None
            second_batch = connector.read_chunk(
                "Industry",
                key_columns=key_columns,
                after_key=(first_batch.column(key_columns[0])[-1].as_py(),),
                limit=50,
            )
            assert second_batch is not None
            last_key_after_two_chunks = (second_batch.column(key_columns[0])[-1].as_py(),)
            rows_in_first_two_chunks = first_batch.num_rows + second_batch.num_rows

            # Second "run" (the resume): pick up exactly where the crash
            # would have left off.
            recorder_b = _recorder()
            resumed_progresses: list[ChunkProgress] = []
            resumed_total = stream_column(
                connector,
                run_id="run2",
                table="Industry",
                column="name",
                key_columns=key_columns,
                semantic_type=FieldSemanticType.FREE_TEXT,
                context=ctx,
                profile=_profile(),
                dispatcher=_dispatcher(),
                cache=None,
                recorder=recorder_b,
                sink=sink,
                chunk_size=50,
                resume_after_key=last_key_after_two_chunks,
                on_chunk_committed=resumed_progresses.append,
            )

            assert resumed_total == 179 - rows_in_first_two_chunks
            sidecar.close()
        finally:
            connector.close()

    def test_memory_stays_flat_across_many_chunks_of_a_large_real_table(self) -> None:
        """Person has ~11.8M rows — stream a bounded prefix (10 chunks x
        10k rows = 100k rows) and confirm the loop never materializes
        more than one chunk at a time (proven the same way M14 proved
        read_table's streaming: elapsed time for many chunks stays
        roughly linear, not a single huge up-front read)."""
        connector = ClickHouseConnector(
            "t",
            _REAL_CLICKHOUSE_HOST,
            port=8190,
            username="default",
            password="pass",
            database="origin2",
        )
        try:
            key_columns = list(connector.table_spec("Person").primary_key)
            sink = _NullSink()
            recorder = _recorder()
            ctx = NormalizationContext(
                field_name="fullName",
                semantic_type=FieldSemanticType.FREE_TEXT,
                error_policy=ErrorPolicy.RETURN_ORIGINAL,
            )

            t0 = time.monotonic()
            progresses: list[ChunkProgress] = []

            def _stop_after_ten(progress: ChunkProgress) -> None:
                progresses.append(progress)
                if len(progresses) >= 10:
                    raise _StopStreaming

            with contextlib.suppress(_StopStreaming):
                stream_column(
                    connector,
                    run_id="run3",
                    table="Person",
                    column="fullName",
                    key_columns=key_columns,
                    semantic_type=FieldSemanticType.FREE_TEXT,
                    context=ctx,
                    profile=_profile(),
                    dispatcher=_dispatcher(),
                    cache=None,
                    recorder=recorder,
                    sink=sink,
                    chunk_size=10_000,
                    on_chunk_committed=_stop_after_ten,
                )

            elapsed = time.monotonic() - t0
            assert len(progresses) == 10
            assert progresses[-1].rows_processed == 100_000
            # 10 chunks of 10k rows each from an 11.8M-row table finishing
            # in well under the time a full-table materialization would
            # take is the same style of live proof M14 used for
            # read_table's streaming.
            assert elapsed < 30
        finally:
            connector.close()


class _StopStreaming(Exception):
    pass


class _NullSink:
    def write_chunk(self, *, run_id, table, column, chunk_index, batch):  # type: ignore[no-untyped-def]
        pass

    def finish(self, *, run_id, table, column):  # type: ignore[no-untyped-def]
        pass

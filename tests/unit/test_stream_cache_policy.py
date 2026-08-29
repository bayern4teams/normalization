"""`normexec.stream.stream_column`'s cardinality-aware cache policy wiring
— Phase 3 item 2 (2026-08-29 throughput/memory program). Uses a minimal
fake `StreamingSourceConnector` (with or without the optional
`CardinalitySamplingConnector` capability) so these run as real unit
tests, not against live ClickHouse — `tests/integration/test_stream_column.py`
covers the real-connector path end to end.
"""

from __future__ import annotations

from typing import Any

import pyarrow as pa
import pytest
from normalizers.passthrough import PassthroughNormalizer
from normexec.stream import stream_column

from normanalysis import RunRecorder
from normcore import (
    Dispatcher,
    FieldSemanticType,
    NormalizationContext,
    NormalizationProfile,
    NormalizationRun,
    NormalizationRunMetrics,
    NormalizerRegistry,
    RunStatus,
)
from normexec import NormalizationCache


class _CountingNormalizer(PassthroughNormalizer):
    def __init__(self) -> None:
        self.call_count = 0

    def normalize(self, value, ctx):  # type: ignore[no-untyped-def]
        self.call_count += 1
        return super().normalize(value, ctx)


class _FakeConnector:
    """Chunks are a fixed, pre-baked list of value-lists — `read_chunk`
    ignores `after_key`/pagination entirely and just serves them in order,
    which is all `stream_column` needs from a connector (it never
    inspects the key values themselves, only rebuilds `after_key` from
    the last row of each returned batch)."""

    def __init__(self, chunks: list[list[str | None]]) -> None:
        self._chunks = chunks
        self.calls = 0

    def read_chunk(
        self,
        table: str,
        *,
        key_columns: list[str],
        columns: list[str] | None = None,
        after_key: tuple[object, ...] | None = None,
        limit: int = 100_000,
        since: object | None = None,
    ) -> pa.RecordBatch | None:
        if self.calls >= len(self._chunks):
            return None
        values = self._chunks[self.calls]
        self.calls += 1
        n = len(values)
        arrays: list[pa.Array] = [pa.array(values, type=pa.large_string())]
        names = ["value"]
        for key_column in key_columns:
            arrays.append(pa.array(list(range(n)), type=pa.int64()))
            names.append(key_column)
        arrays.append(pa.array([str(i) for i in range(n)], type=pa.large_string()))
        names.append("source_row_key")
        return pa.RecordBatch.from_arrays(arrays, names=names)


class _FakeConnectorWithEstimate(_FakeConnector):
    def __init__(self, chunks: list[list[str | None]], *, distinct_ratio: float | None) -> None:
        super().__init__(chunks)
        self._distinct_ratio = distinct_ratio
        self.estimate_calls = 0

    def estimate_distinct_ratio(self, table: str, column: str) -> float | None:
        self.estimate_calls += 1
        return self._distinct_ratio


class _FakeSink:
    def __init__(self) -> None:
        self.chunks: list[pa.RecordBatch] = []

    def write_chunk(
        self, *, run_id: str, table: str, column: str, chunk_index: int, batch: pa.RecordBatch
    ) -> None:
        self.chunks.append(batch)

    def finish(self, *, run_id: str, table: str, column: str) -> None:
        pass


def _profile() -> NormalizationProfile:
    return NormalizationProfile(
        id="p1",
        name="test",
        version="v1",
        created_at="2026-08-29T00:00:00Z",
        updated_at="2026-08-29T00:00:00Z",
        created_by="test",
    )


def _ctx() -> NormalizationContext:
    return NormalizationContext(field_name="value", semantic_type=FieldSemanticType.FREE_TEXT)


def _recorder() -> RunRecorder:
    run = NormalizationRun(
        id="r1",
        profile_id="p1",
        profile_version="v1",
        env_id="e" * 64,
        source_snapshot="s1",
        started_at="2026-08-29T00:00:00Z",
        status=RunStatus.PENDING,
        metrics=NormalizationRunMetrics(),
    )
    recorder = RunRecorder(run)
    recorder.start()
    return recorder


def _run_stream(connector: Any, *, cache: NormalizationCache | None) -> tuple[RunRecorder, int]:
    normalizer = _CountingNormalizer()
    registry = NormalizerRegistry()
    registry.register(normalizer)
    dispatcher = Dispatcher(registry, env_id="e" * 64)
    recorder = _recorder()
    sink = _FakeSink()

    stream_column(
        connector,
        run_id="r1",
        table="t",
        column="value",
        key_columns=["id"],
        semantic_type=FieldSemanticType.FREE_TEXT,
        context=_ctx(),
        profile=_profile(),
        dispatcher=dispatcher,
        cache=cache,
        recorder=recorder,
        sink=sink,
    )
    return recorder, normalizer.call_count


@pytest.mark.unit
class TestStreamColumnCachePolicy:
    def test_no_cache_configured_never_computes_a_policy(self) -> None:
        connector = _FakeConnectorWithEstimate([["a", "b"]], distinct_ratio=0.9)
        recorder, _calls = _run_stream(connector, cache=None)
        assert recorder.snapshot().cache_policy == ()
        assert connector.estimate_calls == 0  # never even asked — no cache to decide about

    def test_connector_estimate_high_cardinality_skips_cross_chunk_reuse(self) -> None:
        # "a" repeats within chunk 0 (structurally deduped regardless of
        # cache) AND across chunk 0/1 (only deduped if the cache is on).
        connector = _FakeConnectorWithEstimate(
            [["a", "b", "a"], ["a", "c"]], distinct_ratio=0.9
        )
        with NormalizationCache(":memory:") as cache:
            recorder, calls = _run_stream(connector, cache=cache)

        policy = recorder.snapshot().cache_policy
        assert len(policy) == 1
        assert policy[0].source == "connector_estimate"
        assert policy[0].use_cache is False
        assert policy[0].distinct_ratio == 0.9
        # No cross-chunk reuse: chunk 0 -> {a, b} (2 real calls), chunk 1
        # -> {a, c} recomputed since nothing was cached (2 more) = 4.
        assert calls == 4

    def test_connector_estimate_low_cardinality_keeps_cross_chunk_reuse(self) -> None:
        connector = _FakeConnectorWithEstimate(
            [["a", "b", "a"], ["a", "c"]], distinct_ratio=0.1
        )
        with NormalizationCache(":memory:") as cache:
            recorder, calls = _run_stream(connector, cache=cache)

        policy = recorder.snapshot().cache_policy
        assert policy[0].use_cache is True
        # chunk 0 -> {a, b} real (2); chunk 1 -> "a" is a cache hit, only
        # "c" is real (1 more) = 3.
        assert calls == 3

    def test_fallback_samples_the_real_first_chunk_when_no_capability(self) -> None:
        """No `estimate_distinct_ratio` on this connector — chunk 0 always
        uses the cache (undecided), and the decision for chunk 1+ comes
        from chunk 0's own real data: 1 distinct out of 3 values -> a low
        ratio -> keep caching."""
        connector = _FakeConnector([["a", "a", "a"], ["a", "b"]])
        with NormalizationCache(":memory:") as cache:
            recorder, calls = _run_stream(connector, cache=cache)

        policy = recorder.snapshot().cache_policy
        assert len(policy) == 1
        assert policy[0].source == "first_chunk_sample"
        assert policy[0].distinct_ratio == pytest.approx(1 / 3)
        assert policy[0].use_cache is True
        # chunk 0: 1 real call ("a", cache used from the start). chunk 1:
        # "a" is a cache hit, only "b" is real = 1 more. Total 2.
        assert calls == 2

    def test_fallback_high_cardinality_first_chunk_skips_later_chunks(self) -> None:
        connector = _FakeConnector([["a", "b", "c"], ["a", "d"]])
        with NormalizationCache(":memory:") as cache:
            recorder, calls = _run_stream(connector, cache=cache)

        policy = recorder.snapshot().cache_policy
        assert policy[0].source == "first_chunk_sample"
        assert policy[0].distinct_ratio == 1.0
        assert policy[0].use_cache is False
        # chunk 0: 3 real calls (a, b, c — cache used for this chunk only,
        # but nothing repeats within it). chunk 1: cache now skipped, so
        # "a" is recomputed even though it was already seen -> 2 more.
        assert calls == 5

    def test_fallback_empty_first_chunk_retries_on_the_next_chunk(self) -> None:
        connector = _FakeConnector([[None, None], ["a", "a", "b"]])
        with NormalizationCache(":memory:") as cache:
            recorder, _calls = _run_stream(connector, cache=cache)

        policy = recorder.snapshot().cache_policy
        assert len(policy) == 1
        assert policy[0].distinct_ratio == pytest.approx(2 / 3)

"""Proves RunRecorder's counting and state-transition logic."""

from __future__ import annotations

import pytest

from normanalysis import InvalidRunTransitionError, RunRecorder
from normcore import (
    FieldSemanticType,
    NormalizationRun,
    NormalizationStatus,
    NormalizedValue,
    Reversibility,
    RunStatus,
    TraceStep,
)


def _result(
    status: NormalizationStatus = NormalizationStatus.NORMALIZED,
    *,
    library_steps: int = 0,
) -> NormalizedValue:
    trace = [
        TraceStep(
            step_order=i,
            rule_id="r",
            operation="op",
            params_hash="a" * 8,
            input_hash="b" * 8,
            output_hash="c" * 8,
            input_mask="m",
            output_mask="m",
            changed=True,
            lossy=False,
            reversibility=Reversibility.LOSSLESS,
            library="some-lib",
        )
        for i in range(library_steps)
    ]
    return NormalizedValue(
        original="x",
        normalization_status=status,
        profile_version="v1",
        env_id="e" * 64,
        semantic_type=FieldSemanticType.PERSON_NAME,
        context_hash="c" * 64,
        trace=trace,
    )


def _pending_run() -> NormalizationRun:
    return NormalizationRun(
        id="run1",
        profile_id="p1",
        profile_version="v1",
        env_id="e" * 64,
        source_snapshot="snap1",
        started_at="2026-08-17T00:00:00Z",
        status=RunStatus.PENDING,
    )


@pytest.mark.unit
def test_construction_requires_pending_status() -> None:
    running_run = _pending_run().model_copy(update={"status": RunStatus.RUNNING})
    with pytest.raises(InvalidRunTransitionError):
        RunRecorder(running_run)


@pytest.mark.unit
def test_start_transitions_to_running() -> None:
    recorder = RunRecorder(_pending_run())
    started = recorder.start()
    assert started.status is RunStatus.RUNNING


@pytest.mark.unit
def test_counters_accumulate_correctly() -> None:
    recorder = RunRecorder(_pending_run())
    recorder.start()

    recorder.record_field()
    recorder.record_field()
    recorder.record_value(changed=True)
    recorder.record_value(changed=True)
    recorder.record_value(changed=False)
    recorder.record_cache(hit=True)
    recorder.record_cache(hit=True)
    recorder.record_cache(hit=False)
    recorder.record_warning()
    recorder.record_error()
    recorder.record_error()

    snapshot = recorder.snapshot()
    assert snapshot.metrics.fields_processed == 2
    assert snapshot.metrics.records_processed == 3
    assert snapshot.metrics.changed_values == 2
    assert snapshot.metrics.unchanged_values == 1
    assert snapshot.metrics.cache_hits == 2
    assert snapshot.metrics.cache_misses == 1
    assert snapshot.metrics.warnings == 1
    assert snapshot.metrics.errors == 2
    assert snapshot.status is RunStatus.RUNNING  # snapshot() never changes status
    assert snapshot.finished_at is None


@pytest.mark.unit
def test_record_value_counts_parser_and_validation_failures_by_status() -> None:
    recorder = RunRecorder(_pending_run())
    recorder.start()

    recorder.record_value(changed=True, status=NormalizationStatus.FAILED)
    recorder.record_value(changed=True, status=NormalizationStatus.FAILED)
    recorder.record_value(changed=True, status=NormalizationStatus.INVALID)
    recorder.record_value(changed=False, status=NormalizationStatus.UNCHANGED)
    recorder.record_value(changed=True)  # status omitted -> neither counter increments

    snapshot = recorder.snapshot()
    assert snapshot.metrics.parser_failures == 2
    assert snapshot.metrics.validation_failures == 1
    assert snapshot.metrics.records_processed == 5


@pytest.mark.unit
def test_record_computation_feeds_latency_and_library_call_metrics() -> None:
    recorder = RunRecorder(_pending_run())
    recorder.start()

    recorder.record_computation("a", _result(library_steps=2), 0.010)
    recorder.record_computation("b", _result(library_steps=1), 0.020)
    recorder.record_computation("c", _result(library_steps=0), 0.030)

    snapshot = recorder.snapshot()
    assert snapshot.metrics.library_calls == 3  # 2 + 1 + 0
    assert snapshot.metrics.avg_latency_ms == pytest.approx(20.0)
    # 3 samples -> nearest-rank p95/p99 both resolve to the slowest sample
    assert snapshot.metrics.p95_latency_ms == pytest.approx(30.0)
    assert snapshot.metrics.p99_latency_ms == pytest.approx(30.0)


@pytest.mark.unit
def test_snapshot_computes_rows_per_second_from_real_elapsed_time() -> None:
    recorder = RunRecorder(_pending_run())
    recorder.start()
    recorder.record_value(changed=False)
    recorder.record_value(changed=False)

    snapshot = recorder.snapshot()
    assert snapshot.metrics.duration_seconds > 0
    assert snapshot.metrics.rows_per_second == pytest.approx(2 / snapshot.metrics.duration_seconds)


@pytest.mark.unit
def test_cache_hit_ratio_is_computed_from_hits_and_misses() -> None:
    recorder = RunRecorder(_pending_run())
    recorder.start()
    recorder.record_cache(hit=True)
    recorder.record_cache(hit=True)
    recorder.record_cache(hit=True)
    recorder.record_cache(hit=False)

    snapshot = recorder.snapshot()
    assert snapshot.metrics.cache_hit_ratio == pytest.approx(0.75)


@pytest.mark.unit
def test_cache_hit_ratio_is_zero_with_no_cache_activity() -> None:
    recorder = RunRecorder(_pending_run())
    recorder.start()
    snapshot = recorder.snapshot()
    assert snapshot.metrics.cache_hit_ratio == 0.0


@pytest.mark.unit
def test_finish_requires_terminal_status() -> None:
    recorder = RunRecorder(_pending_run())
    recorder.start()
    with pytest.raises(InvalidRunTransitionError):
        recorder.finish(RunStatus.RUNNING)
    with pytest.raises(InvalidRunTransitionError):
        recorder.finish(RunStatus.PENDING)


@pytest.mark.unit
def test_finish_sets_finished_at_and_final_status() -> None:
    recorder = RunRecorder(_pending_run())
    recorder.start()
    recorder.record_value(changed=True)

    final = recorder.finish(RunStatus.COMPLETED)
    assert final.status is RunStatus.COMPLETED
    assert final.finished_at is not None
    assert final.metrics.records_processed == 1


@pytest.mark.unit
def test_historical_run_never_mutated_in_place() -> None:
    """Every NormalizationRun object RunRecorder has ever returned stays
    exactly as it was — proving the "immutable, never edited in place"
    guarantee (ADR-014) actually holds for run tracking, not just profiles.
    """
    recorder = RunRecorder(_pending_run())
    started = recorder.start()
    recorder.record_value(changed=True)
    later_snapshot = recorder.snapshot()

    assert started.metrics.records_processed == 0  # untouched by the later record_value() call
    assert later_snapshot.metrics.records_processed == 1
    assert started is not later_snapshot

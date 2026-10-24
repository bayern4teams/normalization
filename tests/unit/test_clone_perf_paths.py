"""Covers the four clone-path performance changes, each of which can
silently regress into "still correct, just slow again" — or, for the
parallel path, into "different answers than serial".
"""

from __future__ import annotations

import pickle

import pytest
from normalizers.address import AddressNormalizer, LibpostalUnavailableError
from normapi.app import build_normalizer_registry
from normapi.scaffold_profile import SCAFFOLD_PROFILE
from normexec.planner import DistinctValuePlanner

from normapi import clone_executor
from normcore import Dispatcher, FieldSemanticType, NormalizationContext


@pytest.fixture(scope="module")
def dispatcher() -> Dispatcher:
    return Dispatcher(build_normalizer_registry(), env_id="test-env")


def _ctx(semantic_type: FieldSemanticType, **kw: object) -> NormalizationContext:
    return NormalizationContext(field_name="f", semantic_type=semantic_type, **kw)


# --- (a) trace suppression ------------------------------------------------


def test_include_trace_false_skips_the_unicode_trace(dispatcher: Dispatcher) -> None:
    st = FieldSemanticType.COMPANY_NAME
    with_trace = dispatcher.normalize("Acme Widgets Inc", st, _ctx(st), SCAFFOLD_PROFILE)
    without = dispatcher.normalize(
        "Acme Widgets Inc", st, _ctx(st, include_trace=False), SCAFFOLD_PROFILE
    )
    assert len(with_trace.trace) > len(without.trace)
    # The normalized OUTPUT must not depend on whether we recorded how we
    # got there — that is the whole premise of turning the trace off.
    assert without.display == with_trace.display
    assert without.errors == with_trace.errors
    assert without.normalization_status == with_trace.normalization_status


def test_include_trace_changes_the_context_hash() -> None:
    st = FieldSemanticType.COMPANY_NAME
    # Different output shape => must never share a cache key.
    assert _ctx(st).context_hash != _ctx(st, include_trace=False).context_hash


def test_context_hash_is_cached_but_still_correct() -> None:
    st = FieldSemanticType.COMPANY_NAME
    ctx = _ctx(st, table="T")
    assert ctx.context_hash == ctx.context_hash
    # Caching must not leak into serialization, pickling, or value identity.
    assert "context_hash" not in ctx.model_dump()
    assert pickle.loads(pickle.dumps(ctx)).context_hash == ctx.context_hash
    assert _ctx(st, table="T").context_hash == ctx.context_hash
    assert _ctx(st, table="OTHER").context_hash != ctx.context_hash


# --- (c) batched libpostal ------------------------------------------------


class _RecordingParser:
    """Counts round-trips so a regression to per-value HTTP is visible."""

    def __init__(self, *, batch: bool) -> None:
        self.single_calls = 0
        self.batch_calls = 0
        if batch:
            # C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
            self.parse_many = self._parse_many  # type: ignore[method-assign]

    def parse(self, address: str) -> list[tuple[str, str]]:
        self.single_calls += 1
        return [(address.split(maxsplit=1)[0], "road")]

    def _parse_many(self, addresses: list[str]) -> list[list[tuple[str, str]]]:
        self.batch_calls += 1
        return [[(a.split(maxsplit=1)[0], "road")] for a in addresses]


def _address_results(parser: _RecordingParser, values: list[str]) -> dict[str, object]:
    registry = build_normalizer_registry()
    registry.register(AddressNormalizer(parser))
    planner = DistinctValuePlanner(Dispatcher(registry, env_id="test-env"), None)
    st = FieldSemanticType.ADDRESS
    return planner.distinct_value_results(values, st, _ctx(st), SCAFFOLD_PROFILE)


def test_batch_capable_parser_makes_one_round_trip_for_the_whole_column() -> None:
    values = [f"{i} Main Street Springfield" for i in range(25)]
    parser = _RecordingParser(batch=True)
    results = _address_results(parser, values)
    assert parser.batch_calls == 1
    assert parser.single_calls == 0
    assert len(results) == len(values)


def test_parser_without_parse_many_still_works_per_value() -> None:
    values = [f"{i} Main Street Springfield" for i in range(5)]
    parser = _RecordingParser(batch=False)
    results = _address_results(parser, values)
    assert parser.single_calls == len(values)
    assert len(results) == len(values)


def test_batch_and_per_value_paths_agree() -> None:
    values = [f"{i} Main Street Springfield" for i in range(5)]
    batched = _address_results(_RecordingParser(batch=True), values)
    per_value = _address_results(_RecordingParser(batch=False), values)
    assert {k: v.display for k, v in batched.items()} == {
        k: v.display for k, v in per_value.items()
    }
    assert {k: v.structured for k, v in batched.items()} == {
        k: v.structured for k, v in per_value.items()
    }


def test_failing_batch_falls_back_instead_of_losing_the_column() -> None:
    class _BrokenBatch(_RecordingParser):
        def _parse_many(self, addresses: list[str]) -> list[list[tuple[str, str]]]:
            self.batch_calls += 1
            msg = "sidecar down"
            raise LibpostalUnavailableError(msg)

    parser = _BrokenBatch(batch=True)
    results = _address_results(parser, [f"{i} Main Street" for i in range(3)])
    # Every value still gets a result; none of them raise.
    assert len(results) == 3


# --- (b) parallel path ----------------------------------------------------


def test_parallel_and_serial_produce_identical_results(dispatcher: Dispatcher) -> None:
    st = FieldSemanticType.COMPANY_NAME
    ctx = _ctx(st, include_trace=False)
    values = [f"Company Number {i} Inc" for i in range(600)]
    planner = DistinctValuePlanner(dispatcher, None)

    serial = clone_executor._normalize_distinct(
        None, planner, values, semantic_type=st, context=ctx, profile=SCAFFOLD_PROFILE
    )
    pool = clone_executor._make_pool(dispatcher.env_id)
    if pool is None:  # C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
        pytest.skip("process pool disabled or unavailable in this environment")
    try:
        parallel = clone_executor._normalize_distinct(
            pool, planner, values, semantic_type=st, context=ctx, profile=SCAFFOLD_PROFILE
        )
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    assert set(parallel) == set(serial)
    assert {k: v.display for k, v in parallel.items()} == {k: v.display for k, v in serial.items()}
    assert {k: v.errors for k, v in parallel.items()} == {k: v.errors for k, v in serial.items()}


def test_small_batch_stays_serial_and_dead_pool_degrades_not_fails(
    dispatcher: Dispatcher,
) -> None:
    st = FieldSemanticType.COMPANY_NAME
    ctx = _ctx(st, include_trace=False)
    planner = DistinctValuePlanner(dispatcher, None)

    class _DeadPool:
        _max_workers = 2

        def map(self, *_args: object, **_kw: object) -> object:
            msg = "pool is gone"
            raise OSError(msg)

    # Under the threshold: never touches the pool at all.
    small = [f"Small Co {i} Inc" for i in range(10)]
    got = clone_executor._normalize_distinct(
        _DeadPool(), planner, small, semantic_type=st, context=ctx, profile=SCAFFOLD_PROFILE
    )
    assert len(got) == len(small)

    # Over the threshold with a broken pool: degrades to serial, still complete.
    big = [f"Big Co {i} Inc" for i in range(clone_executor._PARALLEL_MIN_VALUES + 5)]
    got = clone_executor._normalize_distinct(
        _DeadPool(), planner, big, semantic_type=st, context=ctx, profile=SCAFFOLD_PROFILE
    )
    assert len(got) == len(big)

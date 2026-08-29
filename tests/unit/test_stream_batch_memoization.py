"""`normexec.stream._results_to_batch` — Phase 2 (2026-08-29 throughput
program) memoized `normalized_value_to_arrow_row` on `id(result)`,
since `DistinctValuePlanner.normalize_values` resolves duplicate rows
back to the SAME `NormalizedValue` object by reference
(`packages/normexec/src/normexec/planner.py:174`). These tests prove
both halves: the memoization actually skips redundant recomputation
(not just "happens to produce the same output"), and the output is
identical to calling `normalized_value_to_arrow_row` fresh per row.
"""

from __future__ import annotations

import pyarrow as pa
import pytest
from normcore.contract import normalized_value_to_arrow_row
from normexec.stream import _results_to_batch

from normcore import FieldSemanticType, NormalizationStatus, NormalizedValue
from normexec import stream as stream_module


def _value(display: str) -> NormalizedValue:
    return NormalizedValue(
        original=display,
        display=display,
        normalization_status=NormalizationStatus.UNCHANGED,
        profile_version="v1",
        env_id="e" * 64,
        semantic_type=FieldSemanticType.FREE_TEXT,
        context_hash="c" * 16,
    )


def _source_batch(keys: list[str]) -> pa.RecordBatch:
    return pa.RecordBatch.from_arrays(
        [pa.array(keys, type=pa.large_string())], names=["source_row_key"]
    )


@pytest.mark.unit
class TestResultsToBatchMemoization:
    def test_duplicate_object_references_are_only_serialized_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        shared_a = _value("John")
        shared_b = _value("Jane")
        # 5 rows, only 2 distinct NormalizedValue OBJECTS (by reference) —
        # exactly the shape DistinctValuePlanner.normalize_values produces.
        results = [shared_a, shared_b, shared_a, shared_a, shared_b]

        call_count = 0

        def _counting(value: NormalizedValue) -> dict[str, object]:
            nonlocal call_count
            call_count += 1
            return normalized_value_to_arrow_row(value)

        monkeypatch.setattr(stream_module, "normalized_value_to_arrow_row", _counting)

        batch = _results_to_batch(_source_batch([str(i) for i in range(5)]), results)

        assert call_count == 2  # once per distinct OBJECT, not once per row
        assert batch.num_rows == 5
        assert batch.column("display").to_pylist() == ["John", "Jane", "John", "John", "Jane"]

    def test_output_is_identical_to_serializing_every_row_fresh(self) -> None:
        shared_a = _value("John")
        shared_b = _value("Jane")
        results = [shared_a, shared_b, shared_a]
        source_keys = ["1", "2", "3"]

        memoized = _results_to_batch(_source_batch(source_keys), results)

        fresh_rows = [normalized_value_to_arrow_row(r) for r in results]
        for i, expected_row in enumerate(fresh_rows):
            for field_name, expected_value in expected_row.items():
                assert memoized.column(field_name)[i].as_py() == expected_value
        assert memoized.column("source_row_key").to_pylist() == source_keys

    def test_distinct_objects_with_equal_content_are_not_conflated(self) -> None:
        """Memoizing on id(), not value equality — two genuinely distinct
        NormalizedValue objects that happen to carry identical content
        must each still be represented correctly (this would only be a
        bug if the memoization accidentally kept a stale row keyed by a
        recycled id, which it cannot: `results` holds every object live
        for the whole call — see the function's own docstring)."""
        obj_a = _value("Same")
        obj_b = _value("Same")  # different object, equal content
        assert obj_a is not obj_b

        batch = _results_to_batch(_source_batch(["1", "2"]), [obj_a, obj_b])
        assert batch.column("display").to_pylist() == ["Same", "Same"]

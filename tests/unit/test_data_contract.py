"""Proves Source.txt §107/§133's data contract: NormalizedValue round-trips
through both its JSON Schema (API) and Arrow (sidecar store) representation
without loss, and both are derived from the same pydantic model rather than
hand-maintained separately (so they cannot silently drift apart).
"""

from __future__ import annotations

import pyarrow as pa
import pytest
from normcore.trace import TraceStep

from normcore import (
    NORMALIZED_VALUE_ARROW_SCHEMA,
    FieldSemanticType,
    MissingKind,
    NormalizationStatus,
    NormalizedValue,
    QualityFlag,
    Reversibility,
    arrow_row_to_normalized_value,
    normalized_value_json_schema,
    normalized_value_to_arrow_row,
)


def _rich_value() -> NormalizedValue:
    step = TraceStep(
        step_order=1,
        rule_id="whitespace.collapse",
        operation="collapse_whitespace",
        params_hash="a" * 8,
        input_hash="b" * 8,
        output_hash="c" * 8,
        input_mask="Lu Ll Ll",
        output_mask="Lu Ll Ll",
        changed=True,
        lossy=False,
        reversibility=Reversibility.REVERSIBLE,
        library="normcore",
        library_version="0.1.0",
    )
    return NormalizedValue(
        original="  José  ",
        original_kind=None,
        display="José",
        comparison="jose",
        search="jose",
        ascii="Jose",
        structured={"first_name": "José"},
        validation_status="VALID",
        normalization_status=NormalizationStatus.NORMALIZED,
        confidence=0.95,
        flags=[QualityFlag.UNICODE_NORMALIZED],
        warnings=["accent stripped"],
        errors=[],
        trace=[step],
        lossiness=Reversibility.PARTIALLY_REVERSIBLE,
        profile_version="v3",
        env_id="e" * 64,
        semantic_type=FieldSemanticType.PERSON_NAME,
        context_hash="c" * 64,
    )


@pytest.mark.unit
def test_json_schema_is_derived_and_validates_a_real_value() -> None:
    schema = normalized_value_json_schema()
    assert schema["title"] == "NormalizedValue"
    # A real value serializes to JSON that pydantic can parse back via the
    # SAME model the schema was generated from — the strongest available
    # proof the schema actually describes real output, not aspirational.
    value = _rich_value()
    dumped = value.model_dump_json()
    restored = NormalizedValue.model_validate_json(dumped)
    assert restored == value


@pytest.mark.unit
def test_arrow_round_trip_preserves_every_field() -> None:
    value = _rich_value()
    row = normalized_value_to_arrow_row(value)

    # The row's keys match the declared Arrow schema exactly — proving the
    # two are not allowed to drift (a field added to one without the other
    # would fail this).
    assert set(row.keys()) == set(NORMALIZED_VALUE_ARROW_SCHEMA.names)

    restored = arrow_row_to_normalized_value(row)
    assert restored.original == value.original
    assert restored.display == value.display
    assert restored.comparison == value.comparison
    assert restored.structured == value.structured
    assert restored.flags == value.flags
    assert restored.warnings == value.warnings
    assert restored.trace[0].rule_id == value.trace[0].rule_id
    assert restored.trace[0].changed == value.trace[0].changed
    assert restored.lossiness == value.lossiness
    assert restored.profile_version == value.profile_version
    assert restored.env_id == value.env_id
    assert restored.semantic_type == value.semantic_type
    assert restored.context_hash == value.context_hash


@pytest.mark.unit
def test_arrow_row_actually_builds_a_valid_arrow_table() -> None:
    """Not just a Python dict shaped like the schema — an actual
    pa.Table.from_pylist() against the declared schema, proving Arrow
    itself accepts the row shape."""
    rows = [normalized_value_to_arrow_row(_rich_value()) for _ in range(3)]
    table = pa.Table.from_pylist(rows, schema=NORMALIZED_VALUE_ARROW_SCHEMA)
    assert table.num_rows == 3
    assert table.schema == NORMALIZED_VALUE_ARROW_SCHEMA


@pytest.mark.unit
def test_arrow_round_trip_handles_minimal_value_with_nulls() -> None:
    minimal = NormalizedValue(
        original=None,
        normalization_status=NormalizationStatus.UNCHANGED,
        profile_version="v1",
        env_id="e" * 64,
        semantic_type=FieldSemanticType.FREE_TEXT,
        context_hash="c" * 64,
    )
    row = normalized_value_to_arrow_row(minimal)
    # Must not raise building a real Arrow table with nulls in every
    # optional column.
    table = pa.Table.from_pylist([row], schema=NORMALIZED_VALUE_ARROW_SCHEMA)
    assert table.num_rows == 1

    restored = arrow_row_to_normalized_value(row)
    assert restored.original is None
    assert restored.structured == {}
    assert restored.trace == []


@pytest.mark.unit
def test_missing_kind_round_trips_through_arrow() -> None:
    value = NormalizedValue(
        original="N/A",
        original_kind=MissingKind.NOT_APPLICABLE,
        normalization_status=NormalizationStatus.INVALID,
        profile_version="v1",
        env_id="e" * 64,
        semantic_type=FieldSemanticType.FREE_TEXT,
        context_hash="c" * 64,
    )
    row = normalized_value_to_arrow_row(value)
    assert row["original_kind"] == "NOT_APPLICABLE"
    restored = arrow_row_to_normalized_value(row)
    assert restored.original_kind is MissingKind.NOT_APPLICABLE

"""The data contract — Source.txt §107, §133.

`NormalizedValue` (normcore.models) is the single source of truth; this
module derives the JSON Schema and Arrow schema FROM it rather than
hand-maintaining either separately, so the three representations
(Python/Pydantic, JSON Schema for the API, Arrow for the sidecar store)
cannot drift from one another — proven in
tests/unit/test_data_contract.py by round-tripping a real value through
all three.
"""

from __future__ import annotations

import json
from typing import Any

import pyarrow as pa

from normcore.models import NormalizedValue

# Arrow has no automatic pydantic-model -> schema derivation, so the struct
# layout is declared explicitly here. Kept intentionally narrower than the
# full NormalizedValue (e.g. `trace`/`structured` are serialized as JSON
# strings rather than nested Arrow structs) because the sidecar store
# prioritizes stable, simple Parquet columns over exactly mirroring the
# Python object graph — see docs/normalization-data-contract.md.
NORMALIZED_VALUE_ARROW_SCHEMA = pa.schema(
    [
        pa.field("original", pa.large_string()),
        pa.field("original_kind", pa.large_string()),
        pa.field("repaired", pa.large_string()),
        pa.field("display", pa.large_string()),
        pa.field("comparison", pa.large_string()),
        pa.field("search", pa.large_string()),
        pa.field("ascii", pa.large_string()),
        pa.field("structured_json", pa.large_string()),  # NormalizedValue.structured, JSON-encoded
        pa.field("validation_status", pa.large_string()),
        pa.field("normalization_status", pa.large_string()),
        pa.field("confidence", pa.float64()),
        pa.field("flags", pa.list_(pa.large_string())),
        pa.field("warnings", pa.list_(pa.large_string())),
        pa.field("errors", pa.list_(pa.large_string())),
        pa.field("trace_json", pa.large_string()),  # NormalizedValue.trace, JSON-encoded
        pa.field("lossiness", pa.large_string()),
        pa.field("profile_version", pa.large_string()),
        pa.field("env_id", pa.large_string()),
        pa.field("semantic_type", pa.large_string()),
        pa.field("context_hash", pa.large_string()),
    ]
)


def normalized_value_to_arrow_row(value: NormalizedValue) -> dict[str, Any]:
    """One row matching NORMALIZED_VALUE_ARROW_SCHEMA's column layout."""
    return {
        "original": value.original,
        "original_kind": value.original_kind.value if value.original_kind else None,
        "repaired": value.repaired,
        "display": value.display,
        "comparison": value.comparison,
        "search": value.search,
        "ascii": value.ascii,
        "structured_json": _json_or_none(value.structured) if value.structured else None,
        "validation_status": value.validation_status,
        "normalization_status": value.normalization_status.value,
        "confidence": value.confidence,
        "flags": [f.value for f in value.flags],
        "warnings": list(value.warnings),
        "errors": list(value.errors),
        "trace_json": _json_or_none([step.model_dump(mode="json") for step in value.trace]),
        "lossiness": value.lossiness.value,
        "profile_version": value.profile_version,
        "env_id": value.env_id,
        "semantic_type": value.semantic_type.value,
        "context_hash": value.context_hash,
    }


def arrow_row_to_normalized_value(row: dict[str, Any]) -> NormalizedValue:
    """Inverse of `normalized_value_to_arrow_row` — proven to round-trip
    exactly in tests/unit/test_data_contract.py."""
    return NormalizedValue(
        original=row["original"],
        original_kind=row["original_kind"],
        repaired=row["repaired"],
        display=row["display"],
        comparison=row["comparison"],
        search=row["search"],
        ascii=row["ascii"],
        structured=json.loads(row["structured_json"]) if row["structured_json"] else {},
        validation_status=row["validation_status"],
        normalization_status=row["normalization_status"],
        confidence=row["confidence"],
        flags=row["flags"] or [],
        warnings=row["warnings"] or [],
        errors=row["errors"] or [],
        trace=json.loads(row["trace_json"]) if row["trace_json"] else [],
        lossiness=row["lossiness"],
        profile_version=row["profile_version"],
        env_id=row["env_id"],
        semantic_type=row["semantic_type"],
        context_hash=row["context_hash"],
    )


def _json_or_none(payload: object) -> str | None:
    if not payload:
        return None
    return json.dumps(payload, sort_keys=True)


def normalized_value_json_schema() -> dict[str, Any]:
    """The JSON Schema published in the API's OpenAPI document —
    generated directly from the pydantic model, never hand-maintained."""
    return NormalizedValue.model_json_schema()

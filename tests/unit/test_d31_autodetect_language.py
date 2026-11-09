"""D31 (owner "b7. a"): LANGUAGE is confirmed by a language-code validator, only
with a matching column name; NUMERIC and FREE_TEXT are never inferred from values."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Any

import pyarrow as pa
import pytest
from normanalysis.type_detection import suggest_semantic_type
from normapi.app import build_normalizer_registry
from normio.connector import ColumnInfo

from normapi import clone_executor
from normcore import FieldSemanticType, NormalizerRegistry

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit

_TAGS = ["en", "de", "fr-CA", "pt-BR", "es"]


@pytest.fixture(scope="module")
def registry() -> NormalizerRegistry:
    return build_normalizer_registry()


def _top(column: str, values: list[str], registry: NormalizerRegistry) -> tuple[str, float]:
    best = suggest_semantic_type(column, sample_values=values, registry=registry)[0]
    return best.semantic_type.value, best.confidence


def test_a_lang_column_of_valid_tags_reaches_the_apply_line(registry: NormalizerRegistry) -> None:
    semantic_type, confidence = _top("lang", _TAGS, registry)
    assert semantic_type == "LANGUAGE"
    assert confidence >= clone_executor._AUTODETECT_MIN_CONFIDENCE


def test_a_lang_column_of_other_values_stays_below_it(registry: NormalizerRegistry) -> None:
    best = suggest_semantic_type(
        "lang", sample_values=["zzzzzz1", "qq qq", "12345"], registry=registry
    )
    language = next(s for s in best if s.semantic_type is FieldSemanticType.LANGUAGE)
    assert language.confidence < clone_executor._AUTODETECT_MIN_CONFIDENCE


@pytest.mark.parametrize("column", ["code", "status", "slang"])
def test_language_needs_the_column_name(column: str, registry: NormalizerRegistry) -> None:
    candidates = suggest_semantic_type(column, sample_values=_TAGS, registry=registry)
    assert all(
        s.semantic_type is not FieldSemanticType.LANGUAGE
        or s.confidence < clone_executor._AUTODETECT_MIN_CONFIDENCE
        for s in candidates
    )


@pytest.mark.parametrize("column", ["code", "number", "reference"])
def test_leading_zeros_are_not_numeric(column: str, registry: NormalizerRegistry) -> None:
    semantic_type, confidence = _top(column, ["00123", "00456", "00789"], registry)
    assert semantic_type != "NUMERIC" or confidence < clone_executor._AUTODETECT_MIN_CONFIDENCE


def test_the_apply_line_is_still_nine_tenths() -> None:
    assert clone_executor._AUTODETECT_MIN_CONFIDENCE == 0.9


# --- The date rule (owner, 2026-11-09: "(b) native date + text dates") -------


class _Typed:
    def __init__(self, native: dict[str, str], values: dict[str, list[Any]]) -> None:
        self.native, self.values = native, values

    def get_columns(self, table: str) -> list[ColumnInfo]:
        return [ColumnInfo(name=n, native_type=t) for n, t in self.native.items()]

    def get_primary_key(self, table: str) -> list[str]:
        return []

    def read_table(self, table: str, **_: Any) -> Iterator[pa.RecordBatch]:
        yield pa.RecordBatch.from_pydict(self.values)


def _inferred(
    native: dict[str, str], values: dict[str, list[Any]], registry: NormalizerRegistry
) -> dict[str, str]:
    source = _Typed(native, values)
    return clone_executor._infer_field_configs(source, ["t"], {}, registry).get("t", {})


@pytest.mark.parametrize("native", ["date", "Date", "Date32", "Nullable(Date32)"])
def test_a_native_date_column_is_date(native: str, registry: NormalizerRegistry) -> None:
    day = datetime.date(2026, 1, 2)
    assert _inferred({"opened": native}, {"opened": [day]}, registry) == {"opened": "DATE"}


@pytest.mark.parametrize("native", ["timestamp without time zone", "DateTime", "DateTime64(3)"])
def test_a_native_timestamp_stays_skipped(native: str, registry: NormalizerRegistry) -> None:
    stamp = datetime.datetime(2026, 1, 2, 3, 4, 5)
    assert _inferred({"opened": native}, {"opened": [stamp]}, registry) == {}


def test_a_text_column_named_date_of_date_only_values_is_date(
    registry: NormalizerRegistry,
) -> None:
    values = ["2026-01-02", "2025-12-31", "2024-02-29"]
    assert _top("event_date", values, registry)[0] == "DATE"


def test_one_stated_time_keeps_a_text_column_datetime(registry: NormalizerRegistry) -> None:
    values = ["2026-01-02", "2025-12-31 10:30:00", "2024-02-29"]
    assert _top("event_date", values, registry)[0] == "DATETIME"


def test_a_stated_midnight_is_a_time(registry: NormalizerRegistry) -> None:
    values = ["2026-01-02 00:00:00", "2025-12-31 00:00:00"]
    assert _top("event_date", values, registry)[0] == "DATETIME"


def test_date_only_values_without_a_name_match_stay_unnamed(
    registry: NormalizerRegistry,
) -> None:
    values = ["2026-01-02", "2025-12-31", "2024-02-29"]
    assert _top("reference", values, registry)[0] != "DATETIME"

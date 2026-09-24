"""A clone is not limited to the columns somebody remembered to configure.

Before this, any column absent from `field_configs` was copied verbatim, so
clone quality was capped by how exhaustively a config was hand-written. On a
real 13-table source a hand-written config covered 10 columns of 114, and
every boolean, date and URL outside those 10 was cloned unnormalized even
though working normalizers for all three already existed.

The guarantees that make filling those gaps safe are what these tests pin
down: an explicit config always wins, a guess must be confirmed by real
values before it is applied, and whatever was inferred is recorded on the
job rather than applied silently.
"""

from __future__ import annotations

from typing import Any

import pyarrow as pa
import pytest
from normapi.app import build_normalizer_registry
from normio.connector import ColumnInfo

from normapi import clone_executor


class _FakeSource:
    """Just enough connector surface for the inference pass."""

    def __init__(self, columns: dict[str, list[str]], rows: dict[str, list[Any]]) -> None:
        self._columns = columns
        self._rows = rows

    def list_tables(self) -> list[str]:
        return list(self._columns)

    def get_columns(self, table: str) -> list[ColumnInfo]:
        return [ColumnInfo(name=c, native_type="text") for c in self._columns[table]]

    def read_table(self, table: str, *, columns: list[str], batch_size: int = 200):
        yield pa.RecordBatch.from_arrays(
            [pa.array(self._rows[table][self._columns[table].index(c)]) for c in columns],
            names=list(columns),
        )

    def close(self) -> None:
        pass


@pytest.fixture(scope="module")
def registry():
    return build_normalizer_registry()


def _infer(source: _FakeSource, explicit: dict, registry) -> dict:
    return clone_executor._infer_field_configs(
        source, list(source.list_tables()), explicit, registry
    )


def test_unconfigured_columns_get_their_type_detected(registry) -> None:
    source = _FakeSource(
        {"company": ["ispublic", "website", "foundingdate"]},
        {"company": [["False", "True"], ["dish.com", "x.com"], ["1982-01-02", "1970-03-04"]]},
    )
    inferred = _infer(source, {}, registry)
    assert inferred["company"]["ispublic"] == "BOOLEAN"
    assert inferred["company"]["website"] == "URL"
    assert inferred["company"]["foundingdate"] in {"DATE", "DATETIME"}


def test_an_explicit_config_is_never_second_guessed(registry) -> None:
    source = _FakeSource({"company": ["website"]}, {"company": [["dish.com", "x.com"]]})
    inferred = _infer(source, {"company": {"website": "FREE_TEXT"}}, registry)
    assert "company" not in inferred


def test_a_name_that_merely_looks_like_a_type_is_not_enough(registry) -> None:
    # "candidate" contains "date" and "district" contains "is"; neither
    # holds anything a date or boolean normalizer accepts, so the relaxed
    # name match must be demoted below the apply threshold by real values.
    source = _FakeSource(
        {"t": ["candidate", "district"]},
        {"t": [["Alice", "Bob"], ["North", "South"]]},
    )
    assert _infer(source, {}, registry) == {}


def test_prose_columns_are_left_as_passthrough(registry) -> None:
    # FREE_TEXT is the "nothing matched" fallback; applying it would rewrite
    # arbitrary prose in every unconfigured column.
    source = _FakeSource(
        {"t": ["description", "companyid"]},
        {"t": [["Some prose", "More prose"], ["E-24TeCP", "E-8Ee2mQ"]]},
    )
    assert _infer(source, {}, registry) == {}


def test_list_shaped_columns_are_detected_through_the_list(registry) -> None:
    source = _FakeSource({"t": ["freeMails"]}, {"t": [["['a@b.com']", "['c@d.com']"]]})
    assert _infer(source, {}, registry)["t"]["freeMails"] == "EMAIL"


def test_a_column_that_cannot_be_sampled_falls_back_to_the_name_alone(registry) -> None:
    class _Unreadable(_FakeSource):
        def read_table(self, table, *, columns, batch_size=200):
            msg = "no read permission"
            raise RuntimeError(msg)

    source = _Unreadable({"t": ["candidate"]}, {"t": [["Alice"]]})
    # Name-only evidence for a relaxed match stays far below the threshold,
    # so nothing is applied — but job creation must not blow up either.
    assert _infer(source, {}, registry) == {}


def test_columns_the_source_already_types_are_left_alone(registry) -> None:
    # A real timestamp/boolean column has no normalization problem to solve,
    # and configuring one would downgrade the destination column to TEXT.
    class _Typed(_FakeSource):
        def get_columns(self, table: str):
            return [
                ColumnInfo(name="created_at", native_type="timestamp without time zone"),
                ColumnInfo(name="ispublic", native_type="boolean"),
                ColumnInfo(name="website", native_type="text"),
            ]

    source = _Typed(
        {"t": ["created_at", "ispublic", "website"]},
        {"t": [["2026-01-01 00:00:00"], ["true"], ["dish.com"]]},
    )
    inferred = _infer(source, {}, registry)
    assert inferred == {"t": {"website": "URL"}}


def test_clickhouse_style_wrapped_string_types_still_count_as_textual() -> None:
    assert clone_executor._is_textual("Nullable(String)")
    assert clone_executor._is_textual("LowCardinality(String)")
    assert clone_executor._is_textual("character varying(255)")
    assert not clone_executor._is_textual("DateTime64(3)")
    assert not clone_executor._is_textual("UInt8")


def test_free_text_fallback_is_opt_in(registry) -> None:
    source = _FakeSource({"t": ["description"]}, {"t": [["Some prose", "More prose"]]})
    assert _infer(source, {}, registry) == {}
    opted_in = clone_executor._infer_field_configs(
        source, ["t"], {}, registry, fallback_free_text=True
    )
    assert opted_in == {"t": {"description": "FREE_TEXT"}}


def test_free_text_fallback_never_overrides_a_confident_detection(registry) -> None:
    source = _FakeSource({"t": ["website"]}, {"t": [["dish.com", "x.com"]]})
    opted_in = clone_executor._infer_field_configs(
        source, ["t"], {}, registry, fallback_free_text=True
    )
    assert opted_in == {"t": {"website": "URL"}}

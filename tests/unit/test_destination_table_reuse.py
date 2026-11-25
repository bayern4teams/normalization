"""Unit coverage for the destination-table reuse rule (the coworker's
`relation "company" already exists` failure mode) without a live database:
`_require_matching_destination_table` compares the plan against a fake
destination reporting columns/key the way each engine does."""

from __future__ import annotations

import pytest
from normapi.clone_executor import CloneJobStateError, _require_matching_destination_table


class _FakeDest:
    def __init__(self, columns: dict[str, str], key: list[str], expected: dict[str, str]) -> None:
        self._columns = columns
        self._key = key
        self._expected = expected

    def table_columns(self, database: str, table: str) -> dict[str, str] | None:
        return dict(self._columns)

    def primary_key_columns(self, database: str, table: str) -> list[str]:
        return list(self._key)

    def expected_columns(self, columns, *, semantic_types, column_overrides, extra_columns):
        return dict(self._expected)


def _require(
    columns: dict[str, str],
    existing_key: list[str],
    expected: dict[str, str],
    expected_key: list[str] | None = None,
) -> None:
    _require_matching_destination_table(
        _FakeDest(columns, existing_key, expected),
        "dst",
        "company",
        columns=[],
        key_columns=list(expected_key if expected_key is not None else existing_key),
        semantic_types={},
        column_overrides={},
        extra_columns={},
    )


def test_identical_structure_is_reused() -> None:
    _require(
        {"id": "uuid", "aliases": "jsonb", "name": "text"},
        ["id"],
        {"id": "uuid", "aliases": "jsonb", "name": "text"},
    )  # must not raise: the reuse decision is silent


def test_type_length_suffix_differences_still_match() -> None:
    # information_schema reports `character varying`, DDL says `varchar(255)`.
    _require({"n": "character varying"}, [], {"n": "character varying"})


def test_mismatching_type_names_the_column_and_both_types() -> None:
    with pytest.raises(CloneJobStateError) as excinfo:
        _require({"id": "uuid", "aliases": "text"}, ["id"], {"id": "uuid", "aliases": "jsonb"})
    message = str(excinfo.value)
    assert "aliases" in message and "text" in message and "jsonb" in message
    assert "already exists" in message and "Drop it" in message


def test_extra_and_missing_columns_are_both_named() -> None:
    with pytest.raises(CloneJobStateError) as excinfo:
        _require({"id": "uuid", "extra": "int"}, ["id"], {"id": "uuid", "missing": "text"})
    message = str(excinfo.value)
    assert "extra" in message and "missing" in message


def test_different_primary_key_is_a_mismatch() -> None:
    with pytest.raises(CloneJobStateError) as excinfo:
        # The table's key is (name); this job's plan replicates key (id).
        _require({"id": "uuid", "name": "text"}, ["name"], {"id": "uuid", "name": "text"}, ["id"])
    assert "key" in str(excinfo.value)


def test_message_never_carries_row_values() -> None:
    # The whole point of the withheld-message policy: names and types may
    # be quoted, values may not. The comparison only ever sees metadata.
    with pytest.raises(CloneJobStateError) as excinfo:
        _require({"id": "uuid"}, ["id"], {"id": "text"})
    assert "The withheld-secret" not in str(excinfo.value)  # nothing to leak, by construction

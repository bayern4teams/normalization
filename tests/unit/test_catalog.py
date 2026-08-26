"""Unit tests for normio.catalog's value objects (M14)."""

from __future__ import annotations

import pytest
from normio.catalog import ColumnSpec, TableSpec


@pytest.mark.unit
class TestTableSpecPrimaryKey:
    def test_primary_key_returns_only_flagged_columns_in_declared_order(self) -> None:
        spec = TableSpec(
            name="PersonContact",
            columns=(
                ColumnSpec(
                    name="contactString",
                    type="Nullable(String)",
                    nullable=True,
                    is_primary_key=True,
                ),
                ColumnSpec(name="personID", type="String", nullable=False, is_primary_key=True),
                ColumnSpec(
                    name="created_at", type="DateTime", nullable=False, is_primary_key=False
                ),
            ),
        )
        assert spec.primary_key == ("contactString", "personID")

    def test_primary_key_is_empty_tuple_when_no_column_is_flagged(self) -> None:
        spec = TableSpec(
            name="no_pk_table",
            columns=(ColumnSpec(name="value", type="String", nullable=True, is_primary_key=False),),
        )
        assert spec.primary_key == ()


@pytest.mark.unit
class TestTableSpecHasCreatedAt:
    def test_true_when_a_created_at_column_exists(self) -> None:
        spec = TableSpec(
            name="Company",
            columns=(
                ColumnSpec(name="companyID", type="String", nullable=False, is_primary_key=True),
                ColumnSpec(
                    name="created_at",
                    type="Nullable(DateTime)",
                    nullable=True,
                    is_primary_key=False,
                ),
            ),
        )
        assert spec.has_created_at is True

    def test_false_when_no_created_at_column_exists(self) -> None:
        spec = TableSpec(
            name="customers",
            columns=(ColumnSpec(name="id", type="INTEGER", nullable=False, is_primary_key=True),),
        )
        assert spec.has_created_at is False

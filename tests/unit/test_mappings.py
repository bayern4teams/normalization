"""Unit tests for normapi.mappings (M16) — ColumnMapping's field_ref
property and materialize_field_config(). No database needed."""

from __future__ import annotations

import pytest
from normapi.mappings import ColumnMapping, materialize_field_config

from normcore import ErrorPolicy, FieldSemanticType, SemanticSource


def _mapping(**overrides: object) -> ColumnMapping:
    defaults: dict[str, object] = {
        "connection_identity": "a" * 64,
        "database": "origin2",
        "table_name": "Person",
        "column_name": "fullName",
        "semantic_type": FieldSemanticType.PERSON_NAME,
        "semantic_source": SemanticSource.USER,
        "enabled": True,
        "updated_at": "2026-08-26T04:00:00Z",
        "updated_by": "tester",
    }
    defaults.update(overrides)
    return ColumnMapping.model_validate(defaults)


@pytest.mark.unit
class TestColumnMappingFieldRef:
    def test_field_ref_is_dot_joined_identity_database_table_column(self) -> None:
        mapping = _mapping()
        assert mapping.field_ref == f"{'a' * 64}.origin2.Person.fullName"

    def test_field_ref_changes_when_the_column_changes(self) -> None:
        a = _mapping(column_name="fullName")
        b = _mapping(column_name="firstName")
        assert a.field_ref != b.field_ref

    def test_field_ref_is_stable_regardless_of_alias_or_connection_id(self) -> None:
        """The whole point: field_ref never depends on a connection's own
        id/alias — only on its real identity, database, table, column."""
        a = _mapping(connection_identity="b" * 64)
        b = _mapping(connection_identity="b" * 64)
        assert a.field_ref == b.field_ref


@pytest.mark.unit
class TestMaterializeFieldConfig:
    def test_field_ref_matches_the_mapping(self) -> None:
        mapping = _mapping()
        config = materialize_field_config(mapping)
        assert config.field_ref == mapping.field_ref

    def test_semantic_type_matches_the_mapping(self) -> None:
        mapping = _mapping(semantic_type=FieldSemanticType.COMPANY_NAME)
        config = materialize_field_config(mapping)
        assert config.semantic_type == FieldSemanticType.COMPANY_NAME

    def test_semantic_source_matches_the_mapping(self) -> None:
        mapping = _mapping(semantic_source=SemanticSource.DETECTED)
        config = materialize_field_config(mapping)
        assert config.semantic_source == SemanticSource.DETECTED

    def test_error_policy_defaults_to_return_original(self) -> None:
        config = materialize_field_config(_mapping())
        assert config.error_policy == ErrorPolicy.RETURN_ORIGINAL

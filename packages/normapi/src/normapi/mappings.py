"""Connection-keyed column mappings — M16 of the M13-M22 program
(docs/plan/M13-M22-program-plan.md).

A `ColumnMapping` is the UI-facing editable surface for "what semantic
type does this column have" (the Explore step of decision 6's 3-step
UI), keyed by `(connection_identity, database, table_name, column_name)`
— never by a connection's alias or id (decision 4), so deleting a
connection and re-adding the same real database under a different alias
reuses its mappings automatically. Persistence lives in
`PostgresMetadataStore`, mirroring `connections.py`'s own pattern.

Mappings and a versioned `NormalizationProfile`'s own `field_configs` are
two sources of truth for the same underlying concept, by design: the
mappings table is the UI-facing editable surface, and
`materialize_field_config()` is the one function that turns a mapping
into a real `FieldNormalizationConfig` — `run.profile_version` stays the
one thing execution actually reads (load-bearing for cache keys, A/B
compare, and the handoff artifact), never bypassed.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from normcore import ErrorPolicy, FieldNormalizationConfig, FieldSemanticType, SemanticSource


class ColumnMapping(BaseModel):
    model_config = ConfigDict(frozen=True)

    connection_identity: str
    database: str
    table_name: str
    column_name: str
    semantic_type: FieldSemanticType
    semantic_source: SemanticSource
    enabled: bool
    updated_at: str
    updated_by: str

    @property
    def field_ref(self) -> str:
        """The exact string a materialized `FieldNormalizationConfig` is
        keyed by — real connection identity, not an alias, so it stays
        valid even after the connection that created it is deleted and
        re-added under a different alias/connection id."""
        return f"{self.connection_identity}.{self.database}.{self.table_name}.{self.column_name}"


def materialize_field_config(mapping: ColumnMapping) -> FieldNormalizationConfig:
    """Turns a saved mapping into a real `FieldNormalizationConfig` a
    profile version can carry — the one place that conversion happens,
    so a profile's `field_configs` and the mappings table never drift on
    what a mapping actually means once applied."""
    return FieldNormalizationConfig(
        field_ref=mapping.field_ref,
        semantic_type=mapping.semantic_type,
        semantic_source=mapping.semantic_source,
        error_policy=ErrorPolicy.RETURN_ORIGINAL,
    )

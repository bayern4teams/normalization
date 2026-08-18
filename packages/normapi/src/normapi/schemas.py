"""Request/response schemas for the §98 API surface.

Reuses normcore domain models directly as response bodies wherever a
model already represents exactly what the endpoint returns
(NormalizationProfile, NormalizationRun, NormalizedValue, Dictionary) —
no parallel "API DTO" duplicating fields that would drift from the real
contract. Request-only shapes (things clients send that aren't a stored
entity themselves) get their own thin models here.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from normcore import (
    ErrorPolicy,
    FieldNormalizationConfig,
    FieldSemanticType,
)


class ProfileCreateRequest(BaseModel):
    name: str
    description: str = ""
    locale_policy: dict[str, str] = Field(default_factory=dict)
    default_operations: tuple[str, ...] = ()
    field_configs: tuple[FieldNormalizationConfig, ...] = ()
    created_by: str


class ProfileVersionRequest(BaseModel):
    """Body for POST /normalization/profiles/{id}/versions — creates a new
    version of an existing profile. Only fields being changed need to be
    supplied; omitted fields carry over from the profile being versioned.
    """

    description: str | None = None
    locale_policy: dict[str, str] | None = None
    default_operations: tuple[str, ...] | None = None
    field_configs: tuple[FieldNormalizationConfig, ...] | None = None
    created_by: str


class PreviewRequest(BaseModel):
    field_name: str
    semantic_type: FieldSemanticType
    values: list[str | None]
    error_policy: ErrorPolicy = ErrorPolicy.RETURN_ORIGINAL


class FieldTestRequest(BaseModel):
    field_name: str
    semantic_type: FieldSemanticType
    value: str | None
    error_policy: ErrorPolicy = ErrorPolicy.RETURN_ORIGINAL


class RunExecutionRequest(BaseModel):
    """Optional body for POST /normalization/runs — when supplied, the
    run actually normalizes `values` through the live Dispatcher (M6);
    when omitted, the run is created PENDING with no field execution,
    exactly matching M1's original scaffold behavior."""

    field_name: str
    semantic_type: FieldSemanticType
    values: list[str | None]
    error_policy: ErrorPolicy = ErrorPolicy.RETURN_ORIGINAL


class ProfileRollbackRequest(BaseModel):
    target_version: str


class DictionaryCreateRequest(BaseModel):
    id: str
    entries: dict[str, Any] = Field(default_factory=dict)
    locale: str | None = None
    source: str
    license: str
    created_by: str


class DictionaryVersionRequest(BaseModel):
    entries: dict[str, Any] = Field(default_factory=dict)
    locale: str | None = None
    source: str | None = None
    license: str | None = None
    created_by: str
    merge: bool = False


class DictionaryRollbackRequest(BaseModel):
    target_version: str
    by: str


class FieldSummary(BaseModel):
    """One row of GET /normalization/fields — derived from every known
    profile's field_configs, not a separately-maintained list."""

    field_ref: str
    semantic_type: FieldSemanticType
    profile_ids: list[str]


class DictionarySummary(BaseModel):
    id: str
    version: str
    locale: str | None
    source: str
    license: str
    entry_count: int
    is_custom: bool = False
    active_version: str | None = None


class NotImplementedResponse(BaseModel):
    """Honest, schema-valid placeholder for §98 endpoints whose real
    implementation is still out of scope at the current milestone —
    returned with HTTP 501 rather than silently faking success.
    """

    detail: str
    planned_milestone: str


__all__ = [
    "DictionaryCreateRequest",
    "DictionaryRollbackRequest",
    "DictionarySummary",
    "DictionaryVersionRequest",
    "FieldSummary",
    "FieldTestRequest",
    "NotImplementedResponse",
    "PreviewRequest",
    "ProfileCreateRequest",
    "ProfileRollbackRequest",
    "ProfileVersionRequest",
    "RunExecutionRequest",
]

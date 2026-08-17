"""Rule, step, pipeline, and field-config models — Source.txt §7, §81, §99,
§100, §116.

A `NormalizationPipeline` is an ordered sequence of `NormalizationStep`s;
each step references a `NormalizationRule` (the reusable, named operation
definition) plus per-field parameter overrides. This is what the Rule
Builder UI (M7, §81/§116) edits, and what `normexec` (M1) walks when
normalizing a field's distinct-value set.

Concrete implementations of the `StepSpec`/`ComponentVersion` Protocols
declared in normcore.interfaces live here — `NormalizationStep` below is
structurally compatible with `StepSpec` (same field names), so any
concrete step model satisfies that Protocol without inheriting from it.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from normcore.enums import (
    ErrorPolicy,
    FieldSemanticType,
    OnErrorAction,
    ProfileStatus,
    Reversibility,
    SemanticSource,
)


class NormalizationRule(BaseModel):
    """A reusable, named operation definition — Source.txt §7.

    Rules are library-level building blocks (e.g. "whitespace.collapse",
    "unicode.nfc", "name.parse_western"); `NormalizationStep` below
    references a rule by `rule_id` and supplies per-field parameters.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    field_type: FieldSemanticType
    operation: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    priority: int = 0
    enabled: bool = True
    claimed_reversibility: Reversibility
    lossy: bool = False
    dictionary_ref: str | None = None


class NormalizationStep(BaseModel):
    """One position in a `NormalizationPipeline`. Structurally satisfies
    the `StepSpec` Protocol (normcore.interfaces) via `step_id`,
    `operation`, `claimed_reversibility`, `lossy`.
    """

    model_config = ConfigDict(frozen=True)

    step_id: str
    rule_id: str
    operation: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    on_error: OnErrorAction = OnErrorAction.SKIP_STEP
    produces_view: str | None = None
    claimed_reversibility: Reversibility = Reversibility.LOSSLESS
    lossy: bool = False


class NormalizationPipeline(BaseModel):
    """An ordered sequence of steps for one field. Step order is the list
    order — no separate `step_order` field on the pipeline itself, since
    reordering is exactly what the Rule Builder UI's drag/drop (§81, §116)
    mutates.
    """

    model_config = ConfigDict(frozen=True)

    steps: tuple[NormalizationStep, ...] = ()

    def enabled_steps(self) -> tuple[NormalizationStep, ...]:
        return tuple(step for step in self.steps if step.enabled)


class FieldNormalizationConfig(BaseModel):
    """Per-field configuration within a `NormalizationProfile` —
    Source.txt §7, §60, §61, §62.
    """

    model_config = ConfigDict(frozen=True)

    field_ref: str  # "source.table.column"
    semantic_type: FieldSemanticType
    semantic_confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    semantic_source: SemanticSource = SemanticSource.USER
    pipeline: NormalizationPipeline = Field(default_factory=NormalizationPipeline)
    error_policy: ErrorPolicy = ErrorPolicy.RETURN_ORIGINAL
    locale_overrides: dict[str, str] = Field(default_factory=dict)
    dictionary_refs: tuple[str, ...] = ()
    emitted_views: tuple[str, ...] = ()


class ComponentVersionInfo(BaseModel):
    """Concrete implementation of the `ComponentVersion` Protocol
    (normcore.interfaces) — what `Normalizer.version()` returns.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    version: str


class ValidationOutcome(BaseModel):
    """Concrete implementation of the `ValidationResult` Protocol."""

    model_config = ConfigDict(frozen=True)

    is_valid: bool
    status: str
    reason: str | None = None


class ExplanationText(BaseModel):
    """Concrete implementation of the `Explanation` Protocol — backs the
    "Why did this change?" UX (§117)."""

    model_config = ConfigDict(frozen=True)

    plain_language: str
    technical: str


class NormalizationProfile(BaseModel):
    """Source.txt §7, §62, §95, §120 — the top-level, versioned,
    immutable-once-activated configuration object.

    Profiles are never mutated in place once `status` leaves `DRAFT`
    (ADR-014): a change creates a new `NormalizationProfile` with an
    incremented `version` and `parent_version` pointing at the one it
    supersedes. Enforcement of that immutability lives in the profile
    store (normapi/normdict), not in this model — this model just carries
    the shape.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    version: str
    description: str = ""
    status: ProfileStatus = ProfileStatus.DRAFT
    locale_policy: dict[str, str] = Field(default_factory=dict)
    default_operations: tuple[str, ...] = ()
    field_configs: tuple[FieldNormalizationConfig, ...] = ()
    created_at: str  # ISO 8601 — kept as str at the model layer, parsed at the storage boundary
    updated_at: str
    created_by: str
    parent_version: str | None = None

    def config_for(self, field_ref: str) -> FieldNormalizationConfig | None:
        for config in self.field_configs:
            if config.field_ref == field_ref:
                return config
        return None

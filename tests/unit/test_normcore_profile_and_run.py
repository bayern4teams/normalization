"""Proves the M1 domain-model additions (profile/pipeline/run/version) hold
together as a coherent object graph, not just as individually-valid
pydantic models.
"""

from __future__ import annotations

import pytest

from normcore import (
    ComponentVersionInfo,
    ErrorPolicy,
    FieldNormalizationConfig,
    FieldSemanticType,
    NormalizationPipeline,
    NormalizationProfile,
    NormalizationRule,
    NormalizationRun,
    NormalizationRunMetrics,
    NormalizationStep,
    NormalizationVersion,
    ProfileStatus,
    Reversibility,
    RunStatus,
)


def _sample_pipeline() -> NormalizationPipeline:
    return NormalizationPipeline(
        steps=(
            NormalizationStep(
                step_id="s1",
                rule_id="whitespace.collapse",
                operation="collapse_whitespace",
                claimed_reversibility=Reversibility.REVERSIBLE,
                lossy=False,
            ),
            NormalizationStep(
                step_id="s2",
                rule_id="unicode.casefold",
                operation="casefold",
                produces_view="comparison",
                claimed_reversibility=Reversibility.LOSSY,
                lossy=True,
                enabled=False,
            ),
        )
    )


@pytest.mark.unit
def test_pipeline_enabled_steps_filters_disabled() -> None:
    pipeline = _sample_pipeline()
    assert len(pipeline.steps) == 2
    enabled = pipeline.enabled_steps()
    assert len(enabled) == 1
    assert enabled[0].step_id == "s1"


@pytest.mark.unit
def test_profile_config_for_lookup_and_immutability() -> None:
    field_config = FieldNormalizationConfig(
        field_ref="customers.first_name",
        semantic_type=FieldSemanticType.PERSON_NAME,
        pipeline=_sample_pipeline(),
    )
    profile = NormalizationProfile(
        id="p1",
        name="default",
        version="v1",
        status=ProfileStatus.DRAFT,
        field_configs=(field_config,),
        created_at="2026-08-17T00:00:00Z",
        updated_at="2026-08-17T00:00:00Z",
        created_by="test",
    )

    found = profile.config_for("customers.first_name")
    assert found is not None
    assert found.semantic_type is FieldSemanticType.PERSON_NAME
    assert profile.config_for("customers.missing_field") is None

    # Profiles are frozen — attempting mutation must raise, this is the
    # mechanical enforcement behind ADR-014's "immutable once activated"
    # claim (a real code guarantee, not just a policy statement).
    with pytest.raises(Exception, match=r"frozen|Instance is frozen"):
        profile.status = ProfileStatus.ACTIVE  # type: ignore[misc]


def _profile(
    field_configs: tuple[FieldNormalizationConfig, ...] = (),
    locale_policy: dict[str, str] | None = None,
) -> NormalizationProfile:
    return NormalizationProfile(
        id="p1",
        name="p",
        version="v1",
        locale_policy=locale_policy or {},
        field_configs=field_configs,
        created_at="2026-08-17T00:00:00Z",
        updated_at="2026-08-17T00:00:00Z",
        created_by="test",
    )


@pytest.mark.unit
class TestBuildContext:
    """`NormalizationProfile.build_context` (M10) — the real profile ->
    NormalizationContext plumbing several normalizers already branch on
    (`ctx.country`/`ctx.locale`/`ctx.default_region`), see
    tests/golden/test_m10_corpus.py for proof this actually changes live
    normalizer output, not just that the context object is shaped right.
    """

    def test_profile_locale_policy_populates_context(self) -> None:
        profile = _profile(locale_policy={"country": "US", "default_region": "US"})
        ctx = profile.build_context("f", FieldSemanticType.FREE_TEXT)
        assert ctx.country == "US"
        assert ctx.default_region == "US"

    def test_field_locale_overrides_win_over_profile_locale_policy(self) -> None:
        field_config = FieldNormalizationConfig(
            field_ref="f",
            semantic_type=FieldSemanticType.FREE_TEXT,
            locale_overrides={"country": "GB"},
        )
        profile = _profile(field_configs=(field_config,), locale_policy={"country": "US"})
        ctx = profile.build_context("f", FieldSemanticType.FREE_TEXT)
        assert ctx.country == "GB"

    def test_unrelated_field_does_not_see_another_fields_overrides(self) -> None:
        field_config = FieldNormalizationConfig(
            field_ref="f1",
            semantic_type=FieldSemanticType.FREE_TEXT,
            locale_overrides={"country": "GB"},
        )
        profile = _profile(field_configs=(field_config,), locale_policy={"country": "US"})
        ctx = profile.build_context("f2", FieldSemanticType.FREE_TEXT)
        assert ctx.country == "US"

    def test_unknown_locale_keys_are_silently_dropped_not_raised(self) -> None:
        profile = _profile(locale_policy={"nonsense_key": "x", "country": "US"})
        ctx = profile.build_context("f", FieldSemanticType.FREE_TEXT)
        assert ctx.country == "US"
        assert not hasattr(ctx, "nonsense_key")

    def test_dictionary_refs_become_dictionary_set(self) -> None:
        field_config = FieldNormalizationConfig(
            field_ref="f",
            semantic_type=FieldSemanticType.FREE_TEXT,
            dictionary_refs=("honorifics.common", "custom.aliases"),
        )
        profile = _profile(field_configs=(field_config,))
        ctx = profile.build_context("f", FieldSemanticType.FREE_TEXT)
        assert ctx.dictionary_set == ("honorifics.common", "custom.aliases")

    def test_explicit_error_policy_wins_over_field_config(self) -> None:
        field_config = FieldNormalizationConfig(
            field_ref="f",
            semantic_type=FieldSemanticType.FREE_TEXT,
            error_policy=ErrorPolicy.SKIP_FIELD,
        )
        profile = _profile(field_configs=(field_config,))
        ctx = profile.build_context(
            "f", FieldSemanticType.FREE_TEXT, error_policy=ErrorPolicy.MARK_INVALID
        )
        assert ctx.error_policy is ErrorPolicy.MARK_INVALID

    def test_field_config_error_policy_used_when_none_supplied(self) -> None:
        field_config = FieldNormalizationConfig(
            field_ref="f",
            semantic_type=FieldSemanticType.FREE_TEXT,
            error_policy=ErrorPolicy.SKIP_FIELD,
        )
        profile = _profile(field_configs=(field_config,))
        ctx = profile.build_context("f", FieldSemanticType.FREE_TEXT, error_policy=None)
        assert ctx.error_policy is ErrorPolicy.SKIP_FIELD

    def test_default_error_policy_when_no_field_config_and_none_supplied(self) -> None:
        profile = _profile()
        ctx = profile.build_context("f", FieldSemanticType.FREE_TEXT, error_policy=None)
        assert ctx.error_policy is ErrorPolicy.RETURN_ORIGINAL


@pytest.mark.unit
def test_run_lifecycle_terminal_states() -> None:
    run = NormalizationRun(
        id="run1",
        profile_id="p1",
        profile_version="v1",
        env_id="e" * 64,
        source_snapshot="snap1",
        started_at="2026-08-17T00:00:00Z",
        status=RunStatus.RUNNING,
    )
    assert run.is_terminal() is False

    completed = run.model_copy(
        update={
            "status": RunStatus.COMPLETED,
            "finished_at": "2026-08-17T00:05:00Z",
            "metrics": NormalizationRunMetrics(records_processed=1000, changed_values=800),
        }
    )
    assert completed.is_terminal() is True
    assert completed.metrics.records_processed == 1000


@pytest.mark.unit
def test_normalization_rule_carries_reversibility_claim() -> None:
    rule = NormalizationRule(
        id="unicode.nfc",
        name="Unicode NFC normalization",
        field_type=FieldSemanticType.FREE_TEXT,
        operation="nfc_normalize",
        claimed_reversibility=Reversibility.LOSSLESS,
    )
    assert rule.claimed_reversibility is Reversibility.LOSSLESS
    assert rule.lossy is False


@pytest.mark.unit
def test_component_version_and_normalization_version_shapes() -> None:
    version_info = ComponentVersionInfo(name="phonenumbers", version="8.13.0")
    assert version_info.name == "phonenumbers"

    env_version = NormalizationVersion(
        env_id="a" * 64,
        profile_version="v1",
        library_versions={"phonenumbers": "8.13.0"},
        icu_version="78.3",
        unicode_version="17.0",
    )
    assert env_version.library_versions["phonenumbers"] == "8.13.0"

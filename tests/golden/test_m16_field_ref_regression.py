"""Golden regression test for M16's `field_ref` bug fix
(docs/plan/M13-M22-program-plan.md).

Before M16, `InMemoryStore.execute_run()` always called
`profile.build_context(field_name, ...)` with the bare `field_name` — a
profile's real `FieldNormalizationConfig.field_ref` (the structured key a
saved column mapping materializes into, e.g.
`"<identity>.<database>.<table>.<column>"`) could essentially never match
a bare column name like `"comments"`, so `error_policy`/
`locale_overrides`/`dictionary_refs` were silently unapplied even when a
matching config existed. This locks the fix: the SAME profile, the SAME
failing value, produces a DIFFERENT observable result depending only on
whether the real field_ref is threaded through — proving the field
config's `error_policy` genuinely took effect, not just that no
exception was raised.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from normalizers.generic_text import GenericTextNormalizer
from normapi.store import InMemoryStore

from normcore import (
    Dispatcher,
    ErrorPolicy,
    FieldNormalizationConfig,
    FieldSemanticType,
    NormalizerRegistry,
)
from normdict import DictionaryLoader

_DICT_ROOT = Path(__file__).parents[2] / "data" / "dictionaries"

_REAL_FIELD_REF = "conn-abc123.origin2.Company.description"


def _dispatcher_that_always_fails() -> Dispatcher:
    """A real GenericTextNormalizer whose internal UnicodeNormalizer is
    monkeypatched to always raise — the same "force a real
    NormalizerFailure" pattern this project's own M12 mutation-coverage
    work already established for CompanyNormalizer's `_unicode`
    attribute, reused here rather than inventing a new technique."""
    normalizer = GenericTextNormalizer(DictionaryLoader(_DICT_ROOT))

    def _always_raise(*_args: object, **_kwargs: object) -> None:
        msg = "forced failure for the M16 field_ref regression test"
        raise RuntimeError(msg)

    normalizer._unicode.process = _always_raise  # type: ignore[assignment]

    registry = NormalizerRegistry()
    registry.register(normalizer)
    return Dispatcher(registry, env_id="e" * 64)


def _store_with_profile(
    field_configs: tuple[FieldNormalizationConfig, ...],
) -> tuple[InMemoryStore, str]:
    store = InMemoryStore()
    profile = store.create_profile(
        name="p",
        description="",
        locale_policy={},
        default_operations=(),
        field_configs=field_configs,
        created_by="tester",
    )
    return store, profile.id


@pytest.mark.golden
class TestFieldRefThreadingAppliesTheMatchingProfileConfig:
    def test_without_a_real_field_ref_the_profile_config_is_not_consulted(self) -> None:
        """Baseline: a field config keyed by the real structured
        field_ref exists on the profile, but this call only supplies the
        bare `field_name` (`field_ref=None`, the pre-M16 shape) — the
        config can't match, so the DEFAULT error_policy
        (RETURN_ORIGINAL) applies to the forced failure."""
        field_config = FieldNormalizationConfig(
            field_ref=_REAL_FIELD_REF,
            semantic_type=FieldSemanticType.FREE_TEXT,
            error_policy=ErrorPolicy.RETURN_NULL,
        )
        store, profile_id = _store_with_profile((field_config,))
        dispatcher = _dispatcher_that_always_fails()
        run = store.create_run(profile_id=profile_id, env_id=dispatcher.env_id, source_snapshot="s")

        finished = store.execute_run(
            run.id,
            dispatcher=dispatcher,
            field_name="description",
            semantic_type=FieldSemanticType.FREE_TEXT,
            values=["hello world"],
            # field_ref intentionally omitted -> falls back to bare field_name
        )

        execution = store.get_execution(finished.id)
        assert execution is not None
        result = execution.results[0]
        assert result.normalization_status == "INVALID"
        # RETURN_ORIGINAL (the un-configured default) — NOT the profile's
        # own RETURN_NULL, because the config never matched.
        assert result.display == "hello world"

    def test_with_the_real_field_ref_the_matching_profile_config_error_policy_applies(
        self,
    ) -> None:
        """Same profile, same forced failure, same input value — only
        difference is passing the real `field_ref` M16 wires through from
        a connection-based source. The profile's own `RETURN_NULL`
        error_policy now genuinely applies."""
        field_config = FieldNormalizationConfig(
            field_ref=_REAL_FIELD_REF,
            semantic_type=FieldSemanticType.FREE_TEXT,
            error_policy=ErrorPolicy.RETURN_NULL,
        )
        store, profile_id = _store_with_profile((field_config,))
        dispatcher = _dispatcher_that_always_fails()
        run = store.create_run(profile_id=profile_id, env_id=dispatcher.env_id, source_snapshot="s")

        finished = store.execute_run(
            run.id,
            dispatcher=dispatcher,
            field_name="description",
            semantic_type=FieldSemanticType.FREE_TEXT,
            values=["hello world"],
            field_ref=_REAL_FIELD_REF,
        )

        execution = store.get_execution(finished.id)
        assert execution is not None
        result = execution.results[0]
        assert result.normalization_status == "INVALID"
        # RETURN_NULL, from the matched field config — the real fix.
        assert result.display is None

    def test_semantic_type_omitted_falls_back_to_the_matching_profile_config(self) -> None:
        """The other half of the same bug: `semantic_type` used to be
        required and always won unconditionally. Now, when the caller
        supplies `None`, the matched field config's own `semantic_type`
        is used instead of raising or silently defaulting to something
        wrong."""
        field_config = FieldNormalizationConfig(
            field_ref=_REAL_FIELD_REF,
            semantic_type=FieldSemanticType.FREE_TEXT,
            error_policy=ErrorPolicy.RETURN_ORIGINAL,
        )
        store, profile_id = _store_with_profile((field_config,))
        dispatcher = _dispatcher_that_always_fails()
        run = store.create_run(profile_id=profile_id, env_id=dispatcher.env_id, source_snapshot="s")

        finished = store.execute_run(
            run.id,
            dispatcher=dispatcher,
            field_name="description",
            semantic_type=None,
            values=["hello world"],
            field_ref=_REAL_FIELD_REF,
        )

        execution = store.get_execution(finished.id)
        assert execution is not None
        assert execution.semantic_type == FieldSemanticType.FREE_TEXT

    def test_no_semantic_type_and_no_matching_config_raises(self) -> None:
        store, profile_id = _store_with_profile(())
        dispatcher = _dispatcher_that_always_fails()
        run = store.create_run(profile_id=profile_id, env_id=dispatcher.env_id, source_snapshot="s")

        with pytest.raises(ValueError, match="No semantic_type given"):
            store.execute_run(
                run.id,
                dispatcher=dispatcher,
                field_name="description",
                semantic_type=None,
                values=["hello world"],
                field_ref="no-such-field-ref",
            )

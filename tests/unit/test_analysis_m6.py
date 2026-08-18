"""Unit tests for normanalysis's M6 additions — impact/collision/A-B/
invariant/profiling analysis (Source.txt §77, §78, §79, §96, §97, §71).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from normalizers.generic_text import GenericTextNormalizer
from normalizers.identifier import IdentifierNormalizer
from normalizers.passthrough import PassthroughNormalizer
from normapi.scaffold_profile import SCAFFOLD_PROFILE
from normcore.enums import FieldSemanticType

from normanalysis import (
    compare_runs,
    compute_impact,
    find_collisions,
    profile_field,
    sample_and_check,
)
from normcore import Dispatcher, NormalizationContext, NormalizerRegistry
from normdict import DictionaryLoader

_DICT_ROOT = Path(__file__).parents[2] / "data" / "dictionaries"


@pytest.fixture
def text_normalizer() -> GenericTextNormalizer:
    return GenericTextNormalizer(DictionaryLoader(_DICT_ROOT))


def _ctx() -> NormalizationContext:
    return NormalizationContext(field_name="name", semantic_type=FieldSemanticType.FREE_TEXT)


@pytest.mark.unit
class TestProfileField:
    def test_source_txt_77_worked_example_shape(
        self, text_normalizer: GenericTextNormalizer
    ) -> None:
        ctx = _ctx()
        originals = ["  Anna  ", "Bob", "Anna"]
        results = [text_normalizer.normalize(v, ctx) for v in originals]
        profile = profile_field("f", results)
        assert profile.rows == 3
        assert profile.changed == 1
        assert profile.unchanged == 2
        assert profile.errors == 0

    def test_top_transformation_patterns_ranked_by_frequency(
        self, text_normalizer: GenericTextNormalizer
    ) -> None:
        ctx = _ctx()
        originals = ["  a  ", "  b  ", "c"]
        results = [text_normalizer.normalize(v, ctx) for v in originals]
        profile = profile_field("f", results)
        patterns = profile.top_transformation_patterns
        operations = [p.operation for p in patterns]
        assert "trim" in operations
        trim_count = next(p.count for p in patterns if p.operation == "trim")
        assert trim_count == 2

    def test_empty_batch(self) -> None:
        profile = profile_field("f", [])
        assert profile.rows == 0
        assert profile.top_transformation_patterns == []


@pytest.mark.unit
class TestComputeImpact:
    def test_matches_source_txt_78_worked_example_shape(
        self, text_normalizer: GenericTextNormalizer
    ) -> None:
        """Source.txt §78's own worked example: unique_before > unique_after
        implies new_collisions == unique_before - unique_after."""
        originals = ["Jose Garcia", "José García", "JOSÉ GARCÍA", "Anna", "Bob"]
        ctx = _ctx()
        results = [text_normalizer.normalize(v, ctx) for v in originals]
        report = compute_impact("name", originals, results)
        # 5 distinct raw strings; "José García"/"JOSÉ GARCÍA" share one
        # casefolded comparison key (GenericTextNormalizer's comparison
        # view), the rest stay distinct -> 4 unique after, 1 new collision.
        assert report.unique_before == 5
        assert report.unique_after == 4
        assert report.new_collisions == 1

    def test_null_counts(self, text_normalizer: GenericTextNormalizer) -> None:
        originals = ["Anna", None, ""]
        ctx = _ctx()
        results = [text_normalizer.normalize(v, ctx) for v in originals]
        report = compute_impact("name", originals, results)
        assert report.null_before == 2
        assert report.null_after == 2

    def test_avg_length(self, text_normalizer: GenericTextNormalizer) -> None:
        originals = ["ab", "abcd"]
        ctx = _ctx()
        results = [text_normalizer.normalize(v, ctx) for v in originals]
        report = compute_impact("name", originals, results)
        assert report.avg_length_before == pytest.approx(3.0)

    def test_warning_emitted_above_ratio_threshold(
        self, text_normalizer: GenericTextNormalizer
    ) -> None:
        # 3 distinct originals collapse to 1 -> ratio 2/3, well above the
        # 2% warning threshold.
        originals = ["Jose Garcia", "JOSE GARCIA", "jose garcia"]
        ctx = _ctx()
        results = [text_normalizer.normalize(v, ctx) for v in originals]
        report = compute_impact("name", originals, results)
        assert report.new_collisions == 2
        assert any("new collisions" in w for w in report.warnings)

    def test_length_mismatch_raises(self) -> None:
        with pytest.raises(ValueError, match="same length"):
            compute_impact("name", ["a", "b"], [])


@pytest.mark.unit
class TestFindCollisions:
    def test_source_txt_79_worked_example(self, text_normalizer: GenericTextNormalizer) -> None:
        originals = ["José García", "Jose Garcia", "JOSÉ GARCÍA"]
        ctx = _ctx()
        results = [text_normalizer.normalize(v, ctx) for v in originals]
        groups = find_collisions(originals, results)
        # "Jose Garcia" (no accents) stays distinct from the two accented
        # case-variants under GenericTextNormalizer's casefold-only
        # comparison view (no accent stripping) — a real, correctly
        # conservative collision, not the full three-way merge.
        assert len(groups) == 1
        assert set(groups[0].original_values) == {"José García", "JOSÉ GARCÍA"}
        assert groups[0].total_occurrences == 2

    def test_no_collision_when_all_distinct(self, text_normalizer: GenericTextNormalizer) -> None:
        originals = ["Anna", "Bob", "Carl"]
        ctx = _ctx()
        results = [text_normalizer.normalize(v, ctx) for v in originals]
        assert find_collisions(originals, results) == []

    def test_duplicate_identical_originals_not_a_collision(
        self, text_normalizer: GenericTextNormalizer
    ) -> None:
        """Two literally identical raw values collapsing to one comparison
        key is ordinary deduplication, not a normalization-caused
        collision — §79 is specifically about *distinct* originals
        merging."""
        originals = ["Anna", "Anna", "Anna"]
        ctx = _ctx()
        results = [text_normalizer.normalize(v, ctx) for v in originals]
        assert find_collisions(originals, results) == []

    def test_groups_sorted_by_occurrence_descending(
        self, text_normalizer: GenericTextNormalizer
    ) -> None:
        originals = ["A1", "a1", "B1", "b1", "B1x", "b1x", "b1X"]
        ctx = _ctx()
        results = [text_normalizer.normalize(v, ctx) for v in originals]
        groups = find_collisions(originals, results)
        occurrences = [g.total_occurrences for g in groups]
        assert occurrences == sorted(occurrences, reverse=True)


@pytest.mark.unit
class TestCompareRuns:
    def test_compare_identical_result_sets(self, text_normalizer: GenericTextNormalizer) -> None:
        originals = ["Anna", "Bob", "Anna"]
        ctx = _ctx()
        results = [text_normalizer.normalize(v, ctx) for v in originals]
        report = compare_runs(
            "name",
            profile_version_a="v1",
            results_a=results,
            profile_version_b="v1",
            results_b=results,
        )
        assert report.changed_between_a_and_b == 0
        assert report.a.unique_values == report.b.unique_values

    def test_compare_detects_display_changes(self) -> None:
        """FREE_TEXT (no digit transliteration) vs IDENTIFIER (Arabic-Indic
        digits -> ASCII, §49) genuinely disagree on `display` for the same
        raw input — a real difference two profile versions could produce,
        not a synthetic one."""
        loader = DictionaryLoader(_DICT_ROOT)
        normalizer = GenericTextNormalizer(loader)
        identifier = IdentifierNormalizer()
        ctx_text = NormalizationContext(field_name="f", semantic_type=FieldSemanticType.FREE_TEXT)
        ctx_identifier = NormalizationContext(
            field_name="f", semantic_type=FieldSemanticType.IDENTIFIER
        )
        originals = ["١٢٣", "٤٥٦"]
        results_a = [normalizer.normalize(v, ctx_text) for v in originals]
        results_b = [identifier.normalize(v, ctx_identifier) for v in originals]
        report = compare_runs(
            "f",
            profile_version_a="v1",
            results_a=results_a,
            profile_version_b="v2",
            results_b=results_b,
        )
        assert report.changed_between_a_and_b == 2
        assert report.changed_between_a_and_b_pct == pytest.approx(1.0)

    def test_mismatched_lengths_raise(self) -> None:
        with pytest.raises(ValueError, match="same aligned input values"):
            compare_runs(
                "f",
                profile_version_a="v1",
                results_a=[],
                profile_version_b="v2",
                results_b=[
                    GenericTextNormalizer(DictionaryLoader(_DICT_ROOT)).normalize("a", _ctx())
                ],
            )


@pytest.mark.unit
class TestInvariantSampler:
    def test_no_violations_on_a_real_stable_normalizer(self) -> None:
        registry = NormalizerRegistry()
        registry.register(PassthroughNormalizer())
        dispatcher = Dispatcher(registry, env_id="test-env")
        ctx = NormalizationContext(field_name="f", semantic_type=FieldSemanticType.UNKNOWN)
        profile = SCAFFOLD_PROFILE

        originals = ["a", "b", "c", "d", "e"]
        results = [
            dispatcher.normalize(v, FieldSemanticType.UNKNOWN, ctx, profile) for v in originals
        ]

        report = sample_and_check(
            dispatcher,
            FieldSemanticType.UNKNOWN,
            ctx,
            profile,
            originals=originals,
            results=results,
            sample_rate=1.0,
            seed=0,
        )
        assert report.is_clean
        assert report.sampled == len(originals)

    def test_sample_size_respects_max_sample(self) -> None:
        registry = NormalizerRegistry()
        registry.register(PassthroughNormalizer())
        dispatcher = Dispatcher(registry, env_id="test-env")
        ctx = NormalizationContext(field_name="f", semantic_type=FieldSemanticType.UNKNOWN)
        profile = SCAFFOLD_PROFILE

        originals = [f"v{i}" for i in range(100)]
        results = [
            dispatcher.normalize(v, FieldSemanticType.UNKNOWN, ctx, profile) for v in originals
        ]

        report = sample_and_check(
            dispatcher,
            FieldSemanticType.UNKNOWN,
            ctx,
            profile,
            originals=originals,
            results=results,
            sample_rate=1.0,
            max_sample=5,
            seed=0,
        )
        assert report.sampled == 5

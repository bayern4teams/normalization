"""`normexec.cache_policy` — Phase 3 item 2 (2026-08-29 throughput/memory
program), the cardinality-aware cache-policy decision itself, independent
of where the `distinct_ratio` input comes from (see
`test_stream_cache_policy.py` for the `stream_column` wiring that supplies
it)."""

from __future__ import annotations

import pytest
from normexec.cache_policy import CACHE_SKIP_DISTINCT_RATIO_THRESHOLD, decide_cache_policy


@pytest.mark.unit
class TestDecideCachePolicy:
    def test_low_cardinality_keeps_the_cache(self) -> None:
        decision = decide_cache_policy(
            table="Location", column="country", distinct_ratio=0.0003, source="connector_estimate"
        )
        assert decision.use_cache is True
        assert decision.distinct_ratio == 0.0003
        assert decision.table == "Location"
        assert decision.column == "country"
        assert decision.source == "connector_estimate"

    def test_high_cardinality_skips_the_cache(self) -> None:
        decision = decide_cache_policy(
            table="Company", column="name", distinct_ratio=0.971, source="connector_estimate"
        )
        assert decision.use_cache is False

    def test_none_ratio_defaults_to_keeping_the_cache(self) -> None:
        """An empty table/chunk has nothing to justify skipping the cache
        with — stays at this run's pre-Phase-3 default (use the cache)."""
        decision = decide_cache_policy(
            table="t", column="c", distinct_ratio=None, source="first_chunk_sample"
        )
        assert decision.use_cache is True
        assert decision.distinct_ratio is None

    def test_threshold_boundary_is_strictly_less_than(self) -> None:
        exactly_at_threshold = decide_cache_policy(
            table="t",
            column="c",
            distinct_ratio=CACHE_SKIP_DISTINCT_RATIO_THRESHOLD,
            source="connector_estimate",
        )
        assert exactly_at_threshold.use_cache is False

        just_under = decide_cache_policy(
            table="t",
            column="c",
            distinct_ratio=CACHE_SKIP_DISTINCT_RATIO_THRESHOLD - 0.0001,
            source="connector_estimate",
        )
        assert just_under.use_cache is True

    def test_plan_worked_examples_land_on_the_expected_side(self) -> None:
        """The plan's own real, measured cardinality table — every "keep
        caching" column should stay well clear of the threshold, and
        every "skip" column likewise, so this threshold isn't a coin
        flip for the real data it was chosen against."""
        keep_examples = {
            "Location.country": 0.0003,
            "Location.city": 0.032,
            "Person.firstName": 0.041,
            "Location.zip": 0.081,
            "Person.lastName": 0.115,
            "Experience.title": 0.233,
        }
        skip_examples = {
            "Person.fullName": 0.768,
            "Company.name": 0.971,
            "PersonContact.contactString": 0.999,
        }
        for label, ratio in keep_examples.items():
            decision = decide_cache_policy(
                table="t", column="c", distinct_ratio=ratio, source="connector_estimate"
            )
            assert decision.use_cache is True, f"{label} ({ratio}) should keep the cache"
        for label, ratio in skip_examples.items():
            decision = decide_cache_policy(
                table="t", column="c", distinct_ratio=ratio, source="connector_estimate"
            )
            assert decision.use_cache is False, f"{label} ({ratio}) should skip the cache"

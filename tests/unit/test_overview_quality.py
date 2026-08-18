"""Unit tests for normanalysis's overview/quality aggregation (M7,
Source.txt §90, §93).
"""

from __future__ import annotations

import pytest
from normalizers.email import EmailNormalizer
from normalizers.phone import PhoneNormalizer
from normcore.enums import FieldSemanticType

from normanalysis import compute_overview, compute_quality_report
from normcore import NormalizationContext, NormalizationRun, NormalizationRunMetrics, RunStatus


def _run(**metrics: int) -> NormalizationRun:
    return NormalizationRun(
        id="r1",
        profile_id="p1",
        profile_version="v1",
        env_id="e" * 64,
        source_snapshot="s",
        started_at="2026-08-18T00:00:00Z",
        finished_at="2026-08-18T00:00:01Z",
        status=RunStatus.COMPLETED,
        metrics=NormalizationRunMetrics(**metrics),
    )


@pytest.mark.unit
class TestComputeOverview:
    def test_empty_state_is_all_zero(self) -> None:
        report = compute_overview([], [])
        assert report.fields_analyzed == 0
        assert report.rows_processed == 0

    def test_aggregates_across_executed_runs(self) -> None:
        normalizer = EmailNormalizer()
        ctx = NormalizationContext(field_name="email", semantic_type=FieldSemanticType.EMAIL)
        originals = ["x@example.com", "not-an-email"]
        results = [normalizer.normalize(v, ctx) for v in originals]
        run = _run(records_processed=2, changed_values=1, warnings=0, errors=0)

        report = compute_overview(
            ["email"],
            [(run, "email", results)],
        )
        assert report.fields_analyzed == 1
        assert report.fields_normalized == 1
        assert report.rows_processed == 2

    def test_unexecuted_profile_fields_still_counted_as_analyzed(self) -> None:
        report = compute_overview(["unexecuted_field"], [])
        assert report.fields_analyzed == 1
        assert report.fields_normalized == 0


@pytest.mark.unit
class TestComputeQualityReport:
    def test_empty_state_all_metrics_zero(self) -> None:
        report = compute_quality_report([])
        assert len(report.metrics) == 7
        assert all(m.count == 0 and m.total_evaluated == 0 for m in report.metrics)

    def test_malformed_email_counted(self) -> None:
        normalizer = EmailNormalizer()
        ctx = NormalizationContext(field_name="email", semantic_type=FieldSemanticType.EMAIL)
        originals = ["x@example.com", "not-an-email"]
        results = [normalizer.normalize(v, ctx) for v in originals]

        report = compute_quality_report([(FieldSemanticType.EMAIL, results)])
        email_metric = next(m for m in report.metrics if m.name == "Malformed emails")
        assert email_metric.total_evaluated == 2
        assert email_metric.count == 1

    def test_unrelated_semantic_type_does_not_pollute_metric(self) -> None:
        normalizer = PhoneNormalizer()
        ctx = NormalizationContext(field_name="phone", semantic_type=FieldSemanticType.PHONE)
        results = [normalizer.normalize("+1-202-555-0143", ctx)]

        report = compute_quality_report([(FieldSemanticType.PHONE, results)])
        email_metric = next(m for m in report.metrics if m.name == "Malformed emails")
        assert email_metric.total_evaluated == 0
        assert email_metric.count == 0

"""Structural exclusions, the per-column quality report, the idempotency
gate, and the scoped error count.

Four separate items, one file, because all four are about what a clone job
can TELL you about itself afterwards — and three of the four exist because
something was invisible: a key column being normalized, a column's real
outcome, and a row count that belonged to someone else's job.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest
from normapi.app import build_normalizer_registry
from normapi.clone_executor import (
    _ColumnStats,
    _infer_field_configs,
    _key_columns,
    _report_column_findings,
)
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType, NormalizationStatus
from normcore.models import NormalizedValue
from normio.connector import ColumnInfo

from normapi import clone_executor


@dataclasses.dataclass
class _FakeSource:
    """Just enough of a source connector for inference."""

    columns: dict[str, list[ColumnInfo]]
    keys: dict[str, list[str]]
    rows: dict[str, list[dict[str, Any]]] = dataclasses.field(default_factory=dict)

    def get_columns(self, table: str) -> list[ColumnInfo]:
        return self.columns[table]

    def get_primary_key(self, table: str) -> list[str]:
        return self.keys.get(table, [])

    def read_table(self, table: str, columns: list[str], batch_size: int) -> list[Any]:
        return []


def _text(name: str) -> ColumnInfo:
    return ColumnInfo(name=name, native_type="text")


class _Recorder:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def save_clone_job_errors(self, job_id: str, rows: list[dict[str, Any]]) -> None:
        self.rows.extend(rows)


@pytest.mark.unit
class TestKeyColumnsAreNeverInferred:
    def test_a_textual_key_column_gets_no_semantic_type(self) -> None:
        """The case that made this a rule.

        On a real source, `PersonContact.freeMails` was detected as EMAIL at
        0.95 — and it is that table's entire sorting key. Normalization is
        many-to-one, so folding a key merges rows that were distinct; on a
        ReplacingMergeTree the merge is silent and permanent.
        """
        source = _FakeSource(
            columns={"PersonContact": [_text("freeMails"), _text("workEmail")]},
            keys={"PersonContact": ["freeMails"]},
        )
        inferred = _infer_field_configs(source, ["PersonContact"], {}, build_normalizer_registry())
        assert inferred.get("PersonContact", {}).get("freeMails") is None
        assert inferred["PersonContact"]["workEmail"] == FieldSemanticType.EMAIL.value

    def test_an_explicit_config_still_wins_on_a_key_column(self) -> None:
        """A structural exclusion governs what is GUESSED, never what an
        operator asked for."""
        source = _FakeSource(columns={"t": [_text("freeMails")]}, keys={"t": ["freeMails"]})
        explicit = {"t": {"freeMails": FieldSemanticType.EMAIL.value}}
        inferred = _infer_field_configs(source, ["t"], explicit, build_normalizer_registry())
        # Nothing inferred, and the caller's own config is untouched.
        assert inferred.get("t", {}) == {}
        assert explicit["t"]["freeMails"] == FieldSemanticType.EMAIL.value

    def test_key_columns_come_from_the_source_not_from_names(self) -> None:
        source = _FakeSource(columns={"t": [_text("a")]}, keys={"t": ["a", "b"]})
        assert _key_columns(source, "t") == ["a", "b"]


@pytest.mark.unit
class TestPerColumnQuality:
    def test_every_status_is_counted_not_a_chosen_few(self) -> None:
        """The report's categories must sum to its own denominator.

        `NormalizationStatus` has nine members; the first version of this
        counted three of them. Measured on a real column, 48,416 of 50,000
        values were UNCHANGED — already clean — and the report did not
        mention them at all, so it looked like normalization had done
        almost nothing.
        """
        stats = _ColumnStats()
        recorded = (
            NormalizationStatus.NORMALIZED,
            NormalizationStatus.NORMALIZED,
            NormalizationStatus.UNCHANGED,
            NormalizationStatus.REPAIRED,
            NormalizationStatus.PARSED,
            NormalizationStatus.AMBIGUOUS,
            NormalizationStatus.INVALID,
        )
        for status in recorded:
            stats.record_status(status)
        stats.total = len(recorded)
        quality = stats.quality()
        assert sum(quality["statuses"].values()) == quality["values"]
        assert quality["statuses"]["NORMALIZED"] == 2
        assert quality["statuses"]["UNCHANGED"] == 1
        assert quality["statuses"]["REPAIRED"] == 1

    def test_no_status_can_be_dropped_by_omission(self) -> None:
        """Every member of the enum is countable, so adding one cannot
        silently start losing values."""
        stats = _ColumnStats()
        for status in NormalizationStatus:
            stats.record_status(status)
        stats.total = len(list(NormalizationStatus))
        assert sum(stats.quality()["statuses"].values()) == stats.total

    def test_ambiguous_is_not_a_failure(self) -> None:
        """A POSTCODE column with no country is 100% AMBIGUOUS and
        perfectly well typed. The report must be able to say that without
        it reading as a problem."""
        stats = _ColumnStats(total=100)
        for _ in range(100):
            stats.record_status(NormalizationStatus.AMBIGUOUS)
        recorder = _Recorder()
        _report_column_findings(
            recorder,  # type: ignore[arg-type]
            "job",
            "t",
            stats={"zip": stats},
            semantic_types={"zip": FieldSemanticType.POSTCODE},
            ceiling=None,
        )
        assert recorder.rows == []
        assert stats.quality()["statuses"] == {"AMBIGUOUS": 100}


@pytest.mark.unit
class TestIdempotencyGate:
    def test_one_unsettled_value_is_reported_with_no_threshold(self) -> None:
        """§71 is `normalize(normalize(x)) == normalize(x)`. One
        counterexample is a defect, not a rate to tolerate — unlike the
        null-rate and mis-typing findings, which both need a share of the
        column before they mean anything."""
        stats = _ColumnStats(total=1000, checked_stable=50)
        stats.record_unstable("Acme  Corp", "Acme Corp")
        recorder = _Recorder()
        _report_column_findings(
            recorder,  # type: ignore[arg-type]
            "job",
            "t",
            stats={"name": stats},
            semantic_types={"name": FieldSemanticType.COMPANY_NAME},
            ceiling=None,
        )
        assert len(recorder.rows) == 1
        error = recorder.rows[0]["error"]
        assert "not converging" in error
        assert "'Acme  Corp' -> 'Acme Corp'" in error

    def test_a_stable_column_reports_nothing(self) -> None:
        stats = _ColumnStats(total=1000, checked_stable=50)
        recorder = _Recorder()
        _report_column_findings(
            recorder,  # type: ignore[arg-type]
            "job",
            "t",
            stats={"name": stats},
            semantic_types={"name": FieldSemanticType.COMPANY_NAME},
            ceiling=None,
        )
        assert recorder.rows == []

    def test_only_values_normalization_changed_are_checked(self) -> None:
        """An output equal to its input is a fixed point by inspection, so
        checking it would spend a normalize call to learn nothing."""
        calls: list[list[str]] = []

        def fake_normalize_distinct(pool: Any, planner: Any, values: list[str], **kw: Any) -> dict:
            calls.append(values)
            return {}

        original = clone_executor._normalize_distinct
        clone_executor._normalize_distinct = fake_normalize_distinct  # type: ignore[assignment]
        try:

            def value(display: str) -> NormalizedValue:
                return NormalizedValue(
                    original=display,
                    display=display,
                    normalization_status=NormalizationStatus.NORMALIZED,
                    profile_version="",
                    env_id="",
                    semantic_type=FieldSemanticType.COMPANY_NAME,
                    context_hash="",
                )

            unchanged = value("Acme Corp")
            changed = value("Acme Corp")
            clone_executor._check_idempotent(
                {"Acme Corp": unchanged, "Acme  Corp": changed},
                pool=None,
                planner=None,
                ctx=NormalizationContext(
                    field_name="name", semantic_type=FieldSemanticType.COMPANY_NAME
                ),
                stats=_ColumnStats(),
            )
        finally:
            clone_executor._normalize_distinct = original  # type: ignore[assignment]
        # One call, carrying only the value whose display differs from its key.
        assert calls == [["Acme Corp"]]

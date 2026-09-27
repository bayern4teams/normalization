"""Job-level normalization context, within-row country propagation, and
the column-level null-rate report.

Three things that only exist because a real 35.1M-row run showed what was
missing: every locale-dependent normalizer was refusing to guess with no
country/locale to guess from, a resolved COUNTRY column's answer was
thrown away instead of reaching its own row's other columns, and typing a
column NULLed 38.5% of it with nothing anywhere saying so.
"""

from __future__ import annotations

from typing import Any

import pytest
from normapi.clone_executor import (
    CloneJobStateError,
    _group_by_country,
    _record_country_signal,
    _report_null_rates,
)
from normapi.schemas import CloneJobCreateRequest
from normcore.enums import FieldSemanticType, NormalizationStatus
from normcore.models import NormalizedValue


def _resolved(alpha2: str | None) -> NormalizedValue:
    return NormalizedValue(
        original="whatever",
        structured={"alpha2": alpha2} if alpha2 else {},
        normalization_status=NormalizationStatus.NORMALIZED,
        profile_version="",
        env_id="",
        semantic_type=FieldSemanticType.COUNTRY,
        context_hash="",
    )


def _rows(*offsets: int) -> list[tuple[int, dict[str, Any]]]:
    return [(offset, {"x": str(offset)}) for offset in offsets]


@pytest.mark.unit
class TestCountrySignals:
    def test_a_resolved_country_column_records_its_alpha2(self) -> None:
        signals: dict[int, tuple[str, str]] = {}
        errors: list[str] = []
        _record_country_signal(signals, 7, "CountryCode", _resolved("US"), errors)
        assert signals == {7: ("CountryCode", "US")}
        assert errors == []

    def test_an_unresolved_country_column_records_nothing(self) -> None:
        signals: dict[int, tuple[str, str]] = {}
        _record_country_signal(signals, 7, "CountryCode", _resolved(None), [])
        assert signals == {}

    def test_two_country_columns_that_agree_are_not_a_conflict(self) -> None:
        signals: dict[int, tuple[str, str]] = {}
        errors: list[str] = []
        _record_country_signal(signals, 1, "a", _resolved("DE"), errors)
        _record_country_signal(signals, 1, "b", _resolved("DE"), errors)
        assert errors == []
        assert signals[1][1] == "DE"

    def test_two_country_columns_that_disagree_are_reported_and_neither_wins(self) -> None:
        """Picking the first, or the more confident, is exactly the guess
        this codebase does not make."""
        signals: dict[int, tuple[str, str]] = {}
        errors: list[str] = []
        _record_country_signal(signals, 1, "billing", _resolved("GB"), errors)
        _record_country_signal(signals, 1, "shipping", _resolved("DE"), errors)
        assert errors == ["country conflict: shipping says DE, billing says GB"]
        assert signals[1][1] == ""

    def test_a_contradicted_row_cannot_be_resurrected_by_a_third_column(self) -> None:
        signals: dict[int, tuple[str, str]] = {}
        errors: list[str] = []
        for column, alpha2 in (("a", "GB"), ("b", "DE"), ("c", "GB")):
            _record_country_signal(signals, 1, column, _resolved(alpha2), errors)
        assert signals[1][1] == ""
        assert len(errors) == 1


@pytest.mark.unit
class TestGroupByCountry:
    def test_rows_are_partitioned_by_their_own_row_country(self) -> None:
        groups = _group_by_country(
            _rows(1, 2, 3), {1: ("c", "US"), 2: ("c", "GB"), 3: ("c", "US")}, None
        )
        assert sorted(groups) == ["GB", "US"]
        assert [offset for offset, _ in groups["US"]] == [1, 3]

    def test_a_row_with_no_signal_falls_back_to_the_job_country(self) -> None:
        groups = _group_by_country(_rows(1, 2), {1: ("c", "US")}, "FR")
        assert sorted(groups) == ["FR", "US"]
        assert [offset for offset, _ in groups["FR"]] == [2]

    def test_a_contradicted_row_falls_back_rather_than_using_either_answer(self) -> None:
        groups = _group_by_country(_rows(1), {1: ("c", "")}, "FR")
        assert list(groups) == ["FR"]

    def test_no_signals_and_no_job_country_is_one_group_of_none(self) -> None:
        """The pre-signals behaviour, and the pre-signals cost: one
        dispatcher batch per column, not one per country."""
        groups = _group_by_country(_rows(1, 2), {}, None)
        assert groups == {None: _rows(1, 2)}


class _CapturingPersistence:
    def __init__(self) -> None:
        self.saved: list[dict[str, Any]] = []

    def save_clone_job_errors(self, job_id: str, errors: Any) -> None:
        self.saved.extend(errors)


@pytest.mark.unit
class TestNullRateReport:
    def test_a_gutted_column_gets_one_report_row(self) -> None:
        p = _CapturingPersistence()
        _report_null_rates(p, "job", "Company", {"revenue": [1000, 385]}, None)  # type: ignore[arg-type]
        assert len(p.saved) == 1
        row = p.saved[0]
        assert row["table_name"] == "Company"
        assert row["field"] == "revenue"
        # A column-level finding cannot collide with a real row's offset.
        assert row["row_index"] == -1
        assert "38.5%" in row["error"]
        assert "385/1000" in row["error"]

    def test_ordinary_messiness_is_not_reported(self) -> None:
        p = _CapturingPersistence()
        _report_null_rates(p, "job", "Company", {"founded": [1000, 4]}, None)  # type: ignore[arg-type]
        assert p.saved == []

    def test_an_empty_source_column_is_not_a_loss(self) -> None:
        p = _CapturingPersistence()
        _report_null_rates(p, "job", "Company", {"unused": [0, 0]}, None)  # type: ignore[arg-type]
        assert p.saved == []

    def test_a_ceiling_fails_the_job_instead_of_reporting(self) -> None:
        p = _CapturingPersistence()
        with pytest.raises(CloneJobStateError, match="max_new_null_rate"):
            _report_null_rates(p, "job", "Company", {"revenue": [1000, 385]}, 0.10)  # type: ignore[arg-type]

    def test_a_ceiling_above_the_loss_still_only_reports(self) -> None:
        p = _CapturingPersistence()
        _report_null_rates(p, "job", "Company", {"revenue": [1000, 385]}, 0.50)  # type: ignore[arg-type]
        assert len(p.saved) == 1


@pytest.mark.unit
class TestRequestDefaults:
    def _request(self, **kwargs: Any) -> CloneJobCreateRequest:
        return CloneJobCreateRequest(
            source_connection_id="s",
            source_database="src",
            destination_connection_id="d",
            destination_database="dst",
            **kwargs,
        )

    def test_typed_columns_are_on_by_default(self) -> None:
        """Flipped once the null-rate report existed to say what typing
        costs — an untyped clone of a numeric column cannot be summed,
        which is most of the reason to normalize it."""
        assert self._request().typed_destination_columns is True

    def test_country_and_locale_are_never_inferred(self) -> None:
        """A wrong locale silently changes what a number MEANS."""
        request = self._request()
        assert request.country is None
        assert request.locale is None

    def test_a_null_rate_ceiling_must_be_a_fraction(self) -> None:
        with pytest.raises(ValueError, match="less than or equal to 1"):
            self._request(max_new_null_rate=38.5)

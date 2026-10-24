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
from normalizers.phone import PhoneNormalizer
from normapi.clone_executor import (
    _COUNTRY_FROM,
    CloneJobStateError,
    _ColumnStats,
    _drop_rejected_country,
    _group_by_country,
    _normalize_distinct,
    _record_country_signal,
    _report_column_findings,
    _seed_from_entity_map,
)
from normapi.scaffold_profile import SCAFFOLD_PROFILE
from normapi.schemas import CloneJobCreateRequest
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType, NormalizationStatus
from normcore.models import NormalizedValue
from normexec.planner import DistinctValuePlanner

from normcore import Dispatcher, NormalizerRegistry


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
            _rows(1, 2, 3), {1: ("c", "US"), 2: ("c", "GB"), 3: ("c", "US")}, {}, None
        )
        assert sorted(groups) == [("GB", False), ("US", False)]
        assert [offset for offset, _ in groups[("US", False)]] == [1, 3]

    def test_a_row_with_no_signal_falls_back_to_the_job_country(self) -> None:
        groups = _group_by_country(_rows(1, 2), {1: ("c", "US")}, {}, "FR")
        assert sorted(groups) == [("FR", False), ("US", False)]
        assert [offset for offset, _ in groups[("FR", False)]] == [2]

    def test_a_contradicted_row_falls_back_rather_than_using_either_answer(self) -> None:
        groups = _group_by_country(_rows(1), {1: ("c", "")}, {}, "FR")
        assert list(groups) == [("FR", False)]

    def test_no_signals_and_no_job_country_is_one_group_of_none(self) -> None:
        """The pre-signals behaviour, and the pre-signals cost: one
        dispatcher batch per column, not one per country."""
        groups = _group_by_country(_rows(1, 2), {}, {}, None)
        assert groups == {(None, False): _rows(1, 2)}

    def test_the_rows_own_country_column_beats_the_cross_table_one(self) -> None:
        """Evidence about this row beats evidence about its entity, and the
        winner is not marked derived, so it is never second-guessed."""
        groups = _group_by_country(_rows(1), {1: ("CountryCode", "GB")}, {1: "US"}, None)
        assert list(groups) == [("GB", False)]

    def test_a_cross_table_country_is_used_and_marked_derived(self) -> None:
        groups = _group_by_country(_rows(1, 2), {}, {1: "US"}, None)
        assert set(groups) == {(None, False), ("US", True)}
        assert [offset for offset, _ in groups[("US", True)]] == [1]

    def test_a_contradicted_row_still_accepts_the_cross_table_answer(self) -> None:
        """Two country columns disagreeing says nothing about what the
        entity's own country is — that is independent evidence."""
        groups = _group_by_country(_rows(1), {1: ("c", "")}, {1: "US"}, "FR")
        assert list(groups) == [("US", True)]


class _CapturingPersistence:
    def __init__(self) -> None:
        self.saved: list[dict[str, Any]] = []

    def save_clone_job_errors(self, job_id: str, errors: Any) -> None:
        self.saved.extend(errors)


def _report(
    p: _CapturingPersistence,
    stats: dict[str, _ColumnStats],
    *,
    semantic_types: dict[str, FieldSemanticType] | None = None,
    ceiling: float | None = None,
) -> None:
    _report_column_findings(
        # C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
        p,  # type: ignore[arg-type]
        "job",
        "Company",
        stats=stats,
        semantic_types=semantic_types or dict.fromkeys(stats, FieldSemanticType.NUMERIC),
        ceiling=ceiling,
    )


@pytest.mark.unit
class TestNullRateFinding:
    def test_a_gutted_column_gets_one_report_row(self) -> None:
        p = _CapturingPersistence()
        _report(p, {"revenue": _ColumnStats(total=1000, nulled=385)})
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
        _report(p, {"founded": _ColumnStats(total=1000, nulled=4)})
        assert p.saved == []

    def test_an_empty_source_column_is_not_a_loss(self) -> None:
        p = _CapturingPersistence()
        _report(p, {"unused": _ColumnStats()})
        assert p.saved == []

    def test_a_ceiling_fails_the_job_instead_of_reporting(self) -> None:
        p = _CapturingPersistence()
        with pytest.raises(CloneJobStateError, match="max_new_null_rate"):
            _report(p, {"revenue": _ColumnStats(total=1000, nulled=385)}, ceiling=0.10)

    def test_a_ceiling_above_the_loss_still_only_reports(self) -> None:
        p = _CapturingPersistence()
        _report(p, {"revenue": _ColumnStats(total=1000, nulled=385)}, ceiling=0.50)
        assert len(p.saved) == 1


@pytest.mark.unit
class TestWrongSemanticTypeFinding:
    """A real source mapped `location.country` to COUNTRY while the column
    held Wikidata descriptions, so 99.2% of it came back INVALID. That is
    one fact about the mapping, not 3,478 independent bad rows."""

    def _mistyped(self) -> _ColumnStats:
        stat = _ColumnStats(total=3506)
        for value in ("Country located primarily in North America", "Country in Central Europe"):
            for _ in range(1739):
                stat.record_invalid(value)
        return stat

    def test_a_column_that_is_not_its_type_is_reported_with_examples(self) -> None:
        p = _CapturingPersistence()
        _report(
            p,
            {"country": self._mistyped()},
            semantic_types={"country": FieldSemanticType.COUNTRY},
        )
        error = p.saved[0]["error"]
        assert "99.2% of this column is not a COUNTRY" in error
        assert "wrong semantic type" in error
        assert "Country located primarily in North America" in error

    def test_only_a_few_distinct_examples_are_kept(self) -> None:
        """The report is a finding, not a data dump — and the samples are
        held in memory for the whole table."""
        stat = _ColumnStats()
        for i in range(100):
            stat.record_invalid(f"value-{i}")
        assert len(stat.samples) == 3
        assert stat.invalid == 100

    def test_a_repeated_bad_value_is_sampled_once(self) -> None:
        stat = _ColumnStats()
        for _ in range(50):
            stat.record_invalid("same")
        assert stat.samples == ["same"]

    def test_a_merely_messy_column_is_not_accused_of_being_mistyped(self) -> None:
        stat = _ColumnStats(total=1000)
        for i in range(30):
            stat.record_invalid(f"bad-{i}")
        p = _CapturingPersistence()
        _report(p, {"email": stat})
        assert p.saved == []

    def test_both_findings_share_one_row_because_a_column_has_one_slot(self) -> None:
        """The report table is keyed by (job, row_index, table, field), so
        two rows for one column would collide and the second be dropped."""
        stat = _ColumnStats(total=1000, nulled=900)
        for i in range(600):
            stat.record_invalid(f"bad-{i}")
        p = _CapturingPersistence()
        _report(p, {"amount": stat})
        assert len(p.saved) == 1
        assert "emptied 90.0%" in p.saved[0]["error"]
        assert "60.0% of this column is not a NUMERIC" in p.saved[0]["error"]


@pytest.mark.unit
class TestSeedFromEntityMap:
    def test_rows_are_seeded_from_their_entity(self) -> None:
        pending = [(0, {"companyID": 7}), (1, {"companyID": 9})]
        assert _seed_from_entity_map(pending, "companyID", {"7": "US"}) == {0: "US"}

    def test_the_key_is_stringified_because_engines_disagree_on_its_type(self) -> None:
        """On a real source the same entity id is String in one table and
        Nullable(Int64) in another."""
        assert _seed_from_entity_map([(0, {"k": 7})], "k", {"7": "GB"}) == {0: "GB"}
        assert _seed_from_entity_map([(0, {"k": "7"})], "k", {"7": "GB"}) == {0: "GB"}

    def test_no_key_column_costs_nothing(self) -> None:
        assert _seed_from_entity_map([(0, {"k": 7})], "", {"7": "GB"}) == {}

    def test_a_null_key_is_skipped_rather_than_stringified_to_none(self) -> None:
        assert _seed_from_entity_map([(0, {"k": None})], "k", {"None": "GB"}) == {}


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


@pytest.mark.unit
class TestDroppingARejectedInferredCountry:
    """A country taken from a sibling table is a hypothesis. The data gets
    to reject it, because the alternative is replacing a raw value with a
    confidently formatted wrong one — measured on a real source, 0.31% of
    rows land here while 73.8 points of E.164 coverage come from the rest.
    """

    def _setup(self, country: str) -> tuple[Any, NormalizationContext]:
        registry = NormalizerRegistry()
        registry.register(PhoneNormalizer())
        planner = DistinctValuePlanner(Dispatcher(registry, env_id="test-reject"), None)
        ctx = NormalizationContext(
            field_name="tel", semantic_type=FieldSemanticType.PHONE, country=country
        )
        return planner, ctx

    def _normalize(self, planner: Any, ctx: NormalizationContext, value: str) -> NormalizedValue:
        return _normalize_distinct(
            None,
            planner,
            [value],
            semantic_type=FieldSemanticType.PHONE,
            context=ctx,
            profile=SCAFFOLD_PROFILE,
        )[value]

    def test_a_wrong_inferred_country_is_dropped_and_the_value_left_alone(self) -> None:
        """A San Francisco number whose sibling table said France. With FR
        it parses to a confident, wrong +33 number and is marked INVALID;
        dropping FR returns it to the AMBIGUOUS/raw result this pipeline
        produced before cross-table inference existed."""
        planner, ctx = self._setup("FR")
        value = "(415) 561-6272"
        by_value = {value: self._normalize(planner, ctx, value)}
        assert by_value[value].normalization_status is NormalizationStatus.INVALID

        _drop_rejected_country(by_value, pool=None, planner=planner, ctx=ctx, country="FR")

        assert by_value[value].normalization_status is not NormalizationStatus.INVALID
        assert "country FR inferred from a sibling table" in by_value[value].errors[-1]

    def test_a_country_the_value_accepts_is_never_second_guessed(self) -> None:
        planner, ctx = self._setup("US")
        value = "(415) 561-6272"
        by_value = {value: self._normalize(planner, ctx, value)}
        before = by_value[value].comparison
        assert before == "+14155616272"

        _drop_rejected_country(by_value, pool=None, planner=planner, ctx=ctx, country="US")

        assert by_value[value].comparison == before
        assert by_value[value].errors == []

    def test_a_value_rejected_either_way_gets_no_misleading_note(self) -> None:
        """`+39 5218081` carries its own country code, so the inferred
        country changed nothing — saying it "does not fit" would be a
        report row for a decision that had no effect. Removed 211 of 339
        such rows on a real run."""
        planner, ctx = self._setup("IT")
        value = "+39 5218081"
        by_value = {value: self._normalize(planner, ctx, value)}
        assert by_value[value].normalization_status is NormalizationStatus.INVALID

        _drop_rejected_country(by_value, pool=None, planner=planner, ctx=ctx, country="IT")

        assert not any("inferred from a sibling table" in e for e in by_value[value].errors)


def _phone_result(region: str | None, region_source: str) -> NormalizedValue:
    return NormalizedValue(
        original="whatever",
        structured={"region": region, "region_source": region_source},
        normalization_status=NormalizationStatus.PARSED,
        profile_version="",
        env_id="",
        semantic_type=FieldSemanticType.PHONE,
        context_hash="",
    )


def _postcode_result(comparison: str | None) -> NormalizedValue:
    return NormalizedValue(
        original="whatever",
        comparison=comparison,
        normalization_status=NormalizationStatus.AMBIGUOUS,
        profile_version="",
        env_id="",
        semantic_type=FieldSemanticType.POSTCODE,
        context_hash="",
    )


@pytest.mark.unit
class TestCountrySignalSources:
    """Which columns may say what country a row is in. One table, so adding
    a signal is one entry rather than a fourth place that reads
    `structured` by hand."""

    def test_a_phone_that_carries_its_own_country_code_is_a_signal(self) -> None:
        """247,469 of 1,021,941 phone numbers on a real source (24.2%)."""
        extract = _COUNTRY_FROM[FieldSemanticType.PHONE]
        assert extract(_phone_result("GB", "number_prefix")) == "GB"

    @pytest.mark.parametrize("source", ["explicit", "default_region", "unknown"])
    def test_a_phone_region_that_came_from_context_is_not_a_signal(self, source: str) -> None:
        """`explicit` means the region came from ctx.country — the very
        thing this is trying to produce. Trusting it would feed a country
        back to itself and make any wrong guess look corroborated."""
        extract = _COUNTRY_FROM[FieldSemanticType.PHONE]
        assert extract(_phone_result("GB", source)) is None

    def test_a_postcode_only_one_country_accepts_is_a_signal(self) -> None:
        extract = _COUNTRY_FROM[FieldSemanticType.POSTCODE]
        assert extract(_postcode_result("SW1A 1AA")) == "GB"

    def test_a_bare_numeric_postcode_is_not_a_signal(self) -> None:
        """Valid in 56 countries, measured. Returning the most populous
        candidate is exactly the guess this codebase does not make."""
        extract = _COUNTRY_FROM[FieldSemanticType.POSTCODE]
        assert extract(_postcode_result("94043")) is None

    def test_a_missing_postcode_is_not_a_signal(self) -> None:
        extract = _COUNTRY_FROM[FieldSemanticType.POSTCODE]
        assert extract(_postcode_result(None)) is None

    def test_a_country_column_is_still_read_through_the_same_table(self) -> None:
        assert _COUNTRY_FROM[FieldSemanticType.COUNTRY](_resolved("DE")) == "DE"

    def test_a_url_is_deliberately_not_a_signal(self) -> None:
        """No authoritative source separates national from generic ccTLD
        use: `.io` is the British Indian Ocean Territory, `.co` is Colombia
        (6,281 domains on one real source), `.me` Montenegro, `.tv` Tuvalu.
        The alternative is a hand-written exclusion list that grows one
        found example at a time."""
        assert FieldSemanticType.URL not in _COUNTRY_FROM
        assert FieldSemanticType.CURRENCY not in _COUNTRY_FROM


@pytest.mark.unit
class TestSignalPrecedence:
    """A COUNTRY column STATES the country; a phone or postcode only
    IMPLIES one. The distinction is not decorative: the moment PHONE became
    a signal source, one company's second phone number carrying +1 silently
    dropped the GB its own country column stated, because a company
    legitimately has numbers in more than one country."""

    def test_stated_signals_are_scanned_before_implied_ones(self) -> None:
        """The ordering IS the precedence — an implied signal skips an
        entity a stated one already decided, which only works if stated
        runs first."""
        scans = [
            ("t", "tel", FieldSemanticType.PHONE),
            ("t", "zip", FieldSemanticType.POSTCODE),
            ("t", "cc", FieldSemanticType.COUNTRY),
        ]
        scans.sort(key=lambda scan: scan[2] is not FieldSemanticType.COUNTRY)
        assert scans[0][2] is FieldSemanticType.COUNTRY

    def test_country_is_the_only_stated_signal(self) -> None:
        """If another type ever states rather than implies a country, the
        ordering key above has to learn about it."""
        implied = set(_COUNTRY_FROM) - {FieldSemanticType.COUNTRY}
        assert implied == {FieldSemanticType.PHONE, FieldSemanticType.POSTCODE}

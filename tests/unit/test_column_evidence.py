"""ADR-008 amendment 2026-10-17: a column's own values can state its day/month
order. Values that leave no choice (`1/13/14` is month first) prove the order
for the column's ambiguous values (`3/4/14`), when every proof agrees and there
are enough of them; anything less states nothing. Fails before the amendment.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from normalizers.date import DateNormalizer, column_date_evidence
from normcore.context import NormalizationContext
from normcore.enums import FieldSemanticType as T
from normcore.enums import NormalizationStatus as S
from tests.unit.test_adjudication_acceptance import TABLE, _Env, _rows

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

_MDY_PROOFS = [f"1/{d}/14" for d in range(13, 19)]  # six, month first only
_DMY_PROOFS = [f"{d}/1/14" for d in range(13, 19)]


def _ctx(**kw: object) -> NormalizationContext:
    return NormalizationContext(field_name="d", semantic_type=T.DATE, **kw)


class TestEvidence:
    def test_six_agreeing_proofs_state_the_order(self) -> None:
        ev = column_date_evidence([*_MDY_PROOFS, "3/4/14", "2024-01-02", "05/05/2024"])
        assert ev == {"DMY": 0, "MDY": 6, "order": "MDY"}

    def test_five_proofs_are_not_enough(self) -> None:
        # a column mixing both orders evenly shows five agreeing proofs 6% of the time
        assert column_date_evidence(_MDY_PROOFS[:5])["order"] is None

    def test_one_contradiction_states_nothing(self) -> None:
        ev = column_date_evidence([*_MDY_PROOFS * 3, _DMY_PROOFS[0]])
        assert ev == {"DMY": 1, "MDY": 6, "order": None}

    def test_repeats_count_once_and_impossible_parts_prove_nothing(self) -> None:
        ev = column_date_evidence([*_DMY_PROOFS[:5] * 4, "13/13/14", "32/1/14", "13/0/14"])
        assert ev == {"DMY": 5, "MDY": 0, "order": None}


class TestNormalizer:
    def test_the_column_order_resolves_an_ambiguous_value(self) -> None:
        r = DateNormalizer().normalize("3/4/14", _ctx(column_date_order=("MDY", 38)))
        assert r.normalization_status is S.PARSED
        assert r.display == "2014-03-04"
        assert r.structured["column_evidence"] == {
            "order": "MDY",
            "proving_values": 38,
            "contradicting_values": 0,
        }

    def test_without_it_the_value_stays_ambiguous(self) -> None:
        r = DateNormalizer().normalize("3/4/14", _ctx())
        assert r.normalization_status is S.AMBIGUOUS

    def test_a_column_contradicting_the_stated_order_states_nothing(self) -> None:
        # GB states day first; a column whose values prove month first is not read either way
        r = DateNormalizer().normalize("3/4/14", _ctx(country="GB", column_date_order=("MDY", 9)))
        assert r.normalization_status is S.AMBIGUOUS

    def test_an_agreeing_column_changes_nothing_for_a_stated_order(self) -> None:
        stated = DateNormalizer().normalize("3/4/14", _ctx(country="GB"))
        both = DateNormalizer().normalize(
            "3/4/14", _ctx(country="GB", column_date_order=("DMY", 9))
        )
        assert (both.display, both.normalization_status) == (stated.display, S.PARSED)

    def test_a_country_that_states_no_order_takes_the_column_order(self) -> None:
        # Canada's official languages are year first in CLDR: no order for `3/4/14`
        assert DateNormalizer().normalize("3/4/14", _ctx(country="CA")).normalization_status is (
            S.AMBIGUOUS
        )
        r = DateNormalizer().normalize("3/4/14", _ctx(country="CA", column_date_order=("DMY", 7)))
        assert r.display == "2014-04-03"


@pytest.fixture
def env(tmp_path: Path) -> _Env:
    return _Env(tmp_path)


def _clone(env: _Env, column: list[str], job_id: str = "j") -> tuple[list[dict], dict]:
    _, rows, done = env.run([_rows([{"d": v} for v in column])], {"d": "DATE"}, job_id=job_id)
    return rows, done


class TestClone:
    def test_a_proven_column_writes_its_ambiguous_dates(self, env: _Env) -> None:
        rows, job = _clone(env, [*_MDY_PROOFS, "3/4/14", "3/4/14", "11/12/13"])
        assert [r["d"] for r in rows][-3:] == ["2014-03-04", "2014-03-04", "2013-11-12"]
        assert job["column_evidence"][TABLE]["d"] == {"DMY": 0, "MDY": 6, "order": "MDY"}
        assert job["quality"][TABLE]["d"]["statuses"].get("AMBIGUOUS", 0) == 0

    def test_a_mixed_column_stays_ambiguous(self, env: _Env) -> None:
        rows, job = _clone(env, [*_MDY_PROOFS, _DMY_PROOFS[0], "3/4/14"])
        assert rows[-1]["d"] == "3/4/14"
        assert job["column_evidence"][TABLE]["d"]["order"] is None
        assert job["quality"][TABLE]["d"]["statuses"]["AMBIGUOUS"] == 1


class TestKeys:
    def test_a_context_without_a_column_order_hashes_as_before(self) -> None:
        # the hash every stored verdict key and cache key was computed with
        assert _ctx(country="GB").context_hash == (
            "12bcdc8c20da7d57c050448c860961cf871da132cfed0bd619f3821dac994589"
        )

    def test_a_verdict_is_found_and_wins_when_the_column_proves_an_order(self, env: _Env) -> None:
        job_id = "asked"
        env.run([_rows([{"d": "3/4/14"}])], {"d": "DATE"}, job_id=job_id)
        assert env.post(env.key_of("3/4/14"), "2014-04-03").status_code < 400
        rows, _ = _clone(env, [*_MDY_PROOFS, "3/4/14"], job_id="proven")
        # the person read it day first; the column's evidence does not overrule them
        assert rows[-1]["d"] == "2014-04-03"


# --- the decimal mark (the same rule for NUMERIC and MONEY) --------------------------------

_DOT_PROOFS = ["1.5", "12.25", "3,456,789", "1,234.56", "0.75", "7,000,000"]  # six: `.` decimal
_COMMA_PROOFS = ["1,5", "12,25", "3.456.789", "1.234,56", "0,75", "7.000.000"]


def _num(value: str, **kw: object) -> object:
    from normalizers.numeric import NumericNormalizer  # noqa: PLC0415

    ctx = NormalizationContext(field_name="n", semantic_type=T.NUMERIC, **kw)
    return NumericNormalizer().normalize(value, ctx)


class TestDecimalEvidence:
    def test_six_agreeing_proofs_state_the_mark(self) -> None:
        from normalizers.numeric import column_decimal_evidence  # noqa: PLC0415

        assert column_decimal_evidence([*_DOT_PROOFS, "1,234", "42", None]) == {
            ".": 6,
            ",": 0,
            "mark": ".",
        }
        assert column_decimal_evidence(_COMMA_PROOFS)["mark"] == ","

    def test_fewer_or_contradicted_states_nothing(self) -> None:
        from normalizers.numeric import column_decimal_evidence  # noqa: PLC0415

        assert column_decimal_evidence(_DOT_PROOFS[:5])["mark"] is None
        assert column_decimal_evidence([*_DOT_PROOFS, "1,5"]) == {".": 6, ",": 1, "mark": None}

    def test_the_column_mark_resolves_an_ambiguous_number(self) -> None:
        r = _num("1,234", column_decimal_mark=(".", 6))
        assert (r.normalization_status, r.display) == (S.NORMALIZED, "1234")
        assert r.structured["column_evidence"] == {
            "decimal_mark": ".",
            "proving_values": 6,
            "contradicting_values": 0,
        }
        assert _num("1.234", column_decimal_mark=(",", 6)).display == "1234"
        assert _num("1,234", column_decimal_mark=(",", 6)).display == "1.234"
        assert _num("1,234").normalization_status is S.AMBIGUOUS

    def test_a_stated_locale_comes_first_and_a_contradiction_states_nothing(self) -> None:
        # Germany states `,`; a column proving `.` is read neither way
        assert _num("1,234", country="DE", column_decimal_mark=(".", 9)).normalization_status is (
            S.AMBIGUOUS
        )
        # Canada's languages disagree (en `.`, fr `,`): the column decides between them
        assert _num("1,234", country="CA").normalization_status is S.AMBIGUOUS
        assert _num("1,234", country="CA", column_decimal_mark=(".", 9)).display == "1234"
        # an unambiguous value is untouched by the column
        assert _num("1,5", column_decimal_mark=(".", 9)).display == "1.5"

    def test_money_reads_its_amount_with_the_column_mark(self) -> None:
        from normalizers.money import MoneyNormalizer  # noqa: PLC0415

        ctx = NormalizationContext(
            field_name="m", semantic_type=T.MONEY, column_decimal_mark=(".", 9)
        )
        r = MoneyNormalizer().normalize("USD 1,234", ctx)
        assert r.structured["canonical_amount"] == "1234"


class TestDecimalClone:
    def test_a_proven_numeric_column_writes_its_ambiguous_numbers(self, env: _Env) -> None:
        _, rows, job = env.run(
            [_rows([{"n": v} for v in [*_DOT_PROOFS, "1,234"]])], {"n": "NUMERIC"}, job_id="n"
        )
        assert job["column_evidence"][TABLE]["n"] == {".": 6, ",": 0, "mark": "."}
        assert rows[-1]["n"] == "1234"

    def test_a_mixed_column_stays_ambiguous(self, env: _Env) -> None:
        _, rows, job = env.run(
            [_rows([{"n": v} for v in [*_DOT_PROOFS, "1,5", "1,234"]])], {"n": "NUMERIC"}
        )
        assert job["column_evidence"][TABLE]["n"]["mark"] is None
        assert rows[-1]["n"] == "1,234"


def test_neither_proof_moves_a_verdict_key() -> None:
    from normapi.adjudication import verdict_key  # noqa: PLC0415

    plain = NormalizationContext(field_name="n", semantic_type=T.NUMERIC)
    keys = {
        verdict_key(T.NUMERIC, "1,234", plain.model_copy(update=proof), "v1")
        for proof in (
            {},
            {"column_decimal_mark": (".", 9)},
            {"column_date_order": ("MDY", 9)},
        )
    }
    assert len(keys) == 1

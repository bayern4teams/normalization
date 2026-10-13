"""D5 acceptance (derive mode): the pre-insert cast gate fits the TARGET column.

Derived from improvement-report D5 (Evidence / Fix), plan 2.4 and 9 "D5", ADR-020 and the
lead's finding: `coerce(semantic_type, value)` knew nothing about the engine or the column's
precision/scale, so a finite decimal wider than the column passed the gate and reached INSERT,
where one rejected row aborts the chunk and the error rows with it (decision #8).

Assumed API (see .handoff/D5.acceptance.md in git history):
`coerce(semantic_type, value, engine="postgres")`.
The helpers below pass `engine` only if `coerce` / `_apply_value` / `_apply_column` accept it,
so on today's code the failures are the real overflow failures and not a TypeError wall.

Truth for "fits" is parsed from `storage_types.sql_type(...)` here, never hand-listed.
"""

from __future__ import annotations

import ast
import contextlib
import decimal
import inspect
import re
import signal
import subprocess
import tempfile
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

import pytest
from normapi.app import build_dispatcher
from normapi.clone_executor import _normalize_table
from normapi.pg_persistence import PgPersistence
from normcore.enums import FieldSemanticType, NormalizationStatus
from normcore.models import NormalizedValue
from normexec.planner import DistinctValuePlanner

from normapi import clone_executor
from normio import storage_types

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

ROOT = Path(__file__).resolve().parents[2]
STORAGE_TYPES_PY = "packages/normio/src/normio/storage_types.py"
ENGINES = ("postgres", "clickhouse")
# Parameter names the executor may use to receive the engine.
_ENGINE_PARAMS = ("engine", "dest_engine", "destination_engine")
# PostgreSQL docs, "Numeric Types": NUMERIC holds "up to 131072 digits before the decimal point".
# External fact, not a corpus count; used only by TestPostgresHardCeiling.
PG_NUMERIC_MAX_INT_DIGITS = 131072

TYPED = sorted(t.value for t in FieldSemanticType if storage_types.is_typed(t.value))
DECIMAL_TYPED = [t for t in TYPED if "NUMERIC" in (storage_types.sql_type(t, "postgres") or "")]


# --------------------------------------------------------------------------- helpers


@contextlib.contextmanager
def _deadline(seconds: int = 10) -> Iterator[None]:
    """A gate that materialises 1e999999999 as an int would hang or exhaust memory."""

    def _boom(*_: object) -> None:
        msg = f"did not return within {seconds}s"
        raise TimeoutError(msg)

    old = signal.signal(signal.SIGALRM, _boom)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


def _coerce(semantic_type: str, value: object, engine: str) -> tuple[object | None, str | None]:
    kwargs = (
        {"engine": engine} if "engine" in inspect.signature(storage_types.coerce).parameters else {}
    )
    with _deadline():
        return storage_types.coerce(semantic_type, value, **kwargs)


def _limits(semantic_type: str, engine: str) -> tuple[int | None, int | None]:
    """(max integer digits, scale) of the column, parsed from the engine type string.
    (None, None) when the type string states no precision (unbounded Postgres NUMERIC)."""
    type_string = storage_types.sql_type(semantic_type, engine)
    assert type_string, f"{semantic_type} must be natively typed on {engine}"
    match = re.search(r"\(\s*(\d+)\s*,\s*(\d+)\s*\)", type_string)
    if not match:
        return None, None
    precision, scale = int(match.group(1)), int(match.group(2))
    return precision - scale, scale


def _fit_problem(semantic_type: str, engine: str, value: object) -> str | None:
    """None when `value` (a coerce result) fits the column, else why not."""
    if semantic_type == "BOOLEAN":
        return None if isinstance(value, bool) else f"not a bool: {value!r}"
    if not isinstance(value, decimal.Decimal) or not value.is_finite():
        return f"typed decimal column got {type(value).__name__}: {value!r}"
    int_digits, scale = _limits(semantic_type, engine)
    if int_digits is None:
        return None
    # Rounding to the column scale can carry into one more integer digit (99.9999 -> 100.000).
    ctx = decimal.Context(prec=int_digits + (scale or 0) + 10, rounding=decimal.ROUND_HALF_UP)
    wide = value.adjusted() >= int_digits
    if not wide:
        quantum = decimal.Decimal(1).scaleb(-(scale or 0))
        wide = value.quantize(quantum, context=ctx).adjusted() >= int_digits
    return f"more than {int_digits} integer digits ({engine}): {str(value)[:30]}" if wide else None


def _assert_clean(semantic_type: str, engine: str, value: object, *, empty_ok: bool = True) -> None:
    cast, error = _coerce(semantic_type, value, engine)
    if cast is None:
        if error is None:
            assert empty_ok, f"{value!r}: (None, None) is only for empty input"
        else:
            assert isinstance(error, str)
            assert error.strip()
        return
    assert error is None, f"value and error both set: {cast!r}, {error!r}"
    problem = _fit_problem(semantic_type, engine, cast)
    assert problem is None, f"{semantic_type}/{engine} {str(value)[:40]!r}: {problem}"


def _digits(n: int) -> str:
    return "9" * n


ADVERSARIAL: list[tuple[str, object]] = [
    ("d-date", "d1989-12-11"),
    ("nan", "NaN"),
    ("snan", "sNaN"),
    ("inf", "inf"),
    ("neg-inf", "-Infinity"),
    ("1e999", "1e999"),
    ("neg-1e999", "-1e999"),
    ("1e30", "1e30"),
    ("1e35", "1e35"),
    ("comma", "1,234"),
    ("eu-decimal", "1.234,56"),
    ("nul", "\x00"),
    ("nul-in-number", "12\x0034"),
    ("ten40", "1" + "0" * 40),
    ("neg-ten40", "-1" + "0" * 40),
    ("ten40-frac", "1" + "0" * 40 + ".5"),
    ("yes-please", "yes please"),
    ("empty", ""),
    ("space", " "),
    ("tabs-newlines", " \t\r\n "),
    ("lone-surrogate", "\ud800"),
    ("surrogate-in-number", "12\udc0034"),
    ("digits-5000", _digits(5000)),
    ("neg-digits-5000", "-" + _digits(5000)),
    ("frac-digits-5000", "0." + _digits(5000)),
    ("exp-huge", "9e999999999"),
    ("exp-tiny", "1e-999999999"),
    ("exp-overflow-literal", "1e99999999999999999999"),
    ("fullwidth-digits", "\uff11\uff12\uff13"),
    ("underscore", "1_000"),
    ("sign-only", "-"),
    ("true-upper", "TRUE"),
    ("true-padded", " true "),
    ("none", None),
    ("float-inf", float("inf")),
    ("float-nan", float("nan")),
    ("float-1e30", 1e30),
    ("int-ten40", 10**40),
    ("decimal-inf", decimal.Decimal("Infinity")),
    ("bytes", b"12"),
    ("bool-true", True),
]
_IDS = [name for name, _ in ADVERSARIAL]
_VALUES = [value for _, value in ADVERSARIAL]


# --------------------------------------------------------------------------- the API


@pytest.mark.unit
class TestApiShape:
    def test_typed_types_are_derived_not_hand_listed(self) -> None:
        assert {"NUMERIC", "MONEY", "BOOLEAN"} <= set(TYPED)
        for semantic_type in TYPED:
            for engine in ENGINES:
                assert storage_types.sql_type(semantic_type, engine)

    def test_coerce_takes_an_engine_keyword_defaulting_to_postgres(self) -> None:
        param = inspect.signature(storage_types.coerce).parameters.get("engine")
        assert param is not None, (
            "coerce must take engine= (ADR-020: gate checks the target column)"
        )
        assert param.default == "postgres", (
            "default must stay postgres so old callers are unchanged"
        )
        assert param.kind in (param.KEYWORD_ONLY, param.POSITIONAL_OR_KEYWORD)

    @pytest.mark.parametrize("semantic_type", TYPED)
    def test_default_engine_is_postgres(self, semantic_type: str) -> None:
        for value in ("12.5", "1e30", "true", "x", "9" * 40):
            assert storage_types.coerce(semantic_type, value) == _coerce(
                semantic_type, value, "postgres"
            )

    def test_executor_passes_the_engine_to_the_per_value_function(self) -> None:
        params = inspect.signature(clone_executor._apply_value).parameters
        assert any(name in params for name in _ENGINE_PARAMS), (
            "clone_executor._apply_value must receive the destination engine "
            f"(one of {_ENGINE_PARAMS}); it only knows typed_as={params.get('typed_as')}"
        )


# --------------------------------------------------------------------------- adversarial


@pytest.mark.unit
class TestAdversarialInputs:
    @pytest.mark.parametrize("engine", ENGINES)
    @pytest.mark.parametrize("semantic_type", TYPED)
    @pytest.mark.parametrize("value", _VALUES, ids=_IDS)
    def test_clean_typed_value_that_fits_or_null_plus_error(
        self, semantic_type: str, engine: str, value: object
    ) -> None:
        """Never raises, never a raw string, never a value the column cannot hold."""
        if isinstance(value, int) and not isinstance(value, bool) and value.bit_length() > 100000:
            pytest.skip("covered by test_huge_int_does_not_raise")
        _assert_clean(semantic_type, engine, value)

    @pytest.mark.parametrize("engine", ENGINES)
    @pytest.mark.parametrize("semantic_type", TYPED)
    @pytest.mark.parametrize(
        "value",
        ["d1989-12-11", "NaN", "inf", "\x00", "yes please", "1,234", "\ud800", "abc", "1.2.3"],
    )
    def test_non_numbers_are_null_with_an_error_naming_the_value(
        self, semantic_type: str, engine: str, value: str
    ) -> None:
        cast, error = _coerce(semantic_type, value, engine)
        assert cast is None
        assert error
        assert "NULL" in error or "null" in error.lower()

    @pytest.mark.parametrize("engine", ENGINES)
    @pytest.mark.parametrize("semantic_type", TYPED)
    @pytest.mark.parametrize("value", ["", " ", " \t\n"])
    def test_empty_is_null_without_an_error(
        self, semantic_type: str, engine: str, value: str
    ) -> None:
        assert _coerce(semantic_type, value, engine) == (None, None)

    @pytest.mark.parametrize("engine", ENGINES)
    @pytest.mark.parametrize("semantic_type", DECIMAL_TYPED)
    def test_huge_int_does_not_raise(self, semantic_type: str, engine: str) -> None:
        """coerce takes `object`; str(10**5000) raises ValueError on CPython 3.11+."""
        cast, error = _coerce(semantic_type, 10**5000, engine)
        if cast is not None:
            assert error is None
            assert _fit_problem(semantic_type, engine, cast) is None
        else:
            assert error


# --------------------------------------------------------------------------- the defect


@pytest.mark.unit
class TestOverflowIsACastFailure:
    """The lead's pinned examples (ADR-020 table). Engine types come from sql_type, so these
    only encode what overflows given the ADR's chosen types."""

    @pytest.mark.parametrize(
        ("semantic_type", "engine", "value", "fits"),
        [
            ("NUMERIC", "clickhouse", "1e30", False),  # 31 digits > 29
            ("NUMERIC", "clickhouse", "1e999", False),
            ("NUMERIC", "clickhouse", "1" + "0" * 40, False),
            ("NUMERIC", "clickhouse", "-1" + "0" * 40, False),
            ("NUMERIC", "clickhouse", "1e28", True),
            ("NUMERIC", "postgres", "1e30", True),  # unbounded
            ("NUMERIC", "postgres", "1" + "0" * 40, True),
            ("NUMERIC", "postgres", "1e999", True),
            ("MONEY", "postgres", "1e35", False),  # 36 digits > 34
            ("MONEY", "clickhouse", "1e35", False),
            ("MONEY", "postgres", "1" + "0" * 40, False),
            ("MONEY", "clickhouse", "1" + "0" * 40, False),
            ("MONEY", "postgres", "-1" + "0" * 40, False),
            ("MONEY", "postgres", "1e999", False),
            ("MONEY", "clickhouse", "1e999", False),
            ("MONEY", "postgres", "1e30", True),
            ("MONEY", "clickhouse", "1e30", True),
        ],
    )
    def test_value_wider_than_the_column(
        self, semantic_type: str, engine: str, value: str, fits: bool
    ) -> None:
        cast, error = _coerce(semantic_type, value, engine)
        if fits:
            assert error is None
            assert cast == decimal.Decimal(value), "an in-range value must pass unchanged"
        else:
            assert cast is None, (
                f"{semantic_type}/{engine} {value[:12]}... would reach INSERT as {cast!r}"
            )
            assert error

    @pytest.mark.parametrize("engine", ENGINES)
    @pytest.mark.parametrize("semantic_type", DECIMAL_TYPED)
    def test_rejection_is_not_saturation_or_truncation(
        self, semantic_type: str, engine: str
    ) -> None:
        """Never-guess: an out-of-range value is NULL + error, not clamped to the max, not
        truncated to its low digits, not turned into a float or a string."""
        int_digits, _ = _limits(semantic_type, engine)
        if int_digits is None:
            pytest.skip("unbounded column")
        cast, error = _coerce(semantic_type, "1" + "0" * (int_digits + 5), engine)
        assert cast is None
        assert error


@pytest.mark.unit
class TestBoundary:
    """Both sides of the limit, derived from the engine's own type string."""

    @pytest.mark.parametrize("engine", ENGINES)
    @pytest.mark.parametrize("semantic_type", DECIMAL_TYPED)
    @pytest.mark.parametrize("sign", ["", "-"])
    def test_max_integer_digits_fits_one_more_does_not(
        self, semantic_type: str, engine: str, sign: str
    ) -> None:
        int_digits, _ = _limits(semantic_type, engine)
        if int_digits is None:
            pytest.skip("unbounded column: see TestPostgresHardCeiling")
        assert int_digits >= 1
        fits = sign + _digits(int_digits)
        cast, error = _coerce(semantic_type, fits, engine)
        assert error is None, "the widest value the column holds must not be rejected"
        assert cast == decimal.Decimal(fits)
        over = sign + "1" + "0" * int_digits
        assert _coerce(semantic_type, over, engine)[0] is None
        assert _coerce(semantic_type, over, engine)[1]

    @pytest.mark.parametrize("engine", ENGINES)
    @pytest.mark.parametrize("semantic_type", DECIMAL_TYPED)
    def test_exponent_spelling_gets_the_same_verdict_as_digits(
        self, semantic_type: str, engine: str
    ) -> None:
        int_digits, _ = _limits(semantic_type, engine)
        if int_digits is None:
            pytest.skip("unbounded column")
        assert _coerce(semantic_type, f"1e{int_digits - 1}", engine)[1] is None
        cast, error = _coerce(semantic_type, f"1e{int_digits}", engine)
        assert cast is None
        assert error
        cast, error = _coerce(semantic_type, f"1.5E+{int_digits}", engine)
        assert cast is None
        assert error

    @pytest.mark.parametrize("engine", ENGINES)
    @pytest.mark.parametrize("semantic_type", DECIMAL_TYPED)
    def test_widest_value_with_a_full_fraction_fits(self, semantic_type: str, engine: str) -> None:
        int_digits, scale = _limits(semantic_type, engine)
        if int_digits is None or scale is None:
            pytest.skip("unbounded column")
        text = _digits(int_digits) + "." + _digits(scale)
        cast, error = _coerce(semantic_type, text, engine)
        assert error is None
        assert cast == decimal.Decimal(text)

    @pytest.mark.parametrize("engine", ENGINES)
    @pytest.mark.parametrize("semantic_type", DECIMAL_TYPED)
    def test_rounding_to_the_column_scale_cannot_carry_past_the_limit(
        self, semantic_type: str, engine: str
    ) -> None:
        """99..9.99..9 with ONE more fractional digit than the column keeps rounds up to
        10**int_digits (one digit too wide): the INSERT would fail although the integer part
        looked in range. Either reject it, or return a value that fits after rounding."""
        int_digits, scale = _limits(semantic_type, engine)
        if int_digits is None or scale is None:
            pytest.skip("unbounded column")
        text = _digits(int_digits) + "." + _digits(scale + 1)
        _assert_clean(semantic_type, engine, text)
        cast, error = _coerce(semantic_type, text, engine)
        assert (cast is None and error) or _fit_problem(semantic_type, engine, cast) is None

    @pytest.mark.parametrize("engine", ENGINES)
    @pytest.mark.parametrize("semantic_type", DECIMAL_TYPED)
    @pytest.mark.parametrize("text", ["0", "-0", "0.0", "1e-999999999", "-1e-999999999", "0e999"])
    def test_zero_and_tiny_are_never_rejected_for_size(
        self, semantic_type: str, engine: str, text: str
    ) -> None:
        """Overflow is about integer digits only; a near-zero value has none.

        fix/robustness: a non-zero value finer than the column's scale is no longer
        stored as 0 (ClickHouse truncated it silently); it is NULL plus an error row,
        like overflow. Zero itself, at any exponent, still fits."""
        if engine == "postgres" and "e-999999999" in text:
            # Lead, after the attack round: real PG 16.14 rejects more than 16383
            # fractional digits, typmod or not (TestPostgresScaleCeiling covers it).
            pytest.skip("beyond Postgres' 16383 fractional digits")
        cast, error = _coerce(semantic_type, text, engine)
        if decimal.Decimal(text).is_zero():
            assert error is None, f"{text} has no integer digits but was rejected: {error}"
            assert isinstance(cast, decimal.Decimal)
        else:
            assert cast is None
            assert error, f"{text} cannot be held by the column but passed silently"

    @pytest.mark.parametrize("engine", ENGINES)
    def test_boolean_has_no_width(self, engine: str) -> None:
        assert _coerce("BOOLEAN", "true", engine) == (True, None)
        assert _coerce("BOOLEAN", "false", engine) == (False, None)
        assert _coerce("BOOLEAN", "9" * 50, engine)[0] is None


@pytest.mark.unit
class TestPostgresHardCeiling:
    """BEYOND the ADR text ("unbounded NUMERIC has no integer-digit limit"). PostgreSQL's own
    docs cap NUMERIC at 131072 digits before the point, so a Decimal like 1e999999999 passes
    any finite check yet the INSERT still fails. If the lead disagrees, say so in the verdict;
    these are the only checks that assume it."""

    @pytest.mark.parametrize("semantic_type", DECIMAL_TYPED)
    def test_past_the_documented_ceiling_is_a_cast_failure(self, semantic_type: str) -> None:
        for text in (
            "1" + "0" * PG_NUMERIC_MAX_INT_DIGITS,
            f"1e{PG_NUMERIC_MAX_INT_DIGITS}",
            "1e999999999",
        ):
            cast, error = _coerce(semantic_type, text, "postgres")
            assert cast is None, (
                f"{text[:14]}... exceeds Postgres NUMERIC and would abort the chunk"
            )
            assert error

    def test_the_documented_ceiling_itself_fits(self) -> None:
        if _limits("NUMERIC", "postgres")[0] is not None:
            pytest.skip("Postgres NUMERIC is bounded in this build")
        text = _digits(PG_NUMERIC_MAX_INT_DIGITS)
        cast, error = _coerce("NUMERIC", text, "postgres")
        assert error is None
        assert cast == decimal.Decimal(text)


# --------------------------------------------------------------------------- unchanged values

# Snapshot of today's results (Decimal repr / bool) for in-range input. A fix may change which
# values are rejected; it must not change what an accepted value looks like.
_SNAPSHOT: list[tuple[str, str, str]] = [
    ("NUMERIC", "1234.56", "Decimal('1234.56')"),
    ("NUMERIC", "-50", "Decimal('-50')"),
    ("NUMERIC", "0", "Decimal('0')"),
    ("NUMERIC", " 12.5 ", "Decimal('12.5')"),
    ("NUMERIC", "+7", "Decimal('7')"),
    ("NUMERIC", ".5", "Decimal('0.5')"),
    ("NUMERIC", "5.", "Decimal('5')"),
    ("NUMERIC", "1e5", "Decimal('1E+5')"),
    ("NUMERIC", "1E-3", "Decimal('0.001')"),
    ("NUMERIC", "-0", "Decimal('-0')"),
    ("NUMERIC", "00012", "Decimal('12')"),
    (
        "NUMERIC",
        "99999999999999999999999999999.999999999",
        "Decimal('99999999999999999999999999999.999999999')",
    ),
    ("NUMERIC", "0.000000001", "Decimal('1E-9')"),
    ("MONEY", "1234.56", "Decimal('1234.56')"),
    ("MONEY", "-0.0001", "Decimal('-0.0001')"),
    ("MONEY", "0.1", "Decimal('0.1')"),
    ("MONEY", "9" * 34, "Decimal('" + "9" * 34 + "')"),
    ("MONEY", "-" + "9" * 34, "Decimal('-" + "9" * 34 + "')"),
    ("BOOLEAN", "true", "True"),
    ("BOOLEAN", "false", "False"),
    ("BOOLEAN", " true ", "True"),
]


@pytest.mark.unit
class TestInRangeValuesUnchanged:
    @pytest.mark.parametrize("engine", ENGINES)
    @pytest.mark.parametrize(("semantic_type", "text", "expected"), _SNAPSHOT)
    def test_same_result_as_before_d5(
        self, semantic_type: str, text: str, expected: str, engine: str
    ) -> None:
        cast, error = _coerce(semantic_type, text, engine)
        assert error is None
        assert repr(cast) == expected

    @pytest.mark.parametrize("engine", ENGINES)
    @pytest.mark.parametrize("semantic_type", DECIMAL_TYPED)
    def test_precision_is_preserved_never_invented(self, semantic_type: str, engine: str) -> None:
        """Never-guess (precision): a source that states 5 stays 5, not 5.000000000; the gate
        must not quantize to the column scale."""
        cast, _ = _coerce(semantic_type, "5", engine)
        assert isinstance(cast, decimal.Decimal)
        assert cast.as_tuple().exponent == 0
        cast, _ = _coerce(semantic_type, "1.5", engine)
        assert isinstance(cast, decimal.Decimal)
        assert cast.as_tuple().exponent == -1

    @pytest.mark.parametrize("engine", ENGINES)
    @pytest.mark.parametrize("semantic_type", DECIMAL_TYPED)
    def test_undecidable_amount_is_never_guessed(self, semantic_type: str, engine: str) -> None:
        """Never-guess (ambiguity): `1,234` is 1234 or 1.234; the gate returns neither."""
        for text in ("1,234", "1.234,56", "1 234"):
            cast, error = _coerce(semantic_type, text, engine)
            assert cast is None
            assert error

    @pytest.mark.parametrize("engine", ENGINES)
    @pytest.mark.parametrize("semantic_type", DECIMAL_TYPED)
    def test_a_value_is_exact_decimal_never_float(self, semantic_type: str, engine: str) -> None:
        cast, _ = _coerce(semantic_type, "0.1", engine)
        assert isinstance(cast, decimal.Decimal)
        assert cast == decimal.Decimal("0.1")


# --------------------------------------------------------------------------- through the executor


def _normalized(display: object, semantic_type: str) -> NormalizedValue:
    return NormalizedValue(
        original=None if display is None else str(display),
        display=None if display is None else str(display),
        normalization_status=NormalizationStatus.NORMALIZED,
        profile_version="test",
        env_id="test",
        semantic_type=FieldSemanticType(semantic_type),
        context_hash="test",
    )


def _call(fn: Callable[..., Any], engine: str, **known: Any) -> Any:
    """Call an executor function with whichever of `known` it accepts, plus the engine under
    whatever name it takes it. Fails loudly (not with TypeError) on an unknown required param."""
    params = inspect.signature(fn).parameters
    kwargs = {k: v for k, v in known.items() if k in params}
    for name in _ENGINE_PARAMS:
        if name in params:
            kwargs[name] = engine
    missing = [
        p.name
        for p in params.values()
        if p.default is p.empty and p.name not in kwargs and p.kind is p.KEYWORD_ONLY
    ]
    if missing:
        pytest.fail(
            f"{fn.__name__} has new required parameters {missing}; extend _call in this test"
        )
    return fn(**kwargs)


def _typed_as(semantic_type: str, engine: str) -> str:
    """What the plan hands the per-value function for this column on this engine."""
    _, _, typed_columns = clone_executor._destination_plan(
        {"amount": semantic_type}, engine, (), typed=True
    )
    assert "amount" in typed_columns
    return typed_columns["amount"]


def _apply_one(semantic_type: str, engine: str, raw: str) -> tuple[Any, list[str]]:
    row: dict[str, Any] = {"amount": raw}
    errors = _call(
        clone_executor._apply_value,
        engine,
        row=row,
        result=_normalized(raw, semantic_type),
        column="amount",
        typed_as=_typed_as(semantic_type, engine),
        companion=None,
        code_column=None,
    )
    return row["amount"], errors


@pytest.mark.unit
class TestThroughTheExecutor:
    @pytest.mark.parametrize("engine", ENGINES)
    @pytest.mark.parametrize(
        ("semantic_type", "raw"),
        [
            ("NUMERIC", "1" + "0" * 40),
            ("NUMERIC", "1e999"),
            ("MONEY", "1e35"),
            ("MONEY", "1" + "0" * 40),
            ("MONEY", "-1" + "0" * 40),
            ("BOOLEAN", "yes please"),
            ("NUMERIC", "d1989-12-11"),
            ("MONEY", "NaN"),
        ],
    )
    def test_planted_bad_value_is_null_with_an_error(
        self, semantic_type: str, raw: str, engine: str
    ) -> None:
        """Skips the cases that legitimately fit (unbounded Postgres NUMERIC)."""
        cast, _ = _coerce(semantic_type, raw, engine)
        cell, errors = _apply_one(semantic_type, engine, raw)
        if cast is not None:
            assert cell == cast, "a value the gate accepts must reach the cell unchanged"
            assert errors == []
        else:
            assert cell is None, f"{semantic_type}/{engine}: {raw[:12]}... would be sent to INSERT"
            assert errors
            assert any("NULL" in e for e in errors)

    @pytest.mark.parametrize(
        ("semantic_type", "engine", "raw"),
        [
            ("NUMERIC", "clickhouse", "1e30"),
            ("MONEY", "postgres", "1e35"),
            ("MONEY", "clickhouse", "1e35"),
        ],
    )
    def test_the_lead_examples_never_reach_the_cell(
        self, semantic_type: str, engine: str, raw: str
    ) -> None:
        """Negative case that FAILS on the old, engine-blind gate."""
        cell, errors = _apply_one(semantic_type, engine, raw)
        assert cell is None
        assert errors

    @pytest.mark.parametrize("engine", ENGINES)
    def test_in_range_values_still_reach_the_cell_typed(self, engine: str) -> None:
        assert _apply_one("MONEY", engine, "1234.56") == (decimal.Decimal("1234.56"), [])
        assert _apply_one("NUMERIC", engine, "-50") == (decimal.Decimal("-50"), [])
        assert _apply_one("BOOLEAN", engine, "true") == (True, [])

    def test_one_engine_does_not_apply_the_other_engines_limit(self) -> None:
        """1e30 is 31 digits: too wide for ClickHouse NUMERIC, fine for unbounded Postgres."""
        pg_cell, pg_errors = _apply_one("NUMERIC", "postgres", "1e30")
        ch_cell, ch_errors = _apply_one("NUMERIC", "clickhouse", "1e30")
        assert pg_cell == decimal.Decimal("1e30")
        assert pg_errors == []
        assert ch_cell is None
        assert ch_errors

    @pytest.mark.parametrize("engine", ENGINES)
    def test_a_failed_cast_is_reported_per_row_with_the_original(
        self, engine: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`_apply_column` over a chunk with one in-range, one overflowing, one non-numeric
        MONEY value: NULL cells, one error row each for the bad ones carrying the ORIGINAL
        string, `nulled` counted, the good row untouched."""
        raws = ["12.50", "1" + "0" * 40, "d1989-12-11"]
        by_value = {raw: _normalized(raw, "MONEY") for raw in raws}
        monkeypatch.setattr(clone_executor, "_normalize_distinct", lambda *a, **k: dict(by_value))
        monkeypatch.setattr(clone_executor, "_check_idempotent", lambda *a, **k: None)
        pending = [(i, {"amount": raw}) for i, raw in enumerate(raws)]
        errors_buffer: list[dict[str, Any]] = []
        stats = clone_executor._ColumnStats()
        _call(
            clone_executor._apply_column,
            engine,
            pending=pending,
            column="amount",
            semantic_type=FieldSemanticType.MONEY,
            table="t",
            source_id="s",
            pool=None,
            planner=object(),
            typed_as=_typed_as("MONEY", engine),
            companion=None,
            code_column=None,
            country=None,
            locale=None,
            signals=None,
            country_is_derived=False,
            stats=stats,
            errors_buffer=errors_buffer,
            adjudication=None,
        )
        cells = [row["amount"] for _, row in pending]
        assert cells == [decimal.Decimal("12.50"), None, None]
        assert sorted(e["row_index"] for e in errors_buffer) == [1, 2]
        assert {e["original"] for e in errors_buffer} == set(raws[1:])
        assert all(
            e["field"] == "amount" and e["table_name"] == "t" and e["error"] for e in errors_buffer
        )
        assert stats.nulled == 2
        assert Counter(stats.statuses)  # statuses still tallied


# --------------------------------------------------------------------------- 2.4 grep


def _added_line_numbers(diff: str) -> set[int]:
    added: set[int] = set()
    for hunk in re.finditer(r"^@@ -\S+ \+(\d+)(?:,(\d+))? @@", diff, flags=re.MULTILINE):
        start, count = int(hunk.group(1)), int(hunk.group(2) or 1)
        added.update(range(start, start + count))
    return added


_TYPE_MAP_ROW = re.compile(r'^\s*"(NUMERIC|MONEY|BOOLEAN)"\s*:\s*"[^"]*",?\s*(#.*)?$')
_PRECISION_IN_STRING = re.compile(r"\(\s*\d+\s*,\s*\d+\s*\)")


def _violations(source: str, added: set[int]) -> list[str]:
    """Added code that hand-writes a digit limit instead of reading it off the type string:
    int literals >= 10 (38, 29, 131072 ...), or a '(P,S)' string outside the type maps, unless
    a `ponytail:` note sits on the line or within 4 lines above."""
    lines = source.splitlines()

    def noted(lineno: int) -> bool:
        return any("ponytail:" in lines[i] for i in range(max(0, lineno - 5), lineno))

    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        lineno = getattr(node, "lineno", None)
        if lineno is None or lineno not in added or noted(lineno):
            continue
        if isinstance(node, ast.Constant):
            line = lines[lineno - 1]
            if (
                isinstance(node.value, int)
                and not isinstance(node.value, bool)
                and node.value >= 10
            ):
                found.append(f"{lineno}: int literal {node.value}")
            elif (
                isinstance(node.value, str)
                and _PRECISION_IN_STRING.search(node.value)
                and not _TYPE_MAP_ROW.match(line)
                and "Decimal(" not in node.value
                and "NUMERIC(" not in node.value
            ):
                found.append(f"{lineno}: precision/scale string {node.value!r}")
    return found


@pytest.mark.unit
class TestSection24Grep:
    def test_the_grep_catches_what_it_is_meant_to_catch(self) -> None:
        planted = (
            "_MAX_INT_DIGITS = 29\n"
            "LIMITS = {'NUMERIC': 38, 'MONEY': 34}\n"
            "WIDTH = '(38,9)'\n"
            "# ponytail: documented ceiling, ClickHouse Decimal128\n"
            "OK = 131072\n"
        )
        found = _violations(planted, {1, 2, 3, 5})
        assert len(found) == 4, found
        # an int < 10 and an unadded line are not flagged
        assert _violations("X = 3\nY = 38\n", {1}) == []

    def test_added_lines_of_storage_types_hand_write_no_digit_limit(self) -> None:
        try:
            diff = subprocess.run(
                ["git", "diff", "main", "--unified=0", "--", STORAGE_TYPES_PY],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        except (OSError, subprocess.CalledProcessError):
            pytest.skip("git or branch main unavailable")
        source = (ROOT / STORAGE_TYPES_PY).read_text()
        found = _violations(source, _added_line_numbers(diff))
        assert found == [], (
            "limits must be parsed from the engine type string (sql_type), or carry a "
            f"`ponytail:` note naming the source: {found}"
        )

    def test_no_test_fixture_value_leaks_into_production(self) -> None:
        tree = ast.parse((ROOT / STORAGE_TYPES_PY).read_text())
        needles = {"d1989-12-11", "yes please", "1e30", "1e35", "1e999", 10**40, 10**30}
        literals = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant)}
        assert not (literals & needles), literals & needles


# --------------------------------------------------------------------------- attack round
# Added by the attack verifier. Each fact below was checked against a real PostgreSQL 16.14
# (psycopg 3, Decimal bound as a parameter): INSERT of these Decimals into NUMERIC and
# NUMERIC(38,4) fails with "value overflows numeric format" and aborts the transaction, so the
# cast gate has to reject them. Source: PostgreSQL docs, "Numeric Types": NUMERIC holds "up to
# 16383 digits after the decimal point" (the storage_types comment states the same).
PG_NUMERIC_MAX_SCALE = 16383


@pytest.mark.unit
class TestPostgresScaleCeiling:
    @pytest.mark.parametrize("semantic_type", DECIMAL_TYPED)
    @pytest.mark.parametrize(
        "text",
        [
            f"1e-{PG_NUMERIC_MAX_SCALE + 1}",
            f"5e-{PG_NUMERIC_MAX_SCALE + 1}",
            f"0.5e-{PG_NUMERIC_MAX_SCALE}",
            f"12345e-{PG_NUMERIC_MAX_SCALE + 4}",
            f"-1.5e-{20000}",
            f"0e-{PG_NUMERIC_MAX_SCALE + 1}",
            "1e-999999999",
            "0e-999999999",
        ],
    )
    def test_more_fraction_digits_than_postgres_stores_is_a_cast_failure(
        self, semantic_type: str, text: str
    ) -> None:
        cast, error = _coerce(semantic_type, text, "postgres")
        assert cast is None and error, f"{text} aborts the INSERT on Postgres but passed the gate"

    @pytest.mark.parametrize("semantic_type", DECIMAL_TYPED)
    @pytest.mark.parametrize("text", [f"1e-{PG_NUMERIC_MAX_SCALE}", f"0e-{PG_NUMERIC_MAX_SCALE}"])
    def test_the_stored_scale_itself_still_fits(self, semantic_type: str, text: str) -> None:
        if semantic_type == "MONEY" and not decimal.Decimal(text).is_zero():
            pytest.skip("finer than NUMERIC(38,4): NULL plus an error row since fix/robustness")
        cast, error = _coerce(semantic_type, text, "postgres")
        assert error is None
        assert cast == decimal.Decimal(text)


@pytest.mark.unit
class TestEngineReachesTheCastEndToEnd:
    """`_normalize_table(source_engine=...)` must hand that engine to `coerce`, not rely on the
    default: spy on the real `storage_types.coerce` during a real `_normalize_table` pass."""

    @pytest.mark.parametrize("engine", ENGINES)
    def test_normalize_table_passes_its_engine_to_coerce(
        self, engine: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:

        seen: list[object] = []
        real = storage_types.coerce

        def spy(semantic_type: str, value: object, *args: object, **kwargs: object) -> Any:
            seen.append(kwargs.get("engine", args[0] if args else "<default>"))
            return real(semantic_type, value, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(storage_types, "coerce", spy)

        class _B:
            def to_pylist(self) -> list[dict[str, Any]]:
                return [{"source_row_key": "t:0", "amt": "12.50"}]

        class _Src:
            def read_table(self, *a: Any, **k: Any) -> Iterator[_B]:
                yield _B()

            def get_columns(self, table: str) -> list[Any]:
                return []

            def get_primary_key(self, table: str) -> list[str]:
                return []

        class _Dst:
            rows: ClassVar[list[Any]] = []

            def insert_block_rows(self, *a: Any) -> int:
                return 2000

            def bulk_insert(self, database: str, table: str, rows: list[Any], **kw: Any) -> None:
                self.rows.extend(rows)

        with tempfile.TemporaryDirectory() as tmp:
            store = PgPersistence(f"sqlite:///{tmp}/m.db")
            store.ensure_schema()
            job: dict[str, Any] = {
                "source_connection_id": "s",
                "destination_database": "d",
                "field_configs": {"t": {"amt": "MONEY"}},
                "destination_plan": {"t": {"typed_columns": {"amt": "MONEY"}}},
                "progress": {"checkpoints": {}, "rows_done": 0, "current_table": None},
                "country": None,
                "locale": None,
            }
            store.create_clone_job("j", job)
            _normalize_table(
                "t",
                job=job,
                job_id="j",
                source=_Src(),
                dest=_Dst(),
                source_engine=engine,
                persistence=store,
                planner=DistinctValuePlanner(build_dispatcher(env_id="e"), None),
                pool=None,
                progress=job["progress"],
                in_place=False,
                entity_countries={},
                adjudication=None,
            )
        assert seen == [engine], seen

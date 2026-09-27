"""How much of a realistic schema autodetection gets right, as a number.

`test_type_detection.py` asserts individual behaviours. This file asserts
the AGGREGATE, because the aggregate is what a clone job actually depends
on and the only way to see a change in it: measured on a real 7-table
source, detection claimed 7 of 12 detectable columns, and every attempt to
raise that traded precision for recall without anyone noticing which.

The fixture is a schema SHAPE, not any real database: the column names use
the three conventions real sources actually use (camelCase, snake_case and
flat lowercase) and the values are synthetic. `None` as the expected type
means "must NOT be detected" — a column no semantic type fits. Those are
the precision half, and they matter more than the recall half: a wrong
semantic type rewrites data, a missing one leaves it alone.
"""

from __future__ import annotations

import pytest
from normanalysis.type_detection import suggest_semantic_type
from normapi.app import build_normalizer_registry
from normcore.enums import FieldSemanticType as T

from normcore import NormalizerRegistry

_APPLY_THRESHOLD = 0.9

# (column_name, sample_values, expected type or None for "leave it alone")
_SCHEMA: tuple[tuple[str, list[str], T | None], ...] = (
    # --- the three naming conventions, same semantic type ----------------
    ("companyPhone", ["+1 650-253-0000", "(415) 555-0132", "+44 20 7946 0958"], T.PHONE),
    ("company_phone", ["+1 650-253-0000", "(415) 555-0132", "+44 20 7946 0958"], T.PHONE),
    ("companyphone", ["+1 650-253-0000", "(415) 555-0132", "+44 20 7946 0958"], T.PHONE),
    # --- money, which needs both a name and confirming values ------------
    ("companyRevenue", ["$1,234.56", "$17.6 Million", "2500000"], T.MONEY),
    ("annual_salary", ["$90,000", "$120,500", "$75,000"], T.MONEY),
    # --- other real types -------------------------------------------------
    ("companyName", ["Acme Corporation", "Globex Inc.", "Initech"], T.COMPANY_NAME),
    ("companyDomain", ["acme.example", "globex.example", "initech.example"], T.URL),
    ("website", ["https://acme.example", "https://globex.example"], T.URL),
    ("CountryCode", ["United States", "GB", "Deutschland"], T.COUNTRY),
    ("postalCode", ["94043", "SW1A 1AA", "10115"], T.POSTCODE),
    ("firstName", ["Ada", "Grace", "Alan"], T.GIVEN_NAME),
    ("lastName", ["Lovelace", "Hopper", "Turing"], T.FAMILY_NAME),
    ("workEmail", ["a@example.com", "b@example.com"], T.EMAIL),
    ("isPublic", ["true", "false", "true"], T.BOOLEAN),
    ("ispublic", ["1", "0", "1"], T.BOOLEAN),
    # --- must NOT be detected --------------------------------------------
    # Digit-string keys. MONEY accepts a bare number, so on values alone it
    # claimed every one of these on a real source.
    ("companyID", ["368938835", "368938860", "368938875"], None),
    ("personID", ["11223344", "55667788", "99001122"], None),
    ("locationID", ["7001", "7002", "7003"], None),
    # "is" inside a word, "has" inside a word. Both matched BOOLEAN on a
    # real source and were saved only by their values disagreeing.
    ("displayName", ["Software", "Aerospace", "Retail"], None),
    ("personHashtags", ["#founder #cto", "#sales", "#eng"], None),
    # A range string is not a currency, even though it contains "$".
    ("companyRevenueRange", ["$5 mil. - $10 mil.", "Under $500,000"], None),
    # Prose, codes and labels no semantic type fits.
    ("companyDescription", ["A maker of fine anvils since 1949.", "Software."], None),
    ("companyTicker", ["ACME", "GLBX", "INTC"], None),
    ("jobTitle", ["Chief Executive Officer", "Staff Engineer"], None),
    ("middleInitial", ["A", "B", "C"], None),
)


@pytest.fixture(scope="module")
def registry() -> NormalizerRegistry:
    return build_normalizer_registry()


def _applied(column: str, values: list[str], registry: NormalizerRegistry, **ctx: str) -> T | None:
    """What a clone job would actually configure for this column, or None."""
    best = suggest_semantic_type(column, sample_values=values, registry=registry, **ctx)[0]
    if best.confidence < _APPLY_THRESHOLD:
        return None
    if best.semantic_type in (T.FREE_TEXT, T.UNKNOWN):
        return None
    return best.semantic_type


def _score(registry: NormalizerRegistry, **ctx: str) -> tuple[int, int, int]:
    """(true positives, false positives, false negatives)."""
    tp = fp = fn = 0
    for column, values, want in _SCHEMA:
        got = _applied(column, values, registry, **ctx)
        if want is None:
            fp += got is not None
        elif got == want:
            tp += 1
        elif got is None:
            fn += 1
        else:
            fp += 1
            fn += 1
    return tp, fp, fn


@pytest.mark.unit
class TestAggregateCoverage:
    def test_nothing_is_wrongly_detected(self, registry: NormalizerRegistry) -> None:
        """Precision first, and at 100%.

        A false positive rewrites a column's data; a false negative leaves
        it exactly as it arrived. So this is the assertion that may not
        regress, whatever happens to recall — and it is the one the MONEY
        keyword broke on real data before this file existed.
        """
        wrong = [
            (column, _applied(column, values, registry, country="US", locale="en-US"), want)
            for column, values, want in _SCHEMA
        ]
        wrong = [(c, got, want) for c, got, want in wrong if got is not None and got != want]
        assert wrong == []

    def test_recall_does_not_regress(self, registry: NormalizerRegistry) -> None:
        tp, fp, fn = _score(registry, country="US", locale="en-US")
        assert fp == 0, f"{fp} false positive(s)"
        # 15 detectable columns in the fixture. Raise this when detection
        # improves; never lower it to make a change pass.
        assert tp >= 15, f"recall fell to {tp}/{tp + fn}"

    def test_a_country_and_locale_can_only_help(self, registry: NormalizerRegistry) -> None:
        """Context is evidence, not noise.

        Without a country, PHONE sees only numbers carrying their own +CC;
        without a locale, MONEY refuses comma-grouped amounts. Detection
        used to ask both questions with neither, so a column full of real
        phones was demoted for holding phones.
        """
        bare_tp, bare_fp, _ = _score(registry)
        ctx_tp, ctx_fp, _ = _score(registry, country="US", locale="en-US")
        assert ctx_tp > bare_tp
        assert ctx_fp == bare_fp == 0


@pytest.mark.unit
class TestWhyEachMissIsDeliberate:
    def test_a_bare_name_column_stays_below_the_apply_threshold(
        self, registry: NormalizerRegistry
    ) -> None:
        """`name` is PERSON_NAME at 0.8 and that is the right answer.

        Raising it to the apply threshold would also claim `Industry.name`
        and `Industry.displayName`, which are not person names — measured
        on a real source. One missed person-name column is cheaper than two
        rewritten industry-label columns.
        """
        suggestion = suggest_semantic_type("name")[0]
        assert suggestion.semantic_type is T.PERSON_NAME
        assert suggestion.confidence < _APPLY_THRESHOLD

    def test_a_validator_that_takes_any_number_cannot_name_a_column(
        self, registry: NormalizerRegistry
    ) -> None:
        """The rule that keeps six primary keys from becoming MONEY."""
        assert _applied("companyID", ["368938835", "368938860"], registry) is None
        # ...while a name match still lets the same type through.
        assert (
            _applied("companyRevenue", ["$1,234.56", "2500000"], registry, locale="en-US")
            is T.MONEY
        )

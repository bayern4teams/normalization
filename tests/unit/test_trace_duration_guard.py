"""Determinism guard for `TraceStep.duration_us` (`packages/normcore/src/normcore/trace.py:32`).

It is serialized into every row's `trace_json`
(`packages/normcore/src/normcore/contract.py:70`) and therefore into the
sidecar Parquet output, but nothing populates it today — confirmed by
grepping every normalizer for `duration_us=` during the 2026-08-29
throughput R&D pass (zero matches) and by `normcli/diff_cmd.py`'s module
docstring, which relies on this staying true so it doesn't need to
exclude `trace_json` content from its comparison.

This test is the guard the R&D pass's plan calls for: if a normalizer
starts setting `duration_us`, this fails with the specific
semantic-type/normalizer at fault, rather than surfacing later as a
mysterious `normcli diff --require-identical` failure that looks like a
process-pool nondeterminism bug (the very thing a future process-pool
phase would otherwise misdiagnose it as).

`ADDRESS` is deliberately excluded — `AddressNormalizer` requires a live
libpostal sidecar, which this unit test does not have (see
`packages/normalizers/src/normalizers/address.py`'s docstring on why it
can never be exercised without one). It is covered by the golden corpus
in `tests/golden/test_m4_corpus.py`, which does have the fixture.
"""

from __future__ import annotations

import uuid

# Import order guard — see normcli/run_cmd.py's identical comment: MUST
# run before `pyarrow` is imported anywhere in this process, or PyICU's
# and PyArrow's bundled native DLLs conflict on Windows (segfault).
# Building the full normalizer registry below transitively imports
# pyarrow (e.g. NormalizedValue's Arrow-backed contract types).
import icu  # noqa: F401
import pytest
from normalizers.address import LibpostalClient
from normcli.registry import DEFAULT_DICTIONARIES_DIR, build_normalizer_registry

from normcore import (
    Dispatcher,
    ErrorPolicy,
    FieldSemanticType,
    NormalizationContext,
    NormalizationProfile,
)

# One representative, valid sample per semantic type this process can
# normalize without a live external service (ADDRESS excluded — see
# module docstring). Not exhaustive per-normalizer edge-case coverage —
# that's the golden corpus's job — just enough real values to produce a
# real `trace` for every registered normalizer.
_SAMPLE_VALUES: dict[FieldSemanticType, str] = {
    FieldSemanticType.PERSON_NAME: "John Smith",
    FieldSemanticType.GIVEN_NAME: "John",
    FieldSemanticType.FAMILY_NAME: "Smith",
    FieldSemanticType.COMPANY_NAME: "Acme Corp",
    FieldSemanticType.EMAIL: "jane.doe@example.com",
    FieldSemanticType.PHONE: "+1 555 123 4567",
    FieldSemanticType.POSTCODE: "10001",
    FieldSemanticType.COUNTRY: "US",
    FieldSemanticType.LANGUAGE: "en",
    FieldSemanticType.SCRIPT: "Hello world",
    FieldSemanticType.DATE: "2024-01-15",
    FieldSemanticType.DATETIME: "2024-01-15T10:00:00Z",
    FieldSemanticType.IDENTIFIER: "ABC123",
    FieldSemanticType.UUID: str(uuid.UUID(int=0)),
    FieldSemanticType.TAX_ID: "123456789",
    FieldSemanticType.URL: "https://example.com",
    FieldSemanticType.NUMERIC: "42",
    FieldSemanticType.CURRENCY: "100.00 USD",
    FieldSemanticType.QUANTITY: "5 kg",
    FieldSemanticType.BOOLEAN: "true",
    FieldSemanticType.FREE_TEXT: "some free text",
    FieldSemanticType.CODE: "AB-001",
    FieldSemanticType.UNKNOWN: "anything",
}

# Every FieldSemanticType member not covered above must be either
# ADDRESS (excluded, see module docstring) or a genuine gap — this
# assertion fails loudly if a new semantic type is ever added without
# updating this guard.
_UNCOVERED = set(FieldSemanticType) - set(_SAMPLE_VALUES) - {FieldSemanticType.ADDRESS}

_DUMMY_PROFILE = NormalizationProfile(
    id="p",
    name="p",
    version="v1",
    created_at="2026-01-01T00:00:00Z",
    updated_at="2026-01-01T00:00:00Z",
    created_by="test",
)


@pytest.mark.unit
def test_every_semantic_type_is_covered_or_deliberately_excluded() -> None:
    assert not _UNCOVERED, (
        f"New FieldSemanticType member(s) {_UNCOVERED} added without a sample value in "
        "test_trace_duration_guard.py — add one (or add to the ADDRESS-style exclusion)."
    )


@pytest.mark.unit
@pytest.mark.parametrize(("semantic_type", "value"), sorted(_SAMPLE_VALUES.items()))
def test_trace_step_duration_us_stays_none(semantic_type: FieldSemanticType, value: str) -> None:
    # A dummy, unreachable URL is safe: nothing in this test's sample set
    # is ADDRESS, so LibpostalClient's HTTP methods are never called —
    # only its presence is required to build the real registry.
    registry = build_normalizer_registry(
        DEFAULT_DICTIONARIES_DIR, LibpostalClient("http://localhost:1")
    )
    dispatcher = Dispatcher(registry, env_id="e" * 64)
    ctx = NormalizationContext(
        field_name="f", semantic_type=semantic_type, error_policy=ErrorPolicy.RETURN_ORIGINAL
    )

    result = dispatcher.normalize(value, semantic_type, ctx, _DUMMY_PROFILE)

    for step in result.trace:
        assert step.duration_us is None, (
            f"{semantic_type.value}: TraceStep {step.rule_id!r} set duration_us="
            f"{step.duration_us!r} — a normalizer now populates this field. Update "
            "normcli/diff_cmd.py's comparison scope deliberately if this is intended."
        )

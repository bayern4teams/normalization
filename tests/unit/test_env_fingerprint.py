"""Proves scripts/env_fingerprint.py's core promise (docs/adr/ADR-014):
same inputs -> same env_id (stability), any one input changed -> different
env_id (sensitivity). This is what makes env_id trustworthy as the basis
for reproducibility comparisons across runs.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from env_fingerprint import EnvFingerprintInputs, compute_env_id


def _baseline() -> EnvFingerprintInputs:
    return EnvFingerprintInputs(
        packages={"phonenumbers": "8.13.0", "ftfy": "6.3.1"},
        icu_version="78.3",
        unicode_version="17.0",
        cldr_version="48",
        libpostal_model_sha256="a" * 64,
        phonenumbers_metadata_version="8.13.0",
        dictionaries={"gleif-elf@2023-09": "b" * 64},
        profile_version="v1",
    )


@pytest.mark.unit
def test_env_id_is_stable_across_repeated_computation() -> None:
    inputs = _baseline()
    assert compute_env_id(inputs) == compute_env_id(inputs)


@pytest.mark.unit
def test_env_id_is_stable_regardless_of_dict_insertion_order() -> None:
    a = _baseline()
    b = EnvFingerprintInputs(
        packages={"ftfy": "6.3.1", "phonenumbers": "8.13.0"},  # reordered
        icu_version=a.icu_version,
        unicode_version=a.unicode_version,
        cldr_version=a.cldr_version,
        libpostal_model_sha256=a.libpostal_model_sha256,
        phonenumbers_metadata_version=a.phonenumbers_metadata_version,
        dictionaries=a.dictionaries,
        profile_version=a.profile_version,
    )
    assert compute_env_id(a) == compute_env_id(b)


@pytest.mark.unit
@pytest.mark.parametrize(
    "mutate",
    [
        lambda i: setattr(i, "icu_version", "79.0"),
        lambda i: setattr(i, "unicode_version", "18.0"),
        lambda i: setattr(i, "cldr_version", "49"),
        lambda i: setattr(i, "libpostal_model_sha256", "c" * 64),
        lambda i: setattr(i, "phonenumbers_metadata_version", "8.14.0"),
        lambda i: setattr(i, "profile_version", "v2"),
        lambda i: i.packages.__setitem__("ftfy", "6.4.0"),
        lambda i: i.dictionaries.__setitem__("gleif-elf@2023-09", "d" * 64),
    ],
)
def test_env_id_changes_when_any_single_input_changes(mutate) -> None:  # type: ignore[no-untyped-def]
    baseline_id = compute_env_id(_baseline())
    mutated = _baseline()
    mutate(mutated)
    assert compute_env_id(mutated) != baseline_id

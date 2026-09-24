"""The environment fingerprint (env_id) that stamps every NormalizedValue,
NormalizationRun, and cache key — ADR-014.

env_id = blake3(canonical_json({
    "packages": {name: version, ...},   # every pinned package actually resolved
    "icu_version": "...",
    "unicode_version": "...",
    "cldr_version": "...",
    "libpostal_model_sha256": "...",
    "phonenumbers_metadata_version": "...",
    "dictionaries": {dict_id: content_hash, ...},
    "profile_version": "...",
}))

Any change to any input above MUST change env_id, or a cached result from
a different environment can be replayed as if it were current.

This lives in normexec, not in scripts/, because BOTH need it: the CI
fingerprint command and the running API, which previously stamped a
hardcoded placeholder (`blake3(b"normapi-m1-scaffold-env-id")`) that was
identical across every environment and every dictionary change — exactly
the thing ADR-014 exists to prevent. scripts/env_fingerprint.py is now a
thin CLI over this module so there is one implementation, not two that
can drift.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version
from pathlib import Path
from typing import Any

import blake3

# Packages whose exact resolved version participates in the fingerprint.
# This list must be kept in sync with docs/dependency-inventory.md — a
# package that can change normalization OUTPUT and is missing here makes
# env_id claim two different environments are the same.
FINGERPRINTED_PACKAGES = [
    "pyicu",
    "ftfy",
    "charset-normalizer",
    "anyascii",
    "nameparser",
    "jellyfish",
    "cleanco",
    "phonenumbers",
    "email-validator",
    "dateparser",
    "python-dateutil",
    "ciso8601",
    "edtf",
    "pycountry",
    "babel",
    "lingua-language-detector",
    "python-stdnum",
    "pint",
    "rapidfuzz",
    "google-i18n-address",
    "polars",
    "duckdb",
    "pyarrow",
]


@dataclass
class EnvFingerprintInputs:
    packages: dict[str, str] = field(default_factory=dict)
    icu_version: str | None = None
    unicode_version: str | None = None
    cldr_version: str | None = None
    libpostal_model_sha256: str | None = None
    phonenumbers_metadata_version: str | None = None
    dictionaries: dict[str, str] = field(default_factory=dict)
    profile_version: str = "unversioned"

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "packages": dict(sorted(self.packages.items())),
            "icu_version": self.icu_version,
            "unicode_version": self.unicode_version,
            "cldr_version": self.cldr_version,
            "libpostal_model_sha256": self.libpostal_model_sha256,
            "phonenumbers_metadata_version": self.phonenumbers_metadata_version,
            "dictionaries": dict(sorted(self.dictionaries.items())),
            "profile_version": self.profile_version,
        }


def collect_package_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for name in FINGERPRINTED_PACKAGES:
        try:
            versions[name] = pkg_version(name)
        except PackageNotFoundError:
            versions[name] = "MISSING"
    return versions


def collect_icu_versions() -> tuple[str | None, str | None, str | None]:
    try:
        import icu  # PyICU  # noqa: PLC0415 - optional capability probe
    except ImportError:
        return None, None, None
    return icu.ICU_VERSION, icu.UNICODE_VERSION, getattr(icu, "CLDR_VERSION", None)


def collect_phonenumbers_metadata_version() -> str | None:
    try:
        import phonenumbers  # noqa: PLC0415 - optional capability probe

        return getattr(phonenumbers, "__version__", None) or pkg_version("phonenumbers")
    except (ImportError, PackageNotFoundError):
        return None


def collect_dictionary_hashes(dictionaries_dir: Path) -> dict[str, str]:
    """Hash every *.json dictionary payload under data/dictionaries/.

    Each dictionary file's own declared {id, version} plus a content hash
    of the file bytes becomes one entry: "{id}@{version}" -> blake3(bytes).
    """
    hashes: dict[str, str] = {}
    if not dictionaries_dir.exists():
        return hashes
    for path in sorted(dictionaries_dir.rglob("*.json")):
        content = path.read_bytes()
        content_hash = blake3.blake3(content).hexdigest()
        try:
            payload = json.loads(content)
            key = f"{payload.get('id', path.stem)}@{payload.get('version', 'unknown')}"
        except json.JSONDecodeError:
            key = path.stem
        hashes[key] = content_hash
    return hashes


def compute_env_id(inputs: EnvFingerprintInputs) -> str:
    canonical = json.dumps(inputs.canonical_dict(), sort_keys=True, separators=(",", ":"))
    return blake3.blake3(canonical.encode("utf-8")).hexdigest()


def gather(
    *,
    libpostal_model_sha256: str | None,
    profile_version: str,
    dictionaries_dir: Path,
) -> EnvFingerprintInputs:
    icu_version, unicode_version, cldr_version = collect_icu_versions()
    return EnvFingerprintInputs(
        packages=collect_package_versions(),
        icu_version=icu_version,
        unicode_version=unicode_version,
        cldr_version=cldr_version,
        libpostal_model_sha256=libpostal_model_sha256,
        phonenumbers_metadata_version=collect_phonenumbers_metadata_version(),
        dictionaries=collect_dictionary_hashes(dictionaries_dir),
        profile_version=profile_version,
    )


def current_env_id(
    *,
    dictionaries_dir: Path | str,
    profile_version: str,
    libpostal_model_sha256: str | None = None,
) -> str:
    """The env_id for the process calling it. Used by the API at startup,
    where it is computed ONCE (ADR-014: never recomputed per value)."""
    return compute_env_id(
        gather(
            libpostal_model_sha256=libpostal_model_sha256,
            profile_version=profile_version,
            dictionaries_dir=Path(dictionaries_dir),
        )
    )

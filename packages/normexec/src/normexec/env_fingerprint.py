"""Compute the environment fingerprint (env_id) that stamps every
NormalizedValue, NormalizationRun, and cache key.

env_id = blake3(canonical_json({
    "packages": {name: version, ...},   # every pinned package actually resolved
    "icu_version": "...",
    "unicode_version": "...",
    "cldr_version": "...",
    "libpostal_model_sha256": "...",    # queried from the sidecar's /version
    "phonenumbers_metadata_version": "...",
    "dictionaries": {dict_id: content_hash, ...},
    "profile_version": "...",
}))

Design rationale: docs/adr/ADR-014-normalization-versioning.md.

Lives here (not in `normcore`, which stays dependency-light and knows
nothing about libpostal/dictionaries/packaging metadata) so the real
running API (`normapi`, which already depends on `normexec`) can import
it directly — `scripts/env_fingerprint.py` is NOT part of the installed
uv workspace (Docker's isolated per-package installs, e.g. `uv sync
--frozen --no-dev --package normapi`, cannot see anything under
`scripts/`), so a running service could never have imported it from
there. `scripts/env_fingerprint.py` is now a thin CLI wrapper around this
module, preserving its existing command-line contract.

Any change to any input listed above MUST change env_id. This is verified
by tests/unit/test_env_fingerprint.py, which mutates one field at a time
and asserts the hash changes, and asserts stability (same input twice ->
same hash).
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
# This list must be kept in sync with docs/dependency-inventory.md.
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
        import icu  # PyICU  # noqa: PLC0415 — guarded: caught below if missing

        icu_version = icu.ICU_VERSION
        unicode_version = icu.UNICODE_VERSION
        cldr_version = getattr(icu, "CLDR_VERSION", None)
        return icu_version, unicode_version, cldr_version
    except ImportError:
        return None, None, None


def collect_phonenumbers_metadata_version() -> str | None:
    try:
        import phonenumbers  # noqa: PLC0415 — guarded: caught below if missing

        return getattr(phonenumbers, "__version__", None) or pkg_version("phonenumbers")
    except (ImportError, PackageNotFoundError):
        return None


def collect_dictionary_hashes(dictionaries_dir: Path) -> dict[str, str]:
    """Hash every *.json dictionary payload under data/dictionaries/.

    Each dictionary file's own declared {id, version} plus a content hash of
    the file bytes becomes one entry: "{id}@{version}" -> blake3(content).
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

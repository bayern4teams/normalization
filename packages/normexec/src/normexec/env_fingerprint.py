"""The environment fingerprint (env_id) that stamps every NormalizedValue,
NormalizationRun, and cache key — ADR-014.

env_id = blake3(canonical_json({
    "packages": {name: version, ...},   # every pinned package actually resolved
    "source_hashes": {pkg: blake3(its .py bytes), ...},  # OUR normalizing code
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

`source_hashes` closes the hole that mattered most in practice. Every
other input here describes the ENVIRONMENT, so a change to OUR OWN
normalizer code changed the output of normalization while leaving env_id
byte-identical — and env_id is part of the cache key. A cache populated
before such a change kept serving the old answer forever: after CLDR
currency and language names landed, "Deutsch" and "₹" resolved on a cold
cache and stayed INVALID on a warm one, with no way to tell which you
had. Versioning the packages would not fix it (they are all a static
"0.1.0" nobody bumps, so it would hash a constant), so the source bytes
are hashed instead. This also covers the generated CLDR tables, which
means regenerating them invalidates the cache even when Babel's version
did not move.
"""

from __future__ import annotations

import importlib
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
    "phonetics",
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
    "publicsuffixlist",
    "google-i18n-address",
    "polars",
    "duckdb",
    "pyarrow",
]

# Our own packages whose SOURCE participates in the fingerprint: the ones
# that can change what a NormalizedValue contains for a given raw value.
#
# `normexec`, `normapi`, `normcli` and `normanalysis` are deliberately
# absent. They decide WHICH values get normalized, WHEN, and where the
# results go — not what the answer is — so including them would bust a
# 1.27M-row cache on every unrelated executor or endpoint change. The
# boundary is exactly `Dispatcher.normalize()`: if a change can alter what
# comes out of it, the package belongs here.
FINGERPRINTED_SOURCE_PACKAGES = [
    "normcore",  # Dispatcher, rules, enums, sentinels
    "normalizers",  # every normalizer + the generated CLDR tables
    "normio",  # storage_types.coerce decides the value actually written
]


_HASHED_SUFFIXES = frozenset({".py", ".txt"})


@dataclass
class EnvFingerprintInputs:
    packages: dict[str, str] = field(default_factory=dict)
    source_hashes: dict[str, str] = field(default_factory=dict)
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
            "source_hashes": dict(sorted(self.source_hashes.items())),
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


def collect_source_hashes() -> dict[str, str]:
    """blake3 over every `*.py` and `*.txt` file of each normalizing package.

    The `*.txt` files are rule data (the vendored Beider-Morse rules under
    `normalizers/_bmpm_data/`): they change a name's phonetic keys exactly as
    code does, so they move env_id too.

    Computed ONCE per process (ADR-014: env_id is never recomputed per
    value); ~4MB of source, so a few milliseconds. Each file's path is
    hashed alongside its bytes, so moving code between files changes the
    digest even when the bytes are unchanged in total.

    Works from a wheel as well as an editable checkout, because the walk
    starts at the imported package's own directory rather than at the
    repo. `__pycache__` is excluded: a `.pyc` is a build artifact of the
    very bytes already being hashed, and its mtime-bearing header would
    make the digest differ between two identical checkouts.
    """
    hashes: dict[str, str] = {}
    for name in FINGERPRINTED_SOURCE_PACKAGES:
        try:
            module = importlib.import_module(name)
        except ImportError:
            hashes[name] = "MISSING"
            continue
        locations = [Path(p) for p in getattr(module, "__path__", [])] or (
            [Path(module.__file__).parent] if module.__file__ else []
        )
        if not locations:
            hashes[name] = "UNLOCATABLE"
            continue
        digest = blake3.blake3()
        for root in sorted(locations):
            for path in sorted(p for p in root.rglob("*") if p.suffix in _HASHED_SUFFIXES):
                if "__pycache__" in path.parts:
                    continue
                digest.update(path.relative_to(root).as_posix().encode("utf-8"))
                digest.update(path.read_bytes())
        hashes[name] = digest.hexdigest()
    return hashes


def collect_icu_versions() -> tuple[str | None, str | None, str | None]:
    try:
        # C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
        import icu  # PyICU  # noqa: PLC0415 - optional capability probe
    except ImportError:
        return None, None, None
    return icu.ICU_VERSION, icu.UNICODE_VERSION, getattr(icu, "CLDR_VERSION", None)


def collect_phonenumbers_metadata_version() -> str | None:
    try:
        # C5: reason=pre-guard baseline; approved=user, 2026-10-24; review=2027-10-24
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
        source_hashes=collect_source_hashes(),
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

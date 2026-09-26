"""CLI over `normexec.env_fingerprint` — prints this environment's env_id.

    python scripts/env_fingerprint.py [--json]

The computation itself lives in `normexec.env_fingerprint` because the
running API needs it too (it used to stamp a hardcoded placeholder). This
file is the ops/CI entry point and nothing more; the names re-exported
below keep `tests/unit/test_env_fingerprint.py` and any existing CI
invocation working unchanged.

Design rationale: docs/adr/ADR-014-normalization-versioning.md.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from normexec.env_fingerprint import (
    FINGERPRINTED_PACKAGES,
    FINGERPRINTED_SOURCE_PACKAGES,
    EnvFingerprintInputs,
    collect_dictionary_hashes,
    collect_icu_versions,
    collect_package_versions,
    collect_phonenumbers_metadata_version,
    collect_source_hashes,
    compute_env_id,
    gather,
)

__all__ = [
    "FINGERPRINTED_PACKAGES",
    "FINGERPRINTED_SOURCE_PACKAGES",
    "EnvFingerprintInputs",
    "collect_dictionary_hashes",
    "collect_icu_versions",
    "collect_package_versions",
    "collect_phonenumbers_metadata_version",
    "collect_source_hashes",
    "compute_env_id",
    "gather",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--libpostal-model-sha256",
        default=os.environ.get("NORM_LIBPOSTAL_MODEL_SHA256"),
    )
    parser.add_argument("--profile-version", default="unversioned")
    parser.add_argument("--dictionaries-dir", default="data/dictionaries", type=Path)
    parser.add_argument(
        "--json",
        action="store_true",
        help="print full canonical input alongside the hash",
    )
    args = parser.parse_args()

    inputs = gather(
        libpostal_model_sha256=args.libpostal_model_sha256,
        profile_version=args.profile_version,
        dictionaries_dir=args.dictionaries_dir,
    )
    env_id = compute_env_id(inputs)

    if args.json:
        print(json.dumps({"env_id": env_id, **inputs.canonical_dict()}, indent=2, sort_keys=True))
    else:
        print(env_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())

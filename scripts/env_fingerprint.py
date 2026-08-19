"""CLI wrapper around `normexec.env_fingerprint` — the real fingerprint
computation lives there now (importable by the running API service,
which `scripts/` is not, since it's outside the installed uv workspace).
This script prints the resulting env_id for ops/CI use (drift detection,
manual inspection), preserving its original command-line contract.

Design rationale: docs/adr/ADR-014-normalization-versioning.md.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Prepend the workspace packages' src dirs so this script runs correctly
# even outside `uv run` (e.g. a bare `python scripts/env_fingerprint.py`),
# matching how this script has always been invoked.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "normexec" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "normcore" / "src"))

# `import icu` must happen before anything that imports pyarrow —
# `normexec` (imported below) pulls in `normexec.planner`, which imports
# pyarrow at module-load time. On Windows, PyICU's and PyArrow's bundled
# native DLLs conflict if pyarrow loads into the process first (`import
# pyarrow` then `import icu` segfaults immediately; the reverse order is
# safe — see docs/adr/ADR-001-unicode-strategy.md's DLL-load-order
# addendum, and packages/normalizers/src/normalizers/__init__.py for the
# same guard applied at that package's entry point). This script's own
# `collect_icu_versions()` only imports icu lazily at call time, which
# would otherwise be too late once `normexec`'s import chain has already
# loaded pyarrow first.
import icu  # noqa: F401 — must precede the normexec import below
from normexec.env_fingerprint import compute_env_id, gather


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

"""A release tag `vX.Y.Z` must equal the version of the workspace and of every
package under packages/, so the image tag and the Python packages a release
publishes name the same version. Used by the release jobs of both CI files.

Usage: python3 scripts/check_release_version.py v1.2.3
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def mismatches(tag: str, root: Path = ROOT) -> list[str]:
    """Each pyproject whose version is not the tag's, as 'path: version'."""
    want = tag.removeprefix("v")
    files = [root / "pyproject.toml", *sorted(root.glob("packages/*/pyproject.toml"))]
    found = {f: tomllib.loads(f.read_text())["project"]["version"] for f in files}
    return [f"{f.relative_to(root)}: {v}" for f, v in found.items() if v != want]


def main() -> int:
    tag = sys.argv[1]
    if not tag.startswith("v"):
        print(f"{tag}: a release tag starts with v, for example v1.2.3")
        return 1
    wrong = mismatches(tag)
    if wrong:
        print(
            f"Tag {tag} does not match these versions:\n  " + "\n  ".join(wrong) + "\n"
            "Fix: set every version above to the tag's (without the v), commit, then tag again."
        )
        return 1
    print(f"check_release_version: OK, every package is {tag.removeprefix('v')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

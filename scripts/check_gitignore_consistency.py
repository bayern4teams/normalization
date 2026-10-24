"""M2/K4: no tracked file may match .gitignore.

A tracked file that .gitignore matches is invisible to status but real in
history: the ignore says "generated, not a source" while the tree says
otherwise, and later edits to it silently stop showing up. The check is
exactly `git ls-files -ci --exclude-standard` printing nothing; this script
adds the fix instructions (J11).

    uv run python scripts/check_gitignore_consistency.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    out = subprocess.run(
        ["git", "ls-files", "-ci", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if out:
        print(
            "check_gitignore_consistency: tracked files match .gitignore (M2). "
            "Fix: `git rm --cached <file>` keeps the file on disk but removes "
            "it from tracking, or delete the ignore rule if the file really "
            "is a source:",
            file=sys.stderr,
        )
        for line in out.splitlines():
            print(f"  {line}", file=sys.stderr)
        return 1
    print("check_gitignore_consistency: OK — nothing tracked matches .gitignore.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

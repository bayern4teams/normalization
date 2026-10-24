"""M1/K4: tracked files in the repository root must be on the agreed allowlist.

The list was agreed with the user on 2026-10-24 (prompt tests-and-housekeeping,
Step 1 report + Step 5 answers). Dotfiles and dot-directories are always
allowed (tool configuration lives there); TODO.md left the root in the same
decision. Adding a root file means editing this list in the same commit, so
the list is a reviewed artifact, not a suggestion.

    uv run python scripts/check_root_files.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Docs (J1), packaging, and the two runtime entry files — user-agreed 2026-10-24.
ALLOWED = {
    "AGENTS.md",
    "ARCHITECTURE.md",
    "CLAUDE.md",
    "GLOSSARY.md",
    "README.md",
    "TECHNICAL_IMPLEMENTATION.md",
    "compose.yaml",
    "conftest.py",
    "puppeteer-config.json",  # referenced by .github/workflows/docs.yml paths filter
    "pyproject.toml",
    "uv.lock",
}


def main() -> int:
    out = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    extra = [
        f
        for f in out.splitlines()
        if "/" not in f and f not in ALLOWED and not f.startswith(".")
    ]
    if extra:
        print(
            "check_root_files: tracked files in the root are not on the M1 "
            "allowlist. Fix: move each to its home (source, tests, scripts, "
            "docs, docs/archive) or add it to ALLOWED in this script with the "
            "user's agreement noted:",
            file=sys.stderr,
        )
        for f in extra:
            print(f"  {f}", file=sys.stderr)
        return 1
    print("check_root_files: OK — root files are on the allowlist.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

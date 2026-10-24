"""Every path in [tool.mutmut].also_copy must exist: a stale entry silently corrupts
the mutation sandbox (see the comment above that key in pyproject.toml).

    uv run python scripts/check_mutmut_paths.py
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
paths = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["mutmut"]["also_copy"]
missing = [p for p in paths if not (ROOT / p).exists()]
for p in missing:
    print(f"pyproject.toml [tool.mutmut].also_copy: '{p}' does not exist. Fix: remove it or restore the path.", file=sys.stderr)
print(f"check_mutmut_paths: {len(paths) - len(missing)}/{len(paths)} paths exist")
sys.exit(1 if missing else 0)

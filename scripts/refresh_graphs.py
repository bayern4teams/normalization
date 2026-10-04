"""Rebuild the three code graphs agents read before touching source.

The loud twin of `.githooks/post-commit`. The hook is best-effort on purpose (a missing tool must
never fail a commit); bootstrap, CI and the cloud supervisor need the opposite: a missing tool or a
failed build is a non-zero exit that names the tool, so "graphs ready" can never be said over an
empty index. Same shallow, no-LLM commands as the hook; never `--deep`, never `graphify label`.

    uv run python scripts/refresh_graphs.py              # all three, in order
    uv run python scripts/refresh_graphs.py --if-missing # skip a graph whose output already exists
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_TIMEOUT_S = 600

# (tool, argv, in-tree output proving it ran; Path() = none, always rebuilt)
GRAPHS: list[tuple[str, list[str], Path]] = [
    ("graft", ["build", "."], ROOT / "graft"),
    ("graphify", ["update", "."], ROOT / "graphify-out" / "graph.json"),
    (
        "codebase-memory-mcp",
        ["cli", "--quiet", "index_repository", '{"repo_path":"."}'],
        Path(),
    ),
]


def refresh(*, if_missing: bool = False) -> int:
    missing: list[str] = []
    failed: list[str] = []
    for tool, args, proof in GRAPHS:
        exe = shutil.which(tool)
        if exe is None:
            missing.append(tool)
            continue
        if if_missing and proof != Path() and proof.exists():
            continue
        try:
            done = subprocess.run(
                [exe, *args],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=_TIMEOUT_S,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            print(f"refresh_graphs: {tool} failed: {exc}", file=sys.stderr)
            failed.append(tool)
            continue
        if done.returncode != 0:
            tail = done.stderr[-800:]
            print(f"refresh_graphs: {tool} exit {done.returncode}\n{tail}", file=sys.stderr)
            failed.append(tool)
    for tool in missing:
        print(f"refresh_graphs: {tool} is not on PATH, its graph was NOT built", file=sys.stderr)
    if failed or missing:
        return 1
    print("refresh_graphs: all three graphs refreshed")
    return 0


if __name__ == "__main__":
    sys.exit(refresh(if_missing="--if-missing" in sys.argv[1:]))

"""Rebuild the three code graphs agents read before touching source.

The loud twin of `.githooks/post-commit`. The hook is best-effort on purpose (a missing tool must
never fail a commit); bootstrap, CI and the cloud supervisor need the opposite: a missing tool or a
failed build is a non-zero exit that names the tool, so "graphs ready" can never be said over an
empty index. Same shallow, no-LLM commands as the hook; never `--deep`, never `graphify label`.

    uv run python scripts/refresh_graphs.py              # all three, in order
    uv run python scripts/refresh_graphs.py --if-missing # skip a graph whose output already exists
    uv run python scripts/refresh_graphs.py --session-start  # E9: freshen what needs it, exit 0
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_TIMEOUT_S = 600

# The one home of the graph-tool versions (owner decision 2026-10-27): both cloud setup scripts must
# install exactly these (tests/unit/test_refresh_graphs.py), and a local mismatch is a warning.
PINS = {"graft": "0.26.0", "graphify": "0.9.96", "codebase-memory-mcp": "0.12.1"}

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


def _run(tool: str, args: list[str]) -> str | None:
    """Run one graph build; return None on success, a one-line reason on failure."""
    exe = shutil.which(tool)
    if exe is None:
        return f"{tool} is not on PATH, its graph was NOT built"
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
        return f"{tool} failed: {exc}"
    if done.returncode != 0:
        return f"{tool} exit {done.returncode}\n{done.stderr[-800:]}"
    return None


def _version_output(exe: str) -> str:
    done = subprocess.run(
        [exe, "--version"], capture_output=True, text=True, timeout=30, check=False
    )
    return done.stdout.strip()


def version_warnings() -> list[str]:
    """One line per installed tool whose `--version` differs from its pin."""
    warnings = []
    for tool, pin in PINS.items():
        exe = shutil.which(tool)
        if exe is None:
            continue
        found = (_version_output(exe).split() or ["unknown"])[-1].removeprefix("v")
        if found != pin:
            warnings.append(f"{tool} is {found}, pinned {pin}")
    return warnings


def refresh(*, if_missing: bool = False) -> int:
    missing: list[str] = []
    failed: list[str] = []
    for warning in version_warnings():
        print(f"refresh_graphs: WARNING {warning}", file=sys.stderr)
    for tool, args, proof in GRAPHS:
        if if_missing and proof != Path() and proof.exists():
            continue
        problem = _run(tool, args)
        if problem is None:
            continue
        if problem.startswith(f"{tool} is not on PATH"):
            missing.append(tool)
        else:
            failed.append(tool)
        print(f"refresh_graphs: {problem}", file=sys.stderr)
    if failed or missing:
        return 1
    print("refresh_graphs: all three graphs refreshed")
    return 0


def _head_time() -> float:
    """Commit time of HEAD (epoch seconds, 0.0 outside a repo): the staleness bar."""
    done = subprocess.run(
        ["git", "log", "-1", "--format=%ct"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return float(done.stdout) if done.returncode == 0 and done.stdout.strip() else 0.0


def _fresh(tool: str, proof: Path) -> bool:
    """Is this graph current enough to leave alone at session start?"""
    if tool == "graft":
        # graft ships its own staleness check (`graft check`, per its --help);
        # trust it instead of guessing from mtimes.
        exe = shutil.which(tool)
        if exe is None or not proof.exists():
            return False
        check = subprocess.run([exe, "check"], cwd=ROOT, capture_output=True, check=False)
        return check.returncode == 0
    if proof == Path():
        # codebase-memory-mcp keeps its index outside the repo and exposes no
        # staleness check; its `index_repository` is incremental, so rebuild.
        return False
    return proof.exists() and proof.stat().st_mtime >= _head_time()


def refresh_session_start() -> int:
    """E9: build missing graphs and refresh stale ones; warn only, always exit 0.

    A session must not start on a hard error from a background housekeeping
    step, so this mode is warning-only (the strict `refresh()` is for CI/setup).
    In a cloud session it does nothing: an idle supervisor tick must stay cheap, and a working tick
    refreshes the graphs itself (docs/plans/round2/SUPERVISOR.md step 4).
    """
    if os.environ.get("CLAUDE_CODE_REMOTE") == "true":
        return 0
    for warning in version_warnings():
        print(f"refresh_graphs --session-start: WARNING {warning}", file=sys.stderr)
    for tool, args, proof in GRAPHS:
        if _fresh(tool, proof):
            continue
        problem = _run(tool, args)
        if problem is not None:
            print(f"refresh_graphs --session-start: WARNING {problem}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    if "--session-start" in sys.argv[1:]:
        sys.exit(refresh_session_start())
    sys.exit(refresh(if_missing="--if-missing" in sys.argv[1:]))

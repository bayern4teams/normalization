"""The post-commit index-refresh hook.

It runs after every commit on every developer's machine, so the failure
modes that matter are: blocking a commit, failing a commit, or quietly
calling an expensive LLM path.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_HOOK = _ROOT / ".githooks" / "post-commit"


@pytest.mark.unit
def test_the_hook_exists_and_is_executable() -> None:
    assert _HOOK.is_file()
    assert _HOOK.stat().st_mode & stat.S_IXUSR


@pytest.mark.unit
def test_the_hook_is_valid_shell() -> None:
    result = subprocess.run(["bash", "-n", str(_HOOK)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


@pytest.mark.unit
@pytest.mark.parametrize("command", ["graft build", "graphify update .", "index_repository"])
def test_all_three_indexes_are_refreshed(command: str) -> None:
    assert command in _HOOK.read_text(encoding="utf-8")


@pytest.mark.unit
def test_the_hook_never_runs_deep_mode() -> None:
    """Deep mode calls an LLM per symbol — minutes and money on a path
    that must stay between a commit and the next prompt."""
    body = [
        line
        for line in _HOOK.read_text(encoding="utf-8").splitlines()
        if not line.strip().startswith("#")
    ]
    assert not any("--deep" in line or "--mode deep" in line for line in body)


@pytest.mark.unit
def test_the_hook_cannot_fail_a_commit() -> None:
    """Every tool call is guarded and the script ends in `exit 0`: a
    missing tool or a broken index must never look like a failed commit."""
    text = _HOOK.read_text(encoding="utf-8")
    assert "exit 0" in text
    assert "|| echo" in text


@pytest.mark.unit
def test_a_missing_tool_is_skipped_silently() -> None:
    """Not every clone has all three installed."""
    assert 'command -v "$1" >/dev/null 2>&1 || return 0' in _HOOK.read_text(encoding="utf-8")


@pytest.mark.unit
def test_the_hook_exits_immediately_when_disabled() -> None:
    """NORM_SKIP_INDEX_HOOK=1 must short-circuit before any indexing."""
    env = {**os.environ, "NORM_SKIP_INDEX_HOOK": "1"}
    result = subprocess.run(
        ["bash", str(_HOOK)], capture_output=True, text=True, env=env, cwd=_ROOT, check=False
    )
    assert result.returncode == 0
    assert result.stdout == ""


@pytest.mark.unit
def test_the_hook_skips_a_replay_in_progress() -> None:
    """A rebase replays many commits; reindexing on each is pure waste."""
    text = _HOOK.read_text(encoding="utf-8")
    for marker in ("rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD"):
        assert marker in text

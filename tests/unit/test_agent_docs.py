"""AGENTS.md and CLAUDE.md are the same document under two names.

Different agents look for different filenames, and the instructions must
not depend on which one a given tool happens to read. Two copies drift
silently, so this asserts they cannot.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_AGENTS = _ROOT / "AGENTS.md"
_CLAUDE = _ROOT / "CLAUDE.md"


@pytest.mark.unit
def test_both_agent_docs_exist() -> None:
    assert _AGENTS.is_file()
    assert _CLAUDE.is_file()


@pytest.mark.unit
def test_the_two_agent_docs_are_identical() -> None:
    """Fix by copying one over the other: `cp AGENTS.md CLAUDE.md`."""
    assert _AGENTS.read_text(encoding="utf-8") == _CLAUDE.read_text(encoding="utf-8")


@pytest.mark.unit
@pytest.mark.parametrize("tool", ["graphify", "graft", "codebase-memory-mcp", "raw code reading"])
def test_every_discovery_tool_is_documented(tool: str) -> None:
    assert tool in _AGENTS.read_text(encoding="utf-8")


@pytest.mark.unit
def test_discovery_tools_are_documented_in_priority_order() -> None:
    """The order is the point — each later step costs more context than
    the one before it."""
    text = _AGENTS.read_text(encoding="utf-8")
    positions = [
        text.index("**graphify**"),
        text.index("**graft**"),
        text.index("**codebase-memory-mcp**"),
        text.index("**raw code reading**"),
    ]
    assert positions == sorted(positions)


@pytest.mark.unit
@pytest.mark.parametrize(
    "command",
    [
        "/ponytail-review",
        "/ponytail-audit",
        "/ponytail-debt",
        "/ponytail-gain",
        "/ponytail-help",
    ],
)
def test_every_ponytail_command_is_documented(command: str) -> None:
    assert command in _AGENTS.read_text(encoding="utf-8")


@pytest.mark.unit
@pytest.mark.parametrize("level", ["lite", "full", "ultra", "off"])
def test_every_ponytail_level_is_documented(level: str) -> None:
    assert level in _AGENTS.read_text(encoding="utf-8")


@pytest.mark.unit
def test_the_hook_is_documented_as_shallow_only() -> None:
    """Deep mode calls an LLM per symbol; running it on every commit is
    exactly what the hook must not do."""
    text = _AGENTS.read_text(encoding="utf-8")
    assert "never deep" in text
    assert "--deep" in text

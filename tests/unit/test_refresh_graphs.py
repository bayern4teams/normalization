"""scripts/refresh_graphs.py must fail loudly.

The post-commit hook may skip a missing tool; bootstrap and the cloud supervisor may not (a past
version printed "all graphs refreshed" having built nothing).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "refresh_graphs", Path(__file__).resolve().parents[2] / "scripts" / "refresh_graphs.py"
)
assert _SPEC and _SPEC.loader
refresh_graphs = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(refresh_graphs)


@pytest.mark.unit
def test_a_missing_tool_is_a_non_zero_exit_that_names_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(refresh_graphs.shutil, "which", lambda _tool: None)
    assert refresh_graphs.refresh() == 1
    err = capsys.readouterr().err
    for tool in ("graft", "graphify", "codebase-memory-mcp"):
        assert f"{tool} is not on PATH" in err


@pytest.mark.unit
def test_the_graph_commands_never_use_an_llm_path() -> None:
    argv = " ".join(" ".join(args) for _tool, args, _proof in refresh_graphs.GRAPHS)
    assert "--deep" not in argv
    assert "label" not in argv

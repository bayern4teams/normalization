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


_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


@pytest.mark.unit
@pytest.mark.parametrize("script", ["cloud_setup.sh", "cloud_environment_setup.sh"])
def test_both_cloud_setup_scripts_install_exactly_the_pinned_versions(script: str) -> None:
    text = (_SCRIPTS / script).read_text(encoding="utf-8")
    assert f"graphifyy=={refresh_graphs.PINS['graphify']}" in text
    assert f"codebase-memory-mcp=={refresh_graphs.PINS['codebase-memory-mcp']}" in text
    assert f"@nanonets/graft@{refresh_graphs.PINS['graft']}" in text
    assert "DO_NOT_TRACK=1" in text


@pytest.mark.unit
def test_an_installed_version_that_differs_from_the_pin_is_a_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(refresh_graphs.shutil, "which", lambda tool: f"/bin/{tool}")
    reported = {"graphify": "graphify 0.0.1", "graft": "v0.26.0", "codebase-memory-mcp": "x 0.12.1"}
    monkeypatch.setattr(refresh_graphs, "_version_output", lambda exe: reported[Path(exe).name])
    warnings = refresh_graphs.version_warnings()
    assert warnings == [f"graphify is 0.0.1, pinned {refresh_graphs.PINS['graphify']}"]


@pytest.mark.unit
def test_session_start_in_the_cloud_builds_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_CODE_REMOTE", "true")
    calls: list[str] = []
    monkeypatch.setattr(refresh_graphs, "_run", lambda tool, _args: calls.append(tool))
    assert refresh_graphs.refresh_session_start() == 0
    assert calls == []

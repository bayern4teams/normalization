"""scripts/check_release_version.py: a release tag must equal every package's version."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_SPEC = importlib.util.spec_from_file_location(
    "check_release_version",
    Path(__file__).resolve().parents[2] / "scripts" / "check_release_version.py",
)
assert _SPEC is not None and _SPEC.loader is not None
check = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(check)


def _project(root: Path, rel: str, version: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'[project]\nname = "x"\nversion = "{version}"\n')


def test_a_tag_equal_to_every_version_passes(tmp_path: Path) -> None:
    _project(tmp_path, "pyproject.toml", "1.2.3")
    _project(tmp_path, "packages/a/pyproject.toml", "1.2.3")
    assert check.mismatches("v1.2.3", tmp_path) == []


def test_a_package_left_behind_is_named(tmp_path: Path) -> None:
    _project(tmp_path, "pyproject.toml", "1.2.3")
    _project(tmp_path, "packages/a/pyproject.toml", "1.2.3")
    _project(tmp_path, "packages/b/pyproject.toml", "0.1.0")
    assert check.mismatches("v1.2.3", tmp_path) == ["packages/b/pyproject.toml: 0.1.0"]

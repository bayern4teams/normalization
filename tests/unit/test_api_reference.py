"""docs/API.md must match what scripts/generate_api_reference.py writes now.

AGENTS.md §4: every new or changed API route regenerates docs/API.md in the
same commit. This test is the machine check (K4).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.unit
def test_api_reference_is_current() -> None:
    spec = importlib.util.spec_from_file_location(
        "_gen_api", ROOT / "scripts" / "generate_api_reference.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert (ROOT / "docs" / "API.md").read_text(encoding="utf-8") == module.build(), (
        "docs/API.md is stale: the API changed without regenerating it. Fix: run "
        "`uv run python scripts/generate_api_reference.py` and commit docs/API.md."
    )

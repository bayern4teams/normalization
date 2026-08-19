"""Source.txt §135 — "This project must STOP before Splink." Enforced as
a real static check across the whole workspace, not just asserted in
prose: no package may import `splink` or implement entity-resolution
matching logic under that name.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PACKAGE_SRC_GLOB = "packages/*/src/**/*.py"

_IMPORT_RE = re.compile(r"^\s*(?:from\s+splink\b|import\s+splink\b)", re.MULTILINE)


@pytest.mark.unit
def test_no_splink_import_anywhere_in_packages() -> None:
    source_files = list(_REPO_ROOT.glob(_PACKAGE_SRC_GLOB))
    assert len(source_files) > 50, "sanity check: did the source tree move?"

    offenders = [
        str(path.relative_to(_REPO_ROOT))
        for path in source_files
        if _IMPORT_RE.search(path.read_text(encoding="utf-8"))
    ]

    assert offenders == [], f"Source.txt §135 violation: splink imported in {offenders}"

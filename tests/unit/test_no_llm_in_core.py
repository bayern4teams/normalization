"""Source.txt §129 — "the final normalization transformation must be
deterministic and reproducible" / "LLM output must not directly mutate
normalized data." Enforced as a real static check: no core normalization
package may import an LLM SDK, not just asserted in prose.

`normanalysis.type_detection`/`profile_suggestion` (§61/§62/§84) are the
one place the spec explicitly says an LLM *may optionally* assist — this
implementation deliberately uses real, deterministic heuristics instead
(consistent with never letting LLM output mutate normalized data), so
the ban applies there too, not just to `normcore`/`normalizers`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

_CORE_PACKAGE_SRC_DIRS = (
    "packages/normcore/src",
    "packages/normalizers/src",
    "packages/normexec/src",
    "packages/normdict/src",
    "packages/normanalysis/src",
)

# Curated, not exhaustive — the well-known LLM/agent SDK import roots.
_BANNED_IMPORT_ROOTS = (
    "openai",
    "anthropic",
    "transformers",
    "langchain",
    "llama_index",
    "google.generativeai",
    "cohere",
    "mistralai",
    "ollama",
)

_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+(" + "|".join(re.escape(r) for r in _BANNED_IMPORT_ROOTS) + r")\b"
    r"|import\s+(" + "|".join(re.escape(r) for r in _BANNED_IMPORT_ROOTS) + r")\b)",
    re.MULTILINE,
)


def _all_source_files() -> list[Path]:
    files: list[Path] = []
    for rel_dir in _CORE_PACKAGE_SRC_DIRS:
        files.extend((_REPO_ROOT / rel_dir).rglob("*.py"))
    return files


@pytest.mark.unit
def test_no_llm_sdk_imports_in_core_packages() -> None:
    source_files = _all_source_files()
    assert len(source_files) > 50, "sanity check: did the source tree move?"

    offenders = []
    for path in source_files:
        text = path.read_text(encoding="utf-8")
        if _IMPORT_RE.search(text):
            offenders.append(str(path.relative_to(_REPO_ROOT)))

    assert offenders == [], (
        f"Source.txt §129 violation: LLM SDK imports found in core packages: {offenders}"
    )

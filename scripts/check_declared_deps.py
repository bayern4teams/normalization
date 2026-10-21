"""M4/K4: every declared runtime dependency must be used or justified in place.

Rule (M4): an import is a declared dependency, and every declared dependency
is used. This check enforces the second half on the root and workspace-member
`pyproject.toml` files: a dependency line whose import name appears nowhere
in Python sources fails CI — UNLESS the same line carries a justification
comment (>= 3 words) naming why it stays (e.g. env_id fingerprint inputs,
DSN-scheme drivers). That keeps each exception honest and visible (C5) while
the machine does the remembering (K4).

Name resolution is heuristic but generous: `python-dateutil` -> `dateutil`,
`PyICU` -> `icu`, extras dropped; a dependency also counts as used when its
name appears inside SQLAlchemy DSN schemes (`postgresql+psycopg://`) or in a
string passed to `import_module`, because those are real usages the repo has.

Second check: every path in `[tool.mutmut].also_copy` must exist in the tree
(a stale entry silently corrupts the mutation sandbox — see the pyproject
comment above that key).

    uv run python scripts/check_declared_deps.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = ("packages", "services", "scripts", "spikes", "tests")
SCAN_FILES = (ROOT / "conftest.py",)
_IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+([A-Za-z_][A-Za-z0-9_.]*)", re.MULTILINE)
_DEP_RE = re.compile(r'^\s*"([A-Za-z0-9_.\-]+)\s*(?:\[[^\]]*\])?\s*(?:[><=~!]=|[><])')
_ALSO_COPY_RE = re.compile(r'^\s*"([^"]+)",?\s*$')


def _import_names() -> set[str]:
    names: set[str] = set()
    for d in SCAN_DIRS:
        for py in (ROOT / d).rglob("*.py"):
            if "__pycache__" in py.parts:
                continue
            for m in _IMPORT_RE.finditer(py.read_text(encoding="utf-8", errors="replace")):
                names.add(m.group(1).split(".")[0])
    for f in SCAN_FILES:
        if f.exists():
            for m in _IMPORT_RE.finditer(f.read_text(encoding="utf-8", errors="replace")):
                names.add(m.group(1).split(".")[0])
    return names


def _text_corpus() -> str:
    """Whole-source blob for the generous usages (DSN schemes, import_module)."""
    parts = []
    for d in SCAN_DIRS:
        for py in (ROOT / d).rglob("*.py"):
            if "__pycache__" in py.parts:
                continue
            parts.append(py.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


def _import_name_for(dep: str) -> str:
    name = dep.lower().replace("-", "_")
    if name.startswith("opentelemetry_"):
        return "opentelemetry"  # *-api/*-sdk dists share the `opentelemetry` package
    for prefix in ("python_", "py"):
        if name.startswith(prefix) and name[len(prefix) :]:
            cand = name[len(prefix) :]
            if cand in _import_names():
                return cand
    return name


def _dep_lines(pyproject: Path) -> list[tuple[int, str, str]]:
    """(lineno, dep-name, raw-line) inside the first [project] dependencies list."""
    lines = pyproject.read_text(encoding="utf-8").splitlines()
    out: list[tuple[int, str, str]] = []
    in_deps = False
    for i, line in enumerate(lines, 1):
        s = line.strip()
        if s.startswith("dependencies") and s.endswith("["):
            in_deps = True
            continue
        if in_deps:
            if s == "]":
                break
            m = _DEP_RE.match(line)
            if m:
                out.append((i, m.group(1), line))
    return out


def _justified(line: str) -> bool:
    comment = line.split("#", 1)[1] if "#" in line else ""
    return len(comment.split()) >= 3


def check_also_copy() -> list[str]:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r"also_copy\s*=\s*\[(.*?)\]", text, re.DOTALL)
    if not m:
        return []
    bad = []
    for raw in m.group(1).splitlines():
        p = _ALSO_COPY_RE.match(raw)
        if p and not (ROOT / p.group(1)).exists():
            bad.append(f"pyproject.toml [tool.mutmut].also_copy: '{p.group(1)}' does not exist")
    return bad


def main() -> int:
    used = _import_names()
    corpus = _text_corpus()
    problems: list[str] = []
    files = [ROOT / "pyproject.toml", *sorted(ROOT.glob("packages/*/pyproject.toml"))]
    for pyproject in files:
        for lineno, dep, raw in _dep_lines(pyproject):
            if dep == "uvicorn":  # invoked as a server process, not imported
                continue
            imp = _import_name_for(dep)
            if imp in used or dep.lower().replace("-", "_") in used:
                continue
            if dep.lower() in corpus or imp in corpus:  # DSN scheme / import_module / string ref
                continue
            if _justified(raw):
                continue
            problems.append(
                f"{pyproject.relative_to(ROOT)}:{lineno}: '{dep}' declared but never "
                "imported and not justified on the line (M4). Fix: import it where "
                "intended, drop it, or add a >=3-word comment naming why it stays."
            )
    problems += check_also_copy()
    if problems:
        print(f"check_declared_deps: {len(problems)} problem(s):", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return 1
    print(
        "check_declared_deps: OK — "
        f"{sum(len(_dep_lines(f)) for f in files)} declared deps used or justified; "
        "also_copy paths exist."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

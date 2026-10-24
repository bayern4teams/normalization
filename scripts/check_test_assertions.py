"""L4/K4: every test function has a real outcome check.

Ruff's PT rules cover most test smells; what no PT rule covers is a test
function with no assertion at all (ruff has no such check — PT rules are
about assertion *style*, raises width, fixture style). This script parses
the test files a change ADDS or EDITS and fails when a `test_*` function
contains no `assert` statement, no `pytest.raises`/`pytest.warns`/
`pytest.fail`, no `assert*`-named helper call, and no hypothesis `@example`
driven body that calls one. Why: a test without an assertion always passes
(L4).

Scope: a test function whose code changed, compared as an AST against the
base version (comments and formatting do not count). A function whose only
assertion was deleted has changed code and still fails. User decision
2026-10-24: tests that were already assertion-less are listed in
docs/PONYTAIL_DEBT.md and block only when their own code changes; a bystander
edit elsewhere in the file, or a comment added to the test, does not.

    uv run python scripts/check_test_assertions.py            # diff vs main (CI base via arg)
    uv run python scripts/check_test_assertions.py --staged
    uv run python scripts/check_test_assertions.py HEAD~1
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEST_GLOBS = ("tests/",)

_HELPER_HINT = ("assert", "fail", "raises", "warns")


def _diff(base_or_flag: list[str]) -> list[str]:
    cmd = ["git", "diff", *base_or_flag, "--name-only", "--diff-filter=AM", "--", *TEST_GLOBS]
    done = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=True)
    return [f for f in done.stdout.splitlines() if f.endswith(".py")]


def _base_dumps(rel: str, ref: str) -> dict[str, set[str]]:
    """AST dump of every test function in the base version of `rel` (empty if new)."""
    done = subprocess.run(
        ["git", "show", f"{ref}:{rel}"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    try:
        tree = ast.parse(done.stdout)
    except SyntaxError:
        return {}
    out: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            out.setdefault(node.name, set()).add(ast.dump(node))
    return out


def _has_check(node: ast.FunctionDef) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Assert):
            return True
        if isinstance(sub, (ast.Call,)):
            name = sub.func
            dotted = ""
            while isinstance(name, ast.Attribute):
                dotted = name.attr + ("." if dotted else "") + dotted
                name = name.value
            if isinstance(name, ast.Name):
                dotted = name.id + ("." if dotted else "") + dotted
            low = dotted.lower()
            if any(h in low for h in _HELPER_HINT):
                return True
    return False


def main(argv: list[str]) -> int:
    staged = "--staged" in argv
    base = argv[0] if argv and argv[0] != "--staged" else "main"
    base_desc = "staged changes" if staged else f"diff vs {base}"
    files = _diff(["--cached"] if staged else [base])
    bad: list[str] = []
    for rel in files:
        old = _base_dumps(rel, "HEAD" if staged else base)
        path = ROOT / rel
        if not path.exists():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            bad.append(f"{rel}: unparseable ({exc})")
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.FunctionDef)
                and node.name.startswith("test_")
                and not _has_check(node)
                and ast.dump(node) not in old.get(node.name, set())
            ):
                bad.append(f"{rel}:{node.lineno}: {node.name} has no assertion")
    if bad:
        print(
            f"check_test_assertions: {len(bad)} test function(s) in {base_desc} "
            "assert nothing (L4). Fix: assert a real outcome, or delete the "
            "test (with a C5: line in the commit message).",
            file=sys.stderr,
        )
        for b in bad:
            print(f"  {b}", file=sys.stderr)
        return 1
    print(f"check_test_assertions: OK ({base_desc}, {len(files)} file(s) scanned).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

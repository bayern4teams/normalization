"""C5/L1/K4: every new exception carries its C5 comment; removed tests carry a C5: commit line.

Two checks, both scoped to lines a change ADDS (pre-existing exceptions
never block; they were grandfathered on 2026-10-24 by user decision):

C5 — an added line containing `noqa`, `type: ignore`, `pytest.skip(` /
`pytest.mark.skip` or `xfail(` fails unless the same line (or the comment
line directly above, for file-level `# ruff:` directives) carries:
    C5: reason=<text>; approved=<who, YYYY-MM-DD>; review=<YYYY-MM-DD>
Why: unexplained exceptions become permanent (C5), and the C5 comment is
the one rule no existing tool checks — so this script is that check (K4).

L1 — the script lists `test_*` functions the change removes; if any are
removed, at least one commit message in the range must carry a line
starting `C5:` with a reason and an approval date. In --staged mode the
commit message does not exist yet, so L1 reports what WOULD be removed and
exits non-zero with instructions.
Why: agents have been measured deleting tests to pass (L1); removal must
leave a named, dated trail.

    uv run python scripts/check_c5_exceptions.py            # diff vs main (CI base via arg)
    uv run python scripts/check_c5_exceptions.py --staged   # pre-commit on the index
    uv run python scripts/check_c5_exceptions.py HEAD~1     # explicit base

Mirrors scripts/check_no_stubs.py's shape (same base-diff contract, same
CI wiring in .github/workflows/guards.yml).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIRS = ("packages/", "services/", "scripts/", "tests/", "spikes/")

# Built from parts so this file's own regex literals never trip the guard.
_MARKERS = re.compile(
    r"(\b" + "noqa\b" + r"|type:" + r"\s*ignore|pytest\.skip\(|pytest\.mark\.skip|xfail\()"
)
_C5 = re.compile(
    r"C5:\s*reason=.+?;\s*approved=.+?,\s*\d{4}-\d{2}-\d{2};\s*review=\d{4}-\d{2}-\d{2}"
)
_ADDED = re.compile(r"^\+(?!\+\+)")
_REMOVED = re.compile(r"^-(?!--)")
_TEST_DEF = re.compile(r"^[\s+-]*def (test_[A-Za-z0-9_]+)\s*\(")


def _diff(base_or_flag: list[str]) -> list[str]:
    cmd = ["git", "diff", *base_or_flag, "--unified=0", "--", *SOURCE_DIRS]
    done = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=True)
    return done.stdout.splitlines()


def _file_lines(path: str) -> list[str]:
    try:
        return (ROOT / path).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []


def _check_added_exceptions(lines: list[str]) -> list[str]:
    hits: list[str] = []
    current_file = "?"
    new_lineno = 0
    for line in lines:
        if line.startswith("+++ "):
            current_file = line[4:].removeprefix("b/").rstrip()
            continue
        # Self-exemption: this script defines the marker patterns, so its
        # own regex-literal lines contain `noqa`/`skip`/`xfail` as data and
        # would trip the very guard they implement. The exemption covers
        # this file only, not any other file's added lines.
        if current_file.endswith("scripts/check_c5_exceptions.py"):
            continue
        m = re.match(r"^@@ -\S+ \+(\d+)", line)
        if m:
            new_lineno = int(m.group(1)) - 1
            continue
        if not _ADDED.match(line):
            continue
        new_lineno += 1
        content = line[1:]
        if not _MARKERS.search(content):
            continue
        if _C5.search(content):
            continue
        # A comment line directly above the added line may carry the C5
        # metadata (file-level ruff noqa directives cannot hold an inline
        # comment without changing the directive).
        above = _file_lines(current_file)
        idx = new_lineno - 1  # 0-based index of the added line in the file
        prev = above[idx - 1] if 0 < idx <= len(above) else ""
        if _C5.search(prev) and prev.lstrip().startswith("#"):
            continue
        hits.append(f"{current_file}:{new_lineno}: {content.strip()[:120]}")
    return hits


def _removed_test_funcs(base: str, staged: bool) -> tuple[list[str], str]:
    """Test-function names on the removed side of the diff, minus ones that
    still exist (renames/moves keep a def on the added side)."""
    flags = ["--cached"] if staged else [base]
    removed: dict[str, set[str]] = {}
    added: dict[str, set[str]] = {}
    for line in _diff(flags):
        bucket = None
        if line.startswith("+++ "):
            current = line[4:].removeprefix("b/").rstrip()
            bucket = added
            continue
        if line.startswith("--- "):
            continue
        if line.startswith("+"):
            bucket = added
        elif line.startswith("-"):
            bucket = removed
        else:
            continue
        if bucket is None:
            continue
        m = _TEST_DEF.match(line)
        if m and current.endswith(".py"):
            bucket.setdefault(current, set()).add(m.group(1))
    gone: list[str] = []
    for f, names in removed.items():
        still = added.get(f, set())
        on_disk = {n.group(1) for n in map(_TEST_DEF.match, _file_lines(f)) if n}
        for name in sorted(names - still - on_disk):
            gone.append(f"{f}::{name}")
    # Commit messages in range (push/PR mode only; --staged has no message).
    if staged:
        return gone, ""
    log = subprocess.run(
        ["git", "log", f"{base}..HEAD", "--format=%B%n---COMMIT---"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return gone, log


def main(argv: list[str]) -> int:
    staged = "--staged" in argv
    base = argv[0] if argv and argv[0] != "--staged" else "main"
    base_desc = "staged changes" if staged else f"diff vs {base}"

    rc = 0
    hits = _check_added_exceptions(_diff(["--cached"] if staged else [base]))
    if hits:
        rc = 1
        print(
            f"check_c5_exceptions: {len(hits)} added line(s) in {base_desc} carry "
            "noqa / type: ignore / skip / xfail without the C5 comment (C5). "
            "Fix: add `# C5: reason=<text>; approved=<who, YYYY-MM-DD>; "
            "review=<YYYY-MM-DD>` on the same line, or remove the exception.",
            file=sys.stderr,
        )
        for h in hits:
            print(f"  {h}", file=sys.stderr)

    gone, messages = _removed_test_funcs(base, staged)
    if gone:
        c5_line = re.search(r"(?m)^C5:.+", messages)
        if c5_line is None:
            rc = 1
            what = (
                "no commit message exists yet (--staged): commit with a line "
                "starting `C5: reason=<text>; approved=<who, YYYY-MM-DD>`"
                if staged
                else "no commit message in the range starts with a `C5:` line "
                "naming the reason and the user approval"
            )
            print(
                f"check_c5_exceptions: {len(gone)} test function(s) removed in "
                f"{base_desc} but {what} (L1).",
                file=sys.stderr,
            )
            for g in gone:
                print(f"  {g}", file=sys.stderr)

    if rc == 0:
        print(f"check_c5_exceptions: OK ({base_desc}).")
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

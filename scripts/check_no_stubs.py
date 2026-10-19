"""C4/K4: fail when a change ADDS a TODO/FIXME marker to shipped source.

Only added lines are checked, so pre-existing markers never block CI (the
baseline in scope is 0 markers: `grep -rnwE 'TODO|FIXME' packages services
ui/src` finds none, measured 2026-10-19). Scope is shipped source:
packages/, services/, ui/src. Tests, docs and tooling files are not
source. A `ponytail:` comment is explicitly allowed — C4 says the code
works and the comment names its known limit (decision 2026-10-19, user's
words: "ponytail: lines exempt").

XXX was dropped from the marker list on 2026-10-19 by user decision (F4),
the user's words: "XXX is also real data (the ISO 4217 code for 'no
currency'), so a normalizer data line with it would fail CI." Matching is
TODO/FIXME only.

    uv run python scripts/check_no_stubs.py                 # diff vs main (CI base)
    uv run python scripts/check_no_stubs.py --staged        # pre-commit on the index
    uv run python scripts/check_no_stubs.py HEAD~1          # diff vs an explicit base

Word-token match (TODO, FIXME as standalone words, case-sensitive,
uppercase only), so ordinary prose and lowercase identifiers pass.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIRS = ("packages/", "services/", "ui/src/")
_MARKER = re.compile(r"\b(TODO|FIXME)\b")

# A diff's "new side" line: starts with '+', but not the '+++' file header.
_ADDED = re.compile(r"^\+(?!\+\+)")


def _diff(base_or_flag: list[str]) -> list[str]:
    cmd = ["git", "diff", *base_or_flag, "--unified=0", "--", *SOURCE_DIRS]
    done = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=True)
    return done.stdout.splitlines()


def _violations(lines: list[str]) -> list[str]:
    hits: list[str] = []
    current_file = "?"
    for line in lines:
        if line.startswith("+++ "):
            current_file = line[4:].removeprefix("b/").rstrip()
            continue
        if not _ADDED.match(line):
            continue
        content = line[1:]
        if _MARKER.search(content) and "ponytail:" not in content:
            hits.append(f"{current_file}: {content.strip()[:120]}")
    return hits


def main(argv: list[str]) -> int:
    if "--staged" in argv:
        diff_lines = _diff(["--cached"])
        base_desc = "staged changes"
    else:
        base = argv[0] if argv else "main"
        diff_lines = _diff([base])
        base_desc = f"diff vs {base}"

    hits = _violations(diff_lines)
    if hits:
        print(
            f"check_no_stubs: {len(hits)} added line(s) in {base_desc} carry a "
            "TODO/FIXME marker (C4). Fix: implement the behaviour, or write a "
            "`ponytail:` comment naming the known limit, or remove the marker.",
            file=sys.stderr,
        )
        for h in hits:
            print(f"  {h}", file=sys.stderr)
        return 1
    print(f"check_no_stubs: OK — no TODO/FIXME added in shipped source ({base_desc}).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""J13/K4: a commit that changes shipped source must say what it did to the docs.

Every commit in the checked range that touches shipped source (the same
scope as scripts/check_no_stubs.py: packages/, services/, ui/src/) needs a
message line starting with `Docs:`, for example `Docs: none, internal
refactor`. Merge commits are skipped. Only the commits in the range are
checked, so history pushed before this check existed never blocks CI.

    python3 scripts/check_docs_note.py <base>..HEAD
    python3 scripts/check_docs_note.py <base>          # means <base>..HEAD
    python3 scripts/check_docs_note.py --range <base>..HEAD

The fix when this fails: add a `Docs:` line to the commit message
(`git commit --amend` for the newest one, `git rebase -i` for older ones)
before pushing. `Docs: none, <why>` is the right line when the change
genuinely affects no document.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIRS = ("packages/", "services/", "ui/src/")


def _git(*args: str) -> str:
    done = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True)
    return done.stdout


def _touches_source(commit: str) -> bool:
    files = _git("show", "--format=", "--name-only", "--no-color", commit).split()
    return any(f.startswith(SOURCE_DIRS) for f in files)


def _has_docs_line(commit: str) -> bool:
    message = _git("log", "-1", "--format=%B", commit)
    return any(line.startswith("Docs:") for line in message.splitlines())


def main(argv: list[str]) -> int:
    args = [a for a in argv if a != "--range"]
    if len(args) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    rng = args[0] if ".." in args[0] else f"{args[0]}..HEAD"

    commits = _git("rev-list", "--no-merges", rng).split()
    offenders = [c for c in commits if _touches_source(c) and not _has_docs_line(c)]
    if offenders:
        print(
            f"check_docs_note: {len(offenders)} commit(s) in {rng} change shipped "
            "source without a `Docs:` line (J13):",
            file=sys.stderr,
        )
        for c in offenders:
            subject = _git("log", "-1", "--format=%s", c).strip()
            print(f"  {c[:9]} {subject}", file=sys.stderr)
        print(
            'Fix: add a line like "Docs: none, internal refactor" (or naming the '
            "updated documents) to each message — `git commit --amend` for the "
            "newest commit, `git rebase -i <base>` for older ones — before "
            "pushing.",
            file=sys.stderr,
        )
        return 1
    print(f"check_docs_note: OK — {len(commits)} commit(s) checked in {rng} (J13).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

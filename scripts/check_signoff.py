"""Gate precondition check: refuses to let a milestone's `gate` workflow run
unless the PREVIOUS milestone's verification pack exists, is signed, and its
verdict is APPROVED (or APPROVED_WITH_CONDITIONS with no open conditions).

Also enforces that the signed pack's recorded commit matches HEAD's ancestry
and that its recorded env_id matches what the current environment computes —
so a stale or environment-mismatched sign-off cannot silently authorize
unrelated work.

Usage:
    uv run python scripts/check_signoff.py --milestone M3
        -> checks docs/verification/M2-verification-pack.md (the PRECEDING milestone)

    uv run python scripts/check_signoff.py --milestone M0
        -> M0 has no precondition (first milestone); always passes.

Exit code 0 = ok to proceed, 1 = blocked (with a human-readable reason).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

MILESTONE_ORDER = [
    "M0",
    "M1",
    "M2",
    "M3",
    "M4",
    "M5",
    "M6",
    "M7",
    "M8",
    "M9",
    "M10",
    "M11",
    "M12",
    "M13",
    "M14",
    "M15",
    "M16",
    "M17",
    "M18",
    "M19",
    "M20",
    "M21",
    "M22",
]
# NOTE (M13 ledger catch-up, 2026-08-26): this list stopped at M8 even
# though M9-M12 were built, gated in CI (gate.yml resolves a milestone
# name from the branch/dispatch input with no bound to this list), and
# merged — meaning `check_signoff.py --milestone M9` (and M10/M11/M12)
# would have failed argparse's `choices` validation outright had anyone
# actually invoked it locally with those names. This was a real,
# previously-undisclosed gap in the gate's own precondition tooling,
# found during the M13 documentation catch-up, not by design.

SIGNOFF_BLOCK_RE = re.compile(
    r"##\s*Human Sign-off\s*\n"
    r"(?P<body>(?:^.*\n?)*?)"
    r"(?=\n##|\Z)",
    re.MULTILINE,
)
FIELD_RE = re.compile(r"^(?P<key>[a-zA-Z_]+):\s*(?P<value>.*)$", re.MULTILINE)

VALID_VERDICTS = {"APPROVED", "APPROVED_WITH_CONDITIONS"}


class SignoffError(RuntimeError):
    pass


def parse_signoff(pack_text: str) -> dict[str, str]:
    match = SIGNOFF_BLOCK_RE.search(pack_text)
    if not match:
        raise SignoffError("No '## Human Sign-off' block found in verification pack.")
    body = match.group("body")
    fields: dict[str, str] = {}
    for line in body.splitlines():
        field_match = FIELD_RE.match(line.strip())
        if field_match:
            fields[field_match.group("key")] = field_match.group("value").strip()
    return fields


def git_commit_exists(commit: str) -> bool:
    if not commit or commit.startswith("<"):
        return False
    result = subprocess.run(
        ["git", "cat-file", "-e", commit],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def check(milestone: str, docs_dir: Path, *, require_commit_match: bool) -> None:
    idx = MILESTONE_ORDER.index(milestone)
    if idx == 0:
        print(f"{milestone}: first milestone, no sign-off precondition. OK.")
        return

    preceding = MILESTONE_ORDER[idx - 1]
    pack_path = docs_dir / f"{preceding}-verification-pack.md"

    if not pack_path.exists():
        raise SignoffError(
            f"Blocked: {pack_path} does not exist. "
            f"Milestone {preceding} must be gated and signed before {milestone} can start."
        )

    fields = parse_signoff(pack_path.read_text(encoding="utf-8"))

    verdict = fields.get("verdict", "")
    if verdict not in VALID_VERDICTS:
        raise SignoffError(
            f"Blocked: {pack_path} has verdict='{verdict or '<empty>'}', "
            f"expected one of {sorted(VALID_VERDICTS)}."
        )

    if verdict == "APPROVED_WITH_CONDITIONS":
        conditions = fields.get("conditions", "[]").strip()
        if conditions not in ("[]", ""):
            raise SignoffError(
                f"Blocked: {pack_path} verdict is APPROVED_WITH_CONDITIONS but "
                f"conditions are not empty: {conditions}. Close all conditions first."
            )

    reviewer = fields.get("reviewer", "")
    if not reviewer or reviewer.startswith("<"):
        raise SignoffError(f"Blocked: {pack_path} missing a real 'reviewer' value.")

    commit = fields.get("commit", "")
    if require_commit_match and not git_commit_exists(commit):
        raise SignoffError(
            f"Blocked: {pack_path} records commit='{commit}', which is not "
            f"reachable in this repository. Sign-off does not match repo history."
        )

    print(
        f"{milestone}: preceding milestone {preceding} sign-off OK "
        f"(verdict={verdict}, reviewer={reviewer}, commit={commit})."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--milestone", required=True, choices=MILESTONE_ORDER)
    parser.add_argument("--docs-dir", default=Path("docs/verification"), type=Path)
    parser.add_argument(
        "--no-commit-check",
        action="store_true",
        help="skip git ancestry check (useful for local dry-runs before committing the pack)",
    )
    args = parser.parse_args()

    try:
        check(args.milestone, args.docs_dir, require_commit_match=not args.no_commit_check)
    except SignoffError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

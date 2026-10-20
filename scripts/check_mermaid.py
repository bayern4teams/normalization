"""Render every Mermaid block in the given Markdown files; fail if any block fails.

J3 says diagrams are Mermaid and true to the code — this proves at least that they are valid
Mermaid. A file with no mermaid block passes (0 blocks is a pass, not a vacuous failure).

    uv run python scripts/check_mermaid.py                 # the five J1 files
    uv run python scripts/check_mermaid.py README.md ...   # explicit files

Needs Node; `npx -y @mermaid-js/mermaid-cli` fetches mmdc (and its Chromium) on first use.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCOPE = [
    "README.md",
    "ARCHITECTURE.md",
    "TECHNICAL_IMPLEMENTATION.md",
    "GLOSSARY.md",
    "docs/LESSONS.md",
    "AGENTS.md",
]
_BLOCK = re.compile(r"^```mermaid\n(.*?)^```", re.DOTALL | re.MULTILINE)


def main(argv: list[str]) -> int:
    files = [Path(a) for a in argv] if argv else [ROOT / f for f in SCOPE]
    failures = 0
    blocks = 0
    with tempfile.TemporaryDirectory(prefix="mmd-") as tmp:
        for path in files:
            if not path.is_file():
                continue  # missing J1 files are prompt 2's job, not a render failure
            for n, body in enumerate(_BLOCK.findall(path.read_text(encoding="utf-8")), 1):
                blocks += 1
                src = Path(tmp) / f"{path.stem}-{n}.mmd"
                out = Path(tmp) / f"{path.stem}-{n}.svg"
                src.write_text(body, encoding="utf-8")
                done = subprocess.run(
                    [
                        "npx",
                        "-y",
                        "@mermaid-js/mermaid-cli@12.0.0",
                        # C5 exception: --no-sandbox for Chromium (puppeteer-config.json).
                        # Reason: Ubuntu 24.04 AppArmor blocks Chromium's sandbox on GitHub
                        # runners; it renders only this repo's own diagrams.
                        # Approved by user 2026-10-20; review 2027-04-20.
                        "-p",
                        str(ROOT / "puppeteer-config.json"),
                        "-i",
                        str(src),
                        "-o",
                        str(out),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if done.returncode != 0:
                    failures += 1
                    print(f"{path} block {n}: {done.stderr[-500:]}", file=sys.stderr)
    print(f"check_mermaid: {blocks} block(s), {failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

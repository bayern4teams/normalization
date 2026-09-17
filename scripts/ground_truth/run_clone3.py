#!/usr/bin/env python3
"""Run the driver into a second destination to prove byte-identical determinism."""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "ground_truth"))
sys.path.insert(0, str(ROOT / "packages" / "normcore" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "normalizers" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "normdict" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "normexec" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "normapi" / "src"))

import run
import json

env = {}
for line in (ROOT / ".env.groundtruth").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip()

# Run into testdiffbot_clone3
import subprocess
result = subprocess.run(
    ["uv", "run", "python", str(ROOT / "scripts" / "ground_truth" / "run.py"),
     "--dest-db", "testdiffbot_clone3"],
    cwd=ROOT,
    capture_output=True,
    text=True,
    env={**__import__("os").environ, **env},
    timeout=600,
)
print(result.stdout)
if result.stderr:
    print("STDERR:", result.stderr, file=sys.stderr)
print(f"Exit code: {result.returncode}")

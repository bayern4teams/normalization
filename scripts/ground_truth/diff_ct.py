#!/usr/bin/env python3
"""Find the exact rows that differ between clone2 and clone3 for companytechnographics."""
from __future__ import annotations
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
env: dict[str, str] = {}
for line in (ROOT / ".env.groundtruth").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip()

# Get the DSN parts
dsn_parts = {}
for line in (ROOT / ".env.groundtruth").read_text().splitlines():
    if line.startswith("GT_DEST_DSN="):
        dsn = line.split("=", 1)[1].strip()
        # postgresql://norm_writable:password@host:port/db
        # Extract host:port (without db)
        idx = dsn.rfind("/")
        if idx >= 0:
            dsn_no_db = dsn[:idx]
        else:
            dsn_no_db = dsn

# We can use psql to dump and diff
import subprocess
for db in ("testdiffbot_clone2", "testdiffbot_clone3"):
    dsn = dsn_no_db + "/" + db
    cmd = f"psql '{dsn}' -Atc \"SELECT * FROM \\\"companytechnographics\\\" ORDER BY ctid\""
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    outpath = f"/tmp/clone3_{db}_ct.csv"
    Path(outpath).write_text(r.stdout)
    print(f"Wrote {outpath} ({len(r.stdout)} bytes, {len(r.stdout.splitlines())} rows)")

# Now diff
import difflib
f2 = Path("/tmp/clone3_testdiffbot_clone2_ct.csv").read_text().splitlines()
f3 = Path("/tmp/clone3_testdiffbot_clone3_ct.csv").read_text().splitlines()

diffs = list(difflib.unified_diff(f2, f3, lineterm=""))
print(f"\nDiff lines: {len(diffs)}")
for d in diffs[:100]:
    print(d)
if len(diffs) > 100:
    print(f"... ({len(diffs)} total lines)")

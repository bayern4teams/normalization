#!/usr/bin/env python3
"""Fix the row_index bug in run.py.

source_row_key from _sql_base.py is a batch offset like "companycontact:763",
not a real PK. Both ledger entries parse this as int, giving chunk offsets
instead of actual PK values (d00fc465b255bf5e, ddddce1766493d4f).

Fix: extract first column (always *id) from row data as row identifier.
"""
from pathlib import Path

RUN_PY = Path(__file__).resolve().parent / "run.py"
content = RUN_PY.read_text()

# Fix 1: Change pending type and row-key extraction
old_pending = '''            pending: list[tuple[int, dict]] = []
            for r in rows:
                try:
                    off = int(r["source_row_key"].rsplit(":", 1)[1])
                except (KeyError, ValueError):
                    continue
                if off > ckpt:
                    pending.append((off, r))'''

new_pending = '''            first_col = cols[0].name
            pending: list[tuple[str, dict]] = []
            row_num = 0
            for r in rows:
                try:
                    row_key = str(r[first_col])
                except (KeyError, ValueError):
                    continue
                row_num += 1
                if ckpt == -1 or row_num > ckpt:
                    pending.append((row_key, r))'''

if old_pending in content:
    content = content.replace(old_pending, new_pending, 1)
    print("✓ Patch 1: row-key extraction (batch offset → first column)")
else:
    print("✗ Patch 1: old pattern not found")

# Fix 2: Update checkpoint tracking
old_ckpt = '''            for off, _ in pending:
                ckpt_off = max(ckpt_off, off)'''
new_ckpt = '''            ckpt_off = row_num'''

if old_ckpt in content:
    content = content.replace(old_ckpt, new_ckpt, 1)
    print("✓ Patch 2: checkpoint tracking")
else:
    print("✗ Patch 2: old checkpoint pattern not found")

# Fix 3: Ledger row_index at normalization errors
old_ledger1 = '''                        ledger.append({
                            "table": table,
                            "row_index": int(row["source_row_key"].rsplit(":", 1)[1]),
                            "field": col,'''
new_ledger1 = '''                        ledger.append({
                            "table": table,
                            "row_index": row[first_col],
                            "field": col,'''

if old_ledger1 in content:
    content = content.replace(old_ledger1, new_ledger1, 1)
    print("✓ Patch 3: ledger row_index (normalization errors)")
else:
    print("✗ Patch 3: old ledger pattern 1 not found")

# Fix 4: Ledger row_index at contactstring errors
old_ledger2 = '''                        ledger.append({
                            "table": "companycontact",
                            "row_index": int(row["source_row_key"].rsplit(":", 1)[1]),
                            "field": "contactstring",'''
new_ledger2 = '''                        ledger.append({
                            "table": "companycontact",
                            "row_index": row[first_col],
                            "field": "contactstring",'''

if old_ledger2 in content:
    content = content.replace(old_ledger2, new_ledger2, 1)
    print("✓ Patch 4: ledger row_index (contactstring errors)")
else:
    print("✗ Patch 4: old ledger pattern 2 not found")

RUN_PY.write_text(content)
print("\nDone. Run: uv run python scripts/ground_truth/run.py")

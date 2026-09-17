#!/usr/bin/env python3
"""Headless ground-truth driver: Phases C-F.

Reads ground_truth/column_config.json, builds the destination schema,
streams rows from origin, normalizes via the repo's deterministic engine,
writes checkpoints, ledger, and run record.

Usage:
  uv run python scripts/ground_truth/run.py         # Fresh run
  uv run python scripts/ground_truth/run.py --resume # Resume from checkpoint
"""
from __future__ import annotations

import argparse
import json
import sys
import blake3
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "normcore" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "normalizers" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "normdict" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "normexec" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "normapi" / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "ground_truth"))

import pre_repair
import sqlalchemy as sa
from normio.connectors import PostgresConnector, PostgresDestination
from normio.connectors._sql_base import ROW_CHUNK_SIZE
from normcore import (
    Dispatcher, ErrorPolicy, FieldSemanticType, NormalizationContext,
    NormalizerRegistry,
)
from normexec.planner import DistinctValuePlanner
from normdict import DictionaryLoader
from normalizers.address import AddressNormalizer, LibpostalClient
from normalizers.boolean import BooleanNormalizer
from normalizers.company import CompanyNormalizer
from normalizers.country import CountryNormalizer
from normalizers.currency import CurrencyNormalizer
from normalizers.date import DateNormalizer
from normalizers.email import EmailNormalizer
from normalizers.generic_text import GenericTextNormalizer
from normalizers.identifier import IdentifierNormalizer, UuidNormalizer
from normalizers.language import LanguageNormalizer
from normalizers.name import NameNormalizer
from normalizers.numeric import NumericNormalizer
from normalizers.passthrough import PassthroughNormalizer
from normalizers.phone import PhoneNormalizer
from normalizers.postcode import PostcodeNormalizer
from normalizers.script import ScriptNormalizer
from normalizers.unit import UnitNormalizer
from normalizers.url import URLNormalizer

# ── Constants ──────────────────────────────────────────────────────────
TABLES = [
    "company", "companycontact", "companyemployeecategory", "companyexperience",
    "companyfinancials", "companyindustry", "companyinvestmentround",
    "companyinvestor", "companyrelation", "companytechnographics",
    "industryclassification", "location", "person",
]
CONFIG_FILE = ROOT / "ground_truth" / "column_config.json"
LEDGER_FILE = ROOT / "ground_truth" / "ledger.jsonl"
CHECKPOINT_FILE = ROOT / "ground_truth" / "checkpoints.json"
RUN_RECORD_FILE = ROOT / "ground_truth" / "run_record.json"


# ── Helpers ────────────────────────────────────────────────────────────
def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in (ROOT / ".env.groundtruth").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    return env


def build_dispatcher(libpostal_url: str):
    loader = DictionaryLoader(str(ROOT / "data" / "dictionaries"))
    registry = NormalizerRegistry()
    registry.register(PassthroughNormalizer())
    registry.register(GenericTextNormalizer(loader))
    registry.register(NameNormalizer(loader))
    registry.register(CompanyNormalizer(loader))
    registry.register(PhoneNormalizer())
    registry.register(EmailNormalizer())
    registry.register(AddressNormalizer(LibpostalClient(libpostal_url)))
    registry.register(PostcodeNormalizer())
    registry.register(DateNormalizer())
    registry.register(CountryNormalizer())
    registry.register(LanguageNormalizer())
    registry.register(ScriptNormalizer())
    registry.register(IdentifierNormalizer())
    registry.register(UuidNormalizer())
    registry.register(NumericNormalizer())
    registry.register(CurrencyNormalizer())
    registry.register(UnitNormalizer())
    registry.register(BooleanNormalizer())
    registry.register(URLNormalizer())
    env_id = blake3.blake3(b"ground-truth-v1").hexdigest()
    return Dispatcher(registry, env_id=env_id), env_id


def validate_config(config):
    for table, cols in config.items():
        for col, stype in cols.items():
            if stype is None or stype == "PASSTHROUGH":
                continue
            try:
                FieldSemanticType(stype)
            except ValueError:
                raise ValueError(f"Invalid type {stype!r} for {table}.{col}")


# ── Phase E pre-repair router ──────────────────────────────────────────
_PRE_REPAIR_MAP: dict[tuple[str, str], tuple[str, callable]] = {
    ("company", "foundingdate"): ("foundingdate", pre_repair.repair_date),
    ("companyemployeecategory", "firsthiredate"): ("firsthiredate", pre_repair.repair_date),
    ("companyinvestmentround", "date"): ("date", pre_repair.repair_date),
    ("company", "website"): ("website", pre_repair.repair_website),
    ("companycontact", "contactstring"): ("contactstring", pre_repair.repair_email),
}


def _pre_repair_col(table: str, col: str, value: str) -> tuple[str, bool]:
    """Apply the Phase E pre-repair rule for this (table, col), if any."""
    key = (table, col)
    if key in _PRE_REPAIR_MAP:
        rule_name, fn = _PRE_REPAIR_MAP[key]
        repaired, changed = fn(value)
        return repaired, changed
    return value, False


# ── Main ───────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="Ground-truth driver")
    ap.add_argument("--resume", action="store_true", help="Resume from last checkpoint")
    ap.add_argument("--dest-db", default=None, help="Override destination database (e.g. determinism run)")
    args = ap.parse_args()

    env = load_env()
    origin_dsn = env["GT_ORIGIN_DSN"]
    dest_dsn = env["GT_DEST_DSN"]
    dest_db = args.dest_db or env["GT_DEST_DB"]
    libpostal_url = env["LIBPOSTAL_URL"]
    origin_schema = env.get("GT_ORIGIN_SCHEMA", "diffbot")

    config = json.loads(CONFIG_FILE.read_text())
    validate_config(config)
    print("✓ Column config validated.\n")

    dispatcher, env_id = build_dispatcher(libpostal_url)
    print(f"✓ Dispatcher built (env_id={env_id[:20]}...)\n")

    # Dest connector
    p = urlparse(dest_dsn)
    dest = PostgresDestination(
        p.hostname or "localhost",
        p.port or 5433,
        p.username,
        p.password,
    )
    if not dest.database_exists(dest_db):
        print(f"✗ {dest_db!r} does not exist."); sys.exit(1)

    origin = PostgresConnector("origin", origin_dsn)

    # ═══════════ PHASE C: Drop + recreate tables ═══════════
    with dest._engine_for(dest_db).begin() as conn:
        for t in TABLES:
            conn.execute(sa.text(f'DROP TABLE IF EXISTS "{t}" CASCADE'))
    print("✓ Drop all 13 tables\n")

    for table in TABLES:
        cols = origin.get_columns(table)
        pk = origin.get_primary_key(table)
        tc = config.get(table, {})
        semantic_types = {
            c.name: st
            for c in cols
            if (st := tc.get(c.name)) and st != "PASSTHROUGH"
        }
        dest.create_table(dest_db, table, cols, primary_key=pk, semantic_types=semantic_types)

    with dest._engine_for(dest_db).begin() as conn:
        conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS _norm_errors (
                row_index INTEGER, table_name TEXT, field TEXT, original TEXT, error TEXT
            )
        """))
    print("✓ Phase C complete.\n")

    # ═══════════ PHASE D: Stream / normalize / populate ═══════════
    planner = DistinctValuePlanner(dispatcher, None)  # no persistent cache
    ledger: list[dict] = []
    stats: dict[str, dict] = {}
    checkpoints = json.loads(CHECKPOINT_FILE.read_text()) if CHECKPOINT_FILE.exists() else {}

    from normapi.scaffold_profile import SCAFFOLD_PROFILE

    for table in TABLES:
        print(f"── {table} ──")
        cols = origin.get_columns(table)
        pk = origin.get_primary_key(table)
        tc = config.get(table, {})
        configured: dict[str, FieldSemanticType] = {
            c.name: FieldSemanticType(tc[c.name])
            for c in cols if tc.get(c.name) and tc[c.name] != "PASSTHROUGH"
        }
        ckpt = checkpoints.get(table, -1) if args.resume else -1
        print(f"  ckpt={ckpt} | config={list(configured.keys())}")

        # Special: companycontact.contactstring → EMAIL/PHONE by contacttype
        cs_lookup: dict[str, tuple] = {}  # {original: (display, error_str)}
        if table == "companycontact" and "contactstring" in [c.name for c in cols]:
            all_rows: list[dict] = []
            for b in origin.read_table("companycontact", batch_size=ROW_CHUNK_SIZE):
                all_rows.extend(b.to_pylist())
            # Map each distinct contactstring → its contacttype(s)
            val2types: dict[str, set[str]] = {}
            for r in all_rows:
                cs = r.get("contactstring")
                ct = r.get("contacttype")
                if cs is not None:
                    val2types.setdefault(cs, set()).add(ct)
            # Normalize each value with the right type
            for cs_val, types in val2types.items():
                if types == {"OFFICE"}:
                    st = FieldSemanticType.PHONE
                elif types <= {"PROFESSIONAL", "None"}:
                    st = FieldSemanticType.EMAIL
                else:
                    continue  # passthrough (shouldn't happen)
                ctx = NormalizationContext(
                    field_name="contactstring", semantic_type=st, table=table,
                    source="ground-truth", error_policy=ErrorPolicy.RETURN_ORIGINAL,
                )
                r = dispatcher.normalize(cs_val, st, ctx, SCAFFOLD_PROFILE)
                cs_lookup[cs_val] = (r.display, "; ".join(r.errors) if r.errors else "")

        rows_done = 0
        errs = 0
        ckpt_off = -1

        for batch in origin.read_table(table, batch_size=ROW_CHUNK_SIZE):
            rows = batch.to_pylist()
            pending: list[tuple[int, dict]] = []
            for r in rows:
                try:
                    off = int(r["source_row_key"].rsplit(":", 1)[1])
                except (KeyError, ValueError):
                    continue
                if off > ckpt:
                    pending.append((off, r))
            if not pending:
                continue

            # ── normalize configured columns ──
            for col, st in configured.items():
                # Phase E: apply pre-repair rules before normalizer
                for off, row in pending:
                    orig = row.get(col)
                    if orig is None or not isinstance(orig, str):
                        continue
                    repaired, changed = _pre_repair_col(table, col, orig)
                    if changed:
                        row[col] = repaired

                vals = list({r[col] for _, r in pending if r[col] is not None})
                ctx = NormalizationContext(
                    field_name=col, semantic_type=st, table=table,
                    source="ground-truth", error_policy=ErrorPolicy.RETURN_ORIGINAL,
                )
                res = planner.distinct_value_results(vals, st, ctx, SCAFFOLD_PROFILE)
                for _, row in pending:
                    orig = row[col]
                    if orig is None:
                        continue
                    rv = res[orig]
                    row[col] = rv.display
                    if rv.errors:
                        errs += 1
                        ledger.append({
                            "table": table,
                            "row_index": int(row["source_row_key"].rsplit(":", 1)[1]),
                            "field": col,
                            "original": str(orig),
                            "error": "; ".join(rv.errors),
                        })

            # ── apply contactstring lookup ──
            if cs_lookup:
                for _, row in pending:
                    orig = row.get("contactstring")
                    if orig is None:
                        continue
                    disp, err = cs_lookup.get(orig, (orig, ""))
                    row["contactstring"] = disp
                    if err:
                        errs += 1
                        ledger.append({
                            "table": "companycontact",
                            "row_index": int(row["source_row_key"].rsplit(":", 1)[1]),
                            "field": "contactstring",
                            "original": str(orig),
                            "error": err,
                        })

            # ── bulk insert ──
            dest_rows = [
                {k: v for k, v in r.items() if k != "source_row_key"}
                for _, r in pending
            ]
            dest.bulk_insert(dest_db, table, dest_rows, primary_key=pk)

            for off, _ in pending:
                ckpt_off = max(ckpt_off, off)
            rows_done += len(pending)

        checkpoints[table] = ckpt_off
        CHECKPOINT_FILE.write_text(json.dumps(checkpoints, indent=2))
        stats[table] = {"rows": rows_done, "errors": errs, "checkpoint": ckpt_off}
        print(f"  {rows_done} rows, {errs} errors, ckpt={ckpt_off}")

    # ── write ledger & _norm_errors ──
    with open(LEDGER_FILE, "w") as f:
        for e in ledger:
            f.write(json.dumps(e, default=str) + "\n")
    if ledger:
        with dest._engine_for(dest_db).begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO _norm_errors (row_index, table_name, field, original, error) "
                    "VALUES (:ri, :tn, :f, :o, :e)"
                ),
                [{"ri": e["row_index"], "tn": e["table"], "f": e["field"],
                  "o": str(e["original"]), "e": str(e["error"])} for e in ledger],
            )
            print(f"  → {len(ledger)} errors written to _norm_errors")
    print("✓ Phase D complete.\n")

    # ═══════════ PHASE E: Report ═══════════
    if ledger:
        print("── Phase E: Ledger error grouping ──")
        groups: dict[tuple, dict] = {}
        for e in ledger:
            k = (e["table"], e["field"], e["error"])
            g = groups.setdefault(k, {"count": 0, "ex": set()})
            g["count"] += 1
            g["ex"].add(str(e["original"])[:80])
        for (t, fld, err), g in sorted(groups.items()):
            print(f"  {t}.{fld} [{err}]: {g['count']} rows")
            for x in sorted(g["ex"])[:3]:
                print(f"    e.g. {x!r}")
    else:
        print("✓ Phase E: ledger is EMPTY — ground truth clean.")

    # ── run record ──
    rr = {
        "env_id": env_id,
        "config_file": str(CONFIG_FILE.relative_to(ROOT)),
        "total_rows": sum(s["rows"] for s in stats.values()),
        "total_errors": sum(s["errors"] for s in stats.values()),
        "status": "COMPLETED",
        "tables": {t: {"rows": s["rows"], "errors": s["errors"]} for t, s in stats.items()},
    }
    RUN_RECORD_FILE.write_text(json.dumps(rr, indent=2))
    print(f"\n{'='*50}")
    print(f"Total rows: {rr['total_rows']}")
    print(f"Total errors: {rr['total_errors']}")
    print(f"Ledger:    {LEDGER_FILE.relative_to(ROOT)}")
    print(f"Run record:{RUN_RECORD_FILE.relative_to(ROOT)}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()

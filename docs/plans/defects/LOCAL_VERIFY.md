# Local verification checklist — what the cloud could not prove

Everything here is **implemented, unverified**. The user runs each entry locally against the real
environment; confirm with an *independent* check (direct query, log inspection, a regenerated
report), never the application's own success message.

## Restore the environment first
```bash
git checkout feat/defects-fixes && git pull --ff-only
uv sync --all-extras                       # Python 3.12; PyICU needs libicu-dev + pkg-config
docker compose up -d postgres libpostal    # metadata/destination Postgres on host port 5535 (compose.yaml)
# ClickHouse: any server you can reach; the clone connector tests read it directly.
( ulimit -v 16777216; uv run pytest -m integration -q )   # needs the services above
```
Use a copy of a real database for the live checks; the sources are read-only by design (ADR-013) but the
destination is created. Never run these against the production metadata database.

## The report's "before" values (the user must see these change)

| item | before value (from the report) | where in the report |
|---|---|---|
| D1 | `AMBIGUOUS` from `phone.py:209`, `date.py:575`, `money.py:183`; `NEEDS_REVIEW` only in `enums.py:23` and `dispatch.py:309`; errors readable only via `GET /runs/{id}/errors`, `GET /clone-jobs/{id}/errors` | Part 1 D1 |
| D2 | 61 `confidence=` sites, 28 literal `1.0`, 14 literal `0.0`, 3 literal `0.5` (plan F4: grep finds 31 `1.0`); 0 calibration code | Part 1 D2 |
| D3 | 0 lineage code | Part 1 D3 |
| D4 | column-level type only; `MissingKind` receives nothing at cell level | Part 1 D4 |
| D5 | report: all 24 types TEXT/String. Code (F1): NUMERIC, MONEY, BOOLEAN typed when `typed_destination_columns` (default true); DATE/DATETIME TEXT | Part 1 D5 |
| D6 | 875 test functions, 46 golden in 7 files, 0 corpus files | Part 1 D6 |
| D7 | `_STDNUM_REGISTRY` has 4 entries (US, GB, DE, FR); python-stdnum ships 100+ | Part 1 D7 |
| D8 | `supported_types = {IDENTIFIER, TAX_ID, CODE}` (`identifier.py:92-94`) | Part 1 D8 |
| D9 | `url.py` imports `urlsplit`, `idna`; no PSL | Part 1 D9 |
| D10 | extension in `structured` only; `comparison`/`search` = E.164 (F2) | Part 1 D10 |
| D11 | jellyfish Soundex/NYSIIS/Metaphone/MRC on `anyascii` output; no Double Metaphone, no BMPM | Part 1 D11 |
| D12 | `NEEDS_REVIEW` produced by nothing | Part 1 D12 |

## Per-item entries (added by the lead when it accepts an item)

```
### <id> — <title>
- Why cloud could not verify: <no database / no endpoint / ...>
- Command: <exact command>
- Independent check: <query / file / report to compare>
- Expected evidence: <numbers from the report, or "any value > X because ...">
- Result (filled in locally):
```

(no entries yet)

## Phase 0 additions
- **D5 overflow (modelled in the cloud):** on a real ClickHouse destination, insert NUMERIC values `1e999` and
  `10000000000000000000000000000000000000000` and a MONEY value of the same size; before D5 they reached the
  INSERT. After D5 they must land as NULL with an error row and the chunk must commit. Check with
  `SELECT count(*)` on the destination and the job's `/errors`.
- **D1 on real Postgres:** `ensure_schema()` creates `normalization_adjudication_queue` and
  `normalization_adjudication_verdicts`; the upsert's `ON CONFLICT ... DO UPDATE` with the `AS q` alias was
  exercised on SQLite only.

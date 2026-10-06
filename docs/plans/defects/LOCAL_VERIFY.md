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

### D7 — TAX_ID verdicts from stdnum discovery
- Why cloud could not verify: no real tax numbers for the 61 newly classified countries; the cloud tests use
  check-digit-generated and random numbers only.
- Command: clone a source with a TAX_ID column whose rows carry a country; then
  `SELECT validation_status, count(*) ... GROUP BY 1` per country on the destination.
- Independent check: a sample of 20 rows per country checked by hand against the national registry.
- Expected evidence: no number the registry accepts comes back INVALID. US/GB/DE/FR rows that were INVALID
  before may now be UNKNOWN with reason "valid under another <CC> identifier" (DE moves the most: 184 of 1260
  probes in the verifier's sample). That change is intended.
- Result (filled in locally):

## Phase 0 additions
- **D5 overflow (modelled in the cloud):** on a real ClickHouse destination, insert NUMERIC values `1e999` and
  `10000000000000000000000000000000000000000` and a MONEY value of the same size; before D5 they reached the
  INSERT. After D5 they must land as NULL with an error row and the chunk must commit. Check with
  `SELECT count(*)` on the destination and the job's `/errors`.
- **D5 gate vs the real columns (cloud proved the gate with fakes only):** (a) ClickHouse `Decimal(38,9)`: insert
  `99999999999999999999999999999.9999999994` (fits after rounding, gate accepts) and `...9999999995` (carries, gate
  rejects); confirm ClickHouse rounds rather than truncates or errors on the accepted one. (b) Postgres unconstrained
  `NUMERIC`: a 131072-integer-digit value inserts, `1e131072` does not reach the INSERT. (c) Fractional digits beyond
  the column scale (`0.00001` into MONEY) are not gated: confirm both engines round silently instead of aborting.
- **D3 lineage, live:** (a) real Postgres: `ensure_schema()` creates `normalization_lineage_events` and its index
  (tests ran on SQLite); `ON CONFLICT (run_id, event_type) DO NOTHING` behaves the same. (b) Marquez: `docker run`
  Marquez, set `NORM_OPENLINEAGE_URL` to its `/api/v1/lineage`, run a real clone with a MONEY and a PHONE column,
  confirm the column lineage (companions included) in its UI/API. (c) Real `get_columns` on Postgres and ClickHouse
  sources returns every column the destination gets (the facet is built from it plus the recorded plan).
- **D1 on real Postgres:** `ensure_schema()` creates `normalization_adjudication_queue` and
  `normalization_adjudication_verdicts`; the upsert's `ON CONFLICT ... DO UPDATE` with the `AS q` alias was
  exercised on SQLite only.
- **D1, NUL and lone surrogates in the queue (from the D1 verdict):** an AMBIGUOUS phone or money value containing
  `\x00` must reach `normalization_adjudication_queue.original` on real Postgres (which rejects NUL in text) without
  aborting the chunk; only SQLite was run.
- **D10 / D11 persistence (accepted-cloud, live check optional):** a real clone keeps `structured["rfc3966"]` and the
  new `phonetic` keys in the destination; the integration tests need the Postgres container.

### D6 — gold corpus (`normanalysis/gold.py`, `normcli gold`)
- Why cloud could not verify: BART is a Java tool that needs Postgres; the six Raha datasets are external
  downloads. The cloud proved the scorer, loader, injectors and κ/α on synthetic and published data only.
- Command: merge each Raha dataset's `dirty.csv`/`clean.csv` into one `dirty,clean` CSV per column (one
  semantic type each), then `uv run normcli gold score <file.csv> --semantic-type <TYPE>`; for BART, export
  its dirty/clean pair the same way. Seeded corpus: `normcli gold generate --seed 0 --n 30 --out g.jsonl &&
  normcli gold score g.jsonl`.
- Independent check: the per-case `wrong-confident` lines the command prints, spot-checked by hand.
- Expected evidence: cloud baseline on `generate --seed 0 --n 30` (180 cases): correct 142, correct-abstain
  21, wrong-confident 11 (10 are bare-host URLs: url.py assumes https), over-abstain 6 (day == month dates),
  wrong-status 0. Report Raha counts with and without the URL bare-host kind.
- Result (filled in locally):

### D2 — confidence calibration (`normanalysis/calibration.py`, `normcli calibrate`, ADR-019)
- Why cloud could not verify: no labelled data from the user's databases; the cloud used synthetic predictors
  and the seeded D6 corpus only.
- Command: `uv run normcli calibrate <labelled corpus.jsonl|csv> --cost-ratio <R> --out-json cal.json --out-md cal.md`
  (R = cost of a wrong value over the cost of an abstention: the user states it, Q16).
- Independent check: for the bins `cal.md` flags, sample 20 cases each and count the right answers by hand.
- Expected evidence: before, 61 `confidence=` sites (28 literal `1.0`) and no calibration code. Cloud seed-0 corpus:
  ECE 0.072, flagged bin [0.8, 0.9) = URL bare-host (stated ~0.82, observed 0.31), threshold 0.85 at R = 5.
  Live: which literal-1.0 sites sit in a flagged bin.
- Result (filled in locally):

### D4 — disguised missing data (`normanalysis/disguised_missing.py`)
- Why cloud could not verify: no real table; recall/precision measured on planted columns of authoritative
  valid values only.
- Command: for a typed column, `SELECT value, count(*) FROM t GROUP BY value` into a dict, then
  `detect_disguised_missing(counts, "<TYPE>", NormalizationContext(field_name=..., semantic_type=..., country=...))`.
- Independent check: the same `GROUP BY`, reading the values that are not of the type by eye.
- Expected evidence: before, nothing at cell level. After, the sentinels (`N/A`, `-`, `unknown`, ...) with their
  exact `GROUP BY` counts; `NA` in a country column is not reported; PHONE/CURRENCY columns without a region
  report nothing (escalation j).
- Result (filled in locally):

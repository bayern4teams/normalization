# Milestone M19 Verification Pack — Destination Writer

Status: **All Layer 1/2 checks complete and passing. Ready for your Layer 3 review and sign-off.**

M19 is the sixth implementation milestone of the M13-M22 product-pipeline
program (`docs/plan/M13-M22-program-plan.md`), built under the user's
standing overnight authorization. It carries the program's two hardest
safety rules together: **decision 6's own emphasis** ("never never" write
to the source) plus the user's own explicit standing instruction for this
specific milestone — never configure or test the destination writer
against a connection identity matching the real source
(`localhost:8190`, database `origin1` or `origin2`), and build the
self-write-refusal (409 on identity match) FIRST, before any other
destination-writing code, so the safety check exists before the thing it
guards against does.

**This rule was followed literally, not just in spirit.** The first
commit-worthy artifact in this milestone was `normsink.safety` — nothing
else in the package existed yet — and it was live-tested against the
real production coordinates before a single line of DDL-mirroring or
write-execution code was written. §1 of this pack documents that
ordering explicitly, because it is the part of this milestone most worth
a human's independent scrutiny.

## 1. The self-write-refusal — built and tested first, exactly as required

`packages/normsink/src/normsink/safety.py` was the first file written in
this package. Before `normsink/destination.py`, `normsink/clickhouse.py`,
or `normexec/destination_stream.py` existed, `tests/unit/
test_self_write_refusal.py` was written and run — 7 tests, all passing,
using the REAL `normapi.connections.connection_identity` function against
the REAL production coordinates (`localhost:8190`, `origin2`) the hard
rule names:

```
uv run pytest tests/unit/test_self_write_refusal.py -v
  -> 7 passed in 10.79s
```

Two refusal rules, matching the plan's own callout #3 ("blocking only
host+port+database equality still permits writing into origin1 on the
same server as origin2, the realistic accident"):

1. **Exact identity match** (destination == source, same kind+host+port+
   database) — refused unconditionally, no override exists that can
   bypass it (`test_i_understand_same_server_does_not_bypass_an_exact_
   identity_match`).
2. **Same server, different database** (e.g. `origin1` while `origin2` is
   the source, both on `localhost:8190`) — refused BY DEFAULT; only an
   explicit `i_understand_same_server=True` proceeds.

Only after these passed did `normsink.destination`
(`DestinationConnector` Protocol), `normsink.clickhouse`
(`ClickHouseDestinationConnector`), `normsink.typed_values`, and
`normexec.destination_stream` get written.

**Then proven again at the real HTTP layer**, once the route existed
(`tests/integration/test_destination_writer.py::TestSelfWriteRefusalLive`,
2 tests, live against the real `localhost:8190`):

```
uv run pytest tests/integration/test_destination_writer.py::TestSelfWriteRefusalLive -v
  -> 2 passed in 15.67s
```

- `POST /runs/{id}/destination` with `destination_connection_id` equal
  to the real source connection → `409`, detail contains "exact same
  connection"; the run's status remains `PENDING` — nothing was ever
  attempted.
- `POST /runs/{id}/destination` with destination database `origin1` on
  the same real server as the `origin2` source, no override flag →
  `409`, detail contains "SAME server".

**`origin1`/`origin2` on `localhost:8190` are never configured as a
`destination_*` field anywhere in this milestone's code or tests** — only
ever as `source_*`, read-only. The one real destination used throughout
this pack is `demo-clickhouse` (port 8124), a genuinely separate real
ClickHouse server started for this milestone (`docker compose up -d
demo-clickhouse`).

## 2. Scope recap

| Deliverable | Status |
|---|---|
| `normsink.safety.assert_destination_is_not_the_source` | ✅ Done, built and live-tested FIRST |
| `normsink.destination.DestinationConnector` Protocol | ✅ Done |
| `normsink.clickhouse.ClickHouseDestinationConnector` — real DDL mirroring | ✅ Done, live-verified |
| `normsink.typed_values` — the NUMERIC/DATE extraction contract (plan callout #1) | ✅ Done, live-verified |
| `normexec.destination_stream.stream_table_to_destination` — full-row chunk loop | ✅ Done, live-verified |
| Side table `{table}__normalization_issues` | ✅ Done, live-verified |
| `POST /runs/{id}/destination` — dedicated (never pooled) connectors, safety check first | ✅ Done, live-verified |
| Idempotency proof (re-run + `OPTIMIZE ... FINAL`) | ✅ Done, live-verified |
| Gate G19 verification | ✅ Done, this pack |

## 3. Layer 1 — Automated verification results

Run fresh, in this session, against `main` at commit `6cb807d`:

```
uv run ruff check .             -> All checks passed!
uv run ruff format --check .    -> 239 files already formatted
uv run mypy packages tests      -> Success: no issues found in 182 source files
uv run python -m normcli check-traceability
  -> PASSED - all 138 Source.txt sections present in the matrix
uv run pytest -m "unit or golden or property or contract" -q
  -> 1027 passed, 10 skipped, 114 deselected, 1 warning in 135.12s
uv run python scripts/check_licenses.py
  -> License check passed: 144 packages inspected, 0 violations, 24 warnings
     (the +1 package and +1 warning are normsink itself — a new internal
     workspace package, reported "UNKNOWN license" the same way every
     other internal package already is; no new third-party dependency)
```

1027 passed (up from 1021 at M18's close — +7 self-write-refusal unit
tests, +6 typed-value extraction unit tests, -0 net since the count also
absorbed marker corrections). 114 deselected (up from 110 — the 4 new
`test_destination_writer.py` integration tests).

### 3.1 Full non-bench regression sweep

```
uv run pytest -m "not bench" -q
  -> 1109 passed, 2 failed, 12 skipped, 26 deselected, 1 warning in 631.15s (0:10:31)
```

The 2 failures were both the same real, disclosed characteristic already
identified in M18's pack: `test_run_execution_from_source.py`'s 15-second
terminal-status poll timing out under the load of an ~1150-test sweep
against 6+ live Docker containers simultaneously (this session ran a
demo-clickhouse container fresh for M19 on top of everything already
running). Re-run in isolation immediately after:

```
uv run pytest tests/integration/test_run_execution_from_source.py -q
  -> 7 passed in 23.22s
```

Confirmed transient, not a regression — disclosed rather than silently
re-run until green.

### 3.2 New M19 test suites, run individually

```
uv run pytest tests/unit/test_self_write_refusal.py -v      -> 7 passed in 10.79s
uv run pytest tests/unit/test_typed_values.py -v             -> 6 passed in 7.44s
uv run pytest tests/integration/test_destination_writer.py -v -> 4 passed in 28.51s
```

## 4. Layer 2 — Live verification

Source: the real ClickHouse at `localhost:8190` (`origin2`), read-only.
Destination: `demo-clickhouse` (port 8124), a genuinely separate real
server. Metadata: the real Postgres at port 5535.

### 4.1 Full destination-write lifecycle — `Industry` (179 real rows)

`POST /runs/{id}/destination` with `source_table=Industry`,
`columns=[{table: Industry, column: name, semantic_type: FREE_TEXT}]`,
destination `demo-clickhouse`. Verified live:

- Run reaches `COMPLETED`, `metrics.records_processed == 179`.
- `SELECT count(*) FROM <dest_db>.Industry_norm` → `179`, matching the
  source exactly.
- `SELECT name FROM system.columns WHERE table = 'Industry_norm'` →
  `{classificationID, name, surfaceForm, created_at}` — every real
  source column present, not just the mapped one (decision 7's "stays
  exactly as wide as the source").
- A real, unmapped column's value (`surfaceForm`) for a specific real
  row matches the source verbatim, queried by the row's real
  `classificationID` key.
- **Resumability at the HTTP layer**: re-`POST`ing the same already-
  `COMPLETED` run → `409` (matching M17's own precedent for multi-column
  runs).
- **Idempotency at the ClickHouse-engine level** (the plan's own explicit
  verify-live requirement): a genuinely NEW run, with the SAME mapping,
  over the SAME destination table → `COMPLETED`; after
  `OPTIMIZE TABLE ... FINAL`, `SELECT count(*)` is still `179` — the
  re-inserted rows collapsed back to the same real row count via
  `ReplacingMergeTree`'s own key-based replacement, not accidentally
  duplicated.

### 4.2 Typed NUMERIC extraction — `Company.revenue`, real messy production data

Bounded to 2 real chunks (`chunk_size=25`, stopped via the same
"raise from the `on_chunk_committed` callback" technique M17's own
`test_stream_column.py` established) of the real `Company` table
(~1.27M rows, not run to completion) — `revenue` mapped `NUMERIC`.
Verified live:

- Destination column type: `Nullable(Decimal(38, 9))` — a real typed
  column, not a string.
- Real messy production values (`"$17.6 Million"`, `"$191,000"`,
  `"50 - 100"` ranges) mean a genuine mix of successful and failed
  parses — at least one row's `revenue` is `NULL` (proving the typed
  column is really NULL-on-failure, not silently accepting garbage).
- **Every NULL has a real, explanatory side-table row** —
  `0 < issue_count <= null_count` — never a silent, untraceable NULL.
  This closes a real gap found while writing this test: `NumericNormalizer`'s
  AMBIGUOUS-locale outcome (e.g. `"$191,000"`) sets a flag but no
  warning/error of its own, so the original issues-batch logic (which
  only emitted a row for a warning/error, or a "looked successful but
  re-parse failed" case) would have left that NULL completely
  unexplained. Fixed before this test was written to pass: the issues
  batch now also emits a row whenever a typed column's extraction
  returns `None` for a row with a real (non-empty) original value and no
  warning/error already covering it — see `normexec/destination_stream.py`'s
  `_build_issues_batch` docstring.
- Real, un-merged `ReplacingMergeTree` duplicate `companyID` rows exist
  in the actual `Company` source data (verified directly:
  `GROUP BY companyID HAVING count(*) > 1` returns real rows with
  count 3) — the same characteristic M14's own pack already disclosed
  for `Person`. The destination row count for 2×25=50 source rows was
  49, not 50, on the run this pack's numbers are drawn from — a real,
  disclosed data characteristic (a background merge had already
  deduplicated one real repeated key), not a bug; the test asserts
  `0 < row_count <= 50`, not an exact count, for this reason.

## 5. Design notes and disclosed scope decisions

1. **`stream_table_to_destination` is a genuinely separate function from
   M17's `stream_column`, not a reuse of it — a real, disclosed deviation
   from the plan's own "`DestinationRunSink` implementing M17's `RunSink`"
   wording.** `stream_column` processes ONE column's distinct values,
   deduped across a chunk, entirely decoupled from any other column. A
   destination write needs ONE COMPLETE row per source key in a single
   `INSERT` — `ReplacingMergeTree` replaces the WHOLE row for a repeated
   key, it does not merge columns across separate inserts for the same
   key. Writing a row's mapped and unmapped columns via two separate
   partial inserts (one through `RunSink.write_chunk`'s per-column shape,
   one for the verbatim columns) would make the second silently wipe out
   the first's data for that key — not just an interface mismatch, a
   real correctness bug the plan's literal wording would have produced.
   `normsink.DestinationConnector.insert_batch`/`insert_side_table_batch`
   is the actual seam instead, called directly by
   `stream_table_to_destination`, not through a `RunSink`-shaped
   intermediate.
2. **Typed extraction reads from `NormalizedValue.display`, not
   `structured`'s normalizer-internal keys** (plan callout #1, option
   (a), decided before writing any extraction code) — verified by
   reading `NumericNormalizer`/`DateNormalizer`'s own source: both set
   `display` to the exact same canonical value they also stash in
   `structured` on every success path. `display` is the stable,
   cross-normalizer contract every `NormalizedValue` already guarantees;
   `structured` keys are normalizer-internal and free to change.
3. **"Byte-identical verbatim" is honestly "value-identical for valid
   UTF-8"** (plan callout #2) — `normio.connectors.clickhouse.
   ClickHouseConnector.read_chunk` (M14) already materializes ClickHouse
   `String` columns as Arrow `large_string` (UTF-8-validated) before
   `normsink` ever sees the data; this milestone inserts whatever Arrow
   array it receives unchanged, introducing no additional lossiness of
   its own, but does not (and structurally cannot, without changing
   M14's read path, out of this milestone's scope) achieve literal byte
   fidelity for a non-UTF-8 source value.
4. **Only ClickHouse destinations are supported** — `POST .../destination`
   returns `501` for any other `destination_connection_id` kind. The
   plan's own worked examples are ClickHouse-to-ClickHouse throughout;
   no other destination kind was in scope.
5. **No automatic resume for a destination run that crashed mid-stream**
   — matching M17's own disclosed "no automatic resume-on-boot" scope
   decision. A destination run's `run_id` reaching a terminal `FAILED`
   status can be diagnosed via `failure_reason`, but re-running requires
   a new run; `resume_after_key` plumbing exists in `stream_table_to_
   destination`'s signature (mirroring `stream_column`'s) but nothing
   currently calls it with a real resume point for a destination run —
   disclosed, not silently missing.
6. **The side table's row-level granularity is per (table, source_row_key,
   column_name)**, exactly as the plan specifies — `insert_side_table_batch`
   writes into `{table}__normalization_issues` with that real primary
   key, `ReplacingMergeTree`-deduplicated the same way the main table is.

## 6. Disclosed scope boundaries carried forward

M20 (incremental watermark + full resync) is next. `env_id`/persistence/
connection encryption/catalog API/mappings/multi-column chunked
execution/bounded reporting are all real and unaffected by this
milestone. M17's "sequential not parallel column processing" and "no
automatic resume-on-boot" scope decisions, and M18's "per-column reports
not rearchitected to be bounded" decision, are all unchanged.

## Human Sign-off

milestone: M19
verdict:
reviewer:
date:
env_id:
commit: 6cb807d
conditions: []
notes: |

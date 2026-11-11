# Round 3 — final report (D16-D32)

Built 2026-11-08 → 2026-11-10 by four build sessions (prompts 1-4 in this folder), three benchmark
sessions and an orchestrator session. Every item is merged into `main`; the last merge is
`56578b8`. Every number is measured; "not checked" marks what was not checked.

The plan of record is [`docs/improvement-report.md`](../../improvement-report.md), Part 1, round 3.
The owner's decisions are quoted in the ADRs and commit messages of each item.

---

## 1. What was built

Each prompt's branches were merged together, checked, benchmarked, then merged into `main`.

| prompt | merged as | items |
|---|---|---|
| 1, API | `e65ebbe` | D25, D16, D17, D18, D19 |
| 2, normalizers | `d55160a` | D27, D28, D29, D30, D20, D21 |
| 3, clone | `b894461` | D26, D22, D23, D31, D32 |
| follow-ups | `1a7774e`, `3a1f4d0` | starlette declared; AGENTS.md §4/§5; UTF-8 path test; D33 planned |
| 4, tests and records | `56578b8` | D24 |

### API (prompt 1)

- **D25:** start-up reads only the review-queue rows that need migrating. 1.02 million queue rows:
  `/health` 200 after 68 s, peak 197 MB under `MemoryMax=1G`. The old `main` was killed out of
  memory after 17 s.
- **D16:** a raw value appears only in the caller's own answer. A planted value was found 0 times in
  `/values`, `/errors` and the log; `/handoff` and `/collisions` mask it too.
- **D17:** a `Host` header with userinfo (`localhost:80@evil.com`) gets 400; it got 200.
- **D18:** a bad `NORM_ALLOWED_NETWORKS` entry stops start-up (exit 1) and the message names it.
- **D19:** a PATCH plan with an unknown key is refused.

### Normalizers (prompt 2, ADR-010)

- **D27:** a withdrawn alpha-2 code with several successors (`SU`, `CS`, `AN`) is AMBIGUOUS with
  CLDR's successors as readings; `DD` resolves to `DE`.
- **D28:** a name ISO 3166 gives only with a qualifier (`Congo`, `Korea`, `Virgin Islands`) is
  AMBIGUOUS; a leading "The" is stripped only before an exact name; CLDR `alt="short"` names are
  generated from CLDR's XML.
- **D29:** reserved currency codes (`XXX`, `XTS`) are INVALID, and the error row says how to fix it.
- **D30:** an amount with a shared symbol (`$`) and no settling country is AMBIGUOUS.
- **D20:** case does not mean "code": `mon`, `MON` and `Mon` are AMBIGUOUS (Mongolian or Mon). By the
  same rule 13 three-letter codes are AMBIGUOUS, `che` among them (Chechen, or the language Che).
- **D21:** a phone in international form names the row's country for LANGUAGE.

### Clone (prompt 3)

- **D26:** the ClickHouse sort key is parsed by its syntax; the 20 sort-key forms the owner copied
  from ClickHouse 26.4.2.10 are parser tests. Live on 26.8.2.7: 12 tables, destination sort keys
  match the source.
- **D22:** one server under two host names is refused (real DNS: `localhost` and `127.0.0.1`).
- **D23:** a clone can name its tables; live, 1 of 12 tables was cloned.
- **D31:** autodetect for LANGUAGE and NUMERIC, and the date rule (owner: "(b) native date + text
  dates"). A native date column typed DATE by autodetect is stored as TEXT plus `__from`/`__to`
  (ADR-020).
- **D32:** a configured key keeps its value and its type, and gets a `<col>_normalized` companion.
  D26's refusal of a retyped key was removed, because after D32 it would refuse keys that copy safely.

### Tests and records (prompt 4, D24)

- **`test_a_time_is_no_day_or_month`** failed every November: the partial-date parser filled a
  missing month from the clock, and in November the "11" then counted as a stated month. Fixed in
  `normalizers/date.py` (ADR-008 amendment); a pinned-clock test failed first. With the clock pinned
  to each of the 12 months the date and golden tests (455) pass; on 600 sampled real dates no
  result changed.
- **`test_groups_cost_is_linear_in_pairs`** failed under CPU load (1 of 60 runs with 48 CPU
  burners over the 0.5 s limit). It now compares the best of 3 at n and 4n with GC off (ratio under
  8; this code 4.2, a quadratic stand-in 12.1). Two `TEST-CHANGE:` commits.
- A URL whose port is not a number (`:.AA`, found by a property test) crashed; it is now INVALID.
- [`docs/plans/round2/FINAL_REPORT.md`](../round2/FINAL_REPORT.md) §9 holds the live re-checks of
  round 2's "record" results; the ZoomInfo 100k count is corrected to 599,853 rows.
- [`docs/PONYTAIL_DEBT.md`](../../PONYTAIL_DEBT.md) is regenerated from the code.

### Follow-ups merged during the round

- `normapi` declares `starlette` (rule M4), so deptry passes. The ADR-014 guard test counts a
  package `main`'s `uv.lock` already installs as present (owner: "TEST-CHANGE to match").
- AGENTS.md §4/§5: the benchmark machine path, and memory caps with `systemd-run` instead of
  `ulimit -v`.
- A test for the non-UTF-8 path (`tests/unit/test_clone_undecodable_bytes.py`).
- 242 saved connections that no key decrypts were deleted from the laptop's app database (owner yes
  for the exact list); the 16 that decrypt remain.

## 2. How it was verified

- Each build session ran the AGENTS.md §5 checks on each branch before pushing.
- Before every merge into `main`, the orchestrator ran the §5 test set again on `main` plus the
  branches and compared the failures with `main` (rule I4). No merge added a failure.
- On `56578b8`: unit 3380, golden 234, defects 29 passed, 0 failed; ruff, format, mypy, the four
  guards, deptry, gitleaks, actionlint and zizmor pass. Before round 3, one test failed (D24) and
  deptry reported 3 issues.
- Every heavy step on the laptop ran under one shared lock with `MemoryMax=4G` and at least 6 GB
  free. There was no out-of-memory event after 2026-11-09 08:04.

## 3. Benchmark (`synthetic_traps_v1`)

One run per column, so there is no noise estimate. "Before" is `ccc2fdf`.

| base run | before | after p1 | after p2 | after p3 |
|---|---|---|---|---|
| wrong values | 9 | 9 | 3 | 3 |
| guesses | 2 | 2 | 0 | 0 |
| precision | 0.99856 | 0.99856 | 1.0 | 1.0 |
| recall | 0.99712 | 0.99712 | 0.99784 | 0.99784 |
| API / queue / plan failures | 4 / 4 / 12 | 4 / 4 / 12 | 0 / 1 / 12 | 0 / 1 / 11 |
| ClickHouse variant | HTTP 500 | HTTP 500 | HTTP 500 | completes, 1414 rows |
| rows per second | 259 | 286 | 289 | 281 |
| peak memory MiB | 824 | 940 | 947 | 984 |

No benchmark ran after prompt 4: its changes are one date fix, tests and records.

## 4. Open items

| item | cause | next |
|---|---|---|
| `che` scored as a failure | D20 is correct; the answer key expects `ce` | the next answer-key batch (owner, 2026-11-10: "Leave as known failure") |
| 17 Postgres and 18 ClickHouse `id` columns score "wrong type" | the keys predate D32 (unconfigured key columns keep their source type) | the same batch (owner: "One key batch later") |
| `'caf\xe9'` copied with no error row on ClickHouse | autodetect leaves small tables' text columns untyped | D33, planned for round 4 |
| `Bonaire, Saint Eustatius and Saba`, `Palestinian Territory` unresolved | not checked | round 4 candidate |
| `XYZ` error class `unclassified` (key: `not_in_standard`) | not checked | round 4 candidate |
| phone `020 7946 0958` INVALID in the locale run (key: ambiguous) | not checked; the same before round 3 | round 4 candidate |
| peak memory 824 → 984 MiB over the round | not checked whether real or noise | measure with repeated runs |

## 5. Checks not run (with reason)

- **Resume after a kill:** the dataset is too small to reach the kill points.
- **The outside-caller 403:** it needs a stub network.
- **The UI walk:** the in-app browser refused the LAN address.
- **The integration suite:** it needs the laptop compose stack.

# Lessons

What was tried and did not work, so the next agent does not try it again
(J14). One entry per approach that failed, was reverted, or was rejected by a
review or a measurement: date, what was tried, the measured result, why it
was dropped, what replaced it, and a link to the report, commit or ADR (link,
do not copy, J2). Add the entry in the same commit as the change that drops
the approach.

The date is the commit that dropped the approach, or the date range of the
report section when the source gives only that.

## Execution and storage

<!-- verified: 9f27526 -->

| Date | Tried | Measured result | Why dropped | Replaced by | Source |
|---|---|---|---|---|---|
| 2026-10-14 | Size ClickHouse inserts at the server's vertical-merge row threshold (131,072 rows). | OnTime failed after 74 s. One 131,072-row insert used 611 MiB. | Merge cost depended on the merge algorithm, not on insert size. | Tables created with `vertical_merge_algorithm_min_rows_to_activate = 0` and 2,000-row inserts. Peak merge memory 16.16 MiB in the OnTime run. | commits `afb36f4`, `130dc96`; [REPORT §10 item 1](benchmarks/REPORT.md) |
| 2026-10-14 | Resume a ClickHouse clone with a dedup token per block. | A killed Postgres clone without a primary key had 931,453 rows but 525,453 distinct. A killed ClickHouse clone had 1,598,468 rows and 1,580,515 distinct. | The problem was read order, not replays. A scan joined the killed job's scan, and the same `LIMIT/OFFSET` returned different rows. `max_threads = 1` is not allowed for a read-only profile. A total `ORDER BY` ran the server out of memory. | Postgres reads in primary-key order, else `ctid`. An unfinished ClickHouse table restarts from empty. | commits `b4de4bb`, `a0fd0fe`; [REPORT §10 item 2](benchmarks/REPORT.md) |
| 2026-09-16 | Keep the persistent DuckDB cache tier in a clone job. | On 1.27 million real rows, columns were 80 to 97 percent unique. The cache reached 3.87 GB and saved about 3 percent of calls. | One entry per row costs more than it saves at that cardinality. | No cache in the clone planner. A bounded in-memory memo covers low-cardinality columns. | commit `108fd59`; `packages/normapi/src/normapi/clone_executor.py::_run_phase2` (comment) |
| 2026-10-13 | Round or truncate excess fraction digits when a value does not fit a typed column. | Postgres rounded and ClickHouse truncated silently. | Silent data change. | The cast gate refuses the value: NULL plus an error row, on both engines. | [REPORT §9](benchmarks/REPORT.md); [ADR-020](adr/ADR-020-typed-destination.md) |
| 2026-10-05 | A typed `DATE` column plus the EDTF original in a companion column. | Not measured. | The typed column would stay NULL for every partial value. | `<col>__from` and `<col>__to` date bounds: every clean value, partial or not, gets a range. | [ADR-020](adr/ADR-020-typed-destination.md) |
| 2026-10-14 | Benchmark OnTime on ClickHouse 24.9. | `MemoryTracking` read 43.6 GiB at 1.0 GiB resident. | The server's own memory tracker was wrong in the container. | Benchmark override on ClickHouse 25.12 with cgroup memory settings. `compose.yaml` keeps 24.9. After a start the tracker read 573 MiB. | [REPORT §11.1](benchmarks/REPORT.md) |
| 2026-10-13 | A daily scheduled `drift.yml`. | Red every day since at least 2026-10-09. | Three of its parts were never built: the `--golden-report` option, `normcli drift-diff` and `tests/golden/expectations/`. | Manual trigger only. A test checks that every command a self-triggered workflow names exists. | commit `14e852b`; [REPORT §10 item 5](benchmarks/REPORT.md) |
| 2026-11-07 | A fallback in `clone_executor.py::_normalize_table` that built `source_identity` from the connector when a job lacked it, so an integration test that calls `_normalize_table` directly passed. | For a Postgres source it returned `postgresql+psycopg://None@None:None/None` for every server (the connector's engine is built from a libpq string, so its URL is empty). Production never reached it: `_run_phase2` already sets the key from the stored connection. | Production code that only a test fixture used, and wrong whenever it ran. | The fallback is deleted; the fixture in `tests/integration/test_followups_live.py` carries `source_identity`, as production always does. | commits `754e8a7`, `ed1c3e7`; [round 2 FINAL_REPORT §8](plans/round2/FINAL_REPORT.md) |
| 2026-08-19 | A custom `conftest.py` path hack so `mutmut` could track mutants in the `uv` workspace. | `mutmut` reported trampoline hits that matched no mutant key. | `mutmut` derives keys from file paths and strips only a leading `src.`. The workspace layout can never match. | A flat `src/` bridge in the image and in `gate.yml`, with `source_paths = ["src"]`. | [M8 pack §4](verification/M8-verification-pack.md) |

## Reading values

<!-- verified: 9f27526 -->

| Date | Tried | Measured result | Why dropped | Replaced by | Source |
|---|---|---|---|---|---|
| 2026-10-13 | Detect column types automatically and apply them by default. | French company numbers (SIREN) became phone numbers in 499,985 of 500,000 rows. US state `al` became `Albania`. Marital status `S` and `M` became the currencies `SOS` and `LSL`. | A type that accepts a value is not evidence that the column has that type. | The detector only suggests. A column is written only when the user gives its type, or the job sets `autodetect_field_types`. | commit `792a9cc`; [REPORT headline and §9](benchmarks/REPORT.md) |
| 2026-10-14 | Let year-only evidence make a column `DATE`. | Norway's 4-digit postal codes were read as years. The clone spent 3 hours on them (10,614 s, against 147.5 s after the fix). | A value read only as a year is no evidence that a column holds dates. | A named column is still found by its name. A year-only reading no longer counts. | [REPORT §11.10](benchmarks/REPORT.md) |
| 2026-10-14 to 2026-10-17 | Hand-written tables: month-first countries as `{US}`, and currency symbols `¥` and `£`. | `10/7/2026` under `ee-GH` read as 10 July, though that locale writes the month first. `1/13/01` under day-first read as 2013-01-01. | A table grows one example at a time and is wrong for the next locale. | CLDR per locale. A numeric value must read in the stated order. A symbol shared by several currencies is `AMBIGUOUS`, resolved by the country's tender. | [REPORT §11.2](benchmarks/REPORT.md) |
| 2026-10-14 to 2026-10-17 | Assume `https` for a bare host such as `example.com`. | 34,853 Brreg websites were answered as `https` with confidence 0.8. | Nothing in the value states the scheme. | `AMBIGUOUS` with both schemes listed. Host and registrable domain are still reported. | [REPORT §11.2](benchmarks/REPORT.md) |
| 2026-10-13 | Trust a lenient parser to drop what it cannot place. | `33429381O23` became a confident phone number. `1O/15/2024` became 2024-01-15. `1234.56O USD` became USD. | Parsers drop letters silently. | `AMBIGUOUS` with the original kept, for phone, date and money. A property test covers every digit-bearing type. | [REPORT §10 item 4](benchmarks/REPORT.md) |
| 2026-10-05 | Key a verdict by `(context_hash, profile_version, env_id)`, as the improvement report proposed. | Not measured. | `context_hash` has no value in it, so one decision would answer a whole column. `env_id` hashes the normalizer source, so every edit would orphan every verdict. | A key of the value hash, context hash and profile version. `env_id` is stored, never matched. | [ADR-018](adr/ADR-018-abstention-and-adjudication.md) |
| 2026-10-14 | Key a verdict's source by the saved connection id. | Deleting and re-adding a connection orphaned the verdict. 2,696 legacy queue rows re-keyed to 2,488. | The id changes whenever a connection is saved again. | `engine://host:port/database[/schema]`, plus a startup migration. | [ADR-018](adr/ADR-018-abstention-and-adjudication.md); [REPORT §11.3](benchmarks/REPORT.md) |

## Measurement

<!-- verified: 9f27526 -->

| Date | Tried | Measured result | Why dropped | Replaced by | Source |
|---|---|---|---|---|---|
| 2026-10 | `ptype` for disguised-missing detection. | Failed its feasibility gate: `greenery` 4 and `pandas` 3 are incompatible, and it pulls 311 MB. | Dependency cost and breakage. | A native detector. | [FINAL_REPORT](archive/plans/defects/FINAL_REPORT.md) (archived 2026-10-18) |
| 2026-10 | A small-set rule for disguised-missing candidates: mean valid count. | Broke recall on categorical columns; 21 tests failed. | The rule treated frequent real categories as noise. | Only definitive `INVALID` verdicts count. A recurring failing value is a candidate when it is no more numerous than the spellings in the missing-value table (17), else only table-named ones. | [FINAL_REPORT](archive/plans/defects/FINAL_REPORT.md) |
| 2026-10-14 to 2026-10-17 | Report an "expected wrong" count from accuracy measured on erroneous cells. | Reported 200,000 expected wrong on an ordinary column. | Accuracy on erroneous cells does not apply to an ordinary column. | Removed from the report. | [REPORT §11.8a](benchmarks/REPORT.md) |
| 2026-10-06 | Temperature or isotonic scaling of stated confidences. | Not measured. | It would rewrite the output of every normalizer before anyone has read the reliability diagram. | Measure first. Risk-controlled threshold per type. | [ADR-019](adr/ADR-019-confidence-calibration.md) |
| 2026-10-06 | Conformal prediction sets (MAPIE). | Not measured. | The normalizers emit one answer or refuse, so a set reduces to emit or abstain, which the threshold already guarantees. It would add a dependency. | Risk-controlled threshold. | [ADR-019](adr/ADR-019-confidence-calibration.md) |
| 2026-10-06 | A default cost ratio for calibration. | Not measured. | The right value depends on what a wrong answer costs the user. | `--cost-ratio` is required and has no default. | [ADR-019](adr/ADR-019-confidence-calibration.md) |

## Libraries

<!-- verified: 9f27526 -->

| Date | Tried | Measured result | Why dropped | Replaced by | Source |
|---|---|---|---|---|---|
| 2026-08-17 | `Unidecode`, `text-unidecode` | Not measured. | GPL-2.0-or-later and a GPL-adjacent lineage. | `anyascii` (ISC). | [ADR-015](adr/ADR-015-library-selection.md); [dependency inventory](dependency-inventory.md) |
| 2026-08-17 | `wordfreq` | Not measured. | Sunset by its author in September 2024. The data is no longer trustworthy. | Nothing. | [ADR-015](adr/ADR-015-library-selection.md) |
| 2026-08-17 | `abydos` for phonetic codes | Not measured. | GPL-3 through its Beider-Morse port. | `jellyfish` for the non-GPL subset. `_bmpm.py`, a port of Apache Commons Codec (Apache-2.0). | [ADR-003](adr/ADR-003-name-normalization.md); [ADR-015](adr/ADR-015-library-selection.md) |
| Date not recorded | `deepparse` for address parsing | Not measured. | A PyTorch model of about 800 MB, with per-address inference, for a job that `libpostal` already does. Memory is a standing constraint. | The `libpostal` service. Reconsider only if `libpostal` is measurably wrong on real data and a run can afford a model. | [dependency inventory](dependency-inventory.md) |
| 2026-10-21 | Dropping `cleanco` from declared dependencies as "never imported" (ponytail audit finding #2) | Measured: `collect_package_versions()` records `MISSING` for it, so `env_id` changes on every machine. The fingerprint input silently stopped being fingerprinted. Caught by the user before merge. | `FINGERPRINTED_PACKAGES` (`normexec.env_fingerprint`) uses packages without importing them (ADR-014). "No import found" is not "unused" for a name on that list. | `cleanco` restored as a declared dependency with a `ponytail:` keep-note (same treatment as `python-dateutil`/`rapidfuzz`), plus K4 test `test_every_fingerprinted_package_is_a_declared_dependency` (fails first on the broken state, L3). | [ADR-014](adr/ADR-014-normalization-versioning.md); commit on `chore/ponytail`; [debt ledger](PONYTAIL_DEBT.md) |

## Tooling and guards

<!-- verified: 12c1dd5 -->

| Date | Tried | Measured result | Why dropped | Replaced by | Source |
|---|---|---|---|---|---|
| 2026-11-07 | `( ulimit -v 16777216; ... )` as the memory cap for test runs while the full compose stack and Langfuse also ran. | The laptop froze; the previous boot's log ends at 06:47:35 with no OOM-kill line. Cause not proven. | `ulimit -v` caps a process's address space, not its resident memory, and nothing capped the containers; Chromium also crashes under it. | Every heavy command under `systemd-run --user --scope -p MemoryMax=<n> -p MemorySwapMax=0`, one at a time, a free-memory check before each, only the containers a step needs. | [round 2 FINAL_REPORT §8](plans/round2/FINAL_REPORT.md) |
| 2026-10-24 | A C5 guard that matched `noqa` with a regex written as `"noqa\b"` in a normal (not raw) Python string. | `\b` became a backspace character, so the pattern never matched. The first "grandfathered lines pass" proof was meaningless. | The guard looked green while checking nothing. | The marker is built from parts in a raw regex. Each guard is re-proven failing on a bad change and passing without it (commit `65150e8`, then the re-proofs of prompt 4). | `scripts/check_c5_exceptions.py::_MARKERS` |
| 2026-10-24 | Copy `edtf`, `idna`, `publicsuffixlist`, `cryptography` and `openpyxl` into the root `pyproject.toml` so `deptry .` passes. | The copy made the ADR-014 test count them as new fingerprint-free dependencies. | `deptry` reads one `pyproject.toml` at a time. Scanning every member from the root judges member imports against the root list, and the copy hid the real gaps (`blake3`, `pydantic`, `PyICU`, and others undeclared in their members). | `scripts/run_deptry.sh` runs `deptry` in each member and then the root, and the imports are declared in the member that imports them. | commit `8206a70` |
| 2026-10-24 | `deptry --config ../../pyproject.toml` from a member folder, to share one config. | It read the root dependency list, so every member reported the root's unused packages. | The config flag also selects where dependencies are read from. | A small `[tool.deptry]` section in each member that needs one. | `scripts/run_deptry.sh` |
| 2026-10-24 | An L4 check that scans the whole file of every edited test file. | It failed this branch's own CI: adding a C5 comment to a file with an old assertion-less benchmark test counted as touching that test. | A bystander edit is not a change to the test. | Compare each test function as an AST against the base version. | commit `9273692` |
| 2026-10-25 | Add `/src/` and `/mutants/` to `.gitignore` so a by-hand `mutmut` run leaves no stray folders (M2). | A fresh clone installed every workspace member with no code: `ModuleNotFoundError: No module named 'normalizers'`, 101 collection errors. `ci-fast` failed on the first push. | hatchling applies the repo `.gitignore` when it builds a member, so `/src/` hid `packages/*/src`. A clone that already had the old editable install, as the author's did, hid the break. | Nothing is ignored; the doc says to delete the folders. A fresh-clone run is part of the red-team procedure. | commit `cd49805`, fix in the next commit |

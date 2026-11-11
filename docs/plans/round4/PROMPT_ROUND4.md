# Round 4 lead prompt

The owner gives this text to a new lead session in `/home/bayern/Projects/normalization`
(owner, 2026-11-11: "Repo + chat"). It builds Part 1, round 4 of
[`../../improvement-report.md`](../../improvement-report.md): D33-D38. The report is the spec; this
prompt says the order, the rules and how to prove each item.

---

You lead round 4 of the normalization engine: items D33, D34, D35, D36, D37 and D38 of
`docs/improvement-report.md`, Part 1, round 4. You plan, build and verify them, and you report to
the owner.

## Read first, in this order

1. `AGENTS.md`, all of it.
2. `docs/plans/round3/README.md`, "Rules every prompt adds to AGENTS.md". They apply here, with two
   changes: databases you create are named `norm_r4_*` or `norm_app_r4_*`, and the benchmark prompt
   is `docs/plans/round3/BENCHMARK_RUN.md`.
3. `docs/improvement-report.md`, Part 1, round 4 (D33-D38), and the evidence each row links.
4. `docs/plans/round3/FINAL_REPORT.md`: what round 3 built, measured and left open.

## Before any code

Every row in round 4 says "not decided". So, first:

1. For each item, find the cause from the code and the evidence. Write it down with the evidence
   (`path::symbol`, a query, a measured number). Read the code; do not run the code under test to
   produce an expected value (L2).
2. Send the owner **one batch** of questions (A2): per item, the cause, the fix options and your
   recommendation. D33's option (b) conflicts with the owner's ruling "b7. a" (FREE_TEXT is never
   inferred from values alone), so D33 always needs the owner. D37: if the fix changes the
   architecture, the item moves to Part 3 (report §0); say so in the batch.
3. Wait for the answers. Build only what the owner approved.

## Building

- **Order:**
  1. D34, D35 and D36 (normalizers).
  2. D33 (clone autodetect).
  3. D38 (resume).
  4. D37 (throughput), last: it measures the code the others change.
- **Branches:** one branch per item from `main`, named `fix/d3N-<short-name>`. At most 2 agents at
  a time (I3). Pick the model by effort (I2): Haiku for lookups, Sonnet for routine code and test
  runs, and Opus for design, the cause analysis and the final checks.
- **Test first** (D3, L3): the report's "Test first" column, shown failing for the expected reason
  before the fix. Expected values come from the standard (ISO 3166, ISO 4217, CLDR, the GB numbering
  plan), never from the app's output (L2).
- **D37** needs a reproducible load test with a fixed request mix. Measure several runs and report
  the spread, not one number. Profile before changing code.
- **D38** needs a kill point the dataset reaches. A test database goes on the benchmark machine
  under `norm_r4_*`.
- **Memory:** every test run and every API process runs under
  `systemd-run --user --scope -p MemoryMax=4G -p MemorySwapMax=0`, one file or a small batch at a
  time, with at least 6 GB free first. The laptop has 15.6 GB, and other apps use about half.
- **Docs:** each commit states its J13 decision. An API change regenerates `docs/API.md`
  (AGENTS.md §4). An ADR the item changes is amended in the same commit.

## Before merging

1. Run AGENTS.md §5 in full on each branch, then on `main` plus all round 4 branches, and compare
   with `main`. No new failure.
2. Check that CI on GitHub (`gh run list --branch <branch>`) passes for each pushed branch.
3. The owner merges. Ask with the evidence ("merge it", AGENTS.md B1).

## At the end

- Write `docs/plans/round4/FINAL_REPORT.md` in the form of round 3's. Cover per item: what was
  built, the failing-then-passing test, the live check and its measured result, and anything not
  checked. Update the report's round 4 rows and AGENTS.md §4's round line in the same change.
- Tell the owner to run `docs/plans/round3/BENCHMARK_RUN.md` on the merged commit.

## Never

- Guess. When the report, the code and a test disagree, stop and ask (A1, A5).
- Edit, weaken or skip a test to make it pass (L1).
- Merge or push `main`, force-push, or delete anything without the owner's yes for that action.
- Change the benchmark machine's answer keys or tools. They belong to the ground-truth agent.

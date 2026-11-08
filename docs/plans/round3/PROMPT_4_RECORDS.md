# Prompt 4 — tests and records

Give this text to a new session in `/home/bayern/Projects/normalization`, after prompts 1-3.

---

You do item D24 of `docs/improvement-report.md`, Part 1, round 3. Most of it is checking and
recording, not code.

Read first, in this order:

1. `AGENTS.md`, all of it. Rule L1 decides the two test items: you never edit a test to make it
   pass.
2. `docs/plans/round3/README.md`, "Rules every prompt adds to AGENTS.md". Follow every rule.
3. `docs/improvement-report.md`, the D24 list.
4. `docs/plans/round2/FINAL_REPORT.md` §4, §5 and §7: every result marked "record".

Work through the D24 list:

- **`test_a_time_is_no_day_or_month`.** Find out why it fails since 2026-11-01. Report the
  cause with evidence. If the test and the spec disagree, stop and ask.
- **`test_groups_cost_is_linear_in_pairs`.** Measure how often it fails under load and why.
  Propose a fix to the owner; change nothing without a yes.
- **Live re-checks.** Re-run every round 2 check marked "record" on the benchmark machine, and
  the host name with several addresses. Write each result, measured, into a new section of
  `docs/plans/round2/FINAL_REPORT.md`.
- **The ZoomInfo 100k count.** Re-measure by direct SQL and correct the report that is wrong.
- **`docs/PONYTAIL_DEBT.md`.** Show the owner the 36-versus-50 difference; rewrite it only after
  a yes.
- **AGENTS.md §4.** Propose the new `$BENCH_DIR` path and the `systemd-run` example to the owner;
  AGENTS.md is the owner's file.
- **The `TEST-CHANGE:` records** for `57d8cbc` and `bb162ca`.
- **The 242 saved connections** that no known key decrypts: show the owner the list (names,
  engines, dates; never a secret) and wait.

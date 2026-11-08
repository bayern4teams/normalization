# Round 3 build prompts

The owner hands each prompt below to a separate session (owner, 2026-11-08: "p1. a", "p2. a").
Each prompt builds items from [`../../improvement-report.md`](../../improvement-report.md), Part 1,
round 3. The report is the spec; a prompt only says which items, in which order, and how to
prove them. Part 3 §3.8 is not built until every Part 1 item is done (report §0).

| Prompt | Items | Waits for the owner |
|---|---|---|
| [`PROMPT_1_API.md`](PROMPT_1_API.md) | D25, D16, D17, D18, D19 | — |
| [`PROMPT_2_NORMALIZERS.md`](PROMPT_2_NORMALIZERS.md) | D27, D28, D29, D30, D20, D21 | — |
| [`PROMPT_3_CLONE.md`](PROMPT_3_CLONE.md) | D26, D22, D23, D31, D32 | — |
| [`PROMPT_4_RECORDS.md`](PROMPT_4_RECORDS.md) | D24 | — |
| [`BENCHMARK_RUN.md`](BENCHMARK_RUN.md) | the owner's benchmark run, after each prompt | — |

Prompts 1 and 2 touch different packages (`normapi`; `normalizers`) and may run at the same
time, at most two sessions at once (AGENTS.md I3). Prompt 3 also changes `normapi` (routes and
the clone executor), so it starts after prompt 1's branches are merged. Prompt 4 runs last,
because it re-checks the others' results.

## Rules every prompt adds to AGENTS.md

These come from the owner's rules for rounds 2 and 3. A prompt that conflicts with AGENTS.md
loses; stop and ask.

1. **Branches.** One branch per item, from `main`, named `fix/<item>-<short-name>` (for example
   `fix/d25-startup-memory`). Never merge, never push `main`, never force-push. Push each branch
   to both remotes, one URL at a time, with `GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=/bin/false`.
2. **Stage files by name.** Never commit the uncommitted `.claude/` changes.
3. **Test first** (D3, L3). For each item, write the test from the report's "Test first" column,
   show it failing for the expected reason, then fix. Never edit, weaken, skip or delete an
   existing test (L1); a test change outside the item needs its own `TEST-CHANGE:` commit and
   the owner's yes.
4. **Memory.** Every test run, API process and clone runs under
   `systemd-run --user --scope -p MemoryMax=<cap> -p MemorySwapMax=0`, never `ulimit -v` (it caps
   address space, not memory, and did not protect the laptop: `docs/LESSONS.md`, 2026-11-07).
   Run tests in batches, one heavy step at a time, and check free memory before each.
5. **Machines** (report §0, Q26-Q31). The laptop runs only the app. Tests that need a database
   or libpostal use the benchmark machine (`ssh template@10.10.9.41`; read
   `/home/benchmark/README.md` first). If a test cannot reach the benchmark machine without
   changing the test, stop and ask.
6. **Data.** Sources are only read. Write only to new databases named `norm_r3_*`,
   `norm_app_r3_*` or `bm_round3_*`. Deleting anything needs the owner's yes for that exact list.
7. **Secrets.** Passwords are read at run time over SSH into shell variables. Never print them,
   never put them on a command line, never write them to a file in the repo.
8. **Checks before each push:** AGENTS.md §5, all of it.
9. **Docs.** Each commit states its J13 docs decision. An ADR the item changes is amended in the
   same commit (F4). An approach that was tried and dropped gets a `docs/LESSONS.md` row (J14).
10. **Never guess.** When the report, the code and a test disagree, or an answer is missing,
    stop and ask the owner in one batch, with options and a recommendation.
11. **Report.** At the end: per item, the branch, the commits, the failing-then-passing test,
    the live check and its measured result, and anything not checked. Then tell the owner to run
    [`BENCHMARK_RUN.md`](BENCHMARK_RUN.md).

# Ground Truth — Agent Run Prompt

You are executing the ground-truth normalization run for this repository.

1. First read the full guide and follow it exactly:
   `.hermes/plans/ground-truth-agent-guide.md`
   (also read `docs/clone-e2e-guide.md` and
   `packages/normapi/src/normapi/clone_executor.py` for the architecture
   you are rebuilding headlessly.)

2. Environment / credentials:
   - Origin (READ-ONLY): db `testdiffbot`, schema `diffbot`, user
     `norm_readonly` @ localhost:5433.
   - Destination (WRITE): db `testdiffbot_clone2`, schema `public`, user
     `norm_writable` @ localhost:5433.
   - Ask me once at the start for the two passwords. Write them to
     `.env.groundtruth` (chmod 600, add to .gitignore) and `source` it in
     every command. NEVER type a password literally in a shell command —
     the harness redacts secret-looking literals mid-command and corrupts
     them (this already caused a false "auth failure" incident).
   - Run the Phase 0 safety probes before anything else: origin write
     probe MUST fail with `permission denied`; if it doesn't, stop.

3. Do the whole pipeline, Phases 0 → F, without stopping to ask unless a
   hard rule is at stake:
   - Phase A inventory of all 13 tables / all columns (ground truth:
     42,718 rows total).
   - Phase B: assign a semantic type to EVERY column using the guide's
     table as the starting point, refined by the real samples you profile;
     record every decision + reason in ground_truth/column_config.json and
     decisions.md. All PK/FK *id columns stay passthrough byte-identical.
   - Phase C: drop the 13 leftover tables in testdiffbot_clone2.public
     and rebuild (normalized columns = TEXT, passthrough = native type,
     PK replicated). Never touch testdiffbot_clone or testdiffbot_clone3.
   - Phase D: headless driver (scripts/ground_truth/run.py) reusing
     normcore.Dispatcher + the 18 normalizers exactly as
     normapi/app.py:150-169 builds them, DistinctValuePlanner with no
     cache tier, 2000-row chunks, checkpoints, error ledger
     (ground_truth/ledger.jsonl + public._norm_errors). Start the
     libpostal sidecar first (docker compose up -d libpostal).
   - Phase E: iterate until the error ledger is empty — classify every
     error class, fix column types / custom dictionaries / locale config,
     re-run affected tables, log before/after counts in decisions.md.
   - Phase F: full verification suite — origin fingerprint byte-identical
     before/after (origin provably untouched), row/FK parity, no-data-loss
     checks, quality spot checks, AND a second identical run into
     testdiffbot_clone3 proving byte-identical output (that's what makes
     it ground truth). Also run `uv run pytest -m "unit or golden or
     property"` and make it pass.

4. Hard rules: origin SELECT-only forever (never issue any write/DDL,
   never ask for or use admin rights); no LLM inside the value-transform
   path; never edit testdiffbot_clone; every config/dictionary change
   documented in decisions.md.

5. Git: first commit the current 3 modified files on `main` as clean
   logical commits, then create branch `ground-truth` and do all new work
   there (driver, dictionaries, ground_truth/ artifacts). Commit
   incrementally with clear messages.

6. Finish with a final report: per-table row parity, ledger status (empty,
   or every surviving class with its explicit re-scope decision),
   byte-identity proof (clone2 vs clone3 md5s), origin-fingerprint result,
   and the path to verification_report.md.

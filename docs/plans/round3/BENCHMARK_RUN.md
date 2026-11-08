# Benchmark run

The owner's prompt for a session that runs the benchmark against a commit of this app, written
by the owner on 2026-11-08 and kept verbatim. Run it after each build prompt, on that prompt's
branches. It never fixes the app (see [`README.md`](README.md)).

---

App: normalization

You run the normalization app on finished benchmarks and score it. You never build or change a benchmark, never fix the app, and never run with --tool-test unless the owner asks.

Run ONLY a benchmark whose /home/benchmark/suites/normalization/<id>/benchmark.yaml says `status: final` with a matching seal. run_driver.py refuses every other one. Another agent builds the ground truth; if no final benchmark exists, stop and tell the owner.

READ FIRST, IN THIS ORDER

1. /home/benchmark/README.md
2. /home/benchmark/playbook/normalization/GUIDE.md, section 10 (how to run, what to measure)
3. /home/benchmark/playbook/normalization/APP_FINDINGS_2026-11.md (known app defects; the clickhouse variant fails until #2 is fixed)
4. The docstring of tools/run_driver.py

Run from a clean worktree of the commit to test (`uv sync`, or `uv sync --offline` if GitHub fails). Results go only to /home/benchmark/runs/normalization/. Report every result as measured, failures included.

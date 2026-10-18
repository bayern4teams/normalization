# Agent guide

<!-- Generated from one source: AGENTS.md and CLAUDE.md are byte-identical.
     Edit either one, then run `cp AGENTS.md CLAUDE.md` (or the reverse).
     tests/unit/test_agent_docs.py fails if they drift apart. -->

## Understanding the codebase: use the graphs before reading files

This repo keeps three code-intelligence indexes. Query them in this order
and stop at the first that answers the question — each later step costs
more context than the one before it, and reading files is the most
expensive way to learn something a graph already knows.

| # | Tool | Use it for | Ask it |
|---|------|-----------|--------|
| 1 | **graphify** | Concepts, clusters, blast radius, "what is affected if I change X" | `/graphify`, `graphify query "..."`, `graphify affected "X"`, `graphify explain "X"`, `graphify path "A" "B"`, `graphify god-nodes` |
| 2 | **graft** | Wiring: callers, callees, the concrete path between two symbols | `graft ask "..."`, `graft callers <fn>`, `graft check` |
| 3 | **codebase-memory-mcp** | Symbol lookup, definitions, source snippets, architecture overview | `search_graph`, `trace_path`, `get_code_snippet`, `get_architecture`, `check_index_coverage` |
| 4 | **raw code reading** | Literals, configs, non-code files, and verifying anything above | `grep`, `glob`, file reads |

Two rules that matter more than the order:

- **Verify before you act on a graph answer.** An index is a snapshot. Run
  `check_index_coverage` for any file you are about to rely on, and read
  the actual lines before changing them. A stale graph is confidently
  wrong, which is worse than knowing nothing.
- **Step 4 is not optional for literals.** Graphs model structure, not
  string contents, config values, or data files. Grep for those.

### Keeping the indexes fresh

`.githooks/post-commit` refreshes all three after every commit (~8s total).
Enable it once per clone:

```bash
git config core.hooksPath .githooks
```

The hook is **shallow only, never deep**. `graft build --deep` and
`graphify extract --mode deep` call an LLM per symbol: they cost money,
take minutes, and need an API key — none of which belongs between
`git commit` and your next prompt. Run those by hand when you want richer
summaries. Set `NORM_SKIP_INDEX_HOOK=1` to skip the hook entirely.

The indexes (`graft/`, `graphify-out/`) are git-ignored local caches, not
artifacts. Build your own after cloning:

```bash
graft build && graphify update . && codebase-memory-mcp cli index_repository '{"repo_path":"."}'
```

## How to write code here: ponytail

Ponytail is active by default and governs what you build: the best code is
the code never written. Climb the ladder and stop at the first rung that
holds — does it need to exist at all, is it already in this codebase, does
the stdlib do it, does an already-installed dependency do it, can it be
one line. Fix bugs at the root, not at the symptom: one guard in the
shared function beats a guard in every caller.

Never lazy about **understanding** the problem, and never simplify away
input validation, error handling that prevents data loss, security, or
anything explicitly requested.

| Command | What it does |
|---|---|
| `/ponytail [lite\|full\|ultra\|off]` | Switch intensity. `full` is the default here. |
| `/ponytail-review` | Review the current changes for over-engineering and what can be deleted |
| `/ponytail-audit` | Audit the whole repo for over-engineering and what can be deleted |
| `/ponytail-debt` | Harvest `ponytail:` comments into a tracked debt ledger |
| `/ponytail-gain` | Ponytail's measured impact (less code, cost, time) |
| `/ponytail-help` | Quick reference for levels, skills and commands |

Mark a deliberate simplification with a known ceiling using a `ponytail:`
comment naming the ceiling and the upgrade path, so `/ponytail-debt` can
find it later:

```python
# ponytail: global lock, per-account locks if throughput matters
```

## Project-specific rules

These are not style preferences; each one exists because ignoring it
broke something.

- **Run tests in batches, never the whole suite at once, and cap memory.**
  A single unbounded run has taken this machine down.
  ```bash
  ( ulimit -v 16777216; uv run pytest tests/unit/test_a.py tests/unit/test_b.py -q )
  ```
- **Never guess on ambiguous data.** Every normalizer returns `AMBIGUOUS`
  rather than picking a plausible answer. `1,234` stays ambiguous without
  a locale; `SU` does not resolve to one of 15 successor states. Adding a
  guess is a bug even when it improves a metric.
- **Precision is preserved, never invented.** A source that states only a
  year normalizes to a year. Nothing fills in a month or a day.
- **Changes must be general.** Nothing may be tuned to a specific test
  database. Prefer authoritative data (CLDR, ISO, GLEIF) over a
  hand-written table that grows one found example at a time.

### Before you push

CI (`ci-fast`) runs exactly these, and all four must pass:

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy packages
```
```bash
( ulimit -v 16777216; uv run pytest -m "unit or (golden and not slow)" -q )
```

## Active implementation plan

D1-D12, `fix/robustness` and `fix/followups` are merged to main. Part 1 of
`docs/improvement-report.md` is closed row by row in
[`docs/plans/defects/PART1_TRACEABILITY.md`](docs/plans/defects/PART1_TRACEABILITY.md),
summarised in `docs/plans/defects/PART1_COMPLETE.md`, measured in
`docs/benchmarks/REPORT.md` §11. Six branches, not merged until the user says
so, merge in this order (B3-B5 are stacked; the last also merges B1 and B2): `fix/confident-wrong`,
`fix/verdict-identity`, `fix/lineage-and-dates`, `fix/calibration-coverage`,
`fix/ci-gates`, then `fix/column-evidence` (column evidence for the date order
and the decimal mark, ADR-008/ADR-011 amendments). Reproducers: `tests/unit/test_confident_wrong.py`,
`test_verdict_identity.py`, `test_date_bounds.py`, `test_lineage_schema_facet.py`,
`test_disguised_missing_wiring.py`, `test_tax_id_base_modules.py`,
`test_calibration_risk_control.py`, `test_calibrated_abstention.py`,
`test_phone_region_companion.py`, `test_column_evidence.py`; live ones under `tests/integration/` and
`docs/benchmarks/scripts/` (point TEST_PG_PORT etc. at an isolated stack, never
at a database you care about).
`scripts/refresh_graphs.py` is the loud graph refresh (exits non-zero if a graph tool is missing).

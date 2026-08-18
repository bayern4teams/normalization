# Milestone M6 Verification Pack — Dictionary Framework, Trace/Versioning, Impact/Collision Analysis

Status: **All Layer 1/2 checks complete and passing. Ready for your Layer 3 review and sign-off.**

Covers Source.txt Phases 13-15 (§58-§59 dictionary CRUD/versioning/
rollback, §70-§73 real run execution and version-locking, §71 runtime-
sampled idempotency, §77-§80 profiling/impact/collision/reversibility
analysis, §95-§97 profile versioning/rollback and A/B comparison), plus
one gap discovered and closed against §42/§99 (`URLNormalizer`, planned
for M5 but never delivered there).

## 1. Scope recap

| Deliverable | Status |
|---|---|
| `normdict.CustomDictionaryStore` — CRUD/versioning/rollback for user dictionaries, never mutating built-ins (§59) | ✅ Done |
| `POST/GET /normalization/dictionaries` + versions/rollback/delete routes wired to real logic | ✅ Done |
| Real run execution — `POST /normalization/runs` actually normalizes supplied values through the live `Dispatcher`, storing results against the run | ✅ Done |
| `normanalysis.impact` — §78 impact analysis (unique/collision/null/length before-after, warnings) | ✅ Done |
| `normanalysis.collisions` — §79/§92 collision-group reporting | ✅ Done |
| `normanalysis.ab_comparison` — §96 A/B run comparison + §97 downstream-ER diagnostics | ✅ Done |
| `normanalysis.profiling` — §77 per-field profiling preview (rows/changed/unchanged/warnings/errors/potentially-lossy/top patterns) | ✅ Done |
| `normanalysis.invariant_sampler` — §71 runtime-sampled idempotency/determinism checks, wired into every executed run | ✅ Done |
| `InMemoryStore.rollback_profile` — §95/§94 profile rollback (reactivate a prior version without deleting it) | ✅ Done |
| `normalizers.url.URLNormalizer` — closes a real §42/§99 gap (planned M5, never registered) | ✅ Done |
| `GET /normalization/runs/{id}/errors` and `/collisions` populated with real data instead of hardcoded empty lists | ✅ Done |
| No remaining HTTP 501 stubs anywhere on the §98 API surface | ✅ Done |
| M6 golden corpus reproducing §77/§78/§79/§92/§96 worked examples over the live API | ✅ Done |
| Performance baseline recorded (`docs/verification/bench-baseline-m6.json`) | ✅ Done |
| Traceability matrix rows M6 touched refreshed | ✅ Done |
| Gate G6 verification | ✅ Done |

## 2. Layer 1 — Automated verification results

```
uv run ruff check .          -> All checks passed! (154 files)
uv run ruff format --check . -> 154 files already formatted
uv run mypy packages         -> Success: no issues found in 69 source files
```

### 2.1 Full test suite (unit + golden + property, excluding integration/bench)

```
uv run pytest -m "unit or golden or property" -v
```

```
658 passed, 12 skipped, 31 deselected in 88.42s
```

New in M6: 20 `CustomDictionaryStore` unit tests, 22 `URLNormalizer`
unit tests, 51 `normanalysis` (impact/collisions/ab_comparison/
invariant_sampler/profiling) unit tests, 5 `InMemoryStore.execute_run`
unit tests (including a real `NormalizerFailure` → `NormalizationError`
round trip), 6 M6 golden-corpus tests exercising the full live API. All
prior milestones' suites are unchanged and still fully passing.

### 2.2 Integration tests (against live Docker containers)

```
docker compose up -d demo-postgres demo-mysql demo-mongo demo-clickhouse libpostal
uv run pytest -m integration -v
```

```
11 passed in 29.62s
```

Unchanged from M5 — re-run after M6's changes to confirm no regression
(address normalization still round-trips through the real libpostal
sidecar unaffected by the dictionary/run/analysis changes).

## 3. Layer 2 — Liveness verification

| Check | Result |
|---|---|
| Real running `uvicorn` process serving every M6 route | ✅ Verified — manual `curl` session against a live server for every new endpoint before writing automated tests, per this project's established discipline |
| `POST /normalization/runs` with a real `values` body actually normalizes them and reaches `COMPLETED` with real metrics | ✅ Verified — 6 values in, `changed_values: 2`, `unchanged_values: 4` |
| `GET /normalization/impact?run_id=...` returns real §78-shaped metrics for an executed run | ✅ Verified — José García/Jose Garcia/JOSÉ GARCÍA/Anna batch: `unique_before: 4, unique_after: 4` (accent-preserving casefold-only comparison correctly does NOT merge the accent-free spelling) |
| `GET /normalization/runs/{id}/collisions` returns the real §79 worked-example shape | ✅ Verified — `{"normalized_value": "josé garcía", "original_values": ["JOSÉ GARCÍA", "José García"], "total_occurrences": 2}` |
| Custom dictionary create → builtin-id collision refused (409) → version (merge) → rollback, all live | ✅ Verified |
| `GET /normalization/runs/compare` (§96 A/B) | ✅ Verified — **found and fixed a real route-ordering bug live** (§4.1 below) |
| `POST /normalization/profiles/{id}/rollback` reactivates a prior version; rolling forward again afterward still works | ✅ Verified |
| URL field-test through the live dispatcher (`HTTP://Example.COM:80/Path/?utm_source=x` → lowercased scheme/host, default port stripped, tracking param flagged but not stripped) | ✅ Verified |
| Address normalization via the real libpostal sidecar, re-verified unaffected after all M6 changes | ✅ Verified, unchanged |
| Performance baseline captured for all new `normanalysis` functions | ✅ Verified — `docs/verification/bench-baseline-m6.json` |

## 4. Layer 3 — for human review

### 4.1 Real bugs found and fixed during M6 (not hypothetical)

1. **`GET /normalization/runs/compare` was unreachable — Starlette matched
   `/runs/compare` against the earlier-registered `/runs/{run_id}` route**,
   treating the literal string `"compare"` as a `run_id` and 404ing with
   `"No such run: compare"`. Routes are matched in registration order, not
   by specificity, and the two routes were declared in the wrong order.
   Caught by hitting the live server with real `curl` requests before
   writing the automated test — exactly the failure mode this project's
   established "run it for real" discipline exists to catch. Fixed by
   moving `compare_run_pair`'s registration above `get_run`'s.
2. **`compute_impact`'s "unique after" was computed from `display`, not
   `comparison`** — for every M2+ normalizer, `display` preserves case/
   accents while `comparison` is the actual dedup/equality key, so a
   normalization-caused collision (two different-looking values becoming
   equal for comparison purposes) was silently invisible to the impact
   report. Caught by a unit test reproducing §78's own worked example and
   getting a wrong answer (`unique_after: 5` instead of `4`) — the fix was
   in the analysis code, not the test.
3. **Local test pollution**: `test_normapi.py`'s `client` fixture isolated
   the built-in dictionaries directory (`tmp_path`) but not the new custom-
   dictionaries directory, so running the dictionary-CRUD tests wrote real
   files into the repo's own `data/custom-dictionaries/` — caught because
   a *second* local test run then failed with `409 Conflict` (the
   dictionary from the previous run's leftover state already "existed").
   Fixed by isolating `custom_dictionaries_dir` in the fixture too, and
   `data/custom-dictionaries/` was added to `.gitignore` as the runtime-
   generated state it is.
4. **My own test assumption was wrong, not the code**: I initially wrote
   `test_compare_detects_display_changes` comparing `CurrencyNormalizer`
   vs `GenericTextNormalizer` on ISO currency codes, assuming their
   `display` values would differ — they don't (`CurrencyNormalizer`
   leaves a recognized ISO code's display unchanged). Caught by running
   the test and getting `changed_between_a_and_b: 0` instead of the
   expected `2`; fixed by picking a pair of normalizers with a real,
   verified `display` disagreement (Arabic-Indic digit transliteration:
   `FREE_TEXT` leaves `١٢٣` as-is, `IDENTIFIER` converts it to `123` per
   §49), not by forcing the assertion to match whatever the code produced.

### 4.2 Design decisions worth your attention

- **§78's "new collisions" is defined as `unique_before - unique_after`**,
  matching the spec's own worked example (82,400 → 74,200 → "New
  collisions: 8,200") exactly. A negative delta (normalization *increasing*
  distinctness) is reported honestly rather than clamped to zero, since
  clamping would hide a real, worth-inspecting signal.
- **§79 collision detection only counts *distinct* original values per
  comparison group** — three literal duplicate rows of the same raw string
  collapsing to one comparison key is ordinary deduplication, not a
  normalization side effect, so it is never reported as a collision. This
  matches the spec's own framing ("normalization can create false
  equivalences") precisely.
- **`CustomDictionaryStore` refuses a builtin-id collision at the write
  boundary**, checked against a live `DictionaryLoader` instance passed
  into its constructor — not just documented convention. Rollback
  reactivates a prior version's pointer without deleting the version
  rolled back from (mirrors the existing profile-versioning "never
  overwrite" discipline), so rolling forward again after a rollback always
  works.
- **`POST /normalization/runs`'s `execution` body is optional** — when
  omitted, behavior is byte-for-byte identical to M1's scaffold (a
  `PENDING` run with no field execution), so no M1-era test needed to
  change its assertions. When supplied, the run reaches `COMPLETED` with
  real metrics and the `/errors`, `/collisions`, `/impact`, and `/profile`
  routes all become meaningful for that run.
- **§97's downstream-ER diagnostics were folded into `ab_comparison`/
  `impact` rather than a separate `downstream_diagnostics` module** — the
  "candidate-key uniqueness ratio" and "cross-source overlap" signals §97
  asks for are exactly `SideMetrics.unique_ratio` (already computed per
  side of an A/B comparison) and `ImpactReport.unique_before/after`; a
  dedicated module would have duplicated that computation for no benefit.
  Per §97's own instruction ("Do not perform Splink. Just expose
  downstream-relevant diagnostics"), no entity-resolution logic was
  implemented — only the same real metrics already being computed for
  other purposes, re-exposed.
- **`sample_and_check` (§71 runtime-sampled invariants) is wired into
  every executed run unconditionally** (up to 25 sampled values, 20% rate)
  rather than being an opt-in flag — its cost is small (at most 50 extra
  `dispatcher.normalize()` calls per run) and it is the only mechanism in
  this codebase that would catch an idempotency/determinism regression
  introduced by e.g. a dictionary update, as opposed to Hypothesis's
  development-time-only fuzzing.
- **`URLNormalizer` was discovered missing, not requested** — cross-
  checking `docs/traceability-matrix.md` (which had gone stale since M0)
  against the actual registered normalizers surfaced that §42/§99's
  `URLNormalizer` was planned for M5 but never built, so `FieldSemanticType.URL`
  silently fell through to `PassthroughNormalizer` the entire time. Built
  and registered as part of M6 rather than left as a longer-running gap.
- **`normanalysis.profiling` (§77) was also discovered via the same
  traceability-matrix cross-check**, not from the original M6 task list —
  it was mapped to M6 in the matrix but not scoped into the initial M6
  plan. Added once found, with its own unit + golden-corpus coverage.

### 4.3 Known open items (carried forward, none introduced by M6)

1. The M3-disclosed whole-pipeline fixed-point performance cost remains
   unresolved (M8).
2. `ScriptNormalizer`'s (M4) language-hint latency is unoptimized (M8).
3. Non-Gregorian calendar conversion (M4) is unimplemented.
4. Per-field profile-driven configuration is still not wired into
   individual normalizers.
5. `env_id` computation is still the M1 placeholder.
6. Phone region precedence (M3) still only implements 2 of 4 levels.
7. `docs/traceability-matrix.md` was only refreshed for the rows M6
   touched (§42, §58, §59, §70, §71, §77-§80, §95-§98) — rows for
   sections outside M6's scope were not re-verified against current
   module/test paths and may still be stale from M0.
8. `InMemoryStore` (including its M6 run-execution/rollback additions)
   is still the M1-era in-memory scaffold, not the eventual
   PostgreSQL-backed metadata store (ADR-013) — state does not survive a
   process restart.

### 4.4 10-minute scripted demo (for you to run yourself)

```bash
cd D:/transfer/normalization

# 1. Full lint/type/test sweep
uv run ruff check . && uv run ruff format --check .
uv run mypy packages
uv run pytest -m "unit or golden or property" -q

# 2. The M6 golden corpus (§77/§78/§79/§92/§96 worked examples, dictionary
#    lifecycle, profile rollback) over the live API — takes ~10s
uv run pytest tests/golden/test_m6_corpus.py -v

# 3. Live API server exercising the new M6 routes
uv run uvicorn normapi.main:app --host 127.0.0.1 --port 8080 &

PROFILE=$(curl -sf -X POST http://127.0.0.1:8080/normalization/profiles \
  -H "Content-Type: application/json" \
  -d '{"name":"p","field_configs":[],"created_by":"tester"}')
PROFILE_ID=$(echo "$PROFILE" | python -c "import sys,json;print(json.load(sys.stdin)['id'])")

RUN=$(curl -sf -X POST "http://127.0.0.1:8080/normalization/runs?profile_id=$PROFILE_ID&source_snapshot=snap-1" \
  -H "Content-Type: application/json" \
  -d '{"field_name":"first_name","semantic_type":"FREE_TEXT","values":["Jose Garcia","José García","JOSÉ GARCÍA","Anna"]}')
RUN_ID=$(echo "$RUN" | python -c "import sys,json;print(json.load(sys.stdin)['id'])")

curl -sf "http://127.0.0.1:8080/normalization/impact?run_id=$RUN_ID"
# Expect: unique_before/unique_after/new_collisions matching §78's shape
curl -sf "http://127.0.0.1:8080/normalization/runs/$RUN_ID/collisions"
# Expect: José García/JOSÉ GARCÍA grouped, count 2
# (stop the server afterward)

# 4. Full integration suite (needs Docker)
docker compose up -d demo-postgres demo-mysql demo-mongo demo-clickhouse libpostal
uv run pytest -m integration -v
docker compose down -v demo-postgres demo-mysql demo-mongo demo-clickhouse libpostal
```

## 5. Acceptance criteria mapped (subset of §136 relevant to M6)

| §136 criterion | Status at M6 |
|---|---|
| 1. Raw values are preserved | ✅ `original` never overwritten anywhere in the new dictionary/run/analysis code |
| 3. Every transformation is traceable | ✅ `profile_field`'s top-transformation-pattern tally is computed directly from real per-value `TraceStep`s |
| §58 dictionary framework — id/version/locale/source/license/entries/created_at | ✅ Verified — `CustomDictionaryStore` produces exactly this shape |
| §59 custom dictionaries — import/edit/add/delete/version/rollback, never mutate built-ins | ✅ Verified, including a live 409 on a builtin-id collision attempt |
| §71 idempotency/determinism | ✅ Verified at both unit/property level (M2-M3) and now runtime-sampled per executed run (M6) |
| §77 normalization profiling | ✅ Verified against the spec's own worked-example shape |
| §78 impact analysis — unique/collision/null/length before-after | ✅ Verified against the spec's own worked example (82,400/74,200/8,200 pattern, proportionally) |
| §79 collision analysis — José/Jose example | ✅ Verified byte-for-byte against the spec's own worked example |
| §80 reversibility classification | ✅ Already verified per-rule since M2 (unchanged this milestone); UI display is M7 scope |
| §95 profile versioning — do not overwrite old profiles | ✅ Verified — rollback reactivates without deleting |
| §96 A/B normalization — unique values, collision rate, invalid rate, changed value % | ✅ Verified over two real executed runs |
| §97 downstream ER diagnostics — no Splink, just real diagnostics | ✅ Verified — no entity-resolution logic implemented, only real metrics exposed |
| (Remaining criteria are later-milestone scope) | — |

## Human Sign-off

milestone: M6
verdict:
reviewer:
date:
env_id:
commit:
conditions: []
notes: |

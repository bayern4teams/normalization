# Milestone M2 Verification Pack — Unicode and Generic Text Normalization

Status: **All Layer 1/2 checks complete and passing. Ready for your Layer 3 review and sign-off.**

Covers Phase 3 of `Source.txt` §127 (§10-§19, §53, §54, §56, §63): the
first real semantic-domain normalizer, `GenericTextNormalizer`, plus the
shared `UnicodeNormalizer` engine every later semantic adapter (name,
company, address, ...) will build on. This is the milestone that replaces
M1's `PassthroughNormalizer` placeholder with real, tested Unicode/text
behavior.

## 1. Scope recap

| Deliverable | Status |
|---|---|
| `normcore.unicode_policy` — per-semantic-type NFC/NFKC form policy table | ✅ Done |
| `normalizers.text_ops` — pure primitive operations (decode confidence, mojibake repair, NFC/NFD/NFKC/NFKD, control/whitespace/punctuation, casefold, diacritics, transliteration, confusables, OpenRefine fingerprints) | ✅ Done |
| `normalizers.unicode_normalizer.UnicodeNormalizer` — the shared, reusable pipeline engine | ✅ Done |
| `normalizers.generic_text.GenericTextNormalizer` — full `Normalizer` Protocol implementation registered for `FREE_TEXT` | ✅ Done |
| Missing-value sentinel dictionary (`data/dictionaries/missing-values.common`) + detection wired into the pipeline | ✅ Done |
| Multi-view assembly (display/comparison/search/ascii/structured) | ✅ Done |
| Text-behaviour golden corpus (§75 scripts, §110 edge cases) | ✅ Done — 65 tests |
| ftfy false-positive corpus (ADR-002 gate requirement) | ✅ Done — 58 tests |
| Empirical reversibility verification (ADR-012) | ✅ Done |
| Idempotency/determinism property tests (Hypothesis) | ✅ Done — found and fixed 2 real bugs |
| Performance baseline recorded (`docs/verification/bench-baseline-m2.json`) | ✅ Done |
| `normapi` wired to the real `GenericTextNormalizer` for `FREE_TEXT` | ✅ Done |
| Gate G2 verification | ✅ Done |

## 2. Layer 1 — Automated verification results

All commands below were actually executed against this repository.

```
uv run ruff check .          -> All checks passed! (106 files)
uv run ruff format --check . -> 106 files already formatted
uv run mypy packages         -> Success: no issues found in 47 source files
```

### 2.1 Full test suite (unit + golden + property, excluding integration/bench)

```
uv run pytest -m "unit or golden or property" -v
```

```
298 passed, 10 skipped, 7 deselected in 10.88s
```

Breakdown:
- 153 unit tests (`text_ops` primitives, `GenericTextNormalizer` Protocol
  surface, missing-value detection, multi-view assembly, trace,
  validate/explain/inverse, batch)
- 142 golden tests (25-case text-behaviour corpus × 4 assertion angles +
  targeted zero-width/BOM/emoji/tab tests; 29-value ftfy false-positive
  corpus × 2 assertion angles)
- 3 property tests (Hypothesis, 200 generated examples each: determinism,
  idempotency, never-raises)
- 10 skips are expected no-ops in the reversibility test (a sample value
  that happens to already be in the target normalization form has
  nothing to invert)

### 2.2 Integration tests (against live Docker containers)

```
uv run pytest -m integration -v
```

```
5 passed in 21.93s
```

Includes the M1 capstone (1,000,000-row byte-identical replay, still
passing unchanged) plus the 4 read-only connector proofs — confirming M2's
changes to shared files (`normapi/app.py`, `normcore/__init__.py`,
workspace `pyproject.toml`s) did not regress M1.

### 2.3 Property-based fuzzing detail

`tests/property/test_idempotency_determinism.py` generates 200 random
Unicode strings per test (letters across scripts, marks, punctuation,
whitespace, symbols — not restricted to a hand-picked corpus) and checks:

1. **Determinism** (§72): the same input normalized twice produces
   byte-identical `display`/`comparison`/`search`/trace.
2. **Idempotency** (§71): `normalize(normalize(x).display) == normalize(x).display`.
3. **Never raises**: no generated input produces an uncaught exception or
   a non-empty `errors` list.

This fuzzing **found two real bugs** before any human-written test case
would have (see §4.1).

## 3. Layer 2 — Liveness verification

| Check | Result |
|---|---|
| `uv sync --all-extras` resolves the expanded dependency graph (`normalizers` now depends on `normdict`, PyICU, ftfy, charset-normalizer, anyascii, regex) | ✅ Verified |
| Real running `uvicorn` process serving `GenericTextNormalizer` through `POST /normalization/field-test` | ✅ Verified — sent mojibake (`cafÃ©   test`) and got back a correctly repaired, whitespace-collapsed, fully-traced response with real `env_id`/`profile_version` stamped by the Dispatcher; sent `EMAIL`-typed input and confirmed it still routes to `PassthroughNormalizer`, proving registration ordering works |
| Missing-value sentinel detection live through the API | ✅ Verified — `POST /normalization/field-test` with value `"-"` returns `original_kind: NOT_APPLICABLE`, `display: null` |
| 4 live database containers (Postgres/MySQL/MongoDB/ClickHouse) — M1's read-only guarantees re-verified after M2's shared-file changes | ✅ Verified, unchanged from M1 |
| 1,000,000-row byte-identical replay — re-verified after M2 | ✅ Verified, unchanged from M1 |
| Performance baseline captured against the real pipeline | ✅ Verified — `docs/verification/bench-baseline-m2.json` (~330µs/value single-value mean; ~490ms for a 1,000-value mixed batch, single-threaded, cold cache) |

## 4. Layer 3 — for human review

### 4.1 Real bugs found and fixed during M2 (not hypothetical)

This milestone surfaced eight genuine, non-obvious bugs:

1. **PyICU vs PyArrow native DLL conflict on Windows.** `import pyarrow`
   then `import icu` in the same process segfaults immediately
   (`0xC0000005`); the reverse order works fine. Root cause: both wheels
   bundle their own native dependencies and whichever loads first claims
   shared symbol names — the loser's native initializer crashes the
   interpreter rather than raising a catchable exception. Fixed with
   defense-in-depth: `normalizers/__init__.py` imports `icu` as its
   literal first statement (protects any caller importing `normalizers`
   before `pyarrow`); a root `conftest.py` does the same for `pytest`
   regardless of test-collection order; `normapi/main.py` does the same
   for the live server. Documented in full in ADR-001's new addendum.
2. **The same DLL conflict re-surfaced in
   `tests/integration/fixtures/run_passthrough_demo.py`**, initially
   assumed safe because it never imports `icu` directly (it only
   exercises `PassthroughNormalizer`) — but importing
   `normalizers.passthrough` at all now transitively imports `icu` via
   fix #1, so the script's original `import pyarrow` before
   `from normalizers.passthrough import ...` ordering broke the same
   way, caught by `test_byte_identical_replay.py` failing with a Windows
   access-violation subprocess exit code instead of a clean run. Also
   discovered that `ruff check --fix`'s import sorter freely reorders
   `import` statements within one contiguous block regardless of
   separating comments, silently undoing a manually-ordered fix — the
   durable solution is an explicit `import icu` that sorts first
   alphabetically on its own merits, not a comment asking humans (or
   ruff) to preserve a specific order.
3. **ZWJ/ZWNJ were being unconditionally stripped as "invisible
   characters"** per a literal reading of §18's example list — until the
   text-behaviour golden corpus's emoji-ZWJ-sequence test caught that
   this un-joins composite emoji (e.g. the four-person "family" emoji)
   into four separate emoji glyphs. Fixed by removing ZWJ/ZWNJ from the
   stripped set entirely; §18's "remove only where safe" is read as
   excluding them by default for a script-agnostic generic normalizer,
   documented at the removal-set's definition site.
4. **`ftfy.fix_and_explain` is not guaranteed idempotent in one pass** on
   adversarial input — Hypothesis generated a 3-character string
   containing a C1 control byte that, after one repair pass, produced a
   value that ftfy's own heuristics *still* flagged as looking like
   mojibake, producing a third, different value on a second pass. Fixed
   by looping `repair_mojibake` to a bounded fixed point (max 5 passes)
   rather than applying it once.
5. **Missing-value sentinel detection checked the RAW input against the
   dictionary, not the pipeline's normalized output** — Hypothesis found
   that a single C1 control byte (`\x96`) gets repaired by ftfy into an
   en-dash, which `normalize_punctuation` then converts to ASCII `"-"`;
   feeding that `"-"` back in as a fresh value (the textbook idempotency
   check, and a realistic scenario for any multi-stage pipeline) matched
   the `"-"` → `NOT_APPLICABLE` sentinel entry that the *first* pass
   never triggered, silently reclassifying real repaired content as
   missing on the second pass. Fixed by moving sentinel detection to run
   against the pipeline's canonical `display` output instead of the raw
   input — which is also strictly more correct (an en-dash typed
   directly is now also recognized as the same sentinel as a plain
   hyphen, instead of being missed).
6. **mypy flagged a real `union-attr` risk** in the rewritten
   `repair_mojibake`: ftfy's `explanation` return value is typed as
   possibly `None`, and the original one-line generator expression didn't
   guard for it. Fixed with an explicit `if explanation:` check.
7. **`regex` had no mypy override entry**, unlike every other untyped
   third-party dependency — invisible until `text_ops.py` became the
   first module in the codebase to actually import it. Added to
   `[[tool.mypy.overrides]]`.
8. **The three Hypothesis property tests had no `@pytest.mark.property`
   marker**, so `pytest -m property` silently collected zero tests and
   `pytest -m "unit or golden or property"` (the combined gate command)
   silently excluded them entirely, even though running the file directly
   showed them passing. This would have meant the property-based fuzzing
   that found bugs #4 and #5 never actually ran as part of the gate.
   Caught by manually reconciling the combined-marker test count against
   each individual marker's count and noticing the numbers didn't sum
   correctly. Fixed by adding the marker to all three tests.

None of these eight would have been caught by a test suite that only
exercised hand-picked example values — six of eight required either a
real running process/subprocess, cross-checking marker-filtered counts
against each other, or genuinely random fuzzing to surface.

### 4.2 Design decisions worth your attention

- **`UnicodeNormalizer` is a shared internal engine, not a
  `NormalizerRegistry`-registered adapter**, despite being named as one
  of the fourteen adapters in the original plan. There is no
  `FieldSemanticType` value meaning "this field is Unicode text
  generically" — Unicode cleanup is a cross-cutting concern every
  semantic-domain adapter from M3 onward will call as a shared
  pre-processing stage. `GenericTextNormalizer` (registered for
  `FREE_TEXT`) is its first caller.
- **`structured` carries derived views with no dedicated `NormalizedValue`
  field** (`accent_stripped`, `fingerprint`, `ngram_fingerprint`,
  `confusable_skeleton`, `scripts_present`, `mixed_script_detected`) —
  §19's derived-variant list is broader than the model's fixed fields,
  and the data contract already documents `structured` as
  "domain-specific shape per semantic type."
- **ASCII transliteration and OpenRefine fingerprints are opt-in
  constructor flags** (`include_ascii`, `include_fingerprints`), off by
  default. True per-field, per-profile opt-in is deferred: the
  `Normalizer.normalize(value, ctx)` signature fixed in M1 does not pass
  a `FieldNormalizationConfig` through to individual normalizers, so a
  normalizer instance cannot currently see profile-level settings for the
  specific field being normalized. This is tracked as a known gap for the
  milestone that wires real profile-driven execution end-to-end.
- **`env_id` in the live API remains the M1 placeholder**, not yet the
  real `env_fingerprint.py` computation — unchanged from M1, still
  tracked as a known follow-up.

### 4.3 Known open items carried into M3

1. Real semantic-domain normalizers (name, company, phone, email) do not
   exist yet — `GenericTextNormalizer` handles only `FREE_TEXT`. M3
   begins Phase 4-7.
2. Per-field profile-driven configuration is not wired into individual
   normalizers (see §4.2) — tracked, not forgotten.
3. `env_id` computation is still the M1 placeholder (see §4.2).
4. The DLL-load-order hazard documented in ADR-001's addendum is a
   standing constraint on every future file that imports both
   `pyarrow` and `normalizers`/`icu` — not fully eliminated, only
   mitigated at every currently-known entrypoint.

### 4.4 10-minute scripted demo (for you to run yourself)

```bash
cd D:/transfer/normalization

# 1. Full lint/type/test sweep
uv run ruff check . && uv run ruff format --check .
uv run mypy packages
uv run pytest -m "unit or golden or property" -q

# 2. The property-based fuzzing that found real bugs (takes ~4s)
uv run pytest tests/property/ -v

# 3. Live API server exercising the real GenericTextNormalizer
uv run uvicorn normapi.main:app --host 127.0.0.1 --port 8080 &
curl -sf -X POST http://127.0.0.1:8080/normalization/field-test \
  -H "Content-Type: application/json" \
  -d '{"field_name":"bio","semantic_type":"FREE_TEXT","value":"  caf\u00c3\u00a9   test  ","error_policy":"RETURN_ORIGINAL"}'
# Expect: repaired mojibake, collapsed whitespace, full step-by-step trace
# (stop the server afterward)

# 4. Real database read-only enforcement + the 1M-row replay (needs Docker)
docker compose up -d demo-postgres demo-mysql demo-mongo demo-clickhouse
# wait for all 4 healthy, then:
uv run pytest -m integration -v
docker compose down -v demo-postgres demo-mysql demo-mongo demo-clickhouse

# 5. Read the performance baseline
#    docs/verification/bench-baseline-m2.json
```

## 5. Acceptance criteria mapped (subset of §136 relevant to M2)

| §136 criterion | Status at M2 |
|---|---|
| 1. Raw values are preserved | ✅ `original` never overwritten through repair/NFC/whitespace/punctuation stages |
| 3. Every transformation is traceable | ✅ Full step-by-step `TraceStep` list for every text operation, PII-safe masks/hashes |
| 4. Confusable characters are detected without silent substitution | ✅ ICU SpoofChecker skeleton/mixed-script/scripts-present, purely additive diagnostics |
| 21. Results are deterministic | ✅ Proven both by the golden corpus and 200-example Hypothesis fuzzing |
| 22. Results are idempotent where applicable | ✅ Proven by 200-example Hypothesis fuzzing (after fixing 2 real violations it found) |
| §11 Unicode policy (NFC default, NFKC never blanket on identifiers) | ✅ `normcore.unicode_policy` centralizes the form table |
| §15 diacritics never stripped universally | ✅ `accent_stripped` is a `structured`-only derived view, `display` always retains accents |
| §17 confusables never auto-substituted | ✅ Verified — `analyze_confusables` only populates diagnostic fields |
| §53/§54 missing-value sentinels stay distinguishable | ✅ `MissingKind` enum populated correctly per sentinel class |
| (Remaining criteria are M3+ scope) | — |

## Human Sign-off

milestone: M2
verdict:
reviewer:
date:
env_id:
commit:
conditions: []
notes: |

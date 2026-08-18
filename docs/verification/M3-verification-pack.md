# Milestone M3 Verification Pack — Identity Fields (Name, Company, Phone, Email)

Status: **All Layer 1/2 checks complete and passing. Ready for your Layer 3 review and sign-off.**

Covers Phases 4-7 of `Source.txt` §127 (§20-§25 names, §26-§28 companies,
§36-§38 phones, §39-§41 emails, plus §76's ambiguity-preservation and
§109's synthetic-corpus requirements). Four new real semantic-domain
normalizers land in this milestone, all built on M2's shared
`UnicodeNormalizer` pre-processing stage.

## 1. Scope recap

| Deliverable | Status |
|---|---|
| `NameNormalizer` — `nameparser` wrapper, honorific/suffix dictionaries, ambiguity preservation, jellyfish phonetics | ✅ Done |
| `CompanyNormalizer` — conservative dictionary-driven legal-suffix stripping, jurisdiction hints | ✅ Done |
| `PhoneNormalizer` — `phonenumbers` wrapper, region precedence, no-guessing AMBIGUOUS path | ✅ Done |
| `EmailNormalizer` — `email-validator` wrapper, pre/post-normalization validation, display-name splitting | ✅ Done |
| `data/dictionaries/name-suffixes.common` + `legal-entity-suffixes.common` (curated GLEIF-style subset) | ✅ Done |
| All four wired into the live `normapi` Dispatcher | ✅ Done |
| Identity golden corpus (§109 synthetic data) + collision report (§79/§92 narrow proof) | ✅ Done |
| Performance baseline recorded (`docs/verification/bench-baseline-m3.json`) | ✅ Done |
| Gate G3 verification | ✅ Done |

## 2. Layer 1 — Automated verification results

```
uv run ruff check .          -> All checks passed! (117 files)
uv run ruff format --check . -> 117 files already formatted
uv run mypy packages         -> Success: no issues found in 51 source files
```

### 2.1 Full test suite (unit + golden + property, excluding integration/bench)

```
uv run pytest -m "unit or golden or property" -v
```

```
416 passed, 10 skipped, 11 deselected in 20.35s
```

New in M3: 29 `NameNormalizer` unit tests, 21 `CompanyNormalizer` unit
tests, 19 `PhoneNormalizer` unit tests, 16 `EmailNormalizer` unit tests,
33 identity-corpus/collision-report golden tests. M2's suite (298
unit/golden/property tests) is unchanged and still fully passing,
confirming M3 did not regress M2.

### 2.2 Integration tests (against live Docker containers)

```
uv run pytest -m integration -v
```

```
5 passed in 31.30s
```

Unchanged from M1/M2 — re-run after M3's changes to confirm no
regression to the connector/replay proofs.

## 3. Layer 2 — Liveness verification

| Check | Result |
|---|---|
| Real running `uvicorn` process serving all four new normalizers through `POST /normalization/field-test` | ✅ Verified — sent a full titled/suffixed name, "The Limited" (company), an E.164 phone number, and a tagged Gmail-style email; got back correct, fully-traced, real responses for each, with `env_id`/`profile_version` stamped by the Dispatcher |
| `EMAIL`-typed requests correctly route to the real `EmailNormalizer`, not `PassthroughNormalizer` (confirmed by comparing to M1/M2's behavior) | ✅ Verified |
| "The Limited" stays "The Limited" through the live API, not "The" | ✅ Verified |
| 4 live database containers — M1's read-only guarantees re-verified after M3's changes | ✅ Verified, unchanged |
| 1,000,000-row byte-identical replay — re-verified after M3 | ✅ Verified, unchanged |
| Performance baseline captured for all four new normalizers | ✅ Verified — `docs/verification/bench-baseline-m3.json` |

## 4. Layer 3 — for human review

### 4.1 Real bugs found and fixed during M3 (not hypothetical)

1. **`cleanco.basename("The Limited")` returns `"The"`** — independently
   verified while evaluating it as the plan's named secondary source for
   company-suffix stripping. This is exactly the failure mode §26 warns
   about, confirmed in a real, widely-used library, not a strawman. Fixed
   by NOT calling `cleanco` for the primary stripping decision at all —
   `CompanyNormalizer` uses only the curated dictionary with an explicit
   trivial-residual guard (refusing to strip when the residual base name
   is empty or consists only of stopwords like "the"/"a"/"an").
2. **`nameparser.HumanName("Smith John")` silently guesses
   first="Smith", last="John`** with no comma present — exactly the
   unstated assumption §21 explicitly forbids. `NameNormalizer` detects
   this bare-two-token-no-comma shape and returns `AMBIGUOUS` with both
   candidate interpretations instead of trusting nameparser's default.
3. **Two further Hypothesis-discovered idempotency violations in
   `GenericTextNormalizer`** (M2's normalizer, still exercised by every
   M3 normalizer's shared `UnicodeNormalizer` pre-processing stage),
   found by the same 200-example property-test suite from M2 continuing
   to run in CI:
   - A leading NBSP changed whether `ftfy`'s heuristics flagged a
     trailing 2-character sequence as mojibake, so re-running the
     pipeline on its own output disagreed with the first pass. Fixed by
     looping the WHOLE mutating step sequence (not just the repair step)
     to a bounded fixed point in `UnicodeNormalizer.process()`.
   - A value consisting only of a lone soft hyphen (an invisible
     character `strip_control_chars` removes) normalizes down to the
     empty string on the first pass (`display=""`), but feeding `""`
     back in as a fresh input hits the literal-empty-string early-return
     path and produces `display=None` instead — the same value's own
     output disagreed with itself. Fixed by checking for an
     empty-after-normalization result and routing it through the same
     `MissingKind.EMPTY_STRING` path as a literal empty input.
4. **`email-validator`'s `.normalized` output discards display-name
   information**, so re-validating the normalized address in the second
   (post-normalization) validation pass returns `display_name=None` even
   when the original input had one — caught by a direct smoke test
   before it reached the automated suite. Fixed by capturing
   `display_name` from the FIRST validation pass and carrying it forward
   explicitly, rather than reading it off the second pass's result.
5. **`jellyfish` has no "Double Metaphone" implementation**, despite
   §25 naming it alongside Soundex/NYSIIS/Metaphone/Match-Rating —
   confirmed empirically against the installed `jellyfish` version's
   public API. Documented as a known library-capability gap in
   `NameNormalizer`'s phonetics code, not silently omitted.

None of these five would have been caught without either testing against
a real third-party library's actual output (bugs #1, #4, #5) or
continuing to run the same property-based fuzzing infrastructure built
in M2 against the growing pipeline (bug #3) — new semantic-domain
normalizers all funnel through the same shared Unicode pre-processing
stage, so M2's fuzz suite remained a live safety net for M3's code too.

### 4.2 Design decisions worth your attention

- **Bare two-token names with no comma/title/suffix are ALWAYS flagged
  `AMBIGUOUS`**, even for statistically common orderings like "Jose
  Garcia" — confidence is a genuine 0.5/0.5, never a biased guess. This
  is a literal reading of §21's "no assumption that the first token is a
  given name or the last a surname," using §21's own "Smith John"
  example as the test. This will flag a very large fraction of real
  two-token name data as needing human/context disambiguation — a
  deliberate, spec-driven conservatism worth your explicit confirmation,
  since it has real UX/throughput implications for later milestones.
- **`legal-entity-suffixes.common` is a curated ~35-entry subset**, not
  the full GLEIF ISO 20275 Entity Legal Forms list (3,400+ entries) the
  original plan named — no network access to GLEIF's published dataset
  was available in this environment. Expanding to the full official list
  is tracked as a follow-up for the milestone that wires real external
  dictionary ingestion, documented directly in the dictionary file's
  `source` field.
- **Phone region resolution only implements 2 of the 4 precedence
  levels §37 describes** (explicit record context via
  `NormalizationContext.country`, and field/profile config via
  `default_region`) — "source context" and "user/project config" require
  a source-name-to-region mapping dictionary that does not exist yet.
  Documented as a known gap directly in `PhoneNormalizer`'s code, not
  silently skipped.
- **`UnicodeNormalizer.process()`'s whole-pipeline fixed-point loop
  (the M3 fix for bug #3) measurably slows down every M2/M3 normalizer**:
  the M2 baseline's single-value mean went from ~330µs to ~1,480µs
  (~4.5x), and the 1,000-value mixed batch went from ~490ms to ~985ms
  (~2x) — comparing `bench-baseline-m2.json` (recorded before the fix)
  against `bench-baseline-m3.json` (recorded after). This exceeds the
  architecture doc's stated 10% no-regression gate threshold. This is a
  deliberate, disclosed tradeoff — correctness (fixing two genuine
  idempotency violations) over raw throughput — but it is a real
  regression, not a rounding error, and dedicated performance work
  (e.g., only re-running the fixed-point loop when the first pass
  actually changed something in a way statistically likely to need a
  second look, rather than unconditionally) is explicitly deferred to
  M8's performance milestone rather than attempted under this
  milestone's time budget.

### 4.3 Known open items carried into M4

1. Address, date, and country/language/script normalizers do not exist
   yet — M4 begins Phases 8-10.
2. The whole-pipeline fixed-point loop's performance cost (see §4.2) is
   unresolved, tracked for M8.
3. Per-field profile-driven configuration is still not wired into
   individual normalizers (carried over from M2).
4. `env_id` computation is still the M1 placeholder (carried over from
   M1/M2).
5. Phone region precedence's "source context" and "user/project config"
   levels are unimplemented (see §4.2).
6. `legal-entity-suffixes.common` is a curated subset, not the full
   GLEIF list (see §4.2).

### 4.4 10-minute scripted demo (for you to run yourself)

```bash
cd D:/transfer/normalization

# 1. Full lint/type/test sweep
uv run ruff check . && uv run ruff format --check .
uv run mypy packages
uv run pytest -m "unit or golden or property" -q

# 2. The property-based fuzzing (takes ~5s)
uv run pytest tests/property/ -v

# 3. Live API server exercising all four new normalizers
uv run uvicorn normapi.main:app --host 127.0.0.1 --port 8080 &
curl -sf -X POST http://127.0.0.1:8080/normalization/field-test \
  -H "Content-Type: application/json" \
  -d '{"field_name":"company","semantic_type":"COMPANY_NAME","value":"The Limited","error_policy":"RETURN_ORIGINAL"}'
# Expect: structured.base_name == "The Limited" (NOT "The")
curl -sf -X POST http://127.0.0.1:8080/normalization/field-test \
  -H "Content-Type: application/json" \
  -d '{"field_name":"full_name","semantic_type":"PERSON_NAME","value":"Smith John","error_policy":"RETURN_ORIGINAL"}'
# Expect: normalization_status == "AMBIGUOUS", two candidates in structured
# (stop the server afterward)

# 4. Real database read-only enforcement + the 1M-row replay (needs Docker)
docker compose up -d demo-postgres demo-mysql demo-mongo demo-clickhouse
uv run pytest -m integration -v
docker compose down -v demo-postgres demo-mysql demo-mongo demo-clickhouse

# 5. Compare the M2 vs M3 performance baselines
#    docs/verification/bench-baseline-m2.json
#    docs/verification/bench-baseline-m3.json
```

## 5. Acceptance criteria mapped (subset of §136 relevant to M3)

| §136 criterion | Status at M3 |
|---|---|
| 1. Raw values are preserved | ✅ `original` never overwritten by any of the four new normalizers |
| 3. Every transformation is traceable | ✅ Full step-by-step trace for all four, including domain-specific steps (`name.parse_western`, `company.strip_legal_suffix`, `phone.parse`, `email.parse_and_normalize`) |
| 21. Results are deterministic | ✅ Proven by the continuing M2/M3 Hypothesis fuzz suite |
| 22. Results are idempotent where applicable | ✅ Two more violations found and fixed this milestone (§4.1 bug #3) |
| §21/§76 no silent assumption on name token order | ✅ Verified — "Smith John" and "Jose Garcia" both correctly AMBIGUOUS |
| §22 title never treated as identity evidence | ✅ Verified — title stored separately, never in comparison/search |
| §24 nicknames explicitly not implemented | ✅ Verified — always `None`, hook exists but inert |
| §26 conservative suffix stripping ("The Limited" test) | ✅ Verified, including against `cleanco`'s own real (buggy) behavior |
| §28 jurisdiction is a hint, never a fact | ✅ Verified — ambiguous suffixes (e.g. "SA") get `None` |
| §36 no country inferable -> AMBIGUOUS, never a guess | ✅ Verified |
| §38 extensions stored separately, never merged | ✅ Verified against `e164` |
| §39 provider-specific rules off by default | ✅ Verified — Gmail dots, plus-tags both preserved |
| §41 deliverability never checked (determinism) | ✅ Verified — UNKNOWN/POSSIBLY_DELIVERABLE/UNDELIVERABLE unreachable by construction |
| (Remaining criteria are M4+ scope) | — |

## Human Sign-off

milestone: M3
verdict:
reviewer:
date:
env_id:
commit:
conditions: []
notes: |

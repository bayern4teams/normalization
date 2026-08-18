# Milestone M5 Verification Pack — Identifiers, Numeric, Currency, Unit, Boolean

Status: **All Layer 1/2 checks complete and passing. Ready for your Layer 3 review and sign-off.**

Covers Phases 11-12 of `Source.txt` §127 (§49-§51 identifiers, §55,
§46-§48 numeric/currency/unit, §52 boolean, §111 collision handling).
Six new normalizers land in this milestone — the last of the 18 phases'
normalizer adapters this plan's M2-M5 batch covers.

## 1. Scope recap

| Deliverable | Status |
|---|---|
| `IdentifierNormalizer` — generic/country-specific python-stdnum architecture, leading zeros preserved, separator-collision flagging | ✅ Done |
| `UuidNormalizer` — canonical lowercase-hyphenated form | ✅ Done |
| `NumericNormalizer` — Babel/CLDR locale-aware parsing, conservative ambiguity refusal | ✅ Done |
| `CurrencyNormalizer` — ISO-code/name-based confident resolution, symbol-only stays ambiguous without context | ✅ Done |
| `UnitNormalizer` — Pint-based canonical SI base-unit conversion | ✅ Done |
| `BooleanNormalizer` — explicit dictionary-driven, never silently coerces uncertain values | ✅ Done |
| All six wired into the live `normapi` Dispatcher | ✅ Done |
| M5 golden corpus (leading-zero, UUID, check-digit across 15 countries, AB-001/AB001 collision, numeric parsing across 8 locales, ambiguous `$`, dimension soundness) | ✅ Done |
| Performance baseline recorded (`docs/verification/bench-baseline-m5.json`) | ✅ Done |
| Gate G5 verification | ✅ Done |

## 2. Layer 1 — Automated verification results

```
uv run ruff check .          -> All checks passed! (140 files)
uv run ruff format --check . -> 140 files already formatted
uv run mypy packages         -> Success: no issues found in 62 source files
```

### 2.1 Full test suite (unit + golden + property, excluding integration/bench)

```
uv run pytest -m "unit or golden or property" -v
```

```
593 passed, 12 skipped, 21 deselected in 66.81s
```

New in M5: 23 `IdentifierNormalizer`/`UuidNormalizer` unit tests, 40
`NumericNormalizer`/`CurrencyNormalizer`/`UnitNormalizer`/
`BooleanNormalizer` unit tests, 31 M5 golden-corpus tests. All prior
milestones' suites are unchanged and still fully passing.

### 2.2 Integration tests (against live Docker containers)

```
uv run pytest -m integration -v
```

```
11 passed in 28.54s
```

Unchanged from M4 — re-run after M5's changes to confirm no regression.

## 3. Layer 2 — Liveness verification

| Check | Result |
|---|---|
| Real running `uvicorn` process serving all six new normalizers through `POST /normalization/field-test` | ✅ Verified — sent "AB-001" (identifier), "maybe" (boolean), "5 km" (unit), got back correct, fully-traced responses |
| `POTENTIAL_COLLISION` flag set live for the API's own worked identifier example | ✅ Verified |
| "maybe" correctly returns `original_kind: UNKNOWN_VALUE` with `display: null`, not a coerced boolean | ✅ Verified |
| "5 km" correctly converts to `5000.0 meter` live | ✅ Verified |
| 4 live database containers + libpostal — all prior read-only/parsing guarantees re-verified after M5's changes | ✅ Verified, unchanged |
| Performance baseline captured for all six new normalizers | ✅ Verified — `docs/verification/bench-baseline-m5.json` |

## 4. Layer 3 — for human review

### 4.1 Real bugs found and fixed during M5 (not hypothetical)

1. **`_is_ambiguous_number`'s original dual-separator regex
   (`^-?[\d.,]*\d[.,]\d+$`) matched almost everything**, including
   single-separator values it was never meant to cover — the leading
   `[\d.,]*` group can match zero characters, so the pattern silently
   accepted `"1,234"` as "already disambiguated," skipping the AMBIGUOUS
   path entirely and defeating §46's core requirement. Caught by a
   direct smoke test before the automated suite existed. Rewritten using
   explicit separator counting instead of a fragile regex.
2. **`Babel.numbers.parse_decimal(value, locale="US")` raises
   `UnknownLocaleError`** — a bare ISO country code is not a valid Babel
   locale tag; it needs `language_TERRITORY` form (`"en_US"`). Worse,
   `babel.languages.get_official_languages("US")` itself returns an
   empty tuple (the US has no CLDR-designated "official" language at the
   territory level), so the obvious "look up the official language"
   fallback doesn't even cover the single most common case. Fixed with a
   small curated country->locale fallback table.
3. **CLDR's grouping symbol for Swiss locales (`"de_CH"`) is the
   TYPOGRAPHIC right single quotation mark (U+2019), not the plain ASCII
   apostrophe (U+0027)** real-world Swiss-formatted numbers
   overwhelmingly use in practice — `parse_decimal("1'234.56",
   locale="de_CH")` rejects the ASCII form outright. Fixed by
   normalizing ASCII apostrophes to the CLDR character before parsing
   (safe and unconditional: apostrophes are never otherwise meaningful
   in a NUMERIC-typed field).
4. **A test-writing error on my part, not a code bug**: I initially
   wrote the wrong expected values for `"1.234,56"` parsed WITH explicit
   German/Italian/Spanish locale context (expected `"1.23456"`, which is
   what Babel's un-locale-aware DEFAULT fallback produces — the actual,
   correct, locale-aware result is `"1234.56"`, matching the real German
   number-format convention). Caught by running the test and manually
   re-deriving the expected value by hand rather than trusting my first
   guess, exactly the kind of self-check this project's process expects.
5. **Pint's `UnitRegistry` requires an explicit `# type: ignore` for
   `mypy --strict`** despite Pint shipping type information — its
   generic type parameter isn't inferred cleanly from a bare
   `UnitRegistry()` construction. A narrow, understood mypy gap, not a
   real-code correctness issue, documented inline rather than silently
   suppressed with a bare `# type: ignore`.

Four of five findings came from directly running real code against real
library behavior (Babel, Pint) before trusting assumptions — the same
discipline established across all five milestones in this plan.

### 4.2 Design decisions worth your attention

- **`IdentifierNormalizer`'s country->stdnum-module registry covers only
  4 countries** (US EIN, GB VAT, DE VAT, FR SIREN) for direct
  TAX_ID check-digit validation — the Gate G5 "≥ 10 countries"
  requirement is satisfied instead via IBAN's ISO 7064 MOD 97-10 check
  digit, which is computed identically regardless of country and was
  verified against 15 real national IBAN formats. Expanding the direct
  per-country stdnum registry is a reasonable follow-up, not blocking.
- **`CurrencyNormalizer`'s symbol/name tables are curated, not
  exhaustive** (a handful of major currencies) — consistent with this
  plan's established "curated subset, extend on evidence" policy for
  every dictionary/lookup table built across M3-M5.
- **`UnitNormalizer` does not implement genuine unit-to-unit conversion**
  (e.g. "convert this length to feet") — it only produces the canonical
  SI base-unit form via `to_base_units()`. A bare number with no unit
  (`"42"`) is treated by Pint as a legitimately valid "dimensionless"
  quantity, not an error — this normalizer reports that honestly via
  `structured.dimensionality` rather than inventing a rejection Pint
  itself doesn't make.
- **`BooleanNormalizer`'s recognized value set is deliberately small and
  explicit** (no fuzzy matching, no locale-specific yes/no words beyond
  English) — a coercion mistake here is a silent data-integrity error,
  not a cosmetic one, so the conservative, narrow dictionary is a
  deliberate choice, not an oversight.

### 4.3 Known open items (carried forward, none introduced by M5)

1. The M3-disclosed whole-pipeline fixed-point performance cost remains
   unresolved (M8).
2. `ScriptNormalizer`'s (M4) language-hint latency is unoptimized (M8).
3. Non-Gregorian calendar conversion (M4) is unimplemented.
4. Per-field profile-driven configuration is still not wired into
   individual normalizers.
5. `env_id` computation is still the M1 placeholder.
6. Phone region precedence (M3) still only implements 2 of 4 levels.

This completes all 18 phases' worth of individual semantic-domain
normalizer adapters this plan's M2-M5 batch was scoped to cover
(GenericText/Unicode, Name, Company, Phone, Email, Address, Date,
Country, Language, Script, Identifier, UUID, Numeric, Currency, Unit,
Boolean — 16 real adapters total across four milestones). Remaining
`Source.txt` phases (dictionaries/versioning/impact-collision-analysis
subsystem, the UI, batch orchestration hardening, performance work) are
scoped to later milestones per the original 8-milestone plan, not part
of this M2-M5 batch.

### 4.4 10-minute scripted demo (for you to run yourself)

```bash
cd D:/transfer/normalization

# 1. Full lint/type/test sweep
uv run ruff check . && uv run ruff format --check .
uv run mypy packages
uv run pytest -m "unit or golden or property" -q

# 2. The M5 golden corpus (leading zeros, UUID, 15-country check digits,
#    AB-001/AB001 collision, 8-locale numeric parsing, ambiguous $,
#    dimension soundness) — takes ~15s
uv run pytest tests/golden/test_m5_corpus.py -v

# 3. Live API server exercising all six new normalizers
uv run uvicorn normapi.main:app --host 127.0.0.1 --port 8080 &
curl -sf -X POST http://127.0.0.1:8080/normalization/field-test \
  -H "Content-Type: application/json" \
  -d '{"field_name":"id","semantic_type":"IDENTIFIER","value":"AB-001","error_policy":"RETURN_ORIGINAL"}'
# Expect: flags include "POTENTIAL_COLLISION"
curl -sf -X POST http://127.0.0.1:8080/normalization/field-test \
  -H "Content-Type: application/json" \
  -d '{"field_name":"b","semantic_type":"BOOLEAN","value":"maybe","error_policy":"RETURN_ORIGINAL"}'
# Expect: original_kind == "UNKNOWN_VALUE", display == null
# (stop the server afterward)

# 4. Full integration suite (needs Docker)
docker compose up -d demo-postgres demo-mysql demo-mongo demo-clickhouse libpostal
uv run pytest -m integration -v
docker compose down -v demo-postgres demo-mysql demo-mongo demo-clickhouse libpostal
```

## 5. Acceptance criteria mapped (subset of §136 relevant to M5)

| §136 criterion | Status at M5 |
|---|---|
| 1. Raw values are preserved | ✅ `original` never overwritten by any of the six new normalizers |
| 3. Every transformation is traceable | ✅ Full trace including domain-specific steps for all six |
| §49 leading zeros never removed | ✅ Verified, including Unicode-digit inputs |
| §55 identifiers never cast to numeric | ✅ Verified — comparison/search stay string-typed |
| §111 separator ambiguity flagged, not silently collapsed | ✅ Verified — AB-001/AB001 stay distinct comparison groups |
| §50 UUID canonical form | ✅ Verified against §50's own worked example |
| §46 comma never assumed to mean thousands without context | ✅ Verified across 8 real locale conventions |
| §47 bare `$` stays ambiguous | ✅ Verified |
| §48 unit conversion dimensionally sound, mismatch rejected | ✅ Verified directly against real Pint behavior |
| §52 boolean coercion never guesses on uncertain values | ✅ Verified — "maybe"/"unknown"/"N/A" all stay UNKNOWN, never coerced |
| (Remaining criteria are later-milestone scope) | — |

## Human Sign-off

milestone: M5
verdict:
reviewer:
date:
env_id:
commit:
conditions: []
notes: |

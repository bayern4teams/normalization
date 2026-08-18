# Milestone M4 Verification Pack — Address, Date/Time, Country/Language/Script

Status: **All Layer 1/2 checks complete and passing. Ready for your Layer 3 review and sign-off.**

Covers Phases 8-10 of `Source.txt` §127 (§29-§32 addresses, §43-§45
dates, §33-§35 country/language/script, §76's ambiguity-preservation,
§109's synthetic-corpus requirement). Five new normalizers land in this
milestone, including the first real use of the M0 libpostal Docker
sidecar.

## 1. Scope recap

| Deliverable | Status |
|---|---|
| `AddressNormalizer` — libpostal sidecar client, circuit breaker, per-country postal-code validation | ✅ Done |
| `DateNormalizer` — ISO fast path, conservative ambiguous-date refusal, context-aware resolution | ✅ Done |
| `CountryNormalizer` — pycountry-based, UK/Great Britain alias flagging | ✅ Done |
| `LanguageNormalizer` — ISO 639 canonicalization | ✅ Done |
| `ScriptNormalizer` — ICU script detection + lingua-py language hint, never transliterates | ✅ Done |
| `normalizers.country_codes` — shared country-code resolver (`AddressNormalizer` + `CountryNormalizer`) | ✅ Done |
| All five wired into the live `normapi` Dispatcher | ✅ Done |
| M4 golden corpus (§109 addresses, ambiguous dates, GB/UK, postal codes across 15 countries) | ✅ Done |
| Performance baseline recorded (`docs/verification/bench-baseline-m4.json`) | ✅ Done |
| Gate G4 verification | ✅ Done |

## 2. Layer 1 — Automated verification results

```
uv run ruff check .          -> All checks passed! (130 files)
uv run ruff format --check . -> 130 files already formatted
uv run mypy packages         -> Success: no issues found in 57 source files
```

### 2.1 Full test suite (unit + golden + property, excluding integration/bench)

```
uv run pytest -m "unit or golden or property" -v
```

```
499 passed, 12 skipped, 21 deselected in 55.06s
```

New in M4: 20 `AddressNormalizer` unit tests, 16 `DateNormalizer` unit
tests, 25 `CountryNormalizer`/`LanguageNormalizer`/`ScriptNormalizer`
unit tests, 24 M4 golden-corpus tests. M2/M3's suites are unchanged and
still fully passing.

### 2.2 Integration tests (against live Docker containers)

```
uv run pytest -m integration -v
```

```
11 passed in 26.63s
```

5 unchanged from M1 (DB connectors + 1M-row replay) + 6 new
`AddressNormalizer` tests against the REAL libpostal sidecar, including
its failure path (a deliberately unreachable endpoint).

## 3. Layer 2 — Liveness verification

| Check | Result |
|---|---|
| Real running `uvicorn` process serving all five new normalizers through `POST /normalization/field-test` | ✅ Verified — sent §109's Baker St. address, an ambiguous date, and "UK" as a country; got back correctly-parsed, fully-traced responses for each |
| §109's UK address (`10-12 Baker St., London, W1U 3BW, UK`) parses with house-number range intact and postcode validated | ✅ Verified against the live sidecar |
| §109's US address (`1600 Pennsylvania Avenue NW, Washington, DC 20500, USA`) parses correctly, postcode validated | ✅ Verified against the live sidecar |
| libpostal sidecar failure path (unreachable endpoint) | ✅ Verified — `PARSER_FALLBACK` + `ADDRESS_PARSE_PARTIAL`, no crash |
| Postal-code validation correct across 15 real countries (GB, US, CA, FR, DE, JP, AU, NL, IT, ES, SE, CH, BR, IN, SG) plus a deliberately-invalid case | ✅ Verified — exceeds §136's "≥ 15 countries" bar |
| 4 live database containers — M1's read-only guarantees re-verified after M4's changes | ✅ Verified, unchanged |
| 1,000,000-row byte-identical replay — re-verified after M4 | ✅ Verified, unchanged |
| Performance baseline captured for the four standalone normalizers | ✅ Verified — `docs/verification/bench-baseline-m4.json` |

## 4. Layer 3 — for human review

### 4.1 Real bugs found and fixed during M4 (not hypothetical)

1. **`AddressNormalizer`'s `comparison` field had the `(value, label)`
   tuple unpacking backwards** — a genuine, embarrassingly simple bug
   that produced `comparison = "house_number road city postcode
   country"` (the LABEL names) instead of the actual address text.
   Caught immediately by manually inspecting real output against the
   live libpostal sidecar before writing the automated test suite, not
   by the test suite itself — a reminder that "the code runs without
   error" is not the same as "the code is correct," and is exactly why
   this project's process requires eyeballing real output before
   trusting a new component.
2. **libpostal's `country` component is free text (e.g. "uk", "usa"),
   not an ISO 3166-1 alpha-2 code**, which `google-i18n-address`'s
   postal-code validator requires — postcode validation silently never
   fired for any real address until a resolution step
   (`normalizers.country_codes.resolve_country_alpha2`) was added.
3. **`google-i18n-address`'s postal-code regex patterns are uppercase**
   (matching `ValidationRules.upper_fields`), but libpostal lowercases
   every component it parses — every real postcode failed validation
   regardless of correctness until the postcode was uppercased before
   matching. Both bugs #2 and #3 were caught the same way: running real
   §109 addresses (`10-12 Baker St....`, `1600 Pennsylvania Avenue...`)
   against the live sidecar and finding `postcode_valid: False` for
   addresses that are obviously valid, then tracing why.
4. **`pycountry.languages.lookup("en")` does not return English** — it
   returns an unrelated language whose `name` field happens to also be
   the string "En" (alpha_3 "enc"), because `lookup()` appears to check
   name-equality before (or instead of) an exact alpha_2 code match for
   short inputs. Fixed by trying `pycountry.languages.get(alpha_2=...)`/
   `get(alpha_3=...)` explicitly first, falling back to `lookup()` only
   for full names. Caught by a direct smoke test printing real pycountry
   output before writing the automated suite — the same "verify against
   real library behavior, don't assume" discipline that caught M3's
   `cleanco` bug.
5. **"Great Britain" (one of §33's own three named UK-alias examples)
   does not resolve via `pycountry.countries.lookup()`** at all (raises
   `LookupError`) — only "UK" was in the original alias table. Added
   alongside "UK" once found.
6. **Dotted country abbreviations ("U.S.", "U.S.A.") fail
   `pycountry.countries.lookup()`** even though the undotted forms
   ("US", "USA") resolve fine — added a single dot-stripping retry to
   `resolve_country_alpha2`.

Six real bugs across five files, every one found by running the actual
code against real inputs (the live libpostal container, or direct
library calls) before trusting the automated test suite to catch them —
consistent with the pattern established across all four milestones so
far.

### 4.2 Design decisions worth your attention

- **Address region precedence for postal-code validation is entirely
  derived from libpostal's own parsed `country` component** (with
  `ctx.country` as a fallback only when libpostal found no country at
  all) — there is no separate "which country context wins" precedence
  chain like `PhoneNormalizer`'s, because the address text itself is the
  authoritative source for its own country in a way a bare phone number
  string is not.
- **Non-Gregorian calendar support (Jalali, Hijri) is NOT implemented**
  as confident conversion. `dateparser`'s calendar-conversion behavior
  could not be reliably verified against this environment's installed
  version during manual probing (a Jalali-formatted numeric string was
  parsed as if it were already Gregorian, with no conversion applied at
  all) — rather than ship unverified logic, this is an honest, disclosed
  gap. `DateNormalizer` handles ISO dates, unambiguous dates, and
  context-resolved ambiguous D/M/Y dates correctly and confidently; any
  non-Gregorian input outside those categories either fails to parse
  (`INVALID`) or is parsed by `dateparser`'s generic path without any
  calendar-aware guarantee.
- **`ScriptNormalizer`'s `lingua-py` language-hint detection is slow**
  (~5ms/call in the recorded benchmark, vs. <100µs for the other three
  M4 normalizers) because it scores against every supported language on
  every call. A faster, narrower language subset (or skipping the hint
  entirely for fields where it's not needed) is a reasonable follow-up,
  deferred to M8's performance milestone alongside M3's disclosed
  whole-pipeline fixed-point cost.
- **Phone region precedence (from M3) still only implements 2 of 4
  levels** — unchanged, still tracked.

### 4.3 Known open items carried into M5

1. Identifiers, numeric, currency, and unit normalizers do not exist yet
   — M5 begins Phases 11-12.
2. Non-Gregorian calendar conversion is unimplemented (see §4.2).
3. `ScriptNormalizer`'s language-hint latency is unoptimized (see §4.2).
4. The M3-disclosed whole-pipeline fixed-point performance cost remains
   unresolved, tracked for M8.
5. Per-field profile-driven configuration is still not wired into
   individual normalizers (carried over from M2/M3).
6. `env_id` computation is still the M1 placeholder.

### 4.4 10-minute scripted demo (for you to run yourself)

```bash
cd D:/transfer/normalization

# 1. Full lint/type/test sweep
uv run ruff check . && uv run ruff format --check .
uv run mypy packages
uv run pytest -m "unit or golden or property" -q

# 2. Real address parsing + postal-code validation (needs Docker)
docker compose up -d libpostal
uv run pytest tests/integration/test_address_normalizer_integration.py -v
uv run pytest tests/golden/test_m4_corpus.py -v

# 3. Live API server exercising all five new normalizers
uv run uvicorn normapi.main:app --host 127.0.0.1 --port 8080 &
curl -sf -X POST http://127.0.0.1:8080/normalization/field-test \
  -H "Content-Type: application/json" \
  -d '{"field_name":"address","semantic_type":"ADDRESS","value":"10-12 Baker St., London, W1U 3BW, UK","error_policy":"RETURN_ORIGINAL"}'
# Expect: house_number == "10-12", postcode_valid == true
curl -sf -X POST http://127.0.0.1:8080/normalization/field-test \
  -H "Content-Type: application/json" \
  -d '{"field_name":"d","semantic_type":"DATE","value":"03/04/2024","error_policy":"RETURN_ORIGINAL"}'
# Expect: normalization_status == "AMBIGUOUS"
# (stop the server afterward)

# 4. Full integration suite (needs Docker)
docker compose up -d demo-postgres demo-mysql demo-mongo demo-clickhouse libpostal
uv run pytest -m integration -v
docker compose down -v demo-postgres demo-mysql demo-mongo demo-clickhouse libpostal
```

## 5. Acceptance criteria mapped (subset of §136 relevant to M4)

| §136 criterion | Status at M4 |
|---|---|
| 1. Raw values are preserved | ✅ `original` never overwritten by any of the five new normalizers |
| 3. Every transformation is traceable | ✅ Full trace including domain-specific steps (`address.libpostal_parse`, `date.parse`, `country.resolve`, `language.resolve`, `script.detect`) |
| §30 display/comparison never collapse to one lossy string | ✅ Verified — `display` keeps the full address, `comparison` built separately |
| §32 postal codes validated per-country, no universal regex | ✅ Verified across 15 real countries |
| §43 ambiguous dates never silently resolve | ✅ Verified — §43's own "03/04/2024" example, plus 3 more shapes |
| §33 GB/UK/Great Britain ambiguity surfaced, not resolved | ✅ Verified — flagged with lower confidence, not silently erased |
| §35 script detection never triggers transliteration | ✅ Verified — display unchanged regardless of detected script |
| §68 one failing dependency never crashes the run | ✅ Verified — libpostal sidecar failure path proven against a real unreachable endpoint |
| (Remaining criteria are M5+ scope) | — |

## Human Sign-off

milestone: M4
verdict:
reviewer:
date:
env_id:
commit:
conditions: []
notes: |

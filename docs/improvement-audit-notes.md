# Improvement audit — working notes (graph-verified, 2026-09-30)

Scratch notes taken while auditing the engine with graphify / graft /
codebase-memory before the research resource sweep. Every claim here was
verified by reading the named file, not from an index alone.

## What exists today (verified)

- 8 workspace packages: `normcore` (contract, dispatch, rules, trace, pii,
  multivalue, unicode_policy), `normalizers` (20 registered adapters),
  `normdict`, `normexec` (planner + 2-tier cache + env fingerprint),
  `normio` (PG/CH read + destination connectors), `normanalysis`
  (profiling, impact, collisions, quality, ab_comparison, type_detection,
  invariant_sampler, handoff), `normapi` (44 routes), `normcli`.
- `NormalizedValue` carries 7 views (original/repaired/display/comparison/
  search/ascii/structured) + status + confidence + flags + trace +
  lossiness + profile_version + env_id + semantic_type + context_hash.
- 25 `FieldSemanticType`s; 20 normalizers registered in
  `normapi/app.py:build_normalizer_registry`.
- 74 test files across unit/golden/property/contract/integration/bench.
- 15 `ponytail:` debt markers in `packages/`.

## Semantic types with NO real normalizer (fall through to Passthrough)

Registry covers: ADDRESS, BOOLEAN, COMPANY_NAME, COUNTRY, CURRENCY, DATE,
DATETIME, EMAIL, FREE_TEXT, IDENTIFIER, TAX_ID, CODE, UUID, LANGUAGE,
MONEY, PERSON_NAME/GIVEN_NAME/FAMILY_NAME, NUMERIC, PHONE, POSTCODE,
SCRIPT, QUANTITY, URL.

Gap: `UNKNOWN` is the only type with no adapter — correct by design.
No missing type. The gap is depth, not coverage.

## Depth gaps found by reading the normalizers

1. `TAX_ID` and `CODE` are handled by the *same* `IdentifierNormalizer`
   with a curated `_STDNUM_REGISTRY` subset — python-stdnum has far more.
2. `name.py` has no Double Metaphone / Beider-Morse (jellyfish omits
   both); no nickname dictionary (deliberate, §24).
3. `company.py` does not consume GLEIF ISO 20275 ELF codes at runtime
   (script exists: `scripts/generate_legal_entity_suffixes.py`).
4. `url.py` uses stdlib urlsplit + idna — no Public Suffix List
   (`tldextract`), no WHATWG canonicalization (`urlcanon`), no registrable
   domain in `structured`.
5. `phone.py` stores E.164; no RFC 3966 `tel:` URI, so extensions cannot
   round-trip in a single string.
6. `country_codes.py` uses CLDR territoryAlias + pycountry but not
   `pycountry.historic_countries` (SU/YU/ZR withdrawal dates).
7. No cross-field / multi-pass normalization: each value is normalized
   independently; `NormalizationContext` carries country/locale but there
   is no record-level pass that reconciles conflicting fields.
8. No review queue: `NEEDS_REVIEW` exists in the enum (3 refs) but nothing
   consumes it — an AMBIGUOUS value has no human-in-the-loop path.
9. No confidence calibration: `confidence` is a float set per normalizer
   by hand, never calibrated against labelled outcomes.
10. `type_detection.py` is keyword table + validator sniffing — no
    ptype-style disguised-missing-data model, no learned classifier.
11. Provenance stops at the process: `trace` is per-value, but there is no
    OpenLineage/PROV export at the job boundary.
12. Destination columns collapse to TEXT/String (`postgres_destination.py`
    line 38, `clickhouse_destination.py` line 30) — typed columns exist
    for money only.

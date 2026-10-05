# P0-B acceptance basis: D10, D11, D5, D4 (derive mode, current code, branch feat/defects-fixes)

Files: `tests/defects/fixtures_phase23.py` (constants/builders, no tests), `tests/defects/measure_phase23_before.py`
(run: `uv run python tests/defects/measure_phase23_before.py`, rc 0, ~90 lines). Both ruff-clean. Truth sources are
named in the fixture docstring: libphonenumber example numbers, ICU BGN/PCGN schemes (`iuliia` is NOT installed),
pycountry/ISO 3166, and `storage_types` itself for the typed set and numeric ceilings. D6/D2: nothing (phase 3).

## Fixture groups
- **D10** 10 regions x {`x45`, `ext. 45`, `;ext=45`, `#45`} + base + `x46` + national-with-ext + libphonenumber RFC 3966 string.
  Never-guess: `020 7946 0000 x45` with no region -> AMBIGUOUS; `+999 123 4567 x45` -> INVALID.
- **D11** 5 same-name groups (muhammad, yuri, alexander, hossein, elena; 31 human-asserted pairs, 54 incl. ICU-generated),
  10 different-name pairs, 6 CJK/Hangul names, 5 other-script names, 4 Latin-diacritic names (no expectation planted), 7 plain
  Latin names with `LATIN_OLD_KEYS` (byte-identity snapshot of today's four keys).
- **D5** 17 adversarial strings (the nine in the plan plus sNaN, Infinity, `1e1000000`, `1e-1000000`, -10**40, tab/newline,
  `1_000`, Arabic-Indic digits) x typed types read from `storage_types.is_typed` (NUMERIC, MONEY, BOOLEAN) x both engines.
  `engine_accepts(sql_type, value)` is an integer-digit overflow oracle derived from the DDL string. Partial dates for the
  keep-TEXT decision.
- **D4** four planted columns: 10,000 rows 97% dates + `N/A` 150, `unknown` 100, `-` 50 (exact); 2,040-row COUNTRY column with
  `NA` x40 (Namibia, must not be reported); no-sentinel dates; 30 distinct junk strings each once (must not be reported:
  they do not recur). `MAGIC_NUMBER_COLUMN` (-999) is marked ceiling-only (ptype territory), not a requirement.

## BEFORE numbers (current code)
- **D10:** all 4 spellings share one `comparison` in 10/10 regions (already passes, trivially, because the extension is dropped).
  Defect: base number == base+x45 == base+x46 in `comparison` in 10/10 regions. Extension is parsed into `structured["extension"]`
  40/40; `structured["rfc3966"]` 0/40; `search` already extension-free 10/10; re-normalizing `comparison` stable 10/10.
  No-region+ext AMBIGUOUS and invalid+ext INVALID already hold.
- **D11:** Soundex baseline: 22 of 31 human pairs share Soundex; **any of the four old keys: 25 of 31**. Cross-script pairs only:
  Soundex 10/18, any key 13/18. Pairs with no shared key today: Мухаммед vs Muhammad/Mohammed/Mohammad/محمد, Елена vs Yelena.
  Different-name pairs colliding: 0/10 (Soundex and any key). Non-Latin inputs carrying all four keys: 17/17 (incl. CJK 6/6);
  `phonetic_status=not_applicable` today: 0/17.
- **D5:** no raise anywhere. Both engines: `d1989-12-11`, NaN, `1,234`, `\x00`, `yes please` -> (None, error); empty/whitespace -> NULL
  with no error. **Overflow reaches the INSERT today (modelled, not live):** end-to-end via `_apply_value`, NUMERIC: 4 values fit
  no ClickHouse Decimal(38,9) (`1e999`, `1e1000000`, +-10**40) and `1e1000000` exceeds Postgres unbounded NUMERIC; MONEY: +-10**40
  fits neither NUMERIC(38,4) nor Decimal(38,4). `coerce` checks finiteness, not precision. DATE/DATETIME stay TEXT and keep all
  four partial dates unchanged. 22/22 untyped types pass `\x00` through to a TEXT column (Postgres rejects NUL; outside D5's
  typed scope, noted).
- **D4:** `normanalysis/disguised_missing.py` absent. Cell level is NOT "nothing today": `Dispatcher` already maps `N/A`, `-`
  (NOT_APPLICABLE) and `unknown` (UNKNOWN_VALUE) per cell from the hand-written `missing-values.common` dictionary, for every type,
  with no per-column counts. Only `unknown` yields an error row. **Defect confirmed: `NA` in a COUNTRY column is classified
  NOT_APPLICABLE, 40/40 Namibia rows.** Column-level `suggest_semantic_type` gives DATE 0.97 / COUNTRY 0.95 for every planted
  column (including the noise column).

## Report examples already passing, and criteria that are weak
- D10 "four spellings give one `comparison`" passes on main trivially (extension dropped). The meaningful test is base != ext and
  x45 != x46 (fails today 10/10).
- D5 report cases `d1989-12-11`, NaN, `1,234` already pass and are already in `test_typed_destinations.py`; only the overflow
  strings are new.
- **D11 criterion is vacuous as written:** "share a key in more pairs than the Soundex baseline" (22) is already beaten by the OLD
  keys (25). Recommend baseline = any old key (25/31) and the cross-script count (13/18), with the five named pairs above as
  must-fix. Also unspecified in the plan: Latin names with diacritics (Müller) go through anyascii too; `LATIN_DIACRITIC_NAMES`
  carries no expectation, the lead must decide.
- D4: the plan says `NA` must not be reported; today it is silently converted to missing at cell level by the dictionary. A
  detector that only reports will not fix that; the dictionary entry `na` is the cause.

## Could not do / unverified
- No live Postgres or ClickHouse: overflow behaviour is a model (integer digits from the DDL string); ClickHouse may reject at
  the client before the insert. Marked unverified-live.
- `iuliia` not installed; ICU BGN/PCGN used. Arabic BGN output is consonant-only, so generated Arabic pairs are informational.
- Pair "truth" (Мухаммед = Muhammad) is a human assertion, not a dataset; there is no authoritative name-equivalence list.
- `libpostal` not needed here; nothing else was skipped.

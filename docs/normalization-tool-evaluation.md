# Normalization Tool Evaluation

Status: living document, updated at every milestone gate. Last updated: M0 (2026-08-17).

This document satisfies `Source.txt` §6 (tool evaluation document + matrix)
and §132 (final tool evaluation report). Per §137 and §130, no library's
capabilities are taken on the spec's word alone — each entry below reflects
direct research against the library's own repository, documentation, and
(where feasible) source, performed during Milestone 0. Sources are cited
inline; full citations are in the "Sources" section of the implementation
plan and are re-linked here where directly relevant.

Decision records for each domain live in `docs/adr/`; this document is the
supporting evidence and comparison detail behind those decisions.

---

## 1. Capability matrix

| Capability | Preferred tool | Secondary / fallback | Why | Limitations | Custom logic required |
|---|---|---|---|---|---|
| Unicode normalization, case mapping, transforms, script detection, confusables | **PyICU** (pinned ICU 78 / Unicode 17 / CLDR 48) | stdlib `unicodedata` + `regex` | Full UTS #15 (normalization forms), UTS #39 (confusables via `SpoofChecker`), locale-aware case mapping (Turkish İ/ı), script property queries — stdlib covers none of the locale-aware or confusable pieces | Requires prebuilt wheels per platform; no bundled-ICU alternative yet covers our needs (see ADR-001) | Thin policy wrapper choosing NFC/NFD/NFKC/NFKD per semantic type; own `SpoofChecker` config |
| Encoding detection | **charset-normalizer** | — | Actively maintained `chardet` successor, confidence-scored, MIT | Not infallible on very short strings | Decode-stage integration only |
| Mojibake repair | **ftfy** (`fix_and_explain`) | — | Documented zero-false-positive design goal; explains exactly what it fixed | Heuristic — cannot repair information genuinely lost at the byte level | Evidence-gating wrapper (only accept when a fix was actually applied) |
| ASCII transliteration | **anyascii** | ICU `Any-Latin; Latin-ASCII` transform | ISC license (Unidecode is GPL — rejected, ADR-015); 2x+ character coverage vs Unidecode, includes non-BMP | Inherently lossy; never a substitute for Unicode representation | None — used as-is, output always marked LOSSY |
| Confusables / look-alikes | **ICU SpoofChecker** (UTS #39) | — | Standards-based skeleton algorithm; single/mixed/whole-script checks | Detection only — no library "fixes" confusables safely | Policy: emit diagnostics only, never auto-substitute (§17) |
| Person names | **nameparser 2.0** | `probablepeople` (offline calibration only) | Deterministic, rule-based, composable Lexicon/Policy, immutable results | Western/romanized names only; no native non-Latin-script name-order logic | Deterministic wrapper + our own honorific/suffix dictionaries |
| Phonetic name variants | **jellyfish** | — | MIT; covers Soundex/NYSIIS/Metaphone/Match Rating (exactly §25's list) | No Beider-Morse (multilingual) — `abydos`'s port is GPL-3, rejected | None |
| Company names | **GLEIF ISO 20275 ELF list** | `cleanco` 2.3 | Externally governed, versioned, 3,400+ forms / 185+ jurisdictions | Requires our own conservative-stripping policy layer | Conservative stripping policy; jurisdiction-hint (never fact) logic |
| Addresses (parsing) | **libpostal** (Docker sidecar) | `deepparse` (offline calibration only) | MIT, 10-30k addr/sec, statistical NLP trained on real geodata, official Python binding | 1.8-2.2GB resident memory; no native Windows build (MSys2/MinGW needed) | Sidecar wrapper, circuit breaker, expansion-candidate policy |
| Addresses (validation/format) | **google-i18n-address** (libaddressinput metadata) | — | Per-country `postal_code_regexp`, required fields, canonical field order — same data powering Chromium/Android | Metadata only, not a parser | Combine with libpostal output |
| Postal codes | **google-i18n-address** | — | Country-aware regex per §32's explicit requirement | Regex coverage varies by country data completeness | None beyond lookup |
| Phones | **python-phonenumbers** | — | Canonical `libphonenumber` port, Apache-2.0, pure Python | None material for our use case | Region-precedence resolution wrapper (§37) |
| Email | **email-validator** | — | Unlicense/CC0; NFC + IDNA/UTS-46 domain normalization | `check_deliverability` defaults True — must be explicitly disabled | Dual pre/post-normalization validation wrapper; provider-policy gate (off by default) |
| Dates | **dateparser** (strict settings) + **ciso8601** fast path | `python-dateutil` | Only library with genuine 200+-locale multilingual date parsing; actively maintained (v1.4.2, Aug 2026) | Permissive defaults must be tightened; historically dependent on volunteer maintenance | Strict-settings wrapper, ambiguity-preserving policy, calendar-conversion trace |
| Country / language codes | **pycountry** | — | ISO 3166/639/4217/15924 canonical reference | LGPL-2.1 — unmodified dynamic use only | GB/UK/Great-Britain disambiguation logic |
| Locale-aware numeric/currency parsing | **Babel** (CLDR) | — | Only CLDR-backed option for separator conventions + currency-symbol ambiguity tables | Not a full ICU replacement | Ambiguity-preserving numeric/currency wrapper |
| Identifiers, check digits | **python-stdnum** | — | Hundreds of country ID/VAT/IBAN modules, full ISO/IEC 7064 check-digit family | LGPL-2.1 — unmodified dynamic use only | Dispatch layer + domain-specific hooks + collision-flagging policy |
| Units | **Pint** | — | Mature dimensional-analysis library, BSD | None material | Dimension-safety wrapper (reject cross-dimension conversion) |
| Fuzzy matching utility (analysis only) | **RapidFuzz** | — | MIT, fast; used only for offline collision/impact analysis, never core normalization | Must not become a de facto record-linkage engine (§5's explicit warning) | Strict boundary: analysis modules only, never imported by `normalizers` package |
| Language hinting | **lingua-py** | `py3langid` | Strongest short-text accuracy (our field values are typically short) | Slower per-call than fastText at very high volume — acceptable given distinct-value-first batching | Diagnostic-only wrapper; never triggers transliteration |
| Batch execution engine | **Polars + DuckDB + Arrow** | — | Single-node, no cluster ops, Arrow-native dictionary encoding | Bounded by single-node resources | Distinct-value-first planner (ADR-016) |
| Hashing | **blake3** | `xxhash` (non-security paths) | Fast, secure, used for `env_id` and cache keys | — | None |
| OpenRefine-style keys | Custom implementation of `fingerprint`/`ngram-fingerprint` per OpenRefine's published spec | — | OpenRefine itself is a UI/reconciliation tool, not embedded; only its documented algorithm is reimplemented | Reimplementation must be tested against OpenRefine's own published examples | Full implementation (small, well-specified) |

---

## 2. Rejected candidates

| Library | Reason for rejection | ADR |
|---|---|---|
| **Unidecode** | GPL-2.0-or-later; copyleft risk on a cosmetic transliteration feature. Superseded by `anyascii` (ISC). | ADR-015 |
| **wordfreq** | Formally sunset by its author (Sept 2024) — generative-AI-polluted training corpora; no longer a reliable source of current language-frequency data. | ADR-015 |
| **abydos** | GPL-3 (via its Beider-Morse port, itself ported from a GPL-3 PHP reference). `jellyfish` covers the non-GPL subset of §25's phonetic algorithm list. | ADR-003, ADR-015 |
| **OpenRefine (embedded)** | A full Java desktop application, not a library — used only as the published-algorithm reference for `fingerprint`/`ngram-fingerprint`, never embedded or run as a service. | — |
| **`deepparse` (runtime)** | Neural/trained-model dependency with a weaker production track record than libpostal for our purposes; used only for offline confidence calibration, never in the deterministic runtime path (§72, §129). | ADR-005 |
| **`probablepeople` (runtime)** | Same reasoning as `deepparse` — CRF probabilistic model retained for offline calibration only. | ADR-003 |
| **`icu4py`** | Too early-stage (Feb 2026 release) — no normalization/collation/transliteration/SpoofChecker coverage yet. Tracked as a watch item, re-evaluated at M8. | ADR-001 |

---

## 3. Final tool evaluation report (§132 format)

Each selected library answers: why this library, exact capability used, what
is deliberately NOT used, limitations, edge-case behavior, determinism,
multilingual support, versioning, license, performance profile, failure
mode, and fallback.

### PyICU

- **Why**: only mature Python binding to ICU4C with normalization,
  locale-aware case mapping, and `SpoofChecker` in one package.
- **Use**: NFC/NFD/NFKC/NFKD normalization, `Transliterator` (for optional
  ICU-based transliteration), `BreakIterator` (grapheme/word boundaries),
  `SpoofChecker` (confusables), `Locale`-aware case mapping.
- **Do not use**: ICU collation (not needed — comparison uses our own
  comparison-value contract, not locale sort order); ICU message
  formatting (no i18n UI strings in the engine itself).
- **Limitations**: wheel availability is platform-dependent; system ICU
  version skew if not using pinned wheels.
- **Edge cases**: NFKC on identifiers can silently change meaning
  (superscripts, ligatures) — mitigated by never applying NFKC to
  identifier-typed fields by default (ADR-001).
- **Determinism**: fully deterministic given a pinned ICU version.
- **Multilingual**: yes — this is ICU's core purpose.
- **Versioning**: ICU version pinned; captured in `env_id`.
- **License**: ICU License (permissive, MIT-like).
- **Performance**: native C++ under the hood via bindings; fast.
- **Failure mode**: import/wheel failure at startup (fail-fast, not
  per-value).
- **Fallback**: stdlib `unicodedata` for basic NFC/NFD only, no
  locale-aware case mapping or SpoofChecker — used only in constrained
  environments where PyICU cannot be installed, with a recorded
  capability-degradation warning.

### ftfy

- **Why**: mandated by §4.2; documented zero-false-positive design goal.
- **Use**: `fix_and_explain()` for evidence-gated mojibake repair.
- **Do not use**: `ftfy.fix_text()` blind mode (no explanation) — we
  always use the explaining variant so every repair is traceable.
- **Limitations**: heuristic-based; cannot recover genuinely destroyed
  byte-level information.
- **Edge cases**: uppercase-word mojibake (e.g. "ZURÜCK"), improbable
  punctuation sequences — both explicitly handled per the 6.3 changelog.
- **Determinism**: deterministic given a pinned version.
- **Multilingual**: yes, by design (mojibake patterns are
  encoding-specific, not language-specific).
- **Versioning**: pinned; heuristic changes across versions participate
  in `env_id`.
- **License**: Apache-2.0.
- **Performance**: pure Python, fast enough for the distinct-value-first
  execution model.
- **Failure mode**: exception on genuinely malformed input is caught and
  routed through the standard error-policy machinery (§68/§69), never
  crashes the run.
- **Fallback**: none — repair is skipped (value passes through unchanged,
  `UNCHANGED` status) if `ftfy` is unavailable; never silently substituted
  with a weaker heuristic.

### libpostal (sidecar)

- **Why**: mandated by §4.3; the strongest open-source international
  address parser with real production track record.
- **Use**: `/parse` (component extraction), `/expand` (expansion
  candidates) via the sidecar's batch endpoints.
- **Do not use**: libpostal's own "duplicate detection" adjacent features
  if any — out of scope, that is entity-resolution territory (§112).
- **Limitations**: 1.8-2.2GB resident memory; no native Windows build.
- **Edge cases**: incomplete/malformed addresses produce partial parses
  (`ADDRESS_PARSE_PARTIAL`), never a fabricated complete address.
- **Determinism**: deterministic given a pinned model + git ref.
- **Multilingual**: yes — trained on global open geodata.
- **Versioning**: git ref pinned in the sidecar Dockerfile
  (`LIBPOSTAL_COMMIT`); model data SHA-256 computed at image build and
  queryable at runtime; both feed `env_id`.
- **License**: MIT.
- **Performance**: 10-30k addresses/sec/thread server-side; network hop
  cost amortized by distinct-value-first batching.
- **Failure mode**: sidecar unreachable → circuit breaker →
  `PARSER_FALLBACK` flag, structured-passthrough with original preserved,
  never a pipeline crash.
- **Fallback**: `google-i18n-address` validation/formatting metadata
  remains available even if the parser sidecar is down, providing partial
  value (postal code format checking) without full parsing.

### python-phonenumbers

- **Why**: mandated by §4.4; canonical `libphonenumber` port.
- **Use**: `parse`, `is_valid_number`, `is_possible_number`,
  `format_number` (E164/INTERNATIONAL/NATIONAL), region metadata.
- **Do not use**: carrier/geocoder/timezone submodules (not adopted by
  default — optional, evaluated only if a demonstrated need arises).
- **Limitations**: none material for our scope.
- **Edge cases**: ambiguous national-format numbers without resolvable
  region → `AMBIGUOUS`, never guessed.
- **Determinism**: fully deterministic given pinned metadata version.
- **Multilingual**: N/A (numbers, not text) — but covers every
  ITU-assigned country code.
- **Versioning**: package version (bundles metadata) pinned; feeds
  `env_id`.
- **License**: Apache-2.0.
- **Performance**: pure Python, fast; no native build step at all.
- **Failure mode**: parse exceptions caught, routed to error policy,
  never crash the run.
- **Fallback**: none needed — no viable alternative was found that
  matches `libphonenumber` semantics, per §36's explicit mandate.

### email-validator

- **Why**: mandated by §4.5; the most complete deterministic Python email
  syntax/normalization library.
- **Use**: `validate_email()` with `check_deliverability=False`, local
  part / domain / IDNA outputs.
- **Do not use**: deliverability checking (network calls) — explicitly
  disabled in the core path per ADR-007.
- **Limitations**: normalization can shift validity (documented by the
  library itself) — handled by dual pre/post-normalization validation.
- **Edge cases**: internationalized domains/local parts (SMTPUTF8) —
  fully supported and flagged via `smtputf8`.
- **Determinism**: fully deterministic with `check_deliverability=False`.
- **Multilingual**: yes — IDNA/UTS-46 and SMTPUTF8 support.
- **Versioning**: pinned; IDNA mapping table updates participate in
  `env_id`.
- **License**: Unlicense/CC0 (effectively public domain).
- **Performance**: pure Python, fast.
- **Failure mode**: `EmailNotValidError` caught, routed to
  `INVALID_SYNTAX` status, never crashes the run.
- **Fallback**: none needed.

### dateparser + ciso8601

- **Why**: `dateparser` mandated by §4.6 for multilingual coverage;
  `ciso8601` added as a fast path for the common already-ISO case
  (performance optimization not named in the spec but consistent with
  §102).
- **Use**: `dateparser.parse()` with strict settings and explicit
  `DATE_ORDER`; `ciso8601.parse_datetime()` for pre-validated ISO strings.
- **Do not use**: `dateparser`'s permissive defaults (auto-guessing date
  order without locale context) — explicitly overridden.
- **Limitations**: `dateparser` has historically depended on a small
  volunteer maintainer base — tracked as an operational risk, not a
  blocker (current status: actively released, v1.4.2 Aug 2026).
- **Edge cases**: `"01/02/03"`-shaped ambiguity → `AMBIGUOUS` status,
  never resolved silently.
- **Determinism**: deterministic given pinned versions and fixed settings
  (no relative-date parsing against wall-clock "now" in the core
  pipeline, since that would violate determinism — relative-date support
  is a documented non-goal for the deterministic path).
- **Multilingual**: yes, 200+ locales.
- **Versioning**: both pinned; feed `env_id`.
- **License**: BSD (dateparser), MIT (ciso8601).
- **Performance**: `ciso8601` fast path avoids `dateparser`'s heavier
  parsing for the common well-formed case.
- **Failure mode**: parse failure → `PARSING_FAILED` status via the
  standard error policy.
- **Fallback**: `python-dateutil` for basic ISO-adjacent parsing if
  `dateparser` is unavailable — English-only, documented capability
  degradation.

### pycountry + Babel

- **Why**: `pycountry` is the standard ISO code reference; Babel/CLDR
  fills the locale-aware parsing/display gap `Source.txt` does not name
  any library for.
- **Use**: `pycountry` for 3166/639/4217/15924 lookups; Babel for
  decimal/grouping separator conventions, currency symbol ambiguity
  tables, localized display names.
- **Do not use**: Babel's full i18n message-catalog/gettext features —
  not relevant to this engine.
- **Limitations**: `pycountry`'s LGPL-2.1 license restricts it to
  unmodified, dynamically-imported use (ADR-015).
- **Edge cases**: GB/UK/Great-Britain — handled by explicit
  disambiguation logic (ADR-010), not treated as pure lookup.
- **Determinism**: fully deterministic given pinned versions/data.
- **Multilingual**: yes (CLDR covers all major locales).
- **Versioning**: both pinned; CLDR data version feeds `env_id`.
- **License**: LGPL-2.1 (pycountry, unmodified-dynamic-only), BSD
  (Babel).
- **Performance**: lookup-table-driven, fast.
- **Failure mode**: unrecognized country/language/currency string →
  `UNKNOWN_SEMANTIC_TYPE`/low-confidence result, never a fabricated code.
- **Fallback**: none needed for code lookups; numeric/currency parsing
  falls back to `AMBIGUOUS` without Babel's locale data rather than
  guessing.

### python-stdnum

- **Why**: not named in `Source.txt` but the single highest-leverage
  addition found in research — turns §51's country-specific identifier
  architecture from months of bespoke work into a registry lookup.
- **Use**: per-country `validate()`/`compact()`/`format()` for national
  IDs, VAT numbers, IBAN, and the ISO/IEC 7064 check-digit family.
- **Do not use**: any modification/vendoring of the library's source
  (LGPL-2.1 constraint, ADR-009).
- **Limitations**: coverage varies by country; gaps are filled by our own
  `domain-specific` hook layer, not by loosening the generic-stage
  protections (no leading-zero removal, ever).
- **Edge cases**: invalid check digits → `INVALID` status with the
  specific validation failure recorded.
- **Determinism**: fully deterministic.
- **Multilingual**: N/A (numeric/alphanumeric identifiers).
- **Versioning**: pinned; new country modules or corrected algorithms in
  a release participate in `env_id`.
- **License**: LGPL-2.1 — unmodified dynamic use only.
- **Performance**: lookup/algorithm-driven, fast.
- **Failure mode**: unsupported country/identifier type → generic-stage
  handling only (whitespace/separator/case normalization), explicitly
  flagged as not country-validated.
- **Fallback**: our own `domain-specific` hooks for identifier types with
  no external standard (customer IDs, order IDs).

### Pint

- **Why**: mandated by §5/§48; the mature Python units library.
- **Use**: `UnitRegistry`, `Quantity` parsing and conversion within a
  known dimension.
- **Do not use**: Pint's currency-as-unit pattern (some users abuse Pint
  for currency conversion) — currency is handled separately via Babel/
  ISO 4217 (ADR-011), never treated as a physical unit.
- **Limitations**: requires the input to already be identifiable as a
  quantity+unit pair; does not itself detect that a string is a physical
  quantity.
- **Edge cases**: cross-dimension conversion attempts raise
  `DimensionalityError`, caught and surfaced as `INVALID`, never silently
  ignored or wrongly converted.
- **Determinism**: fully deterministic given a pinned unit registry.
- **Multilingual**: unit *symbols* are mostly Latin/ASCII; not a
  multilingual-text concern.
- **Versioning**: pinned; unit registry definitions feed `env_id`.
- **License**: BSD.
- **Performance**: lightweight parsing/conversion, fast.
- **Failure mode**: unparseable quantity → `UNKNOWN_SEMANTIC_TYPE`.
- **Fallback**: none needed.

---

## 4. Newly discovered candidates (§130 autonomous research requirement)

Beyond the spec's explicit shortlist, targeted searches were run for each
category §130 lists (multilingual name normalization, address
standardization, company-name normalization, phone normalization, email
normalization, international date parsing, country/language normalization,
identifier validation, numeric/currency locale handling, Unicode/security
processing, data cleaning, large-scale batch normalization). Results beyond
what is already adopted above:

| Candidate | Category | Verdict |
|---|---|---|
| `deepparse` | Address (neural) | Offline calibration only — see ADR-005 |
| `probablepeople` | Name (CRF) | Offline calibration only — see ADR-003 |
| GLEIF ISO 20275 ELF list | Company | Adopted — see ADR-004 |
| `google-i18n-address` | Address validation | Adopted — see ADR-005 |
| `python-stdnum` | Identifier | Adopted — see ADR-009 |
| Babel/CLDR | Numeric/currency/locale | Adopted — see ADR-010, ADR-011 |
| `charset-normalizer` | Unicode/encoding | Adopted — see ADR-002 |
| `anyascii` | Unicode/transliteration | Adopted — see ADR-015 |
| ICU `SpoofChecker` | Unicode/security | Adopted — see ADR-001 |
| `lingua-py` | Language detection | Adopted (diagnostic only) |
| `py3langid` / `fastText` lang-id | Language detection | Considered, not adopted — weaker short-text recall than `lingua-py` for our field-value-length regime |
| OpenRefine (algorithm reference only) | Data cleaning UX | Reference for `fingerprint`/`ngram-fingerprint` reimplementation only |
| `icu4py` | Unicode (new binding) | Watch item — see ADR-001 |

This table will be extended at each milestone gate if new candidates
surface during implementation; entries are never removed, only marked
superseded, to preserve the audit trail required by §132.

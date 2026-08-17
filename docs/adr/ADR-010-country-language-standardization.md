# ADR-010: Country, Language, and Script Standardization

## Status
Accepted — 2026-08-17

## Context

`Source.txt` §33–§35 require ISO-standard country/language canonicalization
(`United States`/`USA`/`US` → `US`, storing `country_name`, `alpha2`,
`alpha3`, `numeric`, `original`), careful handling of ambiguous
country-vs-territory naming (`UK` vs `Great Britain` vs `United Kingdom` are
not asserted as always semantically identical), ISO language code
canonicalization, and script detection that never triggers transliteration
by default.

`pycountry` (LGPL-2.1) is the standard Python ISO-3166/639/4217/15924
reference. It supplies the *code lookup* layer (name variants → alpha2/
alpha3/numeric) but not locale-dependent *parsing or display* behavior
(e.g. how a decimal number or a currency symbol should be read in a given
locale) — that gap is not addressed anywhere in `Source.txt`'s named
libraries. Research identified **Babel** (BSD), which wraps CLDR locale
data, as the natural complement: locale-specific decimal/grouping
separators, currency symbol→code tables (with the ambiguity in symbols like
`$` represented as data, not guesswork), and localized territory/language
display names.

## Decision

- **`pycountry`** is the ISO code authority for country (3166),
  language (639), currency (4217), and script (15924) canonicalization,
  used as an **unmodified, dynamically-imported dependency** (LGPL-2.1,
  same constraint as `python-stdnum`, ADR-009).
- **Babel/CLDR** supplies locale-dependent *parsing and display*: numeric
  separator conventions, currency symbol ambiguity tables, and localized
  territory/language names — feeding ADR-011's numeric/currency decisions.
- **Country normalization** stores `country_name`, `alpha2`, `alpha3`,
  `numeric`, and `original` together, never collapsing to a single code
  field with the original discarded.
- **`UK`/`Great Britain`/`United Kingdom` are not treated as unconditionally
  interchangeable.** The normalizer maps common variants to `GB` (the
  ISO-3166 code for the sovereign state) for the `alpha2` field, but when
  the *original* text says "Great Britain" specifically, that distinction
  is preserved in `original` and a note is available in `warnings` — the
  system does not assert that "Great Britain" and "United Kingdom" mean
  exactly the same thing in every downstream context (they don't: Great
  Britain excludes Northern Ireland).
- **Script detection** (ICU, per ADR-001) populates `script` + `confidence`
  as a pure diagnostic. It never triggers transliteration or any other
  transformation by default — script-awareness and language-detection
  (`lingua-py`) results are informational (`language_hint`) unless a
  profile explicitly opts a field into script-driven behavior.

## Consequences

- Two libraries (`pycountry` for codes, Babel for locale behavior) is more
  than the spec names, but each has a distinct, non-overlapping
  responsibility — verified in `docs/normalization-tool-evaluation.md`.
- The GB/UK/Great Britain nuance means country normalization cannot be a
  pure lookup table; it requires a small amount of custom disambiguation
  logic, documented and golden-tested explicitly (§76 cultural safety).
- Both libraries' pinned versions (and Babel's CLDR data version)
  participate in `env_id`.

## Revisit triggers

- A downstream consumer (Data Discovery Engine) requires a different GB/UK
  resolution policy for a specific jurisdictional use case — handle via
  `context`-driven configuration, not a global behavior change.
- CLDR major version bump changes currency-symbol ambiguity tables in a way
  that affects existing normalized output — caught by the nightly drift job.

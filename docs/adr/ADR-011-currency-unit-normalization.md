# ADR-011: Numeric, Currency, and Unit Normalization

## Status
Accepted — 2026-08-17

## Context

`Source.txt` §46–§48 require locale-aware numeric parsing (comma vs. period
as thousands/decimal separator is not universal — `"1,234.56"` vs.
`"1.234,56"`), currency canonicalization that never infers a currency from
an ambiguous symbol like `$` without context, and unit normalization via a
mature units library, converting only when the physical dimension is known.

No library named in `Source.txt` addresses locale-aware numeric parsing
directly. **Babel** (BSD, CLDR-backed, already adopted in ADR-010) supplies
exactly this: per-locale decimal/grouping separator conventions and a
currency symbol → ISO 4217 code mapping that is explicit about ambiguity
(multiple locales can share `$`) rather than hard-coding one assumption.
**Pint** (BSD) is the mandated unit library per §5/§48: dimensional
analysis, unit registries, safe conversion, and explicit rejection of
cross-dimension conversion attempts.

## Decision

- **Numeric parsing**: locale-driven via Babel. A numeric string is parsed
  using the separator convention of `context.locale` when known. When
  locale is unknown and the string is syntactically ambiguous (e.g.
  `"1,234"` could be 1234 or 1.234 depending on locale), the value is
  marked `AMBIGUOUS` with both candidate interpretations recorded — never
  silently resolved by assuming comma-is-thousands.
- **Currency**: symbol/code/name variants (`$`, `USD`, `US$`, `US Dollars`)
  canonicalize to ISO 4217 (`USD`) **only when context supports it** —
  `context.country`, `context.locale`, source metadata, or column
  semantics. A bare `$` with no such context stays recorded as
  `original_currency` with `canonical_currency: null` and
  `currency_confidence: low`, never defaulted to USD.
- **Units**: **Pint**, used only when the field's semantic type and unit
  are both identifiable (e.g. `"5 km"` parses to a `Quantity` with
  dimension `[length]`). Conversion between compatible units is performed;
  Pint's own `DimensionalityError` is caught and surfaces as
  `INVALID`/`UNKNOWN_SEMANTIC_TYPE` rather than a silent no-op or a wrong
  conversion. `original_value`, `original_unit`, `canonical_value`,
  `canonical_unit` are all retained.
- **Boolean normalization** (§52) is included in this ADR's scope as a
  related low-risk numeric-adjacent case: canonicalized only when column
  semantics justify it (never applied to free text that happens to contain
  "yes"/"no"), with `maybe`/`unknown`/`N/A` routed to
  `NULL`/`UNKNOWN_VALUE` per configured policy rather than coerced to a
  boolean.

## Consequences

- Babel and Pint both become pinned dependencies whose CLDR/unit-registry
  data versions participate in `env_id`.
- Locale-ambiguous numeric and currency values are expected to be common
  in real multi-source data — the Quality Dashboard (§93) must surface
  `AMBIGUOUS` numeric/currency counts as first-class metrics, not edge
  cases.
- Golden corpus must include the exact examples from §46/§47:
  `"1,234.56"`, `"1.234,56"`, `"£1,234.56"`, `"(1,234.56)"` (parenthesized
  negative), and bare `"$"` amounts without locale context.

## Revisit triggers

- A verified, evidence-backed default currency assumption is requested for
  a specific customer/source (e.g. "this source is always USD") — implement
  as an explicit per-source `context` override, never a global default.
- CLDR currency-symbol tables change in a way that shifts ambiguity
  resolution for a previously-unambiguous symbol — caught by the nightly
  drift job.

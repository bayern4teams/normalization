# ADR-009: Identifier Normalization

## Status
Accepted — 2026-08-17

## Context

`Source.txt` §49–§51, §55 require country-aware and domain-aware identifier
handling (customer IDs, passport numbers, tax IDs, national IDs, SKUs, order
IDs), explicitly forbidding a single global regex and explicitly forbidding
leading-zero removal (`"000123"` must never become `"123"`). §51 mandates an
architecture of `IdentifierNormalizer → generic / country-specific /
domain-specific / custom rules`.

Building country-specific check-digit and format validation from scratch for
every relevant national ID, VAT number, and business identifier is a
multi-month undertaking with high risk of subtle correctness bugs. Research
identified **`python-stdnum`** (arthurdejong, LGPL-2.1) as directly solving
this: hundreds of country-specific modules (national IDs, VAT numbers, IBAN,
ISIN, and more) behind a uniform `validate()`/`compact()`/`format()`
interface, implementing the full ISO/IEC 7064 check-digit family (Mod 11,2 /
Mod 37,2 / Mod 97,10 / Mod 11,10 / Mod 37,36) plus country-specific
algorithms.

## Decision

- **`python-stdnum`** is the primary engine for the `country-specific` and
  much of the `domain-specific` branches of `IdentifierNormalizer`. It is
  used as an **unmodified, dynamically-imported dependency** (never
  vendored or patched in-tree) per its LGPL-2.1 license terms — recorded
  explicitly in `scripts/license_policy.toml` and `docs/dependency-
  inventory.md`.
- `IdentifierNormalizer` architecture exactly per §51:
  - `generic`: Unicode digit normalization, whitespace/separator
    normalization, case normalization — no leading-zero removal, ever.
  - `country-specific`: dispatches to the matching `python-stdnum` module
    keyed by `context.country`.
  - `domain-specific`: our own hooks for platform-specific ID formats
    (customer IDs, order IDs) that have no external standard.
  - `custom rules`: project-level overrides layered via `normdict`.
- **Leading zeros are structurally protected**: the generic stage has no
  code path that can strip a leading zero; this is enforced by a mandatory
  golden test (`"000123"` → `"000123"`, unchanged) that is part of every
  gate from M5 onward, not just M5's own gate.
- **Separator ambiguity defaults to `POTENTIAL_COLLISION`, not silent
  equality**: `"AB-001"` vs `"AB001"` are flagged for the collision
  dashboard (§79, §111) rather than being treated as certainly-equal or
  certainly-distinct — the domain policy is unknown to the normalization
  layer and must not be assumed.
- **Identifier-like text is never coerced to numeric** (§55): semantic type
  inference happens before any numeric casting is considered, and
  identifier/code-typed fields are never eligible for numeric coercion at
  all — `"00123"` and `123` remain distinct string values.
- UUIDs (§50) get their own light-touch normalizer: braces/case/hyphen
  canonicalization to lowercase-hyphenated form, original always retained.

## Consequences

- `python-stdnum`'s LGPL license means it cannot be forked or patched
  in-tree without changing its license classification — any needed fix
  must go upstream or be implemented as a wrapper-level override, not a
  vendored patch.
- Because `python-stdnum` covers so much ground, the amount of genuinely
  custom identifier code in this project is small — mostly the dispatch
  layer, the domain-specific hooks, and the collision-flagging policy.
- `python-stdnum`'s pinned version participates in `env_id`; new country
  modules or corrected check-digit logic in a new release can change
  validation outcomes.

## Revisit triggers

- A required identifier type is not covered by `python-stdnum` — implement
  as a `domain-specific` custom hook, evaluated case by case, never by
  loosening the generic-stage protections.
- `python-stdnum` license terms change — re-evaluate via a new ADR before
  any version bump.

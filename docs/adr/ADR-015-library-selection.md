# ADR-015: Library Selection and License Policy

## Status
Accepted — 2026-08-17

## Context

`Source.txt` §3, §124, §130–§132 require open-source-first evaluation before
any custom implementation, a documented capability/license/maintenance
matrix (`docs/normalization-tool-evaluation.md`), and explicit verification
that the spec's own suggested libraries are actually suitable — §137
explicitly forbids trusting the prompt as the source of truth on library
capabilities.

Research (see `docs/normalization-tool-evaluation.md`) surfaced three
libraries the spec names or implies as candidates that are **not suitable
for adoption**, each for a different reason:

1. **Unidecode** (§5, §16, §124) — GPL-2.0-or-later. Its maintainer has
   stated this is a deliberate choice, not an oversight, and explicitly
   points GPL-averse users toward alternatives. For a commercial platform,
   linking GPL code into the normalization engine would obligate the whole
   linked work under GPL terms — unacceptable for a component this central.
2. **`wordfreq`** (§5) — formally sunset by its author in September 2024;
   the stated reason (generative-AI-polluted training corpora, and loss of
   Reddit/Twitter API access as data sources) is a permanent, structural
   problem, not a temporary maintenance gap. §5 itself already warns not to
   treat its data as an authoritative current dictionary; research confirms
   that warning is now the *entire* status of the project.
3. **`abydos`** (implied by §25's Beider-Morse mention) — GPL-3, via a port
   of a GPL-3 PHP reference implementation of Beider-Morse Phonetic
   Matching. Same reasoning as Unidecode: unacceptable license for a
   linked, in-process dependency.

Conversely, research surfaced strong candidates the spec does not name at
all: `python-stdnum` (identifiers, ADR-009), GLEIF's ISO 20275 ELF list
(company suffixes, ADR-004), `google-i18n-address`/libaddressinput metadata
(postal code validation, ADR-005), ICU `SpoofChecker` (confusables, ADR-001),
Babel/CLDR (locale-aware numeric/currency, ADR-010/ADR-011),
`charset-normalizer` (encoding detection, ADR-002), `anyascii` (ASCII
transliteration, replacing Unidecode), and `lingua-py` (language hinting).

## Decision

- **Reject**: Unidecode, `wordfreq`, `abydos`. None may be added as a
  dependency without a superseding ADR that re-justifies the license or
  maintenance concern that caused rejection here.
- **Adopt in their place**: `anyascii` (ISC, supersedes Unidecode — broader
  Unicode coverage including non-BMP characters, more actively maintained);
  no replacement for `wordfreq` (not adopted at all — frequency-based
  diagnostics are out of scope until a suitable, non-sunset data source is
  identified); `jellyfish` (MIT, covers the exact §25 phonetic algorithm
  list without Beider-Morse).
- **Full selected stack** is recorded in `docs/normalization-tool-
  evaluation.md`'s matrix and `docs/dependency-inventory.md`'s inventory;
  this ADR is the decision record, those documents are the living detail.
- **License policy is machine-enforced**, not just documented:
  `scripts/license_policy.toml` defines an allow-list, a
  restricted-LGPL-unmodified-dynamic-only list (currently `pycountry`,
  `python-stdnum`), and a deny-list (GPL/AGPL/SSPL families, plus the three
  explicitly-rejected packages by name). `scripts/check_licenses.py` runs
  in `ci-full` and `gate` workflows and **fails the build** on any
  violation — this is the mechanism that makes "we already rejected
  Unidecode" durable against a future contributor adding it back
  unknowingly.
- Every dependency's selection answers the §132 questionnaire in
  `docs/normalization-tool-evaluation.md`: why this library, what exact
  capability is used, what is deliberately not used, limitations,
  determinism, multilingual support, versioning, license, performance
  profile, failure mode, fallback.

## Consequences

- The license gate is a hard CI dependency from M0 onward — any new
  dependency addition must pass it before merge, catching license
  regressions at the point of introduction rather than at an audit months
  later.
- Rejecting `wordfreq` means any future frequency-based diagnostic feature
  needs its own sourcing decision — explicitly deferred, not silently
  worked around with a stale snapshot presented as current.
- The LGPL-unmodified-dynamic-only category (`pycountry`, `python-stdnum`)
  is a deliberate, narrow exception, not a general LGPL allowance — adding
  a third LGPL package requires updating the policy file and this ADR
  explicitly, not just installing it.

## Revisit triggers

- A GPL/AGPL package is later found to be the only viable option for some
  capability — this requires an isolated-service architecture (separate
  process/container, no in-process linking) and a new ADR, following the
  pattern already reserved for Beider-Morse in ADR-003.
- `wordfreq` or a credible non-AI-polluted successor becomes available.

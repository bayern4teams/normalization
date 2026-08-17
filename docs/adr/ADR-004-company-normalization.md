# ADR-004: Company Name Normalization

## Status
Accepted — 2026-08-17

## Context

`Source.txt` §26–§28 require conservative legal-suffix stripping (explicitly:
`"The Limited"` must never become `"The"`), a versioned/locale-aware/editable
legal-entity-suffix dictionary, and jurisdiction inference to be stored as a
**hint**, never asserted as fact.

Candidates:

1. **`cleanco` 2.3** (MIT) — `basename()`, `typesources()`,
   `countrysources()`. Its own documentation admits suffixes may be missing
   or incorrect and that `basename()` may need to run twice for compound
   suffixes. It is a fixed, unversioned-in-the-sense-we-need term list
   bundled with the library release.
2. **GLEIF ISO 20275 Entity Legal Forms (ELF) code list** — the official
   registry behind the Legal Entity Identifier (LEI) system: 3,400+ entity
   legal forms across 185+ jurisdictions, each with a 4-character ELF code,
   listed in native language and script, published as a versioned,
   dated, externally-governed dataset.

## Decision

- **Primary dictionary: GLEIF ELF list**, ingested as a versioned
  `normdict` payload (checksummed, dated per GLEIF's own release
  versioning). This satisfies §27's requirement for locale-aware, versioned,
  auditable legal-entity dictionaries far better than any hand-maintained
  list, because the source of truth is an external standards body with its
  own release cadence we can track.
- **`cleanco` as secondary/fallback source**, primarily for its
  `typesources()`/`countrysources()` heuristics where GLEIF's stricter
  registry-form matching doesn't fire, and as a cross-check during golden
  corpus construction.
- **User custom terms layer on top of both**, per §59, as a project-level
  dictionary overlay — built-ins are never mutated.
- **Conservative stripping rule**: a suffix is removed from `base_name`
  only when (a) it appears in token-final position, (b) it matches a
  dictionary entry under a plausible jurisdiction for the record's context,
  and (c) the residual base name is non-trivial (non-empty, not purely a
  stopword). `"The Limited"` is a mandatory, permanently-golden test case
  that must retain `"The Limited"` as `base_name` when there is no
  distinguishing context, because "Limited" here is plausibly part of the
  brand, not a legal-form marker with a clearly separable base.
- **Jurisdiction is always a hint.** `jurisdiction_hint` is populated from
  ELF-code/suffix evidence (e.g. "Oy" → Finland-plausible) but the schema
  has no `jurisdiction` fact field at all for this signal — there is
  nothing to accidentally treat as ground truth.

## Consequences

- GLEIF ELF list updates are a dictionary-version bump, not a code change;
  they flow through the normal `normdict` versioning/rollback machinery
  (§58, §59, §95).
- `legal_name`, `base_name`, `comparison_name`, `organization_type`,
  `elf_code`, `jurisdiction_hint` are all distinct output fields — no
  collapsing to a single "cleaned name" string.
- Golden corpus must include known adversarial cases beyond "The Limited":
  brand names that are themselves legal-form words in another jurisdiction,
  multi-suffix names ("Acme GmbH & Co. KG"), and names where stripping is
  clearly correct ("Acme Corporation" → "Acme").

## Revisit triggers

- GLEIF publishes a major ELF list revision — re-run the full company
  golden corpus before adopting (covered by the nightly drift job once the
  ELF list is added to the tracked-dictionaries manifest).
- A verified false-merge incident traced to over-aggressive suffix
  stripping — tighten the conservative-stripping rule and add the case to
  the golden corpus.

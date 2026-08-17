# ADR-003: Person Name Normalization

## Status
Accepted — 2026-08-17

## Context

`Source.txt` §20–§25 require: title/first/middle/last/suffix/nickname
parsing, preserved ambiguity for reorderable names ("Smith John"), a
versioned honorific and suffix dictionary, an explicit prohibition on
automatic nickname aliasing (Robert→Bob) absent a curated dictionary, and an
optional phonetic variant that never replaces the canonical name.

Candidate parsers evaluated:

1. **`nameparser` 2.1** — rule-based, immutable results, composable
   `Lexicon` (vocabulary) and `Policy` (behavior) objects, opt-in locale
   packs, requires Python 3.11+. Deterministic. LGPL-licensed (confirmed
   via PyPI classifier) — used as an unmodified, dynamically-imported
   dependency, same constraint as `pycountry`/`python-stdnum` (ADR-009,
   ADR-010, ADR-015).
2. **`probablepeople`** — CRF-based (conditional random field) probabilistic
   parser from DataMade, handles person/company/couple ambiguity better on
   noisy input, but is a statistical model (non-trivial determinism story —
   same input always yields the same output because the model is fixed and
   frozen, but confidence/behavior is opaque compared to rule-based parsing)
   and is documented as western-name/romanized-input only, same as
   `nameparser`.
3. **Phonetic algorithms**: `abydos` implements the full family including
   Beider-Morse (multilingual-aware), but its Beider-Morse port is licensed
   GPL-3 (ported from a GPL-3 PHP reference). `jellyfish` (MIT) implements
   Soundex, NYSIIS, (Double) Metaphone, and Match Rating — exactly the
   algorithm list named in §25 — without Beider-Morse.

Neither `nameparser` nor `probablepeople` handles non-Latin-script or
non-Western name ordering; §76 (cultural safety) requires the architecture,
not necessarily the parser, to accommodate locale-specific strategies later.

## Decision

- **Primary parser: `nameparser` 2.0**, wrapped in a deterministic adapter
  bound to our own versioned `Lexicon`/`Policy` (honorifics, suffixes) rather
  than the library's built-in English-only defaults. Chosen over
  `probablepeople` because rule-based + our own dictionary gives fully
  auditable, deterministic behavior (§72) with a directly inspectable
  decision path (§65 trace), whereas a CRF model's decision boundary is
  harder to explain per-value to a normal-mode user (§117).
- **`probablepeople` is retained as an offline calibration tool only**
  (per the plan's dual-parser confidence calibration approach): during M3,
  run it over the golden corpus to measure inter-parser agreement and use
  disagreement rate to set `NEEDS_REVIEW` confidence thresholds for
  `nameparser` output. It is never imported by the runtime normalization
  path — this keeps the shipped pipeline single-parser and deterministic
  per §72 and §129.
- **Phonetics: `jellyfish`** (MIT), covering Soundex/NYSIIS/Metaphone/Match
  Rating. `abydos`/Beider-Morse is rejected due to GPL-3 contamination (see
  ADR-015). If Beider-Morse-quality multilingual phonetic matching is later
  required, it must run as an isolated, separately-licensed service, never
  linked into this codebase.
- **Ambiguity preservation**: `"Smith John"`-shaped input yields multiple
  candidate parses with confidence scores rather than one silently chosen
  order (§21, §76). The architecture is never permitted to assume
  first-token-is-given-name.
- **Nicknames**: not implemented in the default profile (§24). The
  `NameNormalizer` interface has a hook for an optional, explicitly
  configured, versioned, locale-aware nickname dictionary, disabled by
  default, with any output it produces marked `LOSSY`/aliasing rather than
  ordinary normalization.
- **Architecture leaves room for locale-specific strategies**: `NameNormalizer`
  dispatches on `context.locale`/`context.script`; the Western rule-based
  path is the first implemented strategy, not the only one the interface
  permits.

## Consequences

- Golden corpus must include both `nameparser`-vs-`probablepeople` agreement
  cases and deliberate disagreement cases, with the calibration methodology
  documented in `docs/normalization-testing.md`.
- `nameparser`'s and `jellyfish`'s pinned versions participate in `env_id`.
- Reordering ambiguity means the data contract's `structured` field for names
  can hold a **list** of candidate parses, not a single struct — this must be
  reflected precisely in the JSON Schema / Arrow schema (M1).

## Revisit triggers

- A verified curated nickname dictionary with clear provenance becomes
  available and a downstream consumer explicitly requests it — implement as
  strictly opt-in per §24.
- Non-Western name volume in real source data becomes significant enough to
  justify a dedicated locale-specific parsing strategy.

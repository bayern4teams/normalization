# ADR-012: Lossy Transformation Policy

## Status
Accepted — 2026-08-17

## Context

`Source.txt` §64 requires every lossy operation to be explicitly marked
`LOSSY`, with a UI warning and a plain-language explanation that the
original value remains preserved. §80 requires every rule to be classified
`LOSSLESS`/`REVERSIBLE`/`PARTIALLY_REVERSIBLE`/`LOSSY`. §112–§113
additionally require that normalization never manufactures semantic
equivalence that does not exist — a distinct, higher-stakes concern than
mere information loss: a transformation can be lossless in the narrow
technical sense (e.g. lowercasing) yet still create a false merge if applied
carelessly to a case-sensitive identifier.

Hand-labeling each rule's reversibility class in documentation risks drift:
a rule's actual behavior can diverge from its claimed label as the
implementation evolves, and nothing would catch that.

## Decision

- **Every normalization step declares its reversibility class as code**,
  not just documentation: each `StepSpec` in the `Normalizer` interface
  carries a `claimed_reversibility: Reversibility` field and, where
  `REVERSIBLE` or `PARTIALLY_REVERSIBLE`, an `inverse(step_id, value)`
  callable.
- **CI empirically verifies every claim** against the full golden corpus at
  every gate from M2 onward: for `LOSSLESS` steps, assert
  `step(x) == step(step_inverse_identity(x))` is unnecessary (no inverse
  needed — output determines input uniquely, verified by an injectivity
  check on the corpus); for `REVERSIBLE`/`PARTIALLY_REVERSIBLE`, assert
  `inverse(step(x))` recovers `x` (or recovers it within the declared
  partial tolerance); for `LOSSY`, assert the step is *not* injective on at
  least one golden case (proving the claim isn't accidentally too
  conservative, which would hide a real reversibility from the UI).
  A step whose empirical behavior contradicts its claimed label **fails the
  build**.
- **`LOSSY` marking is UI-visible by construction**: `NormalizedValue.
  lossiness` is populated directly from the steps' declared classes, and
  the UI's `⚠ Lossy transformation` warning (§64) reads this field —
  there is no separate manual UI-side classification to fall out of sync.
- **Lossy ≠ permission to merge.** A rule producing a lossy comparison
  representation (e.g. accent-stripped name) is distinguished sharply from
  entity resolution: normalization's job stops at producing candidate
  comparison values; whether two records with equal comparison values
  represent the same entity is explicitly out of scope (§112, §113,
  enforced by not implementing any merge/link decision anywhere in this
  codebase — verified by the Splink-absence CI check, ADR-016).

## Consequences

- Reversibility documentation in the UI (§80) is generated from tested
  fact, not maintained prose — eliminating an entire class of "docs say X
  but code does Y" bugs.
- Adding a new normalization step requires declaring and, where applicable,
  implementing its inverse before it can ship — a small but real
  authorship cost, accepted because it is what makes §80 trustworthy rather
  than aspirational.
- The collision dashboard (§79, §92) and the lossy inventory in every
  milestone verification pack draw from the same underlying, tested data.

## Revisit triggers

- A step's empirical reversibility test starts failing after a library
  upgrade (e.g. a "lossless" Unicode normalization step becomes non-
  injective due to a new Unicode version's compatibility mappings) —
  treat as a release blocker, not a warning to suppress.

# ADR-014: Normalization Versioning and Reproducibility

## Status
Accepted — 2026-08-17

## Context

`Source.txt` §71–§73 require idempotency, determinism, and version locking:
the same input, profile, and library versions must produce the same output,
and normalization output changing due to unnoticed library/dictionary drift
is called out as a known risk to guard against, not merely document. §95 and
§120 require immutable, versioned, rollback-able normalization profiles.

A profile version alone (`v1`, `v2`, ...) is insufficient to guarantee
reproducibility, because the *same* profile version can produce *different*
output if the underlying libraries, ICU/Unicode/CLDR data, dictionaries, or
the libpostal model change between two runs — and nothing in a naive design
would detect that until someone noticed a discrepancy in production.

## Decision

- **Introduce `env_id`**: a `blake3` hash over a canonical JSON
  serialization of every version-sensitive input to normalization:
  - every pinned Python package version actually resolved (not just
    declared range) for the libraries listed in
    `scripts/env_fingerprint.py::FINGERPRINTED_PACKAGES`
  - ICU version, Unicode version, CLDR version (queried from PyICU at
    runtime)
  - libpostal sidecar's model data SHA-256 (queried from its `/version`
    endpoint)
  - phonenumbers metadata version
  - every loaded dictionary's `{id}@{version}` → content hash
  - the active `NormalizationProfile.version`
  `scripts/env_fingerprint.py` computes this deterministically and is
  itself unit-tested for stability (same input twice → same hash) and
  sensitivity (any one field changed → different hash).
- **`env_id` is stamped everywhere**: every `NormalizedValue`, every
  `NormalizationRun`, every cache key. Two runs are directly comparable
  *if and only if* their `env_id` matches — this is the operational
  definition of "same environment" the plan's reproducibility guarantees
  rest on.
- **Profiles are immutable once activated.** A change to a profile's rules
  creates a new `NormalizationProfile` version; the previous version's
  historical run outputs are never rewritten. `Activate` / `Deactivate` /
  `Rollback to Previous` operate on which version is *current*, never on
  historical data.
- **Caches self-invalidate on `env_id` change** — cache keys include
  `env_id`, so a library or dictionary upgrade cannot silently return
  stale-but-different-semantics cached results (ADR-016 covers cache
  mechanics in detail).
- **Nightly drift detection**: a scheduled CI job (`.github/workflows/
  drift.yml`) re-resolves all pinned dependencies to their current latest
  versions into a throwaway lockfile, runs the full golden corpus against
  that environment, and diffs output against the corpus's committed
  expectations. Any difference opens an issue naming the exact library,
  the exact affected inputs, and the exact output delta — turning "did an
  upgrade change our output?" from a manual audit into an automatic,
  dated, attributable finding *before* anyone deliberately upgrades.

## Consequences

- Every run record and every cached value carries a small but nonzero
  amount of extra fingerprinting metadata — accepted as the cost of the
  reproducibility guarantee §72/§73 actually require.
- Byte-identical replay (running the same input+profile twice in two
  separate processes and requiring identical output) becomes a mechanical,
  automatable gate check rather than an aspiration — this is Layer 1,
  item 5 of every milestone gate.
- Upgrading any pinned dependency is now a *visible, deliberate* act with
  a known blast radius (the drift job's diff), not a silent risk.

## Revisit triggers

- The fingerprinted-package list in `env_fingerprint.py` falls out of sync
  with `pyproject.toml`'s actual dependency set — add a CI check
  cross-referencing the two lists (tracked for M1).
- `env_id` computation becomes a measurable performance bottleneck at
  extreme value-volume — cache the computed `env_id` per process/run
  rather than recomputing per value (it is already run-scoped, not
  per-value, in the current design — this trigger exists to catch any
  future regression toward per-value recomputation).

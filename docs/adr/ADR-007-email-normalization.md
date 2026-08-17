# ADR-007: Email Normalization

## Status
Accepted — 2026-08-17

## Context

`Source.txt` §39–§41 require separated `display_name`/`local_part`/`domain`/
`normalized_address`/`domain_ascii(IDNA)`/`validation` fields, and explicitly
forbid provider-specific local-part transformations (Gmail dot-removal,
plus-tag stripping) unless explicitly configured with evidence. §41 requires
deterministic, fast validation — no network deliverability checks by
default.

`email-validator` (JoshData/python-email-validator, Unlicense/CC0) is the
mandated candidate per §4.5. Research confirms it performs: NFC normalization
and quoted-string/backslash cleanup on the local part; lowercasing, NFC,
fullwidth/halfwidth folding, UTS-46 mapping, and Punycode conversion on the
domain; and it explicitly documents a hazard we must design around —
normalization can change an address's length/validity such that a string
valid before normalization is invalid after, or vice versa. Critically, its
`check_deliverability` parameter **defaults to `True`**, which performs live
DNS/MX queries — directly violating §41's determinism requirement if left at
default.

## Decision

- **`email-validator`**, invoked with **`check_deliverability=False` always**
  in the core normalization path. This is a mandatory, tested configuration
  — a golden/contract test asserts no network call occurs during
  normalization (e.g. via a DNS-resolver monkeypatch that raises if invoked).
- Both **pre-normalization and post-normalization validation** are run and
  both results recorded, directly addressing the library's documented
  length/validity-shift hazard, so a value that flips validity across
  normalization is visible rather than silently resolved one way.
- Output struct: `original`, `display_name`, `local_part`, `domain`,
  `normalized_address`, `domain_ascii` (IDNA/Punycode), `smtputf8`,
  `validation_status`.
- **Provider-specific rules (Gmail dot removal, plus-tag stripping) are
  off by default** and structurally cannot be silently enabled — they
  require an explicit `ProviderPolicy` entry naming the exact domain,
  attached to the profile with recorded justification/evidence, and any
  value they touch is marked `LOSSY` and `CUSTOM_RULE_APPLIED`.
- Validation statuses per §41: `VALID_SYNTAX`, `INVALID_SYNTAX`,
  `INTERNATIONALIZED`, `UNKNOWN`, `POSSIBLY_DELIVERABLE`, `UNDELIVERABLE` —
  the deliverability-flavored statuses are reserved for a future, explicitly
  opt-in, rate-limited, async deliverability-check feature that is
  out of scope for the core deterministic pipeline and must never run inline.

## Consequences

- Deterministic-by-construction: same input always produces the same
  output regardless of network conditions or DNS state at run time.
- The pre/post-normalization dual-validation doubles the validator calls
  per unique email but is applied only to the distinct-value set (ADR-016),
  keeping the cost bounded.
- `email-validator`'s pinned version is part of `env_id`, since its IDNA/
  UTS-46 mapping tables can change between releases.

## Revisit triggers

- A verified, evidence-backed business need for a specific provider's
  local-part semantics (e.g. a confirmed Gmail-only customer dataset) — add
  as an explicit, audited `ProviderPolicy`, never a global default.
- A future async deliverability-check feature is scoped — it must run as a
  separate, clearly-labeled, non-blocking enrichment step outside the core
  deterministic pipeline, never inline in `normalize()`.

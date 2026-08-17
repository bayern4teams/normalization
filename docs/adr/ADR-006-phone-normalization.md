# ADR-006: Phone Normalization

## Status
Accepted — 2026-08-17

## Context

`Source.txt` §36–§38 mandate `libphonenumber` semantics (via
`python-phonenumbers`), explicitly forbid "strip non-digits, keep last 10"
heuristics, require explicit/inferred/unknown country-context tracking, and
require extensions to be stored separately and never merged into the
canonical number.

`python-phonenumbers` is the actively maintained, pure-Python port of
Google's `libphonenumber`, Apache-2.0 licensed, with no native-code build
step (unlike libpostal) — a materially simpler dependency.

There is no serious alternative under consideration: `libphonenumber`
semantics are explicitly mandated by the spec, and `python-phonenumbers` is
the canonical Python binding maintained in lockstep with upstream metadata
releases.

## Decision

- **`python-phonenumbers`** is the sole phone parser/validator.
- Output struct always includes: `original`, `parsed`, `country_code`,
  `national_number`, `extension`, `e164`, `international_format`,
  `national_format`, `is_possible`, `is_valid`, `region`,
  `validation_message`.
- **Region resolution precedence** (§37), each level recorded so the
  *source* of the region used is always inspectable:
  `explicit record context → source context → field default region →
  user/project default region`.
- **No country context resolvable → `status: AMBIGUOUS`**, never a guess.
  This is enforced by a golden test asserting that a bare national-format
  number with no resolvable region never receives a fabricated `e164`.
- Extensions are parsed into a separate `extension` field and never
  concatenated into `e164`/`national_number` (§38).
- `phonenumbers`' bundled metadata version (tied to its package version) is
  captured by `env_fingerprint.py` and is part of `env_id`, since upstream
  metadata updates (new area codes, porting changes) can change validity
  results on the same input.

## Consequences

- Because `python-phonenumbers` is pure Python with no compiled extension,
  it imposes no Windows-build or container-isolation burden, unlike
  libpostal (ADR-005) — it runs in-process directly.
- Distinct-value-first batching (ADR-016) still applies: normalize unique
  phone strings once per profile version, not per row.
- The `AMBIGUOUS` status is a first-class, expected, common outcome — UI and
  downstream consumers must treat it as routine, not exceptional.

## Revisit triggers

- Upstream `libphonenumber` metadata schema changes in a way
  `python-phonenumbers` cannot represent — track via the nightly drift job.
- A demonstrated need for carrier/timezone lookup (mentioned as optional in
  §36) — evaluate `phonenumbers`' optional carrier/geocoder/timezone
  submodules at that point; not adopted now to keep the default footprint
  minimal.

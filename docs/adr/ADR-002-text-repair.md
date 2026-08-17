# ADR-002: Text Repair (Mojibake / Encoding Corruption)

## Status
Accepted — 2026-08-17

## Context

`Source.txt` §4.2 and §10 require mojibake/broken-Unicode repair, but explicitly
forbid running aggressive text repair unconditionally: repair must be applied
"only where the input actually looks corrupted," and the system must record
when repair was applied. This means the pipeline needs two distinct
capabilities that are often conflated:

1. **Encoding misdetection** — a byte stream was decoded with the wrong
   codec (e.g. Windows-1252 bytes decoded as UTF-8).
2. **Mojibake already baked into the string** — the value was already
   corrupted upstream (double-encoded, decoded-then-reencoded-then-decoded
   again) before it reached us as a Python `str`.

These require different remedies and different trace entries: (1) is a
decode-stage concern; (2) is a post-decode repair concern.

`ftfy` is the mandated tool for (2) per §4.2. Its documented design goal is
**zero false positives** — it must never alter correctly-decoded text — and
its 6.3 release added targeted heuristics (e.g. detecting mojibake in
uppercase German words like "ZURÜCK", improbable-punctuation sequences)
while explicitly maintaining that goal.

For (1), `chardet` is the historical default but is unmaintained relative to
its 2026 successor `charset-normalizer` (MIT, actively maintained, used by
`requests`/`httpx` internally), which additionally reports a confidence
score per candidate encoding.

## Decision

Two-stage decode/repair pipeline, each stage independently traced:

1. **Decode stage**: `charset-normalizer` detects the source encoding with a
   confidence score when the input arrives as raw bytes (file ingestion) or
   when a source column's declared encoding is suspect. If confidence is
   high and differs from the assumed encoding, re-decode and record
   `ENCODING_REDETECTED` with old/new codec and confidence.
2. **Repair stage**: `ftfy.fix_and_explain(value)` runs on every string, but
   its output is only accepted when `fix_and_explain` reports at least one
   actual fix — i.e. **evidence-gated**, never blanket-applied. The returned
   explanation (list of applied transformations) is copied verbatim into the
   value's trace. `MOJIBAKE_FIXED` flag is set only when a fix was applied.
   Values with no detected corruption pass through unchanged and are marked
   `UNCHANGED` at this step, not `REPAIRED`.

`ftfy`'s own default settings are used (not hand-tuned aggressively) because
its documented false-positive rate is the product of deliberate, tested
heuristics — changing thresholds ourselves would forfeit that guarantee
without our own equivalent validation corpus.

## Consequences

- The distinction between "we redecoded bytes" and "we repaired an
  already-`str` value" is preserved in the trace as two separate step types,
  which matters for explaining *why* a value changed (§117) and for
  attributing errors correctly (§68).
- `ftfy`'s and `charset-normalizer`'s pinned versions are part of `env_id`
  (per ADR-014) since heuristic updates in either library can change output
  on the same input.
- A dedicated "false positive" golden test class exists: a corpus of
  correctly-decoded, heavily-accented, multi-script text that MUST emerge
  byte-identical after both stages (M2 gate requirement).

## Revisit triggers

- `ftfy` major version bump changes its false-positive guarantee.
- A production incident shows either stage over- or under-firing on a
  language/script not represented in the golden corpus — expand the corpus
  before changing the gating logic.

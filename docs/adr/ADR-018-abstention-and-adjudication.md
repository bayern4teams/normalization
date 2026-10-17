# ADR-018: Abstention Has an Exit — Adjudication Queue and Verdicts

## Status
Accepted — 2026-10-05. Implements `docs/improvement-report.md` D1 and D12.

## Context

Three normalizers return `AMBIGUOUS` rather than guess (`phone.py`, `date.py`,
`money.py`). Until now the refusal ended in the destination cell (the original
string, decision #8) plus an error row: nobody could answer it, and the next run
asked the same question again. `NEEDS_REVIEW` was declared in the status enum and
the severity order, and nothing produced it.

The report proposed verdicts keyed by `(context_hash, profile_version, env_id)`.
The code disagrees with that key on substance (plan finding F3):

- `context_hash` never contains the value (`normcore/context.py`, ADR-016). Keyed
  on it alone, one human decision would answer every value of a column.
- `env_id` hashes the whole `normalizers` source (ADR-014). Keyed on it, every
  normalizer edit would orphan every verdict ever given.

## Decision

**Store.** Two tables in the existing metadata Postgres (report decision A),
created beside `normalization_clone_job_errors`:

- `normalization_adjudication_queue` — one row per key: semantic type, the
  original value, the context (as JSON; it holds no value), the normalizer's
  `structured`/`warnings`/`errors` for that value, first/last job, occurrence count.
- `normalization_adjudication_verdicts` — append-only: key, `decided_value`,
  `decided_display` (what the decided value normalized to when it was accepted),
  `decided_by`, `decided_at`, `rationale`, `confidence` (nullable), `env_id`,
  `profile_version`. A verdict is never updated or deleted; the newest row for a
  key wins.

**Key.** `blake3(semantic_type, content_hash(original), context_hash,
profile_version)`. The value is in it (as a hash: ADR-016 forbids raw values in
keys); so is everything that can change how the value normalizes (country,
locale, field, table, source — the whole `context_hash`). `profile_version` is in
it, so a rule change invalidates verdicts. `env_id` is not: it is stored on the
verdict and written into the applied value's trace, never matched on.

**Source (amended 2026-10-14, PART1 D1.3).** `source` in the context is the
source's identity, `engine://host:port/database[/schema]` (host lowercased, no
user, no password), not the saved connection's id. The id changes whenever a
connection is saved again, for example after a password rotation, and keyed on
it every verdict made under the old id was orphaned: the same ambiguity was
asked again, which Part 1 D1 rules out. A moved server (a new host) is a new
source. Rows stored under a connection id are re-keyed at startup
(`migrate_sources`): the queue row moves to the new key and its verdicts are
copied there; the old verdict rows stay, the history is append-only. A row
whose connection or job no longer exists cannot be re-keyed and is counted in
the startup log.

**Dedup.** A million identical ambiguous values in one context are one queue
row with `occurrences = 1000000`. The same value in two countries is two rows.
Occurrences are written in the same transaction that advances the table's
checkpoint, so a chunk re-run on resume (it was not checkpointed) cannot count
twice. A ClickHouse table that starts over on resume (it cannot resume by
offset) first sets this job's counts for that table back to 0.

**Resolve stage** (report decision C). In `clone_executor._apply_column`, before
dispatch, one batched verdict lookup for the chunk's distinct values in that
column's context. A hit is applied by **re-normalizing the decided value through
the same planner, context and profile**, then setting `original` back to the
source string and appending an `adjudication` `TraceStep` (decider, time, env_id)
so provenance does not lie. Misses go through dispatch exactly as before.

**Verdict acceptance.** `POST` accepts a verdict only if the decided value
re-normalizes, in the stored context, to a clean status (`NORMALIZED`, `PARSED`,
`REPAIRED`, `UNCHANGED`: the plan named the first two; an already-canonical
decided value is `UNCHANGED` and is just as clean). Otherwise 422 and nothing is
stored. `decided_by` must match `human:<id>` or `agent:<id>`; swapping a human
for an agent (Q15) is a different string, not a migration, and both apply the
same way.

**Unresolved values.** The first-run write path is unchanged byte for byte. Only
`AMBIGUOUS` is queued (Q14); `INVALID` is not a question anyone can answer.

**`NEEDS_REVIEW` (D12) — kept, with one producer.** Deleting it would break the
literal mapping of the status enum to Source.txt §67. Its meaning is now precise:
*a value was emitted, and a human must confirm it*, as distinct from `AMBIGUOUS`
(*the engine refused to choose*). The producer: at resolve time, a verdict whose
decided value no longer normalizes to the `decided_display` recorded when the
verdict was accepted (a normalizer change since the decision). The new value is
emitted, the status is `NEEDS_REVIEW` and an error row says why. No threshold is
involved; an `env_id` change that does not alter the output applies silently.

**API** (`routes.py`, no UI — Part 3): `GET /adjudication/queue` (filters:
semantic type, status `pending`/`decided`; paged, `X-Total-Count`),
`GET /adjudication/queue/{key}`, `POST /adjudication/queue/{key}/verdicts`.

**PII.** At rest, queue rows hold what `normalization_clone_job_errors` already
holds for the value (the raw original). The API returns `safe_preview(original)`
and masks the candidate values the same way, never the raw string.

## Consequences

- One human answer settles a value for every later run, in that context, until
  the profile changes.
- `context_hash` includes field, table and source, so the same ambiguous date in
  two columns is two questions. Deliberate: the key may only merge what provably
  normalizes identically.
- The clone path runs without traces (`include_trace=False`), so queue rows carry
  `structured`/`warnings`/`errors`, not a trace.
- A reviewer reading through the API sees masked values; deciding needs the raw
  value, which today means the metadata database itself (the same access the
  error rows already need). A role-gated unmasked view belongs to the UI work.

## Alternatives deferred

- **The report's key** — see Context; it is wrong for this code base.
- **Queueing `INVALID`** — Q14 asks for decisions on ambiguity, not on garbage.
- **A confidence threshold for `NEEDS_REVIEW`** — no threshold exists that is not a
  guess until D2 measures confidence; revisit after calibration.
- **Per-row verdicts** — do not scale (>1B rows) and cannot be invalidated
  coherently (report decision B).

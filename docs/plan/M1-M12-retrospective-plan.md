# M1–M12 Retrospective Plan

## Status

**Retroactive.** The original planning document (referenced by `README.md`
as "the planning document that produced this repository") covers the
8-milestone, 18-phase plan for M0–M8 only, mapped section-by-section
against `Source.txt`'s 138 sections in `docs/traceability-matrix.md`.

M9–M12 were never written up as a standalone plan document before being
built — they were scoped conversationally, milestone by milestone, each
approved in chat before work started, and each closed with its own real
`docs/verification/M{n}-verification-pack.md`. This document reconstructs
that plan after the fact from the real commit history and the real packs,
so M9–M12 have the same documentation parity as M0–M8. **Nothing below was
planned in advance of being built** — it is an honest record of what was
decided and why, written after the work, not a claim that a plan existed
before the code did.

## Why M9–M12 exist at all

M0–M8 delivered the 8-milestone plan in full, closing with a genuinely
disclosed gap: mutation-testing coverage sat at 66.0% against Gate G8's own
75% threshold (`docs/verification/M8-verification-pack.md`). Rather than
stop there, the user and the assistant agreed on a 4-milestone follow-on
scope in the same conversation that closed M8 — this is recorded in project
memory, not in any committed doc until now:

> "go ahead with M9: audit + real `env_id`/persistent storage; M10:
> profile-driven config + DB source connectors wired into the API; M11:
> async job execution + collision workflow + lightweight auth; M12: UI
> catch-up + observability export + close the mutation-coverage gap"

Items #12–17 from an earlier, longer candidate list (non-Gregorian
calendars, `ScriptNormalizer` perf tuning, API versioning, etc.) were
explicitly excluded from this follow-on scope at the user's request and
were not resurrected in M9–M12.

## M9 — Audit, real `env_id`, persistent storage

**Commits:** `33cd6e9` (audit), `98a761b` (`env_id`), `4ba3525`
(persistence + pack).

M9 opened with an unbiased, from-scratch audit of M1–M8's own code
(explicitly requested by the user before new feature work started, echoing
the post-M7 self-audit pattern) — it found and fixed a real concurrency
race in `InMemoryStore._normalize_deduped()`'s cache-stats delta
(corruptible by concurrent requests, since `create_run` is a sync route
handler and Starlette really does dispatch those to a thread pool) plus two
latent `NormalizationCache.get_many()`/`put_many()` duplicate-key bugs.

Feature work: §73's version-locking `env_id` was real and tested since M1
but was a hardcoded placeholder in the live `Dispatcher` — wired for real,
live-verified stable across two independent process restarts. Postgres-
backed persistent storage for profiles and runs
(`InMemoryStore(postgres_dsn=...)`, `NORM_PG_DSN`) replaced pure in-memory
state, live-verified with a genuine process kill-and-restart.

**Disclosed boundary carried forward, later closed:** bulk per-value run
*results* did not yet survive a restart — that's ADR-013's sidecar Parquet
store, built in M1 but still unwired. Closed in the same session as a
follow-up (`53d0abf`) after the user asked what M9 had disclosed and
explicitly said "do #2 and #3 [mypy tests/ + sidecar wiring] and then
continue plan and go for M10."

## M10 — Profile-driven config + real source connectors

**Commit:** `daa642b` (plus `e28366a` for the config half).

Two deliverables, both closing gaps that had existed since much earlier
milestones without being acted on:

1. `NormalizationProfile.locale_policy` / field `locale_overrides` /
   `dictionary_refs` / `error_policy` were stored since M1 but never
   actually consulted when a run built its `NormalizationContext` — every
   context left `country`/`locale`/`dictionary_set` `None` regardless of
   profile config, even though several normalizers already branched real
   behavior on those fields. `NormalizationProfile.build_context()` closed
   this, live-proved with the same ambiguous date resolving differently
   under a US vs. GB locale profile with zero normalizer code touched.
2. `normio`'s five DB/file connectors were real and tested since M1 but
   never reachable from the live API — every run only accepted pasted
   `values`. `normapi.sources.SourceRegistry` wired all five in, reading
   from a server-side `NORM_SOURCES_CONFIG_PATH` JSON file (never a
   client-supplied DSN — the trust boundary ADR-017 now records reversing
   for the M13–M22 program). Synchronous execution with an explicit row
   cap (default 10k, max 100k) was a deliberate scoping choice, confirmed
   with the user before implementation, rather than waiting for M11's
   async work.

## M11 — Async execution, collision workflow, lightweight auth

**Commits:** `d680384` (async), `db1d369` (collisions), `295a54f` (auth),
`2b4cf38` (pack).

Confirmed at scoping time, by grepping `Source.txt` for
`async`/`queue`/`job`/`authentic`/`authoriz`/`RBAC`: async execution and
auth are **not** literal spec requirements — zero matches, and §123
Security is PII masking, not access control. Both are engineering-judgment
roadmap additions from an earlier planning conversation. The collision
workflow, by contrast, **is** a real, explicit §92 requirement ("Accept
rule / Reject rule / Inspect / Whitelist collision") that had only ever had
"Inspect" built, disclosed as a gap since M7.

`POST /runs` now returns immediately with a pollable `PENDING`→`RUNNING`→
terminal status via a background-thread wrapper around the still-
synchronous `execute_run()`. A real bug was caught before shipping (not
after): an early version double-transitioned a run to `RUNNING`, racing
`RunRecorder`'s own construction guard — fixed by removing the duplicate
transition. `CollisionDecisionType` (ACCEPTED/REJECTED/WHITELISTED),
Postgres-persisted, closed the §92 gap on the backend; UI wiring was
explicitly deferred to M12. Auth is one shared `NORM_API_KEY` gating only
mutating verbs, unset-disables, matching every other optional-integration
env var in this codebase.

**Disclosed boundaries carried into M12, still real today:** async
execution is one background thread per run, not a distributed queue; a
pre-existing double-start race (two concurrent calls for the same
`run_id`) was described but not newly fixed, since M11 didn't make it more
likely, just easier to name; auth has no rotation, expiry, or per-caller
identity.

## M12 — UI catch-up, observability export, mutation-coverage closure

**Commits:** `30dea98` (observability), `1c3e35e` (UI catch-up), `e6a2b4f`
(traceability update), `7f88739` (mutation-testing CI gate fix),
`7f940b2` (mutation-coverage test closure, committed retroactively during
M13 — see below).

Three deliverables:

1. **Observability export.** `setup_telemetry()`/`NormalizationMetrics`
   were real and tested since M1 but had zero call sites in `normapi` — the
   live API had emitted precisely zero telemetry ever. Wired
   `create_app()` to call `setup_telemetry()` at startup and `execute_run()`
   to call `record_run_metrics()` at completion. Also closed two more real
   gaps in the same file: missing counters `NormalizationMetrics`'s own
   docstring already claimed, and a promised-since-M1 OTLP export parameter
   that didn't exist — added real OTLP/HTTP export, live-verified against a
   local HTTP receiver. Found and fixed, in passing: `scripts/
   check_licenses.py` had been silently blocking on psycopg's LGPL-3.0
   license since M9, never added to the allow-list, never run by any
   verification pack's own Layer 1 checks.
2. **UI catch-up.** Wired the collision workflow buttons (real `POST` to
   the M11 decision route), source-mode run execution in the Runs page, and
   the M11 auth API key into Settings — live-verified against a real server
   that genuinely required the key.
3. **CI gate bug found and fixed.** `gate.yml`'s `mutation-testing` job was
   hardcoded `if: milestone == 'M8'` — it had silently never run for any
   milestone after M8, including M12 itself, the milestone whose own job is
   supposed to close that score. Fixed to check both M8 and M12.

**Mutation-coverage closure** (the fourth deliverable, real baseline
68.0%→ higher, exact final percentage pending a full unscoped run — see
`docs/verification/M12-verification-pack.md` §2 for the honest current
number) was completed in the same working session but its 14 file changes
sat **uncommitted** in the working tree across a context-window boundary.
Found and committed during M13's ledger catch-up (`7f940b2`) rather than
left silently stranded — all 17 ranked-survivor `.normalize()` methods from
the real mutmut baseline (`PostcodeNormalizer` through `GenericTextNormalizer`)
now have comprehensive exact-field tests, each closure backed by real
scoped-Docker mutmut verification, with every equivalent/dead-code mutant
documented via source-level proof rather than guessed at. One real
production bug was found and fixed in the process: `URLNormalizer`
accessed `SplitResult.port` (a lazy property that raises on a malformed
port) outside the `try/except` that caught `urlsplit()`'s own errors — one
bad URL in a batch could have crashed an entire async run.

## What M9–M12 did *not* do (carried into the M13–M22 program)

None of M9–M12 touched: the UI's 11-tab structure (still exposes internal
engine vocabulary, not a task-oriented flow); connection management (still
a hand-edited JSON file, no write endpoint); multi-column runs (a run is
still exactly one column); a destination for normalized output (results are
only ever readable through report endpoints); real streaming execution at
scale (a source-mode run still materializes its whole column into memory,
capped at 100k rows). These are exactly the gaps `docs/plan/
M13-M22-program-plan.md` exists to close.

## Sign-off status as of this writing

Every milestone pack from M0 through M11 has a **blank** `## Human
Sign-off` block — this was found to be genuinely true of the whole
repository during M13's ledger catch-up, not a gap specific to any one
milestone. `scripts/check_signoff.py`'s own gate logic (`--milestone M9`
would have failed argparse validation outright before this M13 fix, since
`MILESTONE_ORDER` stopped at M8) confirms the gate has never actually been
satisfied end-to-end for any milestone in this repository's committed
history. This is disclosed here, not silently left for a future session to
rediscover. Sign-off blocks are intentionally left blank for the user to
fill in — no pack in this project's history has ever had that block
completed on the author's behalf, and this document does not change that.

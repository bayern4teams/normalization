# Prompt 1 — API: start-up memory and raw values

Give this text to a new session in `/home/bayern/Projects/normalization`.

---

You build items D25, D16, D17, D18 and D19 of `docs/improvement-report.md`, Part 1, round 3, in
that order. D25 comes first because it froze the owner's PC twice.

Read first, in this order:

1. `AGENTS.md`, all of it.
2. `docs/plans/round3/README.md`, "Rules every prompt adds to AGENTS.md". Follow every rule.
3. `docs/improvement-report.md`: §0 "Round 3 constraints", the D16-D24 table, and the D25-D32
   table.
4. `docs/plans/round2/FINAL_REPORT.md` §5.6, the diagnosis and fix options for D25.
5. `docs/adr/ADR-022-network-and-database-address-policy.md` and ADR-023 (R23, raw values).

Per item:

- **D25.** FINAL_REPORT §5.6 option 1 in `normapi/adjudication.py::migrate_sources`: select only
  the rows that need migrating, read them with a psycopg server-side cursor. Prove it on a
  metadata database with at least 1M queue rows, created as `norm_app_r3_*`, on the benchmark
  machine: the API answers `/health` under `MemoryMax=1G`. Record the memory you measured.
- **D16.** The owner's rule (report D16): a raw value appears only in the direct answer to the
  caller who sent it. Mask job error text, `/runs/{id}/values` and logs. `/preview` and
  `/field-test` may echo their input. `disguised_missing[].value` stays raw ("d16. c"). One test
  per route and log path, each with a planted value.
- **D17.** Reject a `Host` header with userinfo or anything but a host and an optional port,
  before `TrustedHostMiddleware`. Test: `Host: localhost:80@evil.com` gives 400.
- **D18.** Parse `NORM_ALLOWED_NETWORKS` at start-up; a bad entry stops the API with a message
  naming the entry and how to fix it.
- **D19.** `PATCH /clone-jobs/{id}/plan` forbids unknown keys, as `POST` does: 422.

Stop and ask the owner when a fix needs a new dependency, changes an ADR's decision (not only
its wording), or when D16's masking would hide something the review screen needs.

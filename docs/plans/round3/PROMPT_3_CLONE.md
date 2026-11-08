# Prompt 3 — clone: sort keys, connections, tables, autodetect, column types

Give this text to a new session in `/home/bayern/Projects/normalization`.

---

You build items D26, D22, D23, D31 and D32 of `docs/improvement-report.md`, Part 1, round 3, in
that order. D26 comes first: the owner's ClickHouse benchmark variant fails until it is fixed.

Read first, in this order:

1. `AGENTS.md`, all of it.
2. `docs/plans/round3/README.md`, "Rules every prompt adds to AGENTS.md". Follow every rule.
3. `docs/improvement-report.md`: §0 (Q31: ClickHouse 26.4.2.10 on the owner's server), the
   D16-D24 table (D22, D23) and the D25-D32 table.
4. `docs/research/resources/_raw-clone-detect-throughput-findings.md`.
5. ADR-017 (clone scope), ADR-020 (typed destination), ADR-022 (addresses).

Per item:

- **D26.** Parse `system.tables.sorting_key` by its syntax in
  `normio/connectors/clickhouse.py::get_table_engine_info`, as the D26 row says. Prove it live
  on the benchmark machine's ClickHouse: tables with `ORDER BY (id)`, `(a, b)`, an expression
  key and `tuple()`, each cloned and its destination `ORDER BY` compared with the source's by
  direct SQL. Record the ClickHouse version you tested on.
- **D22.** Refuse an origin and a destination that resolve to the same address, port and
  database, under any host names.
- **D23.** A table list on clone-job create, checked against the origin, and the UI's table
  picker (Playwright test, API stubbed as the other specs do).
- **D31.** The D31 row, exactly. Keep the 0.9 apply line. Never infer NUMERIC or FREE_TEXT from
  values alone.
- **D32.** Amend ADR-020's sentence to cover configured columns only. **The key-column case is
  not decided:** if the D32 row still says "waits for the owner (B8b)", amend only the
  sentence, change no code, and tell the owner.

Stop and ask the owner when a sort key cannot be copied safely and the report does not say what
the job should do, or when a fix changes what an existing clone writes.

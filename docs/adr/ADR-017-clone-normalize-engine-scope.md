# ADR-017: DB-Clone-and-Normalize — Postgres/ClickHouse Scope, MySQL/Mongo/File Deferred

## Status
Accepted — 2026-09-14. Documentation only for §Deferred below — not implemented.

## Context

The DB-clone-and-normalize feature (point the app at a real origin
database, clone its schema, stream+normalize+populate a destination) was
scoped, through explicit user decisions, to **Postgres and ClickHouse
only** — both as origin and destination, always the same engine. `normio`
already has read-only connectors for MySQL and MongoDB too (and a
file-based connector with no "server" concept at all), but wiring the
clone feature to those was suspended pending user approval to continue
after Postgres+ClickHouse ship. This ADR records why each is deferred
rather than trivially extended, so a future implementer starts from real
constraints instead of re-discovering them.

## Decision

Implement Phase 1 (schema clone) and Phase 2 (stream+normalize+populate)
for Postgres and ClickHouse only. Do not implement MySQL/Mongo/File.

## Deferred: MySQL

`normio`'s MySQL read connector reuses the same `_sql_base.py` SQLAlchemy
machinery as Postgres, so a read side would look similar. Two real gaps
block a same-shape write side:

- **No session-level read-only guarantee.** `PostgresConnector` sets
  `execution_options={"postgresql_readonly": True}` — a genuine, driver-
  enforced read-only transaction mode. MySQL/`pymysql` has no equivalent
  session flag; the origin-must-never-be-written guarantee would fall back
  to DB-grant-only enforcement (a `SELECT`-only user), which is real but
  weaker than Postgres's defense-in-depth (interface shape + DB grants +
  session-level enforcement, per `normio/connector.py`'s docstring).
- **No `PostgresDestination`-shaped DDL story.** MySQL has no `pg_database`-
  style catalog query for `database_exists`, and its `CREATE TABLE`
  dialect (`ENGINE=InnoDB`, `AUTO_INCREMENT`, backtick-vs-doublequote
  identifier quoting) is different enough from both the Postgres and
  ClickHouse destination writers that it needs its own DDL builder, not a
  small extension of either.

## Deferred: MongoDB

Decision #11 (replicate primary keys/indexes on Postgres, ORDER BY/engine
on ClickHouse) assumes a fixed, discoverable per-table column schema —
true for every SQL-family origin, false for MongoDB. A collection's
documents are schema-on-read; "clone the schema, then populate it"
doesn't map onto that without a document-shape-inference step (sample N
documents, union their field sets, guess a type per field) that doesn't
exist anywhere in this codebase today. Building that inference step well
enough to trust for a real clone (nested documents, arrays, mixed types
across documents) is a materially larger feature than extending the
Postgres/ClickHouse writers, not a small one.

## Deferred: File

`FileConnector` has no "server" (host+port+credentials) concept at all —
decisions #1 (server-level database discovery), #2 (a second credential,
same server), and #13 (server-level saved connections) all assume a
server to connect to. A file-based "clone" is really "pick a file, pick a
destination, populate it" — a different UX shape (no connection CRUD, no
database/table discovery dropdown chain), not a small extension of the
connection-based flow this feature builds.

## Revisit trigger

Any of the above becomes real scope once a user explicitly approves
continuing past Postgres+ClickHouse. At that point: MySQL needs its own
destination writer (own DDL builder, DB-grant-only read enforcement
documented as a known weaker guarantee); MongoDB needs a document-shape-
inference step before "clone the schema" means anything; File needs a
different page flow, not a third branch bolted onto the connection-based
one.

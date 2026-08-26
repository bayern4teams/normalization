"""A small versioned migration runner for Postgres — M15 of the
M13-M22 program.

Real, previously-unpaid debt: every table this project has added to
Postgres so far (`profiles`, `runs`, `collision_decisions` in
`postgres_store.py`) used `CREATE TABLE IF NOT EXISTS`, which can only
ever create a table that doesn't exist yet — it cannot express "add a
column to a table that might already have rows" on an existing
deployment. Six new tables land across M15-M20 (connections,
column_mappings, run_columns, run_chunks, source_watermarks, plus a
normalization_issues-style side table per M19) and the DuckDB sidecar
catalog gains a real schema change in M17 — this milestone is where that
finally gets a real mechanism instead of another `IF NOT EXISTS`.

Deliberately NOT Alembic (per the M13-M22 plan's explicit instruction):
this project's migrations are few, small, and hand-written; Alembic's
autogeneration/branching machinery is more apparatus than this actually
needs. A migration here is just a name and a function that runs raw SQL
against one psycopg connection, tracked in a `schema_migrations` table
keyed by name so it never re-applies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    import psycopg


@dataclass(frozen=True, slots=True)
class Migration:
    name: str
    apply: Callable[[psycopg.Connection], None]


def run_migrations(conn: psycopg.Connection, migrations: list[Migration]) -> list[str]:
    """Applies every migration in `migrations` not already recorded in
    `schema_migrations`, in list order, each in its own transaction (this
    project's Postgres connections are opened `autocommit=True`, matching
    `PostgresMetadataStore`'s own model — a migration that raises leaves
    every migration before it applied and committed, which is the
    correct, expected behavior for a linear migration list). Returns the
    names actually applied this call (empty on a second run against the
    same database — the real proof migrations don't re-apply)."""
    with conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "  name VARCHAR PRIMARY KEY,"
            "  applied_at TIMESTAMPTZ NOT NULL DEFAULT now()"
            ")"
        )
        cur.execute("SELECT name FROM schema_migrations")
        already_applied = {row[0] for row in cur.fetchall()}

    applied_now: list[str] = []
    for migration in migrations:
        if migration.name in already_applied:
            continue
        migration.apply(conn)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO schema_migrations (name) VALUES (%s)",
                (migration.name,),
            )
        applied_now.append(migration.name)
    return applied_now

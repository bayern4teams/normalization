-- Seeds a tiny demo table and provisions a GENUINELY restricted
-- read-only role. This is what tests/integration/test_readonly_connectors.py
-- verifies against: an actual database-level rejection of writes, not just
-- an absence of a write method in our own connector code.

CREATE TABLE IF NOT EXISTS customers (
    id SERIAL PRIMARY KEY,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    email TEXT
);

INSERT INTO customers (first_name, last_name, email) VALUES
    ('  John  ', 'Smith', 'john.smith@example.com'),
    ('José', 'García', 'jose.garcia@example.com'),
    ('JOHN', 'SMITH', NULL);

CREATE ROLE readonly_user WITH LOGIN PASSWORD 'readonly_pass';
GRANT CONNECT ON DATABASE source_demo TO readonly_user;
GRANT USAGE ON SCHEMA public TO readonly_user;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO readonly_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO readonly_user;
-- Explicitly no INSERT/UPDATE/DELETE/TRUNCATE/CREATE grants of any kind.

-- DB-clone-and-normalize feature: a second, write-capable role for the
-- CLONE DESTINATION side (decision #2 — never the same credential as the
-- read-only origin above). CREATEDB is the one elevated right the app's
-- own flow actually needs the *user* to have (decision #6: the app itself
-- never issues CREATE DATABASE — the user runs it by hand with this
-- role); Postgres makes the creator of a database its owner, so no
-- further per-object grants are needed for writable_user to then create
-- tables/insert rows in whatever new database it creates.
CREATE ROLE writable_user WITH LOGIN PASSWORD 'writable_pass' CREATEDB;

-- A dedicated table for tests/integration/test_clone_pipeline.py, kept
-- separate from `customers` above (whose row count/values other tests in
-- this suite already assert on). One deliberately-invalid email exercises
-- decision #8 (fallback-to-original + a recorded error), one valid email
-- exercises real normalization producing a real destination-side diff.
-- `founded` (text, deliberately not a real date on one row) reproduces a
-- real bug found running this feature against messy real-world data: a
-- failed DATE-configured value's fallback (decision #8) couldn't be
-- inserted into a native DATE destination column, crashing the whole
-- job — see SEMANTIC_TYPE_TO_PG_TYPE's docstring. The value has to be one
-- DateNormalizer genuinely cannot read: a sentinel letter glued to a real
-- date (`d1989-12-11`) is now repaired, so it no longer exercises the
-- failure path this row exists for.
CREATE TABLE IF NOT EXISTS clone_source (
    id SERIAL PRIMARY KEY,
    email TEXT,
    founded TEXT
);

INSERT INTO clone_source (email, founded) VALUES
    ('Valid.User@EXAMPLE.com', '1989-12-11'),
    ('not-an-email', 'no-date-here');

GRANT SELECT ON clone_source TO readonly_user;

-- A dedicated table for the TYPED-destination-column tests (§7/§8).
-- Every column is TEXT at source, which is the real-world case: the whole
-- point of `typed_destination_columns` is that a messy text column becomes
-- a summable native one. Each row exercises a different outcome:
--   1: values that normalize and cast cleanly
--   2: a different locale's separators, and a currency named rather than
--      symbolised, both of which must reach the SAME native value
--   3: values that cannot cast (-> NULL + an error row) and a boolean that
--      means "missing" rather than true/false (-> NULL, which used to be
--      recorded nowhere at all)
CREATE TABLE IF NOT EXISTS typed_source (
    id SERIAL PRIMARY KEY,
    amount TEXT,
    price TEXT,
    active TEXT
);

INSERT INTO typed_source (amount, price, active) VALUES
    ('1,234.56', '€1.234,56', 'yes'),
    ('1.234,56', '1234.56 USD', 'NO'),
    ('not-a-number', 'free', 'maybe');

GRANT SELECT ON typed_source TO readonly_user;

-- In-place normalization (decision: swap a staging table in) needs a
-- database the app may WRITE to, which source_demo deliberately is not.
-- writable_user has CREATEDB, so the test creates and seeds its own.

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
CREATE TABLE IF NOT EXISTS clone_source (
    id SERIAL PRIMARY KEY,
    email TEXT
);

INSERT INTO clone_source (email) VALUES
    ('Valid.User@EXAMPLE.com'),
    ('not-an-email');

GRANT SELECT ON clone_source TO readonly_user;

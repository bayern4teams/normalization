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

-- A dedicated table for the normalization-CONTEXT tests. Several
-- normalizers refuse to guess without a country, and a COUNTRY column in
-- the same row is the answer they were refusing for lack of:
--   1: country resolves (US), so `zip` is validated as a US postcode
--   2: same, and the zip is deliberately not a US format -> a reported
--      INVALID, which is only reachable IF the country propagated
--   3: two COUNTRY columns that contradict each other (GB vs DE) ->
--      reported, and NEITHER is used, so this row's zip stays AMBIGUOUS
--      even though the zip itself is a perfectly good GB postcode
--   4: no country anywhere -> the pre-propagation behaviour
-- `active` exists to be emptied: 2 of its 4 values are neither true nor
-- false, which is what the column-level null-rate report is for.
CREATE TABLE IF NOT EXISTS context_source (
    id SERIAL PRIMARY KEY,
    country TEXT,
    other_country TEXT,
    zip TEXT,
    active TEXT
);

INSERT INTO context_source (country, other_country, zip, active) VALUES
    ('United States',  'US',      '94043',     'yes'),
    ('United States',  'US',      'SW1A 1AA',  'no'),
    ('United Kingdom', 'Germany', 'SW1A 1AA',  'maybe'),
    (NULL,             NULL,      '94043',     'n/a');

GRANT SELECT ON context_source TO readonly_user;

-- Two tables for the CROSS-TABLE country test. The country lives in one
-- table and the value that needs a country to parse lives in the other,
-- joined on an entity id — the shape Phase 2 cannot see within a row,
-- because it streams one table at a time and never holds two.
--
-- `entity_country.country_name` is deliberately mapped to COUNTRY while
-- holding Wikidata-style DESCRIPTIONS for one entity, reproducing a real
-- source where 99.2% of a COUNTRY-mapped column came back INVALID. That
-- entity therefore contributes nothing to the map, which is the point:
-- the map is built from what resolves, not from what was configured.
--
-- Note the entity id is TEXT here and INTEGER in entity_phone: on a real
-- source the same id was String in one table and Nullable(Int64) in
-- another, so the map has to be keyed by a form both agree on.
CREATE TABLE IF NOT EXISTS entity_country (
    id SERIAL PRIMARY KEY,
    company_key TEXT,
    country_name TEXT
);

INSERT INTO entity_country (company_key, country_name) VALUES
    ('11', 'United Kingdom'),
    ('11', 'GB'),                                    -- agrees, no conflict
    ('22', 'Germany'),
    ('33', 'France'),
    ('33', 'Italy'),                                 -- disagrees -> dropped
    ('44', 'Country located primarily in North America');  -- not a country

CREATE TABLE IF NOT EXISTS entity_phone (
    id SERIAL PRIMARY KEY,
    company_key INTEGER,
    tel TEXT
);

INSERT INTO entity_phone (company_key, tel) VALUES
    (11, '020 7930 4832'),   -- only parseable as GB, which only the map knows
    (22, '030 2643 1234'),   -- only parseable as DE
    (33, '01 42 60 30 30'),  -- entity 33 conflicted -> no country -> AMBIGUOUS
    (44, '0118 496 0000'),   -- entity 44 never resolved -> AMBIGUOUS
    (11, '+1 650-253-0000'); -- self-describing; the map must not break it

GRANT SELECT ON entity_country TO readonly_user;
GRANT SELECT ON entity_phone TO readonly_user;

-- A table big enough for the wrong-semantic-type finding, which needs
-- enough values for its fraction to mean anything (see
-- _TYPE_MISMATCH_MIN_VALUES). Kept separate from the tables above for the
-- same reason they are separate from each other: other tests assert on
-- their row counts.
CREATE TABLE IF NOT EXISTS mistyped_source (
    id SERIAL PRIMARY KEY,
    looks_like_a_country TEXT
);

INSERT INTO mistyped_source (looks_like_a_country)
SELECT 'Country located primarily in North America ' || i FROM generate_series(1, 25) AS i;

GRANT SELECT ON mistyped_source TO readonly_user;

-- The entity map's signal sources beyond a COUNTRY column. Neither table
-- here has a COUNTRY column at all: the country comes from a phone that
-- carries its own +CC and from a postcode only one country's format
-- accepts, and reaches the OTHER table through the entity id.
--
--   entity 1: phone says +44 -> GB, so `zip` is validated as GB. The zip
--             is a valid GB postcode, so it passes.
--   entity 2: postcode 'M5V 3L9' is Canadian and nothing else, so the
--             bare local phone parses as CA.
--   entity 3: phone has no +CC and the postcode is a bare five-digit
--             number valid in 56 countries — no signal either way, which
--             is the honest answer rather than the most populous guess.
CREATE TABLE IF NOT EXISTS signal_phone (
    id SERIAL PRIMARY KEY,
    entity_key INTEGER,
    tel TEXT
);

INSERT INTO signal_phone (entity_key, tel) VALUES
    (1, '+44 20 7930 4832'),
    (2, '416 392 2489'),
    (3, '555 0100');

CREATE TABLE IF NOT EXISTS signal_zip (
    id SERIAL PRIMARY KEY,
    entity_key TEXT,
    zip TEXT
);

INSERT INTO signal_zip (entity_key, zip) VALUES
    ('1', 'SW1A 1AA'),
    ('2', 'M5V 3L9'),
    ('3', '94043');

GRANT SELECT ON signal_phone TO readonly_user;
GRANT SELECT ON signal_zip TO readonly_user;

-- #8: a table whose PRIMARY KEY is a textual column of a detectable
-- semantic type. Inferring EMAIL here and normalizing it would fold two
-- distinct keys into one — on a real source this exact shape existed
-- (`PersonContact`'s whole sorting key was an email column).
CREATE TABLE IF NOT EXISTS keyed_email (
    contact_email TEXT PRIMARY KEY,
    work_email TEXT
);

-- The first two differ ONLY in the domain's case, which EMAIL
-- normalization folds (the local part is case-sensitive per RFC 5321, the
-- domain is not). So they are two distinct keys with one normalized form —
-- exactly the collision the exclusion exists to prevent.
INSERT INTO keyed_email (contact_email, work_email) VALUES
    ('ada@EXAMPLE.COM', 'ada@EXAMPLE.COM'),
    ('ada@example.com', 'ada@example.com'),
    ('grace@Example.com', 'grace@Example.com');

-- #9/#13: one table whose columns land in three different outcomes, so a
-- quality report has something to distinguish. `zip_no_country` is
-- AMBIGUOUS (a postcode with no country is not a failure), `amount` is
-- NORMALIZED, `bad_country` is INVALID.
CREATE TABLE IF NOT EXISTS quality_source (
    id SERIAL PRIMARY KEY,
    zip_no_country TEXT,
    bad_country TEXT,
    messy_company TEXT
);

INSERT INTO quality_source (zip_no_country, bad_country, messy_company) VALUES
    ('94043', 'Country located primarily in North America', 'Acme  Corporation'),
    ('SW1A 1AA', 'A sovereign state in Western Europe', 'Globex   Inc.'),
    ('M5V 3L9', 'Not a country at all', 'Initech—Systems'),
    ('10115', 'United States', 'Umbrella  Corp');

GRANT SELECT ON keyed_email TO readonly_user;
GRANT SELECT ON quality_source TO readonly_user;

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

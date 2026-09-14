-- Seeds a tiny demo table. Runs as ClickHouse's default admin user (full
-- access by default) — the actual read-only enforcement for `readonly_user`
-- comes from users.xml (mounted separately), which sets readonly=1 in that
-- user's profile: ClickHouse rejects any non-SELECT query server-side for
-- a connection using that profile, regardless of what SQL is sent.

CREATE TABLE IF NOT EXISTS customers (
    id UInt32,
    first_name String,
    last_name String,
    email Nullable(String)
) ENGINE = MergeTree() ORDER BY id;

INSERT INTO customers (id, first_name, last_name, email) VALUES
    (1, '  John  ', 'Smith', 'john.smith@example.com'),
    (2, 'José', 'García', 'jose.garcia@example.com'),
    (3, 'JOHN', 'SMITH', NULL);

-- A dedicated table for tests/integration/test_clone_pipeline.py, kept
-- separate from `customers` above. One deliberately-invalid email
-- exercises decision #8 (fallback-to-original + a recorded error), one
-- valid email exercises real normalization producing a real
-- destination-side diff.
CREATE TABLE IF NOT EXISTS clone_source (
    id UInt32,
    email Nullable(String)
) ENGINE = MergeTree() ORDER BY id;

INSERT INTO clone_source (id, email) VALUES
    (1, 'Valid.User@EXAMPLE.com'),
    (2, 'not-an-email');

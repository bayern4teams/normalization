-- Seeds a tiny demo table and provisions a GENUINELY restricted
-- read-only user. Verified against in
-- tests/integration/test_readonly_connectors.py.

CREATE TABLE IF NOT EXISTS customers (
    id INT AUTO_INCREMENT PRIMARY KEY,
    first_name VARCHAR(255) NOT NULL,
    last_name VARCHAR(255) NOT NULL,
    email VARCHAR(255)
);

INSERT INTO customers (first_name, last_name, email) VALUES
    ('  John  ', 'Smith', 'john.smith@example.com'),
    ('José', 'García', 'jose.garcia@example.com'),
    ('JOHN', 'SMITH', NULL);

CREATE USER IF NOT EXISTS 'readonly_user'@'%' IDENTIFIED BY 'readonly_pass';
GRANT SELECT ON source_demo.* TO 'readonly_user'@'%';
-- Explicitly no INSERT/UPDATE/DELETE/CREATE/DROP grants of any kind.
FLUSH PRIVILEGES;

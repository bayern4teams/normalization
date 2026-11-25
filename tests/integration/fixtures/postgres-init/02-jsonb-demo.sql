-- jsonb_demo: a dedicated source database for
-- tests/integration/test_jsonb_clone_live.py (the live `company.aliases`
-- incident: a jsonb column whose chunks are all-lists or all-dicts — the
-- shapes that made Arrow SUCCEED, so the Python dict/list reached the
-- destination INSERT and psycopg adapted a list to a SQL array:
-- `invalid input syntax for type json`, whole-job InvalidTextRepresentation).
--
-- A separate database, so the existing clone tests (which clone EVERY
-- table of source_demo and assert its row counts) never see these rows.
--
-- NOTE: postgres-init/ only runs on a fresh volume; on an already-existing
-- demo volume apply this file once:
--   docker compose up -d demo-postgres
--   docker exec -i -e PGPASSWORD=*** normalization-demo-postgres-1 \
--     psql -U source_admin -d postgres < tests/integration/fixtures/postgres-init/02-jsonb-demo.sql
-- (minus the CREATE ROLE lines, which 01-init.sql already ran).

CREATE DATABASE jsonb_demo;

\connect jsonb_demo

CREATE TABLE jsonb_source (
    id int PRIMARY KEY,
    payload jsonb,  -- mixed shapes: list / dict / null (Arrow fallback path)
    tags jsonb      -- 4000 rows: first SOURCE_READ_BATCH all lists, second all dicts
                    -- (Arrow succeeds — the bug's actual shape)
);

INSERT INTO jsonb_source
SELECT i,
       CASE WHEN i % 3 = 0 THEN '["A","B"]'::jsonb
            WHEN i % 3 = 1 THEN '{"k":1}'::jsonb
            ELSE NULL END,
       CASE WHEN i <= 2000 THEN '["x"]'::jsonb
            ELSE '{"deep":{"n":[1,2]}}'::jsonb END
FROM generate_series(1, 4000) t(i);

GRANT CONNECT ON DATABASE jsonb_demo TO readonly_user;
GRANT USAGE ON SCHEMA public TO readonly_user;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO readonly_user;

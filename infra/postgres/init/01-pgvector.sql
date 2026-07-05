-- Infra bootstrap for fresh volumes only. M1's first Alembic migration MUST
-- also run `CREATE EXTENSION IF NOT EXISTS vector` so databases not created
-- via docker-entrypoint-initdb.d (CI, managed PG) are covered.
CREATE EXTENSION IF NOT EXISTS vector;

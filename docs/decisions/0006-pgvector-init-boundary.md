# ADR 0006 — pgvector: infra bootstrap vs Alembic boundary

**Status:** accepted (M0)

**Context.** CLAUDE.md: migrations via Alembic only. But a fresh Postgres
volume needs the `vector` extension before any migration can use it, and
extension installation requires superuser — an infra concern, not app schema.

**Decision.** `infra/postgres/init/01-pgvector.sql` runs
`CREATE EXTENSION IF NOT EXISTS vector` via docker-entrypoint-initdb.d
(fresh volumes only). M1's FIRST Alembic migration must ALSO run the same
idempotent statement so databases not created through initdb (CI throwaway
DBs, future managed Postgres) are covered. App tables/indexes remain
Alembic-only, no exceptions.

**Consequences.** The extension exists on every path; blueprint-reviewer
rule 7 treats extension bootstrap as infra, not an app schema change.

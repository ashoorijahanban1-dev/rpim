# ADR 0008 — M1 identity & tenancy core

**Status:** accepted (M1)

**Decisions.**
- **One user ↔ one tenant in M1** (`users.tenant_id` FK). Multi-seat
  memberships arrive with the approval-queue milestone that needs them;
  adding a join table later is a additive migration.
- **tenant_id comes ONLY from the verified JWT** (`get_identity` dep) —
  never from client-supplied params. Every query on tenant data filters by
  it (rule 6); the acceptance test proves isolation black-box via the API.
- **Auth:** JWT HS256 signed with `JWT_SECRET` (env), 12h TTL; bcrypt
  password hashes; password min length 8 (fixture detail, hardening in M10).
- **Tests run on sqlite in-memory** (StaticPool) so the PostToolUse
  `make test` hook stays docker-free and <5s. `init_db()`/create_all is
  test-only; production schema changes are **Alembic-only** — the core-api
  container runs `alembic upgrade head` before serving (Dockerfile CMD).
  Migration 0001 also executes `CREATE EXTENSION IF NOT EXISTS vector`
  (postgres-only guard) per ADR 0006.
- `DATABASE_URL` with plain `postgresql://` scheme is normalized to
  `postgresql+psycopg://` in code so env files stay driver-agnostic.

**Still open in M1:** conversational onboarding interview (M1 scope, next
iteration) and dashboard register/login screens (thin UI over these APIs).

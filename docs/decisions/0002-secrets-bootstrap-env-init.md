# ADR 0002 — Secrets bootstrap: env-init generates, never copies

**Status:** accepted (M0)

**Context.** Rule 4: secrets never in code/repo/sessions; env var NAMES only.
Copying `.env.*.example` verbatim would boot production with blank/placeholder
secrets and an unbootable Postgres (no `POSTGRES_PASSWORD`).

**Decision.** `make env-init` copies the examples to gitignored `.env.iran` /
`.env.us`, then GENERATES every secret-shaped field (`APP_SECRET_KEY`,
`JWT_SECRET`, `INTERNAL_TOKEN`, `POSTGRES_PASSWORD`) with
`openssl rand -hex 32`, composes `DATABASE_URL` (in-compose host `postgres`),
and syncs `INTERNAL_TOKEN` across both legs. CI generates ephemeral values the
same way. Compose files contain only `${VAR}` interpolation and service
hostnames (hostnames are not secrets). On real servers, values live in the
Coolify UI, not in files this repo manages.

**Consequences.** No blank-secret deploys; `docker compose config` works with
or without env files (`required: false`).

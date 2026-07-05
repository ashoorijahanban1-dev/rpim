# ADR 0005 — Workers health contract (non-HTTP /health equivalent)

**Status:** accepted (M0)

**Context.** CLAUDE.md: "Every service exposes /health". A Celery worker has
no HTTP surface; adding one just for the rule would be scaffolding theater.

**Decision.** For non-HTTP services the approved /health equivalent is the
compose healthcheck `celery -A rpim_workers.celery_app inspect ping` with
`start_period: 30s` (worker cold-start is slow) and generous intervals.
Nothing `depends_on` workers being healthy. HTTP services keep literal
`GET /health` returning the shared `rpim_shared.HealthStatus` contract.
The dashboard serves it at `/api/health` (Next.js route handler); the iran
Caddy maps public `/health` to core-api.

**Consequences.** blueprint-reviewer should treat `inspect ping` as
satisfying the /health rule for queue workers in later milestones too.

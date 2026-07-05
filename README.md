# RPIM — Realistic Persian Intelligent Marketer

Agentic marketing system for Persian-language brands. Architecture, rules and
milestones: [`CLAUDE.md`](CLAUDE.md) · [`docs/RPIM-Blueprint-v1.2.md`](docs/RPIM-Blueprint-v1.2.md) ·
[`docs/RPIM-Blueprint-Web.html`](docs/RPIM-Blueprint-Web.html) (§6.4 = build milestones).

## Layout

Two legs (blueprint §2): **iran** (dashboard, core-api, Postgres+pgvector,
Redis, workers) and **us** (model-gateway, Redis). Legs talk over WireGuard.
`infra/docker-compose.{iran,us}.yml` are the deployable units.

## Local dev / CI

```bash
make env-init     # generates gitignored .env.iran/.env.us (secrets via openssl rand)
make up-iran      # iran leg on localhost:8001 (local-profile Caddy)
make up-us        # us leg — gateway on localhost:8080
make healthcheck  # MODE=local|crossleg-ci|wg (default local)
make test         # fast, docker-free — the PostToolUse hook runs this on every edit
make lint fmt
```

No docker on your machine? CI runs the same thing: the `smoke` job brings both
legs up and runs the two-way `crossleg-ci` healthcheck on every push.

## Production deploy (Coolify)

Coolify is the deploy path on the real servers; its proxy owns 80/443, so the
`local` compose profile (our Caddy) is **not** enabled there.

1. In Coolify create two **Docker Compose** resources from this repo:
   - iran server → `infra/docker-compose.iran.yml`
   - us server → `infra/docker-compose.us.yml`
2. Set environment variables in the Coolify UI (values live ONLY there —
   CLAUDE.md rule 4). Names: see `.env.iran.example` / `.env.us.example`.
   Critical: `INTERNAL_TOKEN` must be identical on both legs;
   `CORE_BIND=10.66.0.1` (iran) and `GATEWAY_BIND=10.66.0.2` (us) so the
   gateway is reachable **only** over WireGuard, never publicly.
3. WireGuard: copy `infra/wireguard/wg0.*.conf.example` to each server,
   fill real keys there, `wg-quick up wg0`.
4. Auto-deploy from CI: add repo **secret** `COOLIFY_TOKEN` (create a
   least-privilege deploy token in Coolify — not root) and repo **variables**
   `COOLIFY_URL`, `COOLIFY_IRAN_UUID`, `COOLIFY_US_UUID` (the two resource
   UUIDs). The deploy job stays skipped until these exist.
   ⚠️ Serve the Coolify panel over HTTPS before creating tokens.
5. Verify from the iran server: `MODE=wg GATEWAY_URL=http://10.66.0.2:8080 \
   CORE_API_URL=http://10.66.0.1:8000 bash scripts/crossleg-healthcheck.sh wg`

## Non-negotiables (short form — full list in CLAUDE.md)

Human-in-the-loop by default · silence flag checked inside every publisher ·
no publish without full metadata+UTM · secrets never in code/repo/session ·
official APIs only · absolute tenant isolation · kill switch <5s ·
apprentice A0 logging from day one.

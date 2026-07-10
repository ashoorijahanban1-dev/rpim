# RPIM — Realistic Persian Intelligent Marketer

Agentic marketing system for Persian-language brands. Architecture, rules and
milestones: [`CLAUDE.md`](CLAUDE.md) · [`docs/RPIM-Blueprint-v1.2.md`](docs/RPIM-Blueprint-v1.2.md) ·
[`docs/RPIM-Blueprint-Web.html`](docs/RPIM-Blueprint-Web.html) (§6.4 = build milestones).

## Layout

Two logical legs (blueprint §2): **iran** (dashboard, core-api,
Postgres+pgvector, Redis, workers) and **us** (model-gateway, Redis).
`docker-compose.{iran,us}.yml` are the deployable units.

> **Topology note (ADR 0025):** the Iran VPS is suspended — both legs deploy
> as separate Coolify resources on the single US server. WireGuard setup and
> the `wg` healthcheck mode are on hold; the two-leg architecture itself is
> unchanged and the split can be restored without code changes.

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

1. In Coolify create two **Docker Compose** resources from this repo
   (`scripts/coolify-provision.sh` does this idempotently) — both on the US
   server while the Iran VPS is suspended (ADR 0025):
   - `rpim-iran-leg` → `docker-compose.iran.yml`
   - `rpim-us-leg` → `docker-compose.us.yml`
2. Set environment variables in the Coolify UI (values live ONLY there —
   CLAUDE.md rule 4). Names: see `.env.iran.example` / `.env.us.example`.
   Critical: `INTERNAL_TOKEN` must be identical on both legs. Single-server:
   keep loopback binds and point `GATEWAY_URL` / `CORE_API_URL` at the
   co-located leg. (Split topology, when restored: `CORE_BIND=10.66.0.1`,
   `GATEWAY_BIND=10.66.0.2` so the gateway is reachable **only** over
   WireGuard, never publicly.)
3. ~~WireGuard~~ — suspended (ADR 0025). Stubs stay in `infra/wireguard/`
   for when the Iran VPS returns; do not set it up now.
   **One-time per server (ADR 0029):** `docker network create rpim-crossleg`
   (Coolify UI → Server → Terminal) — cross-leg traffic rides this shared
   network on the single server.
4. Auto-deploy from CI: add repo **secret** `COOLIFY_TOKEN` (create a
   least-privilege deploy token in Coolify — not root); resource UUIDs are
   read from `infra/coolify-uuids.conf`. The deploy job self-skips until
   these exist.
   ⚠️ Serve the Coolify panel over HTTPS before creating tokens.
5. Verify: `make healthcheck` locally, or the CI `smoke` job (two-way
   `crossleg-ci` mode). The `wg` verification mode is suspended with the
   tunnel (ADR 0025).

## Non-negotiables (short form — full list in CLAUDE.md)

Human-in-the-loop by default · silence flag checked inside every publisher ·
no publish without full metadata+UTM · secrets never in code/repo/session ·
official APIs only · absolute tenant isolation · kill switch <5s ·
apprentice A0 logging from day one.

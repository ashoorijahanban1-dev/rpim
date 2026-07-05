# ADR 0007 — Coolify is the production deploy path

**Status:** accepted (M0) — supersedes the implicit "raw compose over SSH"
assumption of the web blueprint's checklist row 06.

**Context.** Coolify (panel at rpim.ir) manages both VPSes and owns ports
80/443 with its own proxy. Running our own public Caddy on the servers would
collide with it.

**Decision.**
- Both legs deploy as Coolify **Docker Compose resources** pointing at
  `docker-compose.{iran,us}.yml` on this repo.
- Our Caddy moves behind the compose profile `local` — used ONLY for local
  dev and CI. On servers, Coolify's proxy fulfills the blueprint's
  Caddy/ingress role; public routing/TLS is configured in the Coolify UI.
- Env values live in the Coolify UI per resource (rule 4). Binds on servers:
  `CORE_BIND=10.66.0.1`, `GATEWAY_BIND=10.66.0.2` (WireGuard-only exposure).
- CI's `deploy` job triggers Coolify redeploys via its API after the smoke
  gate, authenticated with the `COOLIFY_TOKEN` **GitHub Actions secret**
  (least-privilege deploy token — not root; panel must be HTTPS first).
  The job stays skipped until `COOLIFY_URL`, `COOLIFY_IRAN_UUID`,
  `COOLIFY_US_UUID` repo variables exist.

**Consequences.** The token never enters the repo or any Claude session;
deploys are reproducible from CI; local acceptance flow is unchanged.

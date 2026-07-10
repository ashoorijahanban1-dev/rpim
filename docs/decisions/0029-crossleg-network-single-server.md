# ADR 0029 — Cross-leg traffic on the single server rides a shared docker network

**Status:** accepted — fixes the production-blocking bug where every brain
ingest 500'd after a 60s timeout.

**Context.** With the Iran VPS suspended (ADR 0025), both legs run as two
Coolify compose projects on one host — two isolated docker networks. The
cross-leg URL defaults still pointed at WireGuard IPs (`10.66.0.2` etc.)
that no longer exist, and the gateway's host port binds loopback (never
public, ADR 0003), so containers could not reach it via the host either.
Everything that crosses legs was silently dead in production: embeddings
(all brain ingestion), Telegram sends, image rendering. CI never caught it
because the smoke run overrides the URLs and binds.

**Decision.**
- Cross-leg traffic on the single server rides the **pre-existing `coolify`
  docker network** (declared `external: true` in BOTH compose files) — it
  exists on every Coolify server because the proxy uses it, so there is no
  manual creation step and no deploy-ordering dependency. Only the services
  that need it attach: `core-api` (iran) ↔ `model-gateway`, `renderer` (us);
  compose gives each service its service-name DNS alias on that network.
- Single-server defaults switch to service-name URLs over that network:
  `GATEWAY_URL=http://model-gateway:8080`, `RENDERER_URL=http://renderer:8091`,
  `CORE_API_URL=http://core-api:8000`. The env overrides remain the re-split
  path: when the Iran VPS returns, set the WireGuard IPs in the Coolify UI
  and detach the network — no code change.
- Locally/CI (no Coolify) `make up-*` pre-creates the `coolify` network.
  (First revision of this ADR used a new `rpim-crossleg` external network,
  which required a manual per-server create and took the stack down when it
  was missing — superseded within the hour.)
- `embed_client` timeout drops 60s → 15s: a dead cross-leg path must fail
  fast, not hang user requests for a minute.

**Consequences.** Brain ingestion, Telegram publishing and image rendering
work on the deployed topology with zero manual steps; the gateway stays off
the public interface (no port/bind changes — it is merely reachable by
other containers on the operator's own coolify network).

**Amendment (same day).** Explicitly declaring the `coolify` network in the
compose files collided with the network definition Coolify itself injects
into generated deployments, failing `docker compose up` on the server. The
declaration is removed: Coolify already attaches every service of both
resources to its predefined `coolify` network, which is exactly the shared
rail we need. The compose files keep only the service-name URL defaults;
local/CI never needed the shared network (Caddy/env overrides route there).
If service-name DNS ever fails on the coolify network, the fallback is
setting the cross-leg URLs explicitly in the Coolify UI env.

**Second amendment — the actual root cause.** Ingest kept failing (HTTP 500
after the 15s embed timeout) even after the network fixes above, because the
network layer was never the consulted layer: the ORIGINAL provisioning run
stored `GATEWAY_URL=http://10.66.0.2:8080` / `CORE_API_URL=http://10.66.0.1:8000`
(WireGuard IPs, dead since ADR 0025) as Coolify application envs, the
provision script only writes envs on first creation, and a stored env always
overrides the compose-file default `${GATEWAY_URL:-…}`. Fixes:
- `scripts/coolify-provision.sh` now provisions container-name URLs
  (`http://rpim-model-gateway:8080`, `http://rpim-renderer:8091`,
  `http://rpim-core-api:8000`) and treats `GATEWAY_URL`/`RENDERER_URL`/
  `CORE_API_URL` as *corrective* envs — upserted on every run, existing apps
  included, so a stale override can never survive a provision run again.
- New read-only `ops-diagnose` workflow (`scripts/ops-diagnose.sh`) dumps
  each leg's status, redacted envs and a log tail to
  `docs/ops/ops-diagnose-report.txt`, so production state is verified from
  facts rather than inferred. Env values are redacted by default — only an
  allowlist of known non-secret names prints, with URL userinfo scrubbed
  even from those (rule 4; a denylist misses names like
  `ZARINPAL_MERCHANT_ID`).

**Third amendment — the second half of the root cause.** After the env fix
the failure changed shape (HTTP 500 after 1s instead of the 15s timeout):
core-api now dialed the right name but could not RESOLVE it. The first
amendment's assumption that "Coolify already attaches every service of both
resources to its predefined `coolify` network" is false: for compose
resources that attachment is gated behind the per-resource **"Connect To
Predefined Network"** flag (`connect_to_docker_network`), which defaults to
OFF — each stack stays isolated in its own generated network. The provision
script now sets `connect_to_docker_network: true` at creation AND
correctively on every run (then redeploys), and `ops-diagnose` prints the
flag so the attachment is verifiable remotely.

**Fourth amendment — service names, not container names.** The generated
compose Coolify actually deploys (now dumped by `ops-diagnose`) proved two
things. (1) Coolify **overrides `container_name`** with its own
`<service>-<resource-uuid>-<timestamp>` names, so PR #42's pinned
`rpim-*` names never existed and the cross-leg URLs resolved nothing — the
1s DNS failure. The rail that DOES exist: compose adds each service's
**service name as a DNS alias on every attached network**, including the
predefined `coolify` network. Cross-leg URLs are therefore service-name
URLs (`http://model-gateway:8080`, `http://renderer:8091`,
`http://core-api:8000`), and every service name must be **unique across
BOTH legs** — the us leg's `redis` is renamed `redis-us` because docker DNS
round-robins duplicate aliases across legs (iran's core-api could have
connected to the us redis and mixed the queues). `container_name` lines are
removed as dead weight. (2) The generated compose carries **resolved env
values**: the first compose dump leaked APP_SECRET_KEY / JWT_SECRET /
INTERNAL_TOKEN / the postgres password into a committed report (feature
branch only, no provider keys). Remediation: diagnose now redacts env-shaped
lines inside the compose dump plus a long-hex scrub, the provision workflow
gained a `rotate_secrets` dispatch input (rotates the three app-layer
secrets on both legs and redeploys; postgres password rotation stays a
manual runbook step), and rotation was executed immediately after merge.

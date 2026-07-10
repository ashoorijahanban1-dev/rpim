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

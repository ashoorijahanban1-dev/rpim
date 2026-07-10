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
- A shared, attachable docker network **`rpim-crossleg`** (declared
  `external: true` in BOTH compose files) carries all cross-leg traffic on
  the single server. Only the services that need it attach: `core-api`
  (iran) ↔ `model-gateway`, `renderer` (us).
- Single-server defaults switch to service-name URLs over that network:
  `GATEWAY_URL=http://model-gateway:8080`, `RENDERER_URL=http://renderer:8091`,
  `CORE_API_URL=http://core-api:8000`. The env overrides remain the re-split
  path: when the Iran VPS returns, set the WireGuard IPs in the Coolify UI
  and detach the network — no code change.
- The network is created once per host: `make up-*` does it automatically
  for local/CI; on the server it is a **one-time**
  `docker network create rpim-crossleg` (Coolify UI → Server → Terminal),
  documented in the README deploy steps.
- `embed_client` timeout drops 60s → 15s: a dead cross-leg path must fail
  fast, not hang user requests for a minute.

**Consequences.** Brain ingestion, Telegram publishing and image rendering
work on the deployed topology; the gateway stays off the public interface.
Deploying a leg before the network exists fails loudly with "network
rpim-crossleg not found" — a clear, documented one-time fix.

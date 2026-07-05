# ADR 0003 — Ports, exposure, and compose project names

**Status:** accepted (M0)

**Decision.**
- Distinct top-level `name:` per compose file (`rpim-iran`, `rpim-us`) plus
  `-p` flags in the Makefile. Both files live in `infra/`, and without this
  compose derives the project name "infra" for BOTH legs — bringing up the
  second leg would clobber the first.
- Postgres and Redis publish NO host ports, ever. Dev access:
  `docker compose exec`.
- model-gateway binds `${GATEWAY_BIND:-127.0.0.1}:8080` — loopback locally,
  the WireGuard IP `10.66.0.2` on the real server, `0.0.0.0` only in CI.
  The gateway is never publicly reachable (blueprint §2 placement); this
  matches the committed `GATEWAY_URL=http://10.66.0.2:8080`.
- core-api binds `${CORE_BIND:-127.0.0.1}:8000` symmetrically (WG IP
  `10.66.0.1` on the server) for the us→iran healthcheck path.
- Local-profile Caddy: iran `:8001` (any interface), us `127.0.0.1:8002`.

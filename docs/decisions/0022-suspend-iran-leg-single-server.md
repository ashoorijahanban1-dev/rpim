# ADR 0022 — Iran VPS suspended; single-server topology is the supported deployment

**Status:** accepted (post-M9) — promotes the "interim: both legs on the US
server" topology of ADR 0007 / commit 998495a from stopgap to the official
deployment mode, until further notice.

**Context.** Iran's international connectivity has become unreliable to the
point that an Iran VPS can neither be provisioned nor dependably managed.
Meanwhile the project has never actually depended on it: since the first
successful Coolify provisioning (2026-07-05) both legs run as two separate
Docker Compose resources on the single US server with loopback binds, the
physical Iran VPS was never set up, and the WireGuard tunnel never came up.
Everything M0–M9 shipped — including CI's two-way cross-leg smoke — works in
this topology.

**Decision.**
- The **single-server topology is the supported deployment** until further
  notice. The logical two-leg architecture is **unchanged**: two compose
  files, two Coolify resources, shared `INTERNAL_TOKEN`, and the gateway
  indirection for Telegram all stay exactly as they are.
- **WireGuard setup, Iran VPS provisioning, and the `wg`-mode healthcheck are
  suspended** — off the active roadmap. The stubs in `infra/wireguard/` and
  the `wg` mode in `scripts/crossleg-healthcheck.sh` are kept for a future
  re-introduction; sessions must not spend time on them.
- The cross-leg env defaults (`GATEWAY_URL`, `CORE_API_URL` pointing at
  WireGuard IPs) stay in the compose files for compatibility; on the single
  server the Coolify UI overrides them to reach the co-located leg, as
  already provisioned.
- **M10 scopes to the single US server**: runbook, nightly encrypted
  off-site backup, kill-switch drill — all against this topology.
- Bale/Eitaa live sends will be attempted **from the US server's IP** via the
  official bot APIs (`tapi.bale.ai`, `eitaayar.ir`). Reachability from a
  non-Iran IP must be verified once real tokens exist. If blocked, those
  channels are **deferred, not worked around** — rule 5 (official APIs only)
  remains absolute. Telegram stays the proven live channel.
- The idempotent/resumable job-queue discipline (CLAUDE.md stack rule:
  "assume the tunnel WILL drop mid-job") is **kept** — it is what makes the
  future re-split cheap and it costs nothing now.

**Consequences.** No code change and no stoppage: M10, the 50-prompt Persian
eval, and the data-export DoD item proceed on the single server. Reverting is
cheap and code-free: provision an Iran server, fill the wg0 configs on the
servers, move the `rpim-iran-leg` Coolify resource, flip `CORE_BIND` /
`GATEWAY_BIND` to the WireGuard IPs. Accepted risk: while Iran's international
internet is fully shut, users inside Iran cannot reach the (foreign-hosted)
dashboard — an Iran VPS would not mitigate this in practice, since it could
not be managed or reached by the operator either.

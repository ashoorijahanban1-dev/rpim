# ADR 0026 — Global silence + governance ops surface (national-event feed)

**Status:** accepted — completes the DoD §13.1 "silence-mode simulated event"
acceptance on top of ADR 0022's M10 work.

**Context.** Since M5 the silence flag was per-tenant only and the kill flag
global; `is_publishing_halted()` already checked the global scope for both
kinds, but nothing could SET a global silence, operators could not read the
global flag state without a tenant JWT, and there was no feed entry point for
the blueprint's "national-event → auto-halt" behavior.

**Decision.** Three endpoints on the existing internal-token trust boundary
(the same one as `POST /governance/kill`), token compared constant-time
(`hmac.compare_digest`):
- `GET /governance/global/status` — operator reads global kill+silence state.
- `POST /governance/national-event` — a feed signal auto-sets the GLOBAL
  silence flag (all tenants halt via the in-path publisher check, rule 2).
  A feed-driven `active=false` is **rejected with 409**: a compromised or
  glitchy feed must never re-enable publishing (manual-only resume, rule 7).
- `POST /governance/global/silence` — the only resume path for global
  silence: an explicit operator action.
`POST /governance/kill` now returns `scope: "global"` so the operator can
confirm system-wide application from the response.

**Consequences.** The DoD silence-mode simulated event passes as an
automated acceptance test (feed signal → all tenants blocked → feed resume
rejected → manual resume restores dispatch — including a tenant registered
AFTER the event, proving global scope). Per-tenant silence behavior is
unchanged. The runbook documents the flows.

# ADR 0004 — CI smoke job is the automated M0 acceptance

**Status:** accepted (M0)

**Context.** The Claude Code sandbox has no docker daemon; `make up-*` cannot
run there. M0 acceptance requires both legs up + a TWO-WAY healthcheck.

**Decision.** The GitHub Actions `smoke` job is the automated acceptance
proof: it generates ephemeral env values, brings BOTH legs up on one runner
(`up -d --build --wait`), then runs `scripts/crossleg-healthcheck.sh` in
`local` mode (per-leg liveness) AND `crossleg-ci` mode — curl executed from
INSIDE the iran core-api container to the us leg and from INSIDE the
model-gateway container to the iran leg via `host.docker.internal:
host-gateway`, i.e. genuine cross-leg container egress.

**Honest scope.** `wg` mode (over the real WireGuard tunnel, using
`GATEWAY_URL` / `CORE_API_URL`) runs only on the real servers and is NOT part
of automated M0 acceptance. CI approximates the tunnel with the host gateway.

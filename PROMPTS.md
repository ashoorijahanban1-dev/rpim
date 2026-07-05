# RPIM — Session Kickoff Prompts

## Session rules (every session)
`/model opusplan` → Shift+Tab into Plan mode → paste prompt → read the plan
yourself → approve → execute. One session = one milestone. Before commit:
`@blueprint-reviewer review the current diff`. End of milestone: update
`docs/decisions/`.

## M0 — Scaffold + infrastructure
Read CLAUDE.md and docs/RPIM-Blueprint-v1.2.md fully.
We are on milestone M0 (web blueprint §6.4).
1) Propose the monorepo scaffold + both docker-compose files (iran leg /
   us leg) as a plan. Wait for my approval.
2) Constraints: Python 3.12 + FastAPI, Next.js 15, Postgres 16 + pgvector,
   Redis, Caddy. No secrets in code. All services expose /health.
   Create the Makefile early (up-iran, up-us, test, lint, fmt) so hooks
   start working.
3) Acceptance: `make up-iran` and `make up-us` bring each leg up locally;
   `make test` passes; cross-leg healthcheck script is green over
   WireGuard config stubs.

## M1..M10 — Template
Read CLAUDE.md. We are on milestone M<N>: <title from §6.4>.
First: use @test-writer to encode the acceptance criteria as failing tests.
Then propose your implementation plan and wait for approval.
Acceptance criteria: <paste the row from §6.4 verbatim>.

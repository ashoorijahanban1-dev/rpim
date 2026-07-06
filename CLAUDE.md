# RPIM — Project Constitution (CLAUDE.md)

> This file is intentionally in English: it loads into every session and Persian
> costs 2-3x tokens. Read `docs/RPIM-Blueprint-v1.2.md` before any architectural
> decision. Build milestones (M0-M10) live in `docs/RPIM-Blueprint-Web.html` §6.4.

## What we build
RPIM = agentic marketing system for Persian-language brands. Closed loop:
Brand Brain (RAG) → Trend Engine → Strategy → Content Factory → QA →
Distribution → Measurement → back to Brain. Deployed on two legs:
**Iran VPS** (user-facing: dashboard, core-api, Postgres, Bale/Eitaa, Zarinpal)
and **US VPS** (model-gateway, bge-m3 embeddings, crawlers, template renderer,
Telegram publisher). Legs talk over WireGuard via an idempotent job queue.
**ADR 0025: the Iran VPS is suspended** — both legs run as separate Coolify
resources on the single US server; WireGuard work is on hold. The logical
two-leg split and the tunnel-drop resilience rules stay in force.

## Non-negotiable rules (enforced, not suggested)
1. Human-in-the-loop by default. Nothing publishes outside the approval-queue
   state machine (autonomy levels L0-L3, blueprint §5).
2. **The silence flag precedes every publish job.** The check lives inside the
   publisher itself, not only in the scheduler. Queued jobs must also stop.
3. No content compiles into a publish job without full metadata + UTM/campaign code.
4. Secrets: never in code, never in this repo, never pasted into sessions.
   Env var NAMES only. `.env` is gitignored; `.env.*.example` are committed.
5. Official APIs only for distribution (Telegram/Bale/Eitaa/WordPress REST).
   Instagram = assisted mode only. Browser automation is forbidden, always.
6. Tenant isolation is absolute: every query scoped by `tenant_id`; every new
   table ships with a test proving cross-tenant isolation.
7. Kill switch stops all publish queues in <5s. Silence mode: auto-halt,
   manual-only resume.
8. Apprentice A0 logging (blueprint M9): M4/M6 must persist three signals as
   versioned per-tenant JSONL — (brief+context → approved output),
   (draft → human-edited version), (structured rejection reason).

## Stack & conventions
- Python 3.12 + FastAPI + Pydantic v2. Type hints mandatory. Migrations via
  Alembic only. Celery + Redis for jobs. Postgres 16 + pgvector.
- Dashboard: Next.js 15, mobile-first, RTL. All user-facing text in Persian
  (fa) from locale files — never hardcoded in components.
- Every service exposes `/health`. Cross-leg jobs are idempotent and
  resumable — assume the Iran↔US tunnel WILL drop mid-job.
- All model calls go through `apps/model-gateway` adapters (tiers T1-T5,
  web blueprint §5). Never call a provider directly from a service. Every
  call writes tokens+cost to the per-tenant ledger. `MODEL_T2` stays unset
  until the 50-prompt Persian eval decides it.
- Commits: conventional commits, small, only after green tests.

## Commands
`make up-iran` · `make up-us` · `make test` · `make lint` · `make fmt`
(M0 creates the Makefile; hooks auto-run `make test` after edits.)

## Working method
- One session = one milestone. Plan mode first (`/model opusplan`).
- `test-writer` agent encodes the milestone's acceptance criteria as failing
  tests BEFORE implementation.
- Delegate codebase exploration to the `explorer` agent.
- Call `blueprint-reviewer` before every commit; fix violations, don't argue.
- After each milestone: add one ADR per decision to `docs/decisions/`.

## Definition of Done (MVP)
Blueprint §13.1: onboard a brand <48h · first 7-asset batch <24h · scheduled
publish on 3 messengers · per-tenant cost ledger · kill switch <5s ·
silence-mode simulated event passes acceptance · one-click full data export.

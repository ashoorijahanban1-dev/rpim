---
name: rpim-milestone
description: "The proven RPIM delivery loop — run this for EVERY milestone, epic slice, or production fix in this repo: red-first TDD, constitution gates, blueprint review, PR, merge on green CI, verify the production deploy. Use when starting any development directive (M-numbered epics, slices, hotfixes) or when resuming an in-flight one."
---

# RPIM milestone loop (the operating procedure that shipped M0–M22)

Follow the steps in order. Never skip a gate. Evidence at every checkpoint:
PR number, commit sha, test counts, CI run ids.

## 0. Orient
- Read `CLAUDE.md` (the 8 non-negotiable rules) and the relevant section of
  `docs/design/fable5-pentarchy.md` + the latest `docs/decisions/` ADRs.
- Branch: `git fetch origin main && git checkout -B <work-branch> origin/main`
  (keep the session's designated branch name; force-with-lease is safe only
  when the remote tip is already-merged history — verify with
  `git diff --stat origin/<branch> origin/main` being empty).
- Check the migration chain head (`apps/core-api/migrations/versions/`) —
  numbering follows the DESIGN's per-epic numbers; the alembic chain links
  by `down_revision` in EXECUTION order (ADR 0038 precedent).

## 1. Red phase (strict TDD — tests must fail first)
- Write `test_mXX_*.py` acceptance tests BEFORE any implementation:
  every new tenant-scoped table gets a cross-tenant isolation test (rule 6);
  every retried/cross-leg operation gets a replay/idempotency test (rule 8);
  every env-driven mode gets a missing-env-NAMES-the-var test (rule 4);
  every date boundary rides `rpim_shared.tz.now_app()` (ADR 0032 — never a
  hardcoded timezone).
- Run them; confirm failure (a collection error on a missing module counts).

## 2. Implement (only enough to green the tests)
- Backend conventions: `String(32)` uuid PKs via `_uuid`, tz-aware stamps
  via `_now`, tenant FK indexed, UNIQUE upsert keys, internal endpoints
  gated by `X-Internal-Token`, beat workers are dumb pokers.
- Dashboard conventions: Persian ONLY from `locales/fa.json`; Tailwind v4
  utilities-only (no preflight) + `cn` from `@/lib/utils`; framer-motion
  under `MotionConfig reducedMotion="user"` (ADR 0040).
- Schema change ⇒ Alembic migration with a real `downgrade`, consistent
  with `models.py`. New env vars ⇒ NAMES in `.env.iran.example` /
  `.env.us.example` (values never in the repo).
- Export contract: new tenant-owned tables extend `/export` + bump
  `export_version` (update the pinned asserts in m11/m20 tests).

## 3. Verify locally — all of it
- `make test` (whole repo), `uv run ruff check .` (the CI command — the
  whole tree, not just apps/), and if the dashboard changed:
  `npx tsc --noEmit && npx next lint && npm run build` in `apps/dashboard`.

## 4. Gates before commit
- Write the ADR in `docs/decisions/` (next number) — decisions, rejected
  alternatives, consequences.
- Run the `blueprint-reviewer` agent on the full uncommitted diff; fix
  every finding (do not argue), re-run affected tests.

## 5. Ship
- Conventional commit with the session trailer; push
  `git push -u origin <branch>` (retry with backoff on network errors).
- Open the PR (template-free repo: outcome-first body with evidence),
  subscribe via `subscribe_pr_activity`, then check CI in ~10 minutes
  (success is NOT webhook-delivered).
- Green CI ⇒ squash-merge titled `<subject> (#<pr>)`. Red CI ⇒ read the
  failing job log, fix, push, repeat — one round is never "done".

## 6. Halt condition (the only place to stop)
- The MAIN-branch run for the merge commit must finish with EVERY job
  green including `deploy` (Coolify redeploys both legs). Report: PR,
  merge sha, test count, main run id — then stop the loop with the
  ScheduleWakeup stop call.

## Standing constraints (repeat-offender list)
- PT timezone is an operator mandate (ADR 0032): one env lever, zero
  hardcoded zones — sqlite's naive round-trips get `app_timezone()`
  reattached.
- Secrets: never in code/repo/chat — if a user pastes one, refuse to store
  it and advise rotation.
- No PR without an explicit ask or a standing sprint directive; never
  stack commits on merged history — restart the branch from origin/main.
- Instagram stays assisted-only; Midjourney/browser automation stays
  rejected; official APIs only (rule 5).

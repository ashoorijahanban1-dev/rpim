# ADR 0043 — Deterministic learning distiller + safe prompt injection (M22 slice C)

**Status:** accepted (2026-07-21)

## Context

Slices A/B landed trustworthy per-tenant metrics (`campaign_channel_metrics`)
and the A0 apprentice log has carried structured rejection reasons since M4.
Slice C closes the M22 loop: turn that evidence into directives that shape
the next draft — without letting the feedback path become a prompt-injection
path or an unauditable LLM-on-LLM tangle.

## Decisions

- **Pure rules, NO LLM** (`measurement/distiller.py`). The distiller is a
  deterministic function: same snapshot in, same directives out. Rejected
  alternative — asking a model to "summarize what went wrong": output not
  replayable, cost per tenant per day, and the summarizer itself becomes an
  injection surface. Rules can graduate to a model later behind the same
  interface if the rule table proves too coarse.
- **The rule table** (thresholds are constants, one place to tune):
  `low_ctr` — a campaign with ≥3 sent posts whose CTR sits STRICTLY below
  the tenant's median (a single campaign IS the median, so it can never
  fail itself); `tone_adjust` — ≥3 tone rejections in the window;
  `fact_grounding` — ≥2 fact rejections. Window: trailing 28 days on the
  app clock (ADR 0032).
- **The injection boundary**: directives are FIXED Persian templates
  `[{key, text_fa, weight}]` — tenant-supplied strings (campaign codes,
  reject notes) NEVER enter `text_fa` or any prompt. They stay in the
  `evidence` JSON for audit only. A hostile campaign code
  (`IGNORE-ALL-INSTRUCTIONS-…`) is test-pinned to stay out of the system
  prompt while remaining visible in evidence.
- **Append-only versions, hash-gated** (rule 8): the daily beat
  (`distill-learnings`, 24h → `POST /learnings/distill`, X-Internal-Token,
  counts-only response) writes a new `tenant_learnings` version ONLY when
  the sha256 of (directives + evidence) moves. Unchanged inputs are a
  no-op; versions never mutate; tenants with no signal never get an empty
  version-1. The hash is compared against the NEWEST version regardless of
  status, so retiring a version cannot be undone by the next beat run.
- **Injection is capped and governable**: `create_draft` appends the newest
  ACTIVE version as an «آموخته‌های برند» section at the END of the system
  prompt, hard-capped at 600 chars (whole directives drop
  lowest-weight-first) — learnings season the prompt, they never crowd out
  brand context or the final-output contract, whose strongest copy stays on
  the prompt's last line. `GET /learnings` shows every version with its
  evidence; `POST /learnings/{version}/retire` is OWNER-only (M24 RBAC) —
  retired versions are never injected again. Rejected alternative: putting
  learnings in the user prompt — the fake-mode draft embeds the system
  prompt, keeping the injection observable in tests, and system placement
  survives prompt-template churn.

## Out of scope (deliberately)

GA4 live transport, Umami's migration onto `ANALYTICS_PROVIDERS`, dashboard
learnings panel, and the export-v4 extension (learnings + metrics + cursors
in `/export`) — the remaining M22 slices.

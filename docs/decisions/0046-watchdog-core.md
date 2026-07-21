# ADR 0046 — Watchdog core: propose, never publish (M23a)

**Status:** accepted (2026-07-21)

## Context

The last pentarchy pillar: turn hot trends into draft proposals without
ever weakening rule 1. Slice scope was chosen by explicit comparison:

| | 1. Foundation-only (schema + plumbing) | **2. Full core loop (chosen)** | 3. Dry-run gate prototype |
|---|---|---|---|
| User value | none yet | real: trend → reviewable draft | none (report-only) |
| Simplicity | highest | medium (one coherent unit) | medium |
| Failure mode / reversibility | dead schema | **L0 default = inert for every existing tenant**; full migration downgrade | throwaway code |

Concept 3's purpose (measuring relevance-gate uncertainty) folded into
deterministic tests on the fake-embed seam with env-controlled thresholds.

## Decisions

- **Migration 0018** (number reserved by the design; chain links after
  0020 in execution order, ADR 0038 precedent): `tenants.autonomy_level`
  (server default 0), `content_drafts.origin` (server default `human`),
  `agent_actions` with `UNIQUE(tenant_id, trend_item_id, kind)` —
  trend_item_id NOT NULL so the dedupe always bites (NULLs are distinct
  in unique constraints). Full downgrade.
- **One generation path** (§3.3): `create_draft`'s pipeline moved to
  `content/service.py: generate_draft(session, tenant_id, brief, origin)`
  — golden behavior preserved (the m4 prompt-contract and 503 tests moved
  their seam, contracts unchanged). The watchdog rides the SAME path, so
  learnings injection, the unsourced tripwire, and the T2 ledger apply to
  agent drafts automatically. Dependency outages raise
  `GenerationUnavailable(stage)`: the route maps stages to its two 503s;
  the scan skips the tenant and the beat lives on (rule 8).
- **`POST /agent/scan`** (internal token, 30-min beat, counts-only
  response): per tenant — opt-in (`autonomy_level >= 1`; **L0 ships as
  the default so the watchdog is inert until an owner raises the dial**),
  silence/kill halt via `is_publishing_halted` (rule 2 spirit: halted
  tenants spend nothing), `AGENT_DAILY_DRAFTS` cap per app-clock day
  (ADR 0032), 7-day trend freshness window, dedupe pre-check on the
  unique key, then the **brand-relevance gate** (§3.6): `relevance =
  100 × best cosine hit` on product/claim chunks; below
  `AGENT_MIN_RELEVANCE` → no draft, no T2 spend, no action row. Heat
  alone never spends money or reviewer attention.
- **Transparency (rule 1)**: proposals are ORDINARY drafts with
  `origin="agent"` — same approval queue, same QA, same publish gates.
  `DraftOut`/`list_drafts` carry origin; the queue page badges agent
  drafts (`fa.queue.agent_badge`); the `agent_actions` audit row keeps a
  fixed-fa-template rationale citing heat + relevance numbers.
- **`PUT /agent/autonomy`** — owner-only (M24 RBAC), levels 0..3
  validated. Raising autonomy is a governance act like retiring a
  learning.
- **Export v5**: drafts gain `origin`; new `agent_actions` section
  (tenant-owned audit data). Pinned asserts moved (m11/m20/m21/m22d).
- Env NAMES only (rule 4): `AGENT_DAILY_DRAFTS`, `AGENT_MIN_RELEVANCE`
  in `.env.iran.example`.

## Rejected alternatives

- Auto-publish at high autonomy levels — **never** (design table §0):
  L2/L3 semantics stay approval-queue-side and land with the autonomy UI.
- An LLM "relevance judge" — the cosine gate is deterministic, free, and
  auditable; a judge model can layer on later behind the same threshold.
- Proposing from AI-news (global) items — global content lacks rule-6
  tenant grounding; tenant trend_items only.

## Out of scope (deliberately)

M23b: dashboard autonomy dial + agent-actions audit panel; accepted/
dismissed status transitions from the queue; L2/L3 semantics.

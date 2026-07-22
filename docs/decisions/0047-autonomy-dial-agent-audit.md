# ADR 0047 — Autonomy dial + agent audit surfaces (M23b)

**Status:** accepted (2026-07-21)

## Context

M23a shipped the watchdog inert (L0 default) with no way for an owner to
turn it on from the product, and no surface showing WHY proposals exist
or what humans decided about them. M23b closes both gaps.

## The placement comparison (three concepts, selected explicitly)

| Criterion | 1. New /agent page | **2. Fold into /insights (chosen)** | 3. Dial in settings + audit in queue |
|---|---|---|---|
| User value | same data, new place to find | governance surfaces in ONE place (learnings retire already lives here) | split across two pages |
| Simplicity | new route/nav/fetch scaffold | reuses the page's load/error/motion scaffold | two scattered edits |
| Maintenance | third governance surface | one | two |
| Failure mode | empty page at L0 | sections hide gracefully when fetches fail | queue clutter |

/insights is already "what the brain does and why" — the dial and the
audit list belong beside the learnings they govern.

## Decisions

- **`GET /agent/autonomy`** — every role reads the dial; raising it stays
  owner-only via the existing PUT (M24 RBAC). **`GET /agent/actions`** —
  tenant-scoped audit list (kind, status, heat score, relevance,
  rationale, draft link), newest first, capped at 100.
- **The loop closes on human verdicts**: approving or editing an
  `origin="agent"` draft flips its `agent_actions` row to `accepted`;
  rejecting flips it to `dismissed` — inside the SAME commit as the draft
  verdict (`_close_agent_loop`), so the audit trail and the draft state
  can never diverge. An edit counts as acceptance (the human kept the
  proposal, improved the words). Human drafts have no action row and the
  hook is a no-op — never a crash. This also makes the pilot experiment
  measurable: acceptance rate = accepted / (accepted + dismissed).
- **The dial UI** is a radiogroup of four locale-labeled levels
  (`fa.insights.level_0..3`) with `aria-checked`; L2/L3 labels describe
  their future semantics but publishing remains human-gated at EVERY
  level (rule 1) — the hint says so explicitly.
- **Rejected alternative**: an explicit "dismiss proposal" button on the
  audit list — duplicate of rejecting the draft in the queue, and a
  second write-path to the same row invites divergence.

## Out of scope (deliberately)

L2/L3 behavior (scheduling suggestions, queue prioritization) — labels
exist, semantics land as their own gated slices; DoD §13.1 closure audit.

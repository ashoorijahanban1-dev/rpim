# ADR 0045 — Tenant insights surfaces: cards + learnings list (M22 slice E)

**Status:** accepted (2026-07-21)

## Context

Slices A-D built the measurement loop's write side; the tenant had no
window into it. Slice E is the read side: show the owner what performed,
what the brain learned, and give them the human control (retire) the
governance model promises.

## The UI comparison (three concepts, selected explicitly)

| Criterion | 1. Summary cards + learnings list | 2. Evidence→directive timeline | 3. Channel cockpit |
|---|---|---|---|
| User value | Direct: what worked, what was learned, one governance action | Same data, richer story, no new action | Per-channel drill-down — premature while web/umami is the dominant source |
| Persian/RTL fit | Tables+stat tiles already RTL-proven in this repo | Timelines need custom RTL mirroring | Complex mirrored grids |
| Simplicity | Highest — reuses admin/queue patterns and `.stats` tiles | Medium — new component family | Lowest |
| Security/isolation | Two tenant-scoped GETs, no new surface | Same | New per-channel endpoints to scope and test |
| Cost/latency | 2 requests, no polling | 2 requests, heavier render | N requests |
| Maintenance | Mirrors existing pages | New family | New family + data model |
| Failure mode / reversibility | Graceful empty states; page is deletable | Sparse data renders badly | Worst |

**Selected: concept 1**, grafting concept 2's best idea — evidence rides
each learning as a collapsed `<details>` audit block instead of a
timeline. The measurable prototype IS the vertical slice: static a11y +
locale checks in pytest, tsc/eslint/build in CI.

## Decisions

- **`GET /metrics/summary`** (bearer auth, tenant-scoped) reuses
  `distiller.load_evidence` — ONE source of window truth, so the page
  shows exactly what the brain learns from (28 app-clock days, ADR 0032).
  Response: `{window_days, campaigns: [{campaign, clicks, posts_sent,
  ctr}], rejects}`; ctr is null on a zero denominator; campaigns sort
  clicks-desc. Rejected alternative: a separate SQL aggregation for the
  page — two window definitions WILL drift.
- **`/insights` page**: stat tiles (clicks / campaigns / rejects) +
  campaign table + learnings list with status chips, fixed-template
  directive texts, relative timestamps, and the evidence `<details>`.
  Persian only from `fa.insights.*` / `fa.nav.insights`; framer-motion
  stagger under `MotionConfig reducedMotion="user"` (ADR 0040);
  aria-label/role/alert on the interactive and state elements.
- **Retire is a two-step human act**: first click arms the button
  (`retire_confirm`), second click posts to
  `/learnings/{version}/retire` — and the API remains owner-only (M24
  RBAC), so the UI step is UX, not the security boundary. Editors see
  the API's 403 detail via the standard error path.
- No schema change, no migration, export contract untouched.

## Out of scope (deliberately)

Stalled-job surfacing (belongs with M23's watchdog view), GA4 live
transport (still blocked on operator credentials), and charts (a table
is the honest v1 for sparse pilot data).

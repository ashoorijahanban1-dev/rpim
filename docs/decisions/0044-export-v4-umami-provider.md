# ADR 0044 — Export v4 + Umami on the provider registry (M22 slice D)

**Status:** accepted (2026-07-21)

## Context

Slices A-C left two commitments open: ADR 0042 promised Umami would become
the second `ANALYTICS_PROVIDERS` entry (with the slice-A snapshot migrating
onto it), and the delivery loop's own rule — new tenant-owned tables extend
`/export` — was deferred while `campaign_channel_metrics`,
`tenant_learnings` and `analytics_cursors` accumulated.

## Decisions

- **Export v4** (§13.1 one-click export): `/export` gains three sections —
  `campaign_channel_metrics` (full daily rows), `tenant_learnings` (every
  version WITH its evidence and content_hash — the learned voice is the
  tenant's property, including the audit trail), and `analytics_cursors`
  (provider watermarks, so a tenant can verify exactly what was ingested).
  `export_version` bumps to 4; the pinned asserts in the m11/m20/m21 tests
  move with it. Rejected alternative: exporting only ACTIVE learnings —
  the retired versions are precisely the governance history a data export
  exists to preserve.
- **Umami as a registry entry**: `_umami_fetch_day(utm_id, day)` wraps the
  existing `attribution.fetch_tenant_clicks` transport (fake seam and
  env-name guards intact) and adapts `{campaign: clicks}` onto the shared
  validated row shape (`sessions` is 0 — Umami's query metric has no
  session split). ANY transport or shape failure surfaces as the single
  caller-visible `AnalyticsProviderError`, class name only — no values in
  errors.
- **The snapshot rides the registry**: `/metrics/snapshot` now calls
  `ANALYTICS_PROVIDERS["umami"]` with the tenant's utm_id as property_ref
  instead of reaching into `attribution` directly — one interface for
  every metrics source, exactly as ADR 0042 planned. Its response contract
  (tenants/rows/skipped), tenant keying, and "web"/"umami" row identity
  are unchanged; rows now also carry `sessions` from the provider shape.

## Out of scope (deliberately)

GA4 live transport — **blocked on operator credential provisioning**
(`GA4_CREDENTIALS_FILE` service-account JSON on the leg; flagged to the
operator). Dashboard learnings/metrics surfaces remain the next slice.

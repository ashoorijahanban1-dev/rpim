# ADR 0041 — M22 slice A: tenant-keyed metrics snapshot (utm_id)

**Status:** accepted (2026-07-20)

## Context

M22's feedback loop must read clicks per brand, but campaign codes are
free tenant-chosen strings on ONE shared Umami site — two brands running
`spring-sale` would ingest each other's counts, and the distiller would
bake foreign numbers into a brand's prompts (the pentarchy review's
rule-6 finding). Smallest vertical slice first, per the Technical Lead:
isolation + idempotency before any learning logic.

## Decisions

- **Every job stamps `utm_id = "t-" + tenant_id[:12]`** (`_build_utm` +
  `build_landing_url`'s replace-never-duplicate key set). The key is
  derived, not secret, and rides every landing link.
- **`attribution.fetch_tenant_clicks(utm_id, day)`**: METRICS_MODE=fake
  (CI seam `_FAKE_UTM_CLICKS`) | umami (shared-site query FILTERED by the
  tenant's utm_id; missing env NAMES the var). Day windows use the
  app-TZ lever (ADR 0032) — never a hardcoded zone.
- **`campaign_channel_metrics`** (migration **0017**, chain 0016 → 0017):
  upsert on UNIQUE `(tenant, campaign, channel, source, day)` — beat
  replays update in place (rule 8); `posts_sent` (the tenant's SENT jobs
  for that campaign) carries the CTR denominator in-row. Umami rows land
  as `channel="web"`, `source="umami"`; GA4/per-channel rows are the next
  slice. `tenant_learnings` ships in the same migration (schema +
  `content_hash` no-op key) — distiller logic is a later slice.
- **`POST /metrics/snapshot`** (X-Internal-Token) fans out over the
  tenant registry with every write tenant-scoped (the engine pattern);
  a dead source skips that tenant and never crash-loops the beat.
  Beat: `snapshot-metrics`, 6h.

## Evidence

- Isolation test: two tenants, same `spring-sale` code, different utm_id
  counts (7 vs 3) — each row records only its own.
- Idempotency test: same-day replay updates the single row (4 → 9).
- Rollback: migration 0017 downgrade drops both tables.

## Next slices

GA4 source (platform service account + per-tenant property_id), the
deterministic distiller (§3.5 rule table, golden-tested), prompt
injection of active learnings (≤600 chars), dashboard learnings panel,
export v4.

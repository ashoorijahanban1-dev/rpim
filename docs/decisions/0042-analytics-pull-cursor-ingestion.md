# ADR 0042 — Provider-neutral analytics ingestion: pull-with-cursor, GA4 first (M22 slice B)

**Status:** accepted (2026-07-21)

## Context

The M22 distiller must consume trustworthy, tenant-keyed, idempotent
metrics — that contract has to exist before any learning logic. Three
ingestion shapes were compared before writing code.

## The comparison (and the explicit selection)

| Criterion | A. Pull + cursor | B. Push webhook | C. Hybrid |
|---|---|---|---|
| Persian-market connectivity | Outbound from OUR leg; GA4 blocks Iranian IPs, and today both legs run on the US server (ADR 0025) — when the legs re-split, the pull routes through the us-leg gateway like /embed and /image | Needs a public inbound endpoint; GA4 has NO native report webhook (only BigQuery/Pub-Sub export — heavy) | Both problems |
| Credential exposure | One platform service account, env NAME only; zero per-tenant secrets | Per-tenant HMAC tokens + an inbound attack surface | Both surfaces |
| Retries | Fully ours (beat + cursor) | Sender-controlled | Split |
| Quota/cost | One runReport per property per day — negligible | Pub/Sub + BigQuery billing | Highest |
| Latency | Hours — the distiller runs daily, that is enough | Seconds (unneeded) | Seconds |
| Idempotency | Natural: cursor + day-keyed upsert | Requires receipt dedupe | Complex |
| Reversibility | Stop the beat, drop the adapter — no external cleanup | Endpoint decommission + tenant reconfig | Worst |

**Selected: A — pull with a per-(tenant, provider) cursor.** B is
disqualified outright (GA4 has no report webhook); C buys latency nobody
needs at maximum complexity.

## Decisions

- **Narrow provider interface** (`measurement/analytics_providers.py`):
  `fetch_day(property_ref, day) → [{campaign, clicks, sessions}]` for one
  provider-local day, shape-VALIDATED — a malformed payload raises
  `AnalyticsProviderError` instead of poisoning rows. `ANALYTICS_PROVIDERS`
  registry starts with `ga4`; **Umami plugs in later as a second entry with
  the same signature** (slice A's snapshot then migrates onto it).
- **GA4 adapter**: fake mode (CI seam `_FAKE_GA4`) is complete; live mode
  is env-guarded by NAME (`GA4_MODE`, `GA4_CREDENTIALS_FILE` — rule 4, no
  real credentials anywhere) and its transport (Data API `runReport`
  filtered by `sessionCampaignId == utm_id`, per ADR 0041's tenant key)
  lands in the next slice with credential provisioning. Until then live
  raises and the cursor stays put.
- **Cursor semantics** (`analytics_cursors`, migration **0020**, chain
  0017 → 0020 — 0018 stays reserved for M23 per the ADR 0038 numbering
  precedent; full downgrade): the last FULLY-ingested day per
  (tenant, provider). The ingest loop commits PER DAY and advances the
  cursor only after the day lands — crash or malformed payload resumes
  exactly at the failed day; full-window replays upsert into the existing
  `(tenant, campaign, channel, source, day)` unique key and the cursor
  never moves backward (rule 8, all tested).
- **Window on the app clock**: days run cursor+1 → YESTERDAY per
  `RPIM_TIMEZONE` (ADR 0032); a fresh tenant backfills at most
  `INGEST_BACKFILL_DAYS` (default 7).
- **The ga4 connection slot** rides the hub as an ANALYTICS_CONNECTIONS
  entry: owner-gated `PUT /channels/ga4` with non-secret `{property_id}`
  config, NO secret field used, `connected` iff property_id present. The
  publish listing (m16 contract) is untouched, and `tenant_creds`/the
  engine still resolve `SUPPORTED_CHANNELS` only — an analytics slot can
  never be published to.
- **Observability without PII**: `/metrics/ingest` (internal token, beat
  `ingest-analytics` 6h) answers counts only — tenants, connected, days,
  rows, failed. No campaign names, no property ids in responses or logs.

## Out of scope (deliberately)

The learning distiller (unchanged from ADR 0041's plan), the GA4 live
transport, the Umami adapter migration, and dashboard surfaces.

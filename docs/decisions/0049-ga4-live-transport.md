# ADR 0049 — GA4 live transport: REST + SA-JWT, zero new deps (M22 slice F)

**Status:** accepted (2026-07-22)

## Context

ADR 0042 deferred the GA4 live transport to credential provisioning. To
make go-live a pure operator action (flip `GA4_MODE=live` once the
service-account file exists), the transport ships NOW, fully tested
against fakes.

## Decisions

- **REST + PyJWT service-account flow, zero new dependencies**
  (`measurement/ga4_live.py`): the OAuth2 assertion is an RS256 JWT
  (PyJWT + cryptography already ship for auth/vault) exchanged at the
  SA's token_uri; the report is one httpx POST to the official Data API
  `runReport` (rule 5). Rejected alternative: `google-analytics-data`
  SDK — pulls grpc + five transitive deps for one endpoint, and the
  repo's adapter philosophy is thin official-REST clients.
- **Metric mapping (deliberate, documented):** GA4 has no inbound
  "clicks" metric — campaign-attributed `sessions` ARE the
  click-throughs that landed, so `clicks := sessions` and the stored
  sessions field carries `engagedSessions` as the quality signal.
  `"(not set)"`/`"(direct)"` rows are dropped: direct traffic is not a
  campaign and must never poison `campaign_channel_metrics`.
- **Tenant scoping = the property itself.** Each brand connects ITS OWN
  `property_id` via the channels hub, so the report needs no tenant
  filter. Rejected alternative (deviation from ADR 0042's sketch): a
  `sessionCampaignId == utm_id` dimension filter — that design served a
  SHARED property, which is not the SaaS model here; if a shared-property
  mode ever lands, the filter rides the same narrow interface.
- **Token cache**: one exchange per ~55 minutes (module cache, 300s
  safety margin) — a 7-day backfill does 7 report calls, not 7 token
  exchanges.
- **Failure hygiene (rule 4)**: the transport raises ordinary
  exceptions; the provider layer wraps ANY of them as
  `AnalyticsProviderError` carrying the exception CLASS NAME only — and
  (blueprint-review finding) the wrapper raises OUTSIDE the except block
  so neither `__cause__` nor `__context__` carries the original error:
  httpx error strings embed the request URL, which contains the property
  id, and Sentry/`logging.exception` walk the chain. Test-pinned on both
  chain attributes against a production-faithful fake. The cursor stays
  put on failure and resumes exactly (rule 8, unchanged from slice B).
- **Ops surfaces**: `UMAMI_URL`/`UMAMI_SITE_ID`/`UMAMI_API_KEY` names
  land in `.env.iran.example` (they were only in a comment), and
  `docs/ops/go-live.md` records the full operator checklist — channel
  credentials, GA4 provisioning, the watchdog pilot experiment, and the
  rollback levers.

## Consequences

Go-live is now entirely operator-side: enter values in Coolify/dashboard
per the runbook, flip the mode flags, verify per the checklist. No
further code is required for any of the three go-live items.

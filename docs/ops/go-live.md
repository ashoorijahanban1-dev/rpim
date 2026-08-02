# Go-live checklist (operator-only steps)

Everything in this file is an OPERATOR action: it needs secret VALUES,
which never enter the repo, chat sessions, or code (constitution rule 4).
Values go into the Coolify panel or the product dashboard only. Paths and
env NAMES below are exact; do each step in order and verify before the
next.

## 0. Golden rule

Never paste a token/key into a chat or commit. If one leaks, revoke it at
the issuer immediately and re-enter the new value in Coolify.

## 1. Channel + Umami credentials (first — nothing real ships without it)

Obtain:
- Telegram: @BotFather → `/newbot` → token; make the bot an admin of the
  brand channel with post rights.
- Bale: in-app botfather → token; admin the bot in the Bale channel.
- Eitaa: eitaayar.ir panel → token; admin the bot in the Eitaa channel.
- WordPress: wp-admin → Users → Application Passwords → new password.

Enter in Coolify (two separate services):
- **Iran leg (core-api/workers):** `BALE_BOT_TOKEN`, `EITAA_BOT_TOKEN`,
  `WORDPRESS_BASE_URL`, `WORDPRESS_USER`, `WORDPRESS_APP_PASSWORD`,
  `UMAMI_URL`, `UMAMI_SITE_ID`, `UMAMI_API_KEY`
- **US leg (model-gateway):** `TELEGRAM_BOT_TOKEN`

Per brand, in the dashboard → «کانال‌های برند»: enter each channel's
`chat_id`; the hub seals per-tenant values in the AES-GCM vault and the
slot flips to connected.

Flip live + smoke test:
1. Iran leg: `PUBLISH_MODE=live`, `METRICS_MODE=umami` → redeploy both
   services.
2. Create a PRIVATE test channel per messenger, admin the bot, point the
   hub `chat_id` at it temporarily.
3. Dashboard: brief → draft → approve → schedule for +2 minutes on all 3
   messengers.
4. PASS = message appears in all 3 test channels and the publish page
   shows the jobs as `sent`. Then switch `chat_id`s to the real channels.

## 2. GA4 (analytics ingestion)

1. Google Cloud console → create a service account; enable the
   **Analytics Data API**; download the JSON key.
2. In GA4 admin, grant that service-account email **Viewer** on the
   brand's property.
3. Put the JSON file on the Iran leg (a mounted path), set
   `GA4_CREDENTIALS_FILE=<path>` and `GA4_MODE=live` in Coolify →
   redeploy.
4. Each brand: dashboard → channels hub → ga4 slot → enter the numeric
   `property_id`.
5. Verify next day: `campaign_channel_metrics` gains `source=ga4` rows
   (the `ingest-analytics` beat runs 6-hourly; the cursor backfills up to
   `INGEST_BACKFILL_DAYS`).

## 3. Watchdog pilot experiment (7 days)

1. The PILOT brand owner (only): dashboard → «بینش‌ها و آموخته‌ها» →
   «سطح خودمختاری دستیار» → set autonomy level 1.
2. Agent proposals appear in the normal approval queue with the agent
   badge; approve/edit/reject as usual — verdicts are recorded
   automatically.
3. After 7 days read the audit panel on the same page:
   acceptance = accepted / (accepted + dismissed).
   - **≥ 30%** → experiment passes; L2/L3 design unlocks.
   - below → tune `AGENT_MIN_RELEVANCE` (raise toward 50 for stricter
     proposals) and rerun a week.

## Rollback levers (any step, any time)

- `PUBLISH_MODE=fake` — all sends become dry-run instantly.
- Kill switch (`POST /governance/kill`, ops runbook §kill) — halts every
  queue in <5s.
- Autonomy back to 0 — the watchdog goes inert; nothing else changes.
- `GA4_MODE=fake` — ingestion pauses at its cursor, resumes exactly
  later (rule 8).

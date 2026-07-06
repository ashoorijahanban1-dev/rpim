# ADR 0017 — M7 slice B: live channel adapters, telegram cross-leg, beat dispatch

**Status:** accepted (M7, slice B)

**Decisions.**
- **Official bot APIs only (rule 5), split by leg.** Bale
  (`tapi.bale.ai/bot{BALE_BOT_TOKEN}/sendMessage`) and Eitaa
  (`eitaayar.ir/api/{EITAA_BOT_TOKEN}/sendMessage`) send directly from the
  iran leg. Telegram is cross-leg: the iran-leg adapter forwards to the
  us-leg gateway's `POST /publish/telegram` (X-Internal-Token), and only the
  gateway talks to `api.telegram.org`. No browser automation anywhere.
- **HTTP seams for testability.** Both adapters route through module-level
  `_post_json` functions; tests monkeypatch the seam and assert exact URLs,
  payloads, and headers offline. Transport errors surface as
  `ChannelSendError`/`TelegramSendError` so the engine's job-not-lost retry
  semantics (ADR 0016) apply unchanged.
- **PUBLISH_MODE is explicit or nothing.** `fake` → in-process outbox
  (dry-run, tests/CI, and the committed default in both `.env.*.example`);
  `live` → real sends; anything else → loud `ChannelSendError` and the job
  stays queued. A typo'd mode must neither silently dry-run (false "sent")
  nor accidentally publish.
- **Secrets discipline (rule 4).** Error messages name only env var names
  (`BALE_BOT_TOKEN`, `EITAA_BOT_TOKEN`, `TELEGRAM_BOT_TOKEN`, `GATEWAY_URL`,
  `INTERNAL_TOKEN`, `CORE_API_URL`); adapter errors never echo URLs because
  bot-API URLs embed the token. `.env.iran.example`'s stale `EITAA_TOKEN`
  name was corrected to `EITAA_BOT_TOKEN` to match the code.
- **Dispatch cadence via embedded beat.** The workers container runs
  `celery worker -B`; `rpim_workers.tasks.dispatch_publish_queue` POSTs to
  core-api's internal `/publish/dispatch` every 30s (≤60s asserted by test).
  The task is deliberately dumb: the silence/kill check lives INSIDE the
  core-api send path (rule 2), so a broken or hijacked beat can at worst
  call dispatch more often — never bypass governance. Embedded beat (one
  container) is fine while there is exactly one workers replica; a separate
  beat container becomes necessary only when workers scale out.

**Consequences.** Going live per channel = set `PUBLISH_MODE=live` plus that
channel's token in the leg's `.env` (Coolify env for the deployed legs);
everything else keeps dry-running. Real-send verification against live
channels is an ops step (needs real bot tokens), not a CI step.

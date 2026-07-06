# ADR 0027 — gateway telegram-photo passthrough

**Status:** accepted (completes live image posts for telegram)

**Decision.** `POST /publish/telegram-photo` on the us-leg gateway accepts
the multipart form the iran-leg `channels.send_photo` already emits
(chat_id, caption, photo) behind the internal token, and
`telegram.send_telegram_photo` mirrors the text sender exactly: fake mode
records into `_SENT` (`kind: photo`, `image_size`), live mode POSTs
multipart to the official `sendPhoto` bot API through a `_post_multipart`
seam; missing `TELEGRAM_BOT_TOKEN` → 503 naming the env var, transport
failure → 502 → the iran leg treats both as transient and the job waits.

- **Cross-leg idempotency key (rule 8, reviewer-mandated):** the iran leg
  forwards its `job_id` as `request_id` on BOTH telegram endpoints; the
  gateway caches successful responses under `tgpub:{request_id}` (same
  Redis/memory idempotency store as `/complete`) and replays them on retry.
  Cache write happens only AFTER a successful send — a failed send stays
  retryable, a succeeded one can never double-post even if the tunnel drops
  before the iran-leg commit. Bale/Eitaa go direct to their bot APIs, so
  their only remaining window stays the documented crash-between-send-and-
  commit case.

**Consequences.** The full image-post pipeline is live-capable on all three
channels once ops sets `PUBLISH_MODE=live` + bot tokens. 10 new tests; suite
at 344.

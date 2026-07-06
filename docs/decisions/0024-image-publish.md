# ADR 0024 — image posts: renderer wired into the publish pipeline

**Status:** accepted (post-MVP slice A)

**Decisions.**
- **The job stores the render REQUEST, not the pixels**
  (`publish_jobs.image_spec` = {template, size}, migration 0009): dispatch
  renders at send time via `publisher/renderer_client.py`, so a tunnel drop
  mid-render behaves exactly like a dropped send — `ChannelSendError`, job
  stays queued, next pass retries. Fake fetch mode is deterministic
  (byte-identical retries); the live renderer is near-deterministic and a
  re-render on retry is acceptable.
- **Halt check precedes the render** (rule 2 extended): silenced/killed
  tenants get no renders either — proven by a test that fails if
  `render_for_job` is even called while halted.
- **`channels.send_photo`** mirrors `send`: same fake `_OUTBOX`/`_FAIL_NEXT`
  seam (entries carry `kind: photo` + `image_size`), same official-API rule —
  Bale `sendPhoto` and Eitaa `sendFile` direct from the iran leg (multipart),
  telegram photos via a gateway passthrough (`/publish/telegram-photo`) that
  is the NEXT slice; until it exists a live telegram photo send fails
  transiently and the job waits, which is safe-by-default.
- **Slice A text mapping**: the approved post text doubles as the poster
  title (truncated to the template's 300-char limit); brief-driven
  title/body/cta fields on the image spec are a queued follow-up.

**Consequences.** Follow-ups queued: gateway `/publish/telegram-photo`
multipart passthrough; richer image text fields; dashboard queue UI toggle
to attach a template to a job. 17 new tests; suite at 334.

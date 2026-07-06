# ADR 0016 — M7 slice A: publisher core (queue, dispatch, fake channel seam)

**Status:** accepted (M7, slice A)

**Decisions.**
- **Compile gate enforces rules 1 & 3 at job creation.** `POST /publish/jobs`
  accepts only drafts in `approved`/`edited` status (409 otherwise) and only
  with a non-blank `campaign_code` (422); UTM metadata
  (`utm_source`=channel, `utm_medium`, `utm_campaign`=campaign code) is built
  at compile time and stored on the job. The draft text is **frozen into the
  job row** — what was approved is exactly what ships, later draft edits
  cannot leak into an already-compiled job.
- **Halt check INSIDE the send loop (rule 2).** `engine.dispatch_due_jobs`
  calls `is_publishing_halted(session, job.tenant_id)` per job, immediately
  before the channel call. A silence/kill flag raised after queueing still
  blocks the job (status stays `queued`, nothing reaches the channel);
  release is manual-only via the M5 governance endpoints.
- **Delivery semantics: at-least-once, per-job commit.** Each job commits
  right after its send (success → `sent`; transient failure → stays `queued`
  with `attempts` incremented and `last_error` recorded). A crash or tunnel
  drop mid-run therefore loses nothing and never re-sends already-committed
  jobs. The only double-send window is a crash between the channel API call
  and its commit; we accept that for slice A (single dispatcher process) and
  will add channel-side dedup where the messenger API allows it in slice B.
  No exactly-once claim is made.
- **Fake channel seam.** `publisher/channels.py` routes all sends through an
  in-process `_OUTBOX` when `PUBLISH_MODE=fake` (tests/CI), with `_FAIL_NEXT`
  for one-shot transient-failure injection — this is how the §6.4 acceptance
  («قطع تونل وسط انتشار → نه گم شدن، نه دوباره‌فرستادن؛ پرچم سکوت → توقف فوری
  حتی برای جاب‌های در صف») is executable in CI. In any other mode the adapter
  raises loudly instead of silently dropping; real Bale/Eitaa (iran leg,
  official bot APIs) and Telegram-via-gateway (us leg) land in slice B
  (rule 5: official APIs only).
- **Dispatch is an internal ops surface.** `POST /publish/dispatch` is
  guarded by `X-Internal-Token` (403 without it), same trust boundary as the
  global kill switch — tenants cannot trigger dispatch. Slice B calls it from
  Celery beat; keeping it an HTTP endpoint keeps the engine testable and lets
  ops force a dispatch pass manually.
- **Isolation (rule 6).** `publish_jobs` carries `tenant_id`; every query on
  the table — router and engine alike — is tenant-scoped, and the table
  ships with cross-tenant isolation tests
  (`test_m7_list_jobs_cross_tenant_isolation`,
  `test_m7_create_job_404_cross_tenant_draft`). The dispatch engine fans out
  over the tenant registry (`select(Tenant.id)`) and issues one scoped
  `publish_jobs` query per tenant, so no query ever crosses tenant rows —
  accepted cost: one extra SELECT per tenant per dispatch pass, irrelevant at
  MVP scale and trivially shardable later.

**Consequences.** Scheduling (`scheduled_at`) is respected by dispatch but
nothing calls dispatch periodically yet — slice B adds Celery beat. The
`sending` claim-state pattern (at-most-once) was rejected because a crash
would strand jobs in `sending`, violating the "nothing gets lost" acceptance
without a reaper process.

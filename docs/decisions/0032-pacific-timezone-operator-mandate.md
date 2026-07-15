# ADR 0032 — App timezone = America/Los_Angeles (operator mandate, env-reversible)

**Status:** accepted (2026-07-14) — by explicit operator decision, confirmed
twice after hearing the engineering objection below.

## Decision

- A single source of truth, `rpim_shared.tz` (`RPIM_TIMEZONE`, default
  `America/Los_Angeles`; frontend mirror `NEXT_PUBLIC_RPIM_TIMEZONE` in
  `lib/format.ts`), now feeds every wall-clock read:
  model `created_at`/`updated_at` stamps, report month bucketing
  (`month_key` converts aware stamps), CRM sync month, export stamps,
  publish `sent_at`, Umami click month windows, Celery beat timezone, the
  dashboard's current-month picker and `faDateTime` rendering.
- `TZ`/`RPIM_TIMEZONE` env names ship in both `.env.*.example` templates so
  container logs and libc time follow the same clock.
- Timestamps stay **timezone-aware** — Postgres `timestamptz` still stores
  absolute instants; scheduled-vs-now comparisons remain instant-correct.

## Recorded objection (kept for the record, not re-litigated)

RPIM is a Persian-market product; its users, publish scheduling and monthly
reports live in Tehran time. Pacific bucketing shifts month/day boundaries
by 10.5–11.5 hours relative to the audience, and rows written before this
ADR were bucketed by their UTC fields, so month totals around boundaries are
mixed-basis. Recommendation was UTC storage + Tehran display. The operator
confirmed Pacific regardless; this ADR implements it faithfully.

## Revert path (one lever)

Set `RPIM_TIMEZONE` (and `NEXT_PUBLIC_RPIM_TIMEZONE`) to `UTC` or
`Asia/Tehran` and redeploy — no code changes; `rpim_shared/tests/test_tz.py`
pins the override behavior.

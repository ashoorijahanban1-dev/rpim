# ADR 0021 — M9 slice B: clicks in the report + dashboard report page

**Status:** accepted (M9, slice B — completes the milestone)

**Decisions.**
- **Clicks come from Umami keyed by `utm_campaign`**
  (`measurement/clicks.py`): the same campaign code that
  `build_landing_url` stamped onto every landing link at job birth is the
  join key back — closing the «پست → کلیک → لندینگ» loop of the §6.4
  acceptance. `CLICKS_MODE=fake` serves tests via the `_FAKE_CLICKS` seam;
  `umami` mode needs `UMAMI_URL`/`UMAMI_SITE_ID`/`UMAMI_API_KEY` (names
  only in errors, rule 4) and queries the metrics API over the month
  window. Umami itself is a self-hosted container the user-facing landing
  pages embed — ops wiring documented in env examples when the landing
  site exists.
- **The report only surfaces the tenant's own campaigns** (rule 6): click
  counts for campaign codes outside the tenant's month slice never appear,
  even though the counter itself is site-wide.
- **Dashboard `/reports` page**: month picker + drafts/publish/campaigns/
  clicks/costs sections; every string from `locales/fa.json` `reports.*` —
  a static test now enforces "no Persian characters hardcoded in the tsx"
  for this page, mechanizing the constitution's locale rule.

**Consequences.** M9 acceptance is code-complete: post → click → landing
visible in `GET /reports/monthly` and on the dashboard page. Real Umami
counts appear once ops deploys Umami and sets the three env vars
(`CLICKS_MODE=umami`). Next: M10 operational safety, the last milestone
before the MVP Definition of Done.

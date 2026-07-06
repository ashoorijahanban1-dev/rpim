# ADR 0020 — M9 slice A: UTM landing links + monthly report core

**Status:** accepted (M9, slice A)

**Decisions.**
- **UTM compiles into the landing link at job birth** (`measurement/utm.py`):
  `build_landing_url` replaces (never duplicates) `utm_*` params, preserves
  unrelated query params, percent-encodes Persian campaign codes, and rejects
  non-http(s) schemes — validated again at the API edge (422). This starts
  the «پست → کلیک → لندینگ» attribution chain of the M9 acceptance; rule 3
  already guarantees the campaign code exists.
- **`publish_jobs.landing_url` (migration 0008, nullable).** The compiled
  link is frozen on the job like the text: what was approved+compiled is
  what ships; a post may legitimately carry no link.
- **Costs come from the gateway ledger through a fake/remote seam**
  (`measurement/ledger_client.py`, `LEDGER_MODE`): fake returns a
  deterministic entry for offline tests; remote calls
  `GATEWAY_URL/ledger/{tenant}` with the internal token. The ledger is a
  running total today — month-slicing of costs lands when the gateway stamps
  entries with timestamps (queued follow-up, noted in the module docstring).
- **`GET /reports/monthly?month=YYYY-MM`** aggregates in-process over the
  tenant's month slice (drafts by status, publish queued/sent, sent-by-
  channel, per-campaign counts, costs by provider). In-process aggregation
  is deliberate at MVP scale: it sidesteps naive-vs-aware datetime
  comparisons across sqlite/postgres and keeps every DB query a plain
  tenant-scoped SELECT (rule 6); swap to SQL GROUP BY when volumes demand.
- Month validation via FastAPI `Query(pattern=...)` → automatic 422, no
  hand-rolled error strings.

**Consequences.** Slice B: Umami click ingestion keyed by `utm_campaign`
(fake-mode seam like the ledger), clicks column in the monthly report and
campaigns table, dashboard page (Persian locale strings), and the monthly
«چه گرفتید» export. 22 new tests; suite at 275.

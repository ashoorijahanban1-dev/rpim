# ADR 0012 — M2 crawl ingestion (brand's own site)

**Status:** accepted (M2)

**Decisions.**
- **Synchronous, capped crawl** (`POST /brain/sources/crawl`, max 10 pages,
  same-domain BFS): the brand's own site is small and §6.4 M2 does not
  require async; the Celery/cross-leg job architecture arrives with the
  publishing milestones that genuinely need queues (M7) and the M3 trend
  crawlers. Recorded to keep scope honest — not an oversight.
- **SSRF guard before any fetch**: http(s) only; hosts resolving to
  private/loopback/link-local/reserved/multicast ranges are rejected with
  422. Unresolvable hostnames pass (fetch fails naturally; keeps tests
  offline). DNS-rebinding TOCTOU accepted for MVP — the M3 fetcher hardens.
- Extraction: BeautifulSoup text with script/style stripped; pages join into
  ONE brain source (kind="crawl", title=domain) through the shared `_ingest`
  path — content-hash idempotency and tenant scoping inherited; re-crawling
  an unchanged site returns the same source.
- `fetch_page(url) -> (text, same_domain_links)` is the single seam tests
  stub — no network in the suite.

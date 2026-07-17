# ADR 0036 — Radars read real syndication feeds; AI-news radar is global (M19)

**Status:** accepted (2026-07-17)

## Context

The Trend Radar (M14) shipped with a deterministic simulator and a stubbed
live mode. The sprint asks for real external data. Google Trends has no
official API for this use and scraping it violates its ToS — that path is
rejected outright (rule 5's spirit: official interfaces only). RSS/Atom
syndication exists precisely to be fetched, so feeds are the legitimate
real-data source. The sprint also asks for an operator-facing radar of
AI-industry updates surfaced in the Super Admin panel.

## Decision

- **Feeds, not scraping.** `trends/feeds.py` parses RSS 2.0 + Atom
  (stdlib ElementTree; title+link only). Feed URLs are operator-configured
  env values — `TRENDS_FEED_URLS`, `AI_NEWS_FEED_URLS` — never user input.
- **Trend Radar live mode** (`TRENDS_MODE=live`): feed item titles become
  keyword candidates; a deterministic 0..100 score ranks brand-lexicon
  matches above recency (`50 + 30·matches − 2·position`, clamped); each
  entry carries its feed host as `source`. Dead feeds are skipped; ALL dead
  → `TrendSourceError`, so a bad poll keeps the previous batch (rule 8).
  The fake simulator is unchanged and remains the CI/test default.
- **AI-news radar is a GLOBAL table** (`ai_news_items`, Alembic 0014) — the
  deliberate exception to "every table has tenant_id": it holds public
  industry headlines for the OPERATOR, zero tenant data. Its isolation
  proof inverts rule 6: only the admin gate (ADR 0035) can read it, and no
  tenant-facing route touches it. Upsert is by `url` (rule 8).
- **Beat-driven like every radar:** `rpim_workers.refresh_ai_news` pokes
  the internal `/admin/ai-news/refresh` (X-Internal-Token) every 6h; a dead
  source returns `{"upserted": 0}` with 200 so the beat never crash-loops.

## Consequences

- Going live is config-only: set `TRENDS_MODE=live` + feed URLs in Coolify.
  Persian-market feed curation (which feeds serve which vertical) is an
  operator/editorial decision, not code.
- Feed titles are untrusted text: they are stored truncated (200/500 chars)
  and rendered as text in the dashboard — never interpreted, never fed to a
  publish path without the normal draft→approval pipeline.

"""Trend Radar source (M14, live feeds M19) — رادار ایده‌ی محتوا.

TRENDS_MODE=fake (default, tests/CI/pilot) produces a DETERMINISTIC simulated
batch seeded by the tenant id + its brand lexicon, so each brand gets a
stable, relevant-looking radar without network access. TRENDS_MODE=live
(M19) reads real syndication feeds from TRENDS_FEED_URLS: item titles become
keyword candidates, titles matching the brand lexicon rank higher, and each
entry carries its feed host as source. A dead feed is skipped; all feeds
dead → TrendSourceError so a bad poll never wipes the previous batch.
"""

import hashlib
import os
from urllib.parse import urlparse

import httpx

from rpim_core_api.trends import feeds


class TrendSourceError(Exception):
    """Trend source unavailable/misconfigured — refresh skips, radar keeps
    its previous batch (rule 8: a failed poll must not wipe state)."""


BATCH_SIZE = 8

# Persian marketing angles the simulator combines with brand lexicon terms.
_ANGLES = (
    "قیمت {kw}",
    "خرید {kw}",
    "مقایسه {kw}",
    "بهترین {kw} ۱۴۰۵",
    "آموزش {kw}",
    "تخفیف {kw}",
    "نقد و بررسی {kw}",
    "ترند {kw}",
)


def fetch_trends(tenant_id: str, lexicon: list[str]) -> list[dict]:
    """Return [{keyword, score, source}] — at most BATCH_SIZE rows."""
    mode = os.environ.get("TRENDS_MODE", "fake")
    if mode == "fake":
        seeds = [term for term in lexicon if term.strip()] or [f"برند {tenant_id[:6]}"]
        batch: list[dict] = []
        for index, angle in enumerate(_ANGLES[:BATCH_SIZE]):
            term = seeds[index % len(seeds)]
            keyword = angle.format(kw=term)
            digest = hashlib.sha256(f"{tenant_id}:{keyword}".encode()).digest()
            batch.append(
                {"keyword": keyword, "score": digest[0] * 100 // 255, "source": "simulated"}
            )
        return batch
    if mode != "live":
        raise TrendSourceError("TRENDS_MODE must be 'fake' or 'live'")
    return _fetch_live(lexicon)


def _fetch_live(lexicon: list[str]) -> list[dict]:
    urls = [
        u.strip()
        for u in os.environ.get("TRENDS_FEED_URLS", "").split(",")
        if u.strip()
    ]
    if not urls:
        # Name the env var, never a value (rule 4).
        raise TrendSourceError("missing config: env var TRENDS_FEED_URLS is not set")

    candidates: list[tuple[str, str, int]] = []  # (title, host, position)
    reachable = 0
    for url in urls:
        try:
            response = httpx.get(url, timeout=20, follow_redirects=True)
            response.raise_for_status()
            entries = feeds.parse_feed(response.text)
        except (httpx.HTTPError, feeds.FeedParseError):
            continue  # a dead/garbled feed must not sink the whole poll
        reachable += 1
        host = urlparse(url).netloc or "rss"
        for position, entry in enumerate(entries):
            candidates.append((entry["title"], host, position))
    if reachable == 0:
        # Rule 8: the refresh keeps the previous batch instead of wiping it.
        raise TrendSourceError("all trend feeds unreachable — keeping previous batch")

    terms = [term.strip() for term in lexicon if term.strip()]
    seen: set[str] = set()
    scored: list[dict] = []
    for title, host, position in candidates:
        keyword = title[:200]  # column budget
        if keyword in seen:
            continue
        seen.add(keyword)
        relevance = sum(1 for term in terms if term in title)
        # Deterministic 0..100: newer items (low position) and lexicon
        # matches rank higher; relevance dominates recency.
        score = max(1, min(100, 50 + 30 * relevance - 2 * position))
        scored.append({"keyword": keyword, "score": score, "source": host})
    scored.sort(key=lambda e: (-e["score"], e["keyword"]))
    return scored[:BATCH_SIZE]

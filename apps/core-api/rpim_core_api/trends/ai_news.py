"""AI-industry news source (M19) — رادار اخبار AI for the operator.

AI_NEWS_MODE=fake (default, tests/CI) returns a deterministic simulated
batch. live mode reads AI_NEWS_FEED_URLS (comma-separated RSS/Atom of
official vendor blogs/newsrooms — legitimate syndication only). Dead feeds
are skipped; nothing reachable → AiNewsSourceError so the caller keeps the
stored items (rule 8: a bad poll never wipes state).
"""

import os
from urllib.parse import urlparse

import httpx

from rpim_core_api.trends import feeds


class AiNewsSourceError(Exception):
    """News source unavailable/misconfigured — refresh keeps stored items."""


_FAKE_ITEMS = (
    {
        "title": "مدل زبانی نسل بعدی معرفی شد — پنجره متن بلندتر",
        "url": "https://simulated.rpim/ai/1",
        "source": "simulated",
    },
    {
        "title": "ابزار تازه تولید ویدیوی تبلیغاتی با پرامپت متنی",
        "url": "https://simulated.rpim/ai/2",
        "source": "simulated",
    },
    {
        "title": "کاهش قیمت API مدل‌های تصویری برای کسب‌وکارها",
        "url": "https://simulated.rpim/ai/3",
        "source": "simulated",
    },
)


def fetch_news() -> list[dict]:
    """Return [{title, url, source}] — deduplicated on url."""
    mode = os.environ.get("AI_NEWS_MODE", "fake")
    if mode == "fake":
        return [dict(item) for item in _FAKE_ITEMS]
    if mode != "live":
        raise AiNewsSourceError("AI_NEWS_MODE must be 'fake' or 'live'")

    urls = [
        u.strip()
        for u in os.environ.get("AI_NEWS_FEED_URLS", "").split(",")
        if u.strip()
    ]
    if not urls:
        # Name the env var, never a value (rule 4).
        raise AiNewsSourceError("missing config: env var AI_NEWS_FEED_URLS is not set")

    items: list[dict] = []
    seen: set[str] = set()
    reachable = 0
    for feed_url in urls:
        try:
            response = httpx.get(feed_url, timeout=20, follow_redirects=True)
            response.raise_for_status()
            entries = feeds.parse_feed(response.text)
        except (httpx.HTTPError, feeds.FeedParseError):
            continue  # one dead feed must not sink the poll
        reachable += 1
        host = urlparse(feed_url).netloc or "rss"
        for entry in entries:
            link = entry["link"].strip()
            if not link or link in seen:
                continue
            seen.add(link)
            items.append({"title": entry["title"], "url": link, "source": host})
    if reachable == 0:
        raise AiNewsSourceError("all AI news feeds unreachable — keeping stored items")
    return items

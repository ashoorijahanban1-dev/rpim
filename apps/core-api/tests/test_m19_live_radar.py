"""
M19 acceptance tests (slice A) — the Trend Radar reads REAL market feeds.

Contract:
  trends/feeds.py
    - parse_feed(xml_text) → [{title, link}] for both RSS 2.0 and Atom
    - malformed XML → FeedParseError (never a silent empty batch)

  trends/radar.py  TRENDS_MODE=live
    - Reads TRENDS_FEED_URLS (comma-separated RSS/Atom URLs — legitimate
      syndication only, NO ToS-breaking scraping; rule 5 spirit).
    - Missing env → TrendSourceError NAMING the var (rule 4).
    - Each reachable feed contributes item titles as keyword candidates;
      titles matching the tenant's brand lexicon score HIGHER (relevance).
    - Entries carry source = the feed's host, so the radar UI can say where
      a signal came from; scores stay within 0..100; batch ≤ BATCH_SIZE.
    - A dead feed is skipped; ALL feeds dead → TrendSourceError so the
      refresh keeps the previous batch (rule 8 — never wipe on a bad poll).
    - Deterministic for fixed feed content.

  POST /trends/refresh (internal) persists live entries with their feed
  source, tenant-scoped (rule 6), replay-safe on (tenant, keyword, source).

All tests named test_m19_<criterion>. Fake-mode behavior stays covered by
test_m14_trends (the fake simulator is unchanged).
"""

from __future__ import annotations

import os
import secrets as _secrets

import pytest
from fastapi.testclient import TestClient

from rpim_core_api.trends import feeds, radar

os.environ.setdefault("EMBED_MODE", "fake")
os.environ.setdefault("COMPLETE_MODE", "fake")
_INTERNAL_TOKEN: str = os.environ.setdefault("INTERNAL_TOKEN", _secrets.token_hex(32))

_RSS_MARKET = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>اخبار بازار</title>
<item><title>روش‌های تازه بازاریابی محتوایی</title><link>https://news.example/1</link></item>
<item><title>قیمت دزدگیر اماکن در بازار امسال</title><link>https://news.example/2</link></item>
<item><title>رشد فروش آنلاین در ایران</title><link>https://news.example/3</link></item>
</channel></rss>"""

_ATOM_TECH = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>فناوری</title>
<entry><title>مقایسه دوربین مداربسته و دزدگیر</title><link href="https://tech.example/a"/></entry>
<entry><title>آینده خانه‌های هوشمند</title><link href="https://tech.example/b"/></entry>
</feed>"""


class _Resp:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self):
        return None


def _feed_map(mapping: dict[str, str]):
    def fake_get(url, timeout=None, follow_redirects=None, headers=None):
        if url not in mapping:
            import httpx  # noqa: PLC0415

            raise httpx.ConnectError(f"unreachable in test: {url}")
        return _Resp(mapping[url])

    return fake_get


# ===========================================================================
# 1. Feed parsing — RSS 2.0 and Atom
# ===========================================================================


def test_m19_parse_rss_titles_and_links():
    items = feeds.parse_feed(_RSS_MARKET)
    assert [i["title"] for i in items] == [
        "روش‌های تازه بازاریابی محتوایی",
        "قیمت دزدگیر اماکن در بازار امسال",
        "رشد فروش آنلاین در ایران",
    ]
    assert items[0]["link"] == "https://news.example/1"


def test_m19_parse_atom_titles_and_links():
    items = feeds.parse_feed(_ATOM_TECH)
    assert [i["title"] for i in items] == [
        "مقایسه دوربین مداربسته و دزدگیر",
        "آینده خانه‌های هوشمند",
    ]
    assert items[0]["link"] == "https://tech.example/a"


def test_m19_parse_malformed_raises():
    with pytest.raises(feeds.FeedParseError):
        feeds.parse_feed("<html>این فید نیست</html>")
    with pytest.raises(feeds.FeedParseError):
        feeds.parse_feed("not xml at all <<<")


# ===========================================================================
# 2. Live radar — env guard, relevance, sources, resilience
# ===========================================================================


def test_m19_live_missing_env_names_the_var(monkeypatch):
    monkeypatch.setenv("TRENDS_MODE", "live")
    monkeypatch.delenv("TRENDS_FEED_URLS", raising=False)
    with pytest.raises(radar.TrendSourceError) as excinfo:
        radar.fetch_trends("ten-live", ["دزدگیر"])
    assert "TRENDS_FEED_URLS" in str(excinfo.value), (
        f"error must NAME the env var (rule 4): {excinfo.value}"
    )


def test_m19_live_batch_from_real_feeds(monkeypatch):
    import httpx  # noqa: PLC0415

    monkeypatch.setenv("TRENDS_MODE", "live")
    monkeypatch.setenv(
        "TRENDS_FEED_URLS", "https://news.example/rss, https://tech.example/atom"
    )
    monkeypatch.setattr(
        httpx,
        "get",
        _feed_map(
            {
                "https://news.example/rss": _RSS_MARKET,
                "https://tech.example/atom": _ATOM_TECH,
            }
        ),
    )

    batch = radar.fetch_trends("ten-live", ["دزدگیر"])
    assert 0 < len(batch) <= radar.BATCH_SIZE
    by_keyword = {entry["keyword"]: entry for entry in batch}
    assert "قیمت دزدگیر اماکن در بازار امسال" in by_keyword, (
        f"feed titles must become radar keywords: {sorted(by_keyword)}"
    )
    for entry in batch:
        assert 0 <= entry["score"] <= 100, entry
        assert entry["source"] in {"news.example", "tech.example"}, (
            f"entries must carry the FEED HOST as source: {entry}"
        )
    matched = by_keyword["قیمت دزدگیر اماکن در بازار امسال"]["score"]
    unmatched = by_keyword["رشد فروش آنلاین در ایران"]["score"]
    assert matched > unmatched, (
        "lexicon-relevant titles must outrank unrelated ones "
        f"(matched={matched}, unmatched={unmatched})"
    )


def test_m19_live_dead_feed_is_skipped_all_dead_raises(monkeypatch):
    import httpx  # noqa: PLC0415

    monkeypatch.setenv("TRENDS_MODE", "live")
    monkeypatch.setenv(
        "TRENDS_FEED_URLS", "https://dead.example/rss,https://news.example/rss"
    )
    monkeypatch.setattr(
        httpx, "get", _feed_map({"https://news.example/rss": _RSS_MARKET})
    )
    batch = radar.fetch_trends("ten-live", [])
    assert batch, "one live feed must be enough to serve a batch"
    assert {entry["source"] for entry in batch} == {"news.example"}

    monkeypatch.setenv("TRENDS_FEED_URLS", "https://dead.example/rss")
    with pytest.raises(radar.TrendSourceError):
        radar.fetch_trends("ten-live", [])


def test_m19_live_is_deterministic_for_fixed_content(monkeypatch):
    import httpx  # noqa: PLC0415

    monkeypatch.setenv("TRENDS_MODE", "live")
    monkeypatch.setenv("TRENDS_FEED_URLS", "https://news.example/rss")
    monkeypatch.setattr(httpx, "get", _feed_map({"https://news.example/rss": _RSS_MARKET}))
    first = radar.fetch_trends("ten-det", ["بازاریابی"])
    second = radar.fetch_trends("ten-det", ["بازاریابی"])
    assert first == second, "same feed content must produce the same batch"


# ===========================================================================
# 3. End-to-end through the internal refresh (rule 6 + rule 8)
# ===========================================================================


def _register(client: TestClient, email: str, name: str) -> str:
    resp = client.post(
        "/auth/register",
        json={"email": email, "password": "Password123!", "tenant_name": name},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_m19_refresh_persists_feed_sourced_trends(client: TestClient, monkeypatch):
    import httpx  # noqa: PLC0415

    monkeypatch.setenv("TRENDS_MODE", "live")
    monkeypatch.setenv("TRENDS_FEED_URLS", "https://news.example/rss")
    monkeypatch.setattr(httpx, "get", _feed_map({"https://news.example/rss": _RSS_MARKET}))

    token = _register(client, "radar-live@example.com", "RadarLive")
    for _ in range(2):  # replay must upsert, never duplicate (rule 8)
        resp = client.post(
            "/trends/refresh", headers={"X-Internal-Token": _INTERNAL_TOKEN}
        )
        assert resp.status_code == 200, resp.text

    items = client.get("/trends", headers=_auth(token)).json()["items"]
    keywords = [i["keyword"] for i in items]
    assert "قیمت دزدگیر اماکن در بازار امسال" in keywords, keywords
    assert len(keywords) == len(set(keywords)), f"replay duplicated rows: {keywords}"
    assert {i["source"] for i in items} == {"news.example"}

"""
M19 acceptance tests (slice B) — AI-industry news radar (رادار اخبار AI).

Contract:
  ai_news_items (Alembic 0014) — a GLOBAL platform table, deliberately
  tenant-free: it holds public AI-industry headlines for the OPERATOR, never
  tenant data. Isolation proof (rule 6): only the admin gate can read it and
  no tenant-facing route exposes it.

  POST /admin/ai-news/refresh   (X-Internal-Token — beat-driven)
    - AI_NEWS_MODE=fake → deterministic simulated items (tests/CI)
    - AI_NEWS_MODE=live → fetches AI_NEWS_FEED_URLS (RSS/Atom); a dead
      source yields {"upserted": 0, ...} with 200 — the beat must never
      crash-loop, and a bad poll never wipes stored items (rule 8).
    - Upsert by url: replay never duplicates.
  GET /admin/ai-news            (admin allowlist gate, M18)
    - 401 anonymous / 403 non-admin / 200 admin
    - newest-first items {title, url, source, fetched_at}

  Worker: rpim_workers.refresh_ai_news beat task pokes the internal
  endpoint (tested in apps/workers/tests/test_m19_ai_news_beat.py).

  Admin page shows the suggestions section (fa.admin.suggestions*).

All tests named test_m19_<criterion>.
"""

from __future__ import annotations

import json
import os
import re
import secrets as _secrets
from pathlib import Path

from fastapi.testclient import TestClient

os.environ.setdefault("EMBED_MODE", "fake")
os.environ.setdefault("COMPLETE_MODE", "fake")
os.environ.setdefault("AI_NEWS_MODE", "fake")
_INTERNAL_TOKEN: str = os.environ.setdefault("INTERNAL_TOKEN", _secrets.token_hex(32))

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PAGE_TSX = _REPO_ROOT / "apps" / "dashboard" / "app" / "admin" / "page.tsx"
_FA_JSON = _REPO_ROOT / "apps" / "dashboard" / "locales" / "fa.json"

_ATOM_AI = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>AI blog</title>
<entry><title>مدل زبانی تازه معرفی شد</title><link href="https://ai.example/n1"/></entry>
<entry><title>ابزار جدید تولید ویدیو</title><link href="https://ai.example/n2"/></entry>
</feed>"""


def _register(client: TestClient, email: str, name: str) -> str:
    resp = client.post(
        "/auth/register",
        json={"email": email, "password": "Password123!", "tenant_name": name},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _refresh(client: TestClient) -> dict:
    resp = client.post(
        "/admin/ai-news/refresh", headers={"X-Internal-Token": _INTERNAL_TOKEN}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ===========================================================================
# 1. Internal refresh — trust boundary + idempotent upsert
# ===========================================================================


def test_m19_ai_refresh_requires_internal_token(client: TestClient):
    assert client.post("/admin/ai-news/refresh").status_code == 403
    assert (
        client.post(
            "/admin/ai-news/refresh", headers={"X-Internal-Token": "wrong"}
        ).status_code
        == 403
    )


def test_m19_ai_refresh_fake_upserts_replay_safe(client: TestClient, monkeypatch):
    monkeypatch.setenv("AI_NEWS_MODE", "fake")
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    admin = _register(client, "boss@example.com", "BossCo")

    first = _refresh(client)
    assert first["upserted"] >= 1, first
    count_first = len(client.get("/admin/ai-news", headers=_auth(admin)).json()["items"])
    _refresh(client)  # replay
    count_second = len(client.get("/admin/ai-news", headers=_auth(admin)).json()["items"])
    assert count_second == count_first, "replayed refresh must upsert, not duplicate"


def test_m19_ai_refresh_live_dead_source_returns_zero_not_crash(
    client: TestClient, monkeypatch
):
    monkeypatch.setenv("AI_NEWS_MODE", "live")
    monkeypatch.delenv("AI_NEWS_FEED_URLS", raising=False)
    body = _refresh(client)  # 200, never a beat crash-loop
    assert body["upserted"] == 0, body


def test_m19_ai_refresh_live_reads_feeds(client: TestClient, monkeypatch):
    import httpx  # noqa: PLC0415

    class _Resp:
        def __init__(self, text: str):
            self.text = text

        def raise_for_status(self):
            return None

    monkeypatch.setenv("AI_NEWS_MODE", "live")
    monkeypatch.setenv("AI_NEWS_FEED_URLS", "https://ai.example/feed")
    monkeypatch.setenv("ADMIN_EMAILS", "boss2@example.com")

    def fake_get(url, timeout=None, follow_redirects=None, headers=None):
        assert url == "https://ai.example/feed"
        return _Resp(_ATOM_AI)

    monkeypatch.setattr(httpx, "get", fake_get)
    admin = _register(client, "boss2@example.com", "BossTwo")

    body = _refresh(client)
    assert body["upserted"] == 2, body
    items = client.get("/admin/ai-news", headers=_auth(admin)).json()["items"]
    by_url = {i["url"]: i for i in items}
    assert "https://ai.example/n1" in by_url, by_url
    assert by_url["https://ai.example/n1"]["title"] == "مدل زبانی تازه معرفی شد"
    assert by_url["https://ai.example/n1"]["source"] == "ai.example"


# ===========================================================================
# 2. Admin read — the gate IS the isolation proof (rule 6)
# ===========================================================================


def test_m19_ai_news_list_admin_gated(client: TestClient, monkeypatch):
    assert client.get("/admin/ai-news").status_code == 401
    monkeypatch.setenv("ADMIN_EMAILS", "boss3@example.com")
    tenant = _register(client, "mortal-ai@example.com", "MortalAi")
    assert client.get("/admin/ai-news", headers=_auth(tenant)).status_code == 403
    admin = _register(client, "boss3@example.com", "BossThree")
    resp = client.get("/admin/ai-news", headers=_auth(admin))
    assert resp.status_code == 200, resp.text
    assert "items" in resp.json()


def test_m19_ai_news_items_shape_newest_first(client: TestClient, monkeypatch):
    monkeypatch.setenv("AI_NEWS_MODE", "fake")
    monkeypatch.setenv("ADMIN_EMAILS", "boss4@example.com")
    admin = _register(client, "boss4@example.com", "BossFour")
    _refresh(client)
    items = client.get("/admin/ai-news", headers=_auth(admin)).json()["items"]
    assert items, "fake mode must seed suggestions"
    for item in items:
        assert set(item) >= {"title", "url", "source", "fetched_at"}, item
    stamps = [i["fetched_at"] for i in items]
    assert stamps == sorted(stamps, reverse=True), f"newest first: {stamps}"


# ===========================================================================
# 3. Dashboard static contract — suggestions section on the admin page
# ===========================================================================


def test_m19_admin_page_shows_suggestions_section():
    src = _PAGE_TSX.read_text("utf-8")
    assert "/admin/ai-news" in src, "admin page must load the AI news radar"
    assert not re.compile(r"[؀-ۿ]").search(src), "locale-only rule"
    fa = json.loads(_FA_JSON.read_text("utf-8"))
    section = fa.get("admin", {})
    for key in ("suggestions_title", "suggestions_hint", "suggestions_empty",
                "suggestions_source", "suggestions_open"):
        assert section.get(key), f"fa.admin.{key} missing/empty"


# ===========================================================================
# 4. Env templates carry the NAMES (rule 4, iran leg)
# ===========================================================================


def test_m19_env_example_names_radar_vars():
    text = (_REPO_ROOT / ".env.iran.example").read_text("utf-8")
    for var in ("TRENDS_MODE", "TRENDS_FEED_URLS", "AI_NEWS_MODE", "AI_NEWS_FEED_URLS"):
        assert re.search(rf"^{var}=", text, re.MULTILINE), (
            f".env.iran.example must name {var} (rule 4)"
        )

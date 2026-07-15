"""
M14 acceptance tests — Trend Radar (رادار ایده‌ی محتوا).

Contract:
  POST /trends/refresh  (X-Internal-Token boundary, beat-driven like /crm/sync)
    - 403 without/with wrong internal token
    - For every tenant: TRENDS_MODE=fake produces a deterministic simulated
      batch seeded by the tenant's brand profile; rows UPSERT on
      (tenant_id, keyword, source) so replays never duplicate (rule 8)
    - TRENDS_MODE=live without TRENDS_SOURCE_URL → clean error naming the
      env VAR (rule 4) — the real source layer is the فاز ۲ slice

  GET /trends  (tenant Bearer auth)
    - 401 without token
    - Returns ONLY the calling tenant's items (rule 6), sorted score desc,
      each {keyword, source, score, captured_at}

Dashboard static contract: /trends page exists, appears in the sidebar,
locale-only Persian (fa.trends section).

All tests named test_m14_<criterion>.
"""

from __future__ import annotations

import json
import os
import re
import secrets as _secrets
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rpim_core_api.trends import radar

os.environ.setdefault("EMBED_MODE", "fake")
os.environ.setdefault("COMPLETE_MODE", "fake")
os.environ.setdefault("TRENDS_MODE", "fake")
_INTERNAL_TOKEN: str = os.environ.setdefault("INTERNAL_TOKEN", _secrets.token_hex(32))

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PAGE_TSX = _REPO_ROOT / "apps" / "dashboard" / "app" / "trends" / "page.tsx"
_SIDEBAR = _REPO_ROOT / "apps" / "dashboard" / "components" / "Sidebar.tsx"
_FA_JSON = _REPO_ROOT / "apps" / "dashboard" / "locales" / "fa.json"


def _register(client: TestClient, email: str, password: str, tenant_name: str) -> dict:
    resp = client.post(
        "/auth/register",
        json={"email": email, "password": password, "tenant_name": tenant_name},
    )
    assert resp.status_code == 201, f"register failed: {resp.text}"
    return resp.json()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _internal_header() -> dict:
    return {"X-Internal-Token": _INTERNAL_TOKEN}


# ===========================================================================
# 1. Trust boundaries
# ===========================================================================


def test_m14_refresh_requires_internal_token(client: TestClient):
    resp = client.post("/trends/refresh")
    assert resp.status_code == 403, f"expected 403, got {resp.status_code}: {resp.text}"
    resp = client.post("/trends/refresh", headers={"X-Internal-Token": "wrong"})
    assert resp.status_code == 403, f"expected 403, got {resp.status_code}: {resp.text}"


def test_m14_list_requires_auth(client: TestClient):
    resp = client.get("/trends")
    assert resp.status_code == 401, f"expected 401, got {resp.status_code}: {resp.text}"


# ===========================================================================
# 2. Refresh — simulated batch, shape, idempotent upsert (rule 8)
# ===========================================================================


def test_m14_refresh_populates_tenant_radar(client: TestClient):
    token = _register(client, "radar-a@example.com", "Password123!", "RadarA")[
        "access_token"
    ]
    resp = client.post("/trends/refresh", headers=_internal_header())
    assert resp.status_code == 200, resp.text

    resp = client.get("/trends", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) >= 5, f"a refresh must yield a usable radar batch: {items}"
    for item in items:
        assert set(item) >= {"keyword", "source", "score", "captured_at"}, item
        assert 0 <= item["score"] <= 100, item
        assert item["source"] == "simulated", item
    scores = [i["score"] for i in items]
    assert scores == sorted(scores, reverse=True), f"items must sort score desc: {scores}"


def test_m14_refresh_is_idempotent_upsert(client: TestClient):
    token = _register(client, "radar-idem@example.com", "Password123!", "RadarIdem")[
        "access_token"
    ]
    assert client.post("/trends/refresh", headers=_internal_header()).status_code == 200
    first = client.get("/trends", headers=_auth(token)).json()["items"]
    assert client.post("/trends/refresh", headers=_internal_header()).status_code == 200
    second = client.get("/trends", headers=_auth(token)).json()["items"]
    assert len(second) == len(first), (
        f"replayed refresh must UPSERT, not duplicate (rule 8): "
        f"{len(first)} -> {len(second)}"
    )
    assert {i["keyword"] for i in second} == {i["keyword"] for i in first}


def test_m14_fake_batch_is_deterministic_per_tenant(client: TestClient):
    """Same tenant → same simulated keywords across refreshes (stable radar);
    different tenants → not the identical batch (profile-seeded)."""
    token_a = _register(client, "radar-d1@example.com", "Password123!", "RadarD1")[
        "access_token"
    ]
    token_b = _register(client, "radar-d2@example.com", "Password123!", "RadarD2")[
        "access_token"
    ]
    assert client.post("/trends/refresh", headers=_internal_header()).status_code == 200
    a_items = {i["keyword"] for i in client.get("/trends", headers=_auth(token_a)).json()["items"]}
    b_items = {i["keyword"] for i in client.get("/trends", headers=_auth(token_b)).json()["items"]}
    assert a_items and b_items
    assert a_items != b_items, "tenant radars must be profile-seeded, not one global list"


# ===========================================================================
# 3. Tenant isolation (rule 6)
# ===========================================================================


def test_m14_cross_tenant_isolation(client: TestClient):
    """Each tenant's radar is exactly ITS batch (rule 6): batch size is fixed
    per refresh, so any cross-tenant leak would inflate the count, and the
    profile-seeded keyword sets prove whose rows came back."""
    token_a = _register(client, "radar-iso-a@example.com", "Password123!", "RadarIsoA")[
        "access_token"
    ]
    token_b = _register(client, "radar-iso-b@example.com", "Password123!", "RadarIsoB")[
        "access_token"
    ]
    assert client.post("/trends/refresh", headers=_internal_header()).status_code == 200

    a_items = client.get("/trends", headers=_auth(token_a)).json()["items"]
    b_items = client.get("/trends", headers=_auth(token_b)).json()["items"]
    assert len(a_items) == radar.BATCH_SIZE, (
        f"tenant A must see exactly its own batch, got {len(a_items)} "
        f"(a leak would inflate this past {radar.BATCH_SIZE})"
    )
    assert len(b_items) == radar.BATCH_SIZE
    assert {i["keyword"] for i in a_items} != {i["keyword"] for i in b_items}


def test_m14_live_mode_missing_env_names_the_var(monkeypatch):
    monkeypatch.setenv("TRENDS_MODE", "live")
    monkeypatch.delenv("TRENDS_SOURCE_URL", raising=False)
    with pytest.raises(radar.TrendSourceError) as excinfo:
        radar.fetch_trends("tenant-x", ["کلمه"])
    assert "TRENDS_SOURCE_URL" in str(excinfo.value), (
        f"error must NAME the missing env var (rule 4): {excinfo.value}"
    )


# ===========================================================================
# 4. Dashboard static contract
# ===========================================================================


def test_m14_dashboard_page_exists_and_locale_only():
    assert _PAGE_TSX.exists(), "apps/dashboard/app/trends/page.tsx must exist"
    src = _PAGE_TSX.read_text("utf-8")
    assert "/trends" in src, "page must fetch GET /trends"
    assert not re.compile(r"[؀-ۿ]").search(src), (
        "trends page must stay free of hardcoded Persian (locale-only rule)"
    )


def test_m14_sidebar_links_the_radar():
    assert 'href: "/trends"' in _SIDEBAR.read_text("utf-8"), (
        "sidebar must link the trends radar page"
    )


def test_m14_locale_has_trends_section():
    fa = json.loads(_FA_JSON.read_text("utf-8"))
    trends = fa.get("trends", {})
    for key in ("title", "empty", "keyword", "score", "captured_at", "refresh_hint"):
        assert trends.get(key), f"fa.trends.{key} missing/empty"
    assert fa["nav"].get("trends"), "fa.nav.trends missing"

"""
M9 slice C acceptance tests — multi-month trend report (backend → dashboard).

Contract:
  GET /reports/trend?months=N[&until=YYYY-MM]
    - Bearer auth required (401 otherwise)
    - months: int, 1..12, default 6 → response carries exactly N buckets in
      ASCENDING month order, ending at `until` (default: current month)
    - each bucket: {month, drafts_created, drafts_approved, sent, clicks}
    - clicks are counted ONLY for campaign codes belonging to THIS tenant's
      jobs in that month (rule 6 — same containment as /reports/monthly)
    - absolute tenant isolation (rule 6)

Dashboard static contract (no JS runner, mirrors test_m9b_dashboard_locale):
  - reports page calls /reports/trend and renders via fa.json keys only.

All tests named test_m9c_<criterion>. EMBED_MODE/COMPLETE_MODE fake at module
level (established pattern).
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

os.environ.setdefault("EMBED_MODE", "fake")
os.environ.setdefault("COMPLETE_MODE", "fake")
os.environ.setdefault("CLICKS_MODE", "fake")

import pytest
from fastapi.testclient import TestClient

from rpim_core_api.measurement import clicks

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PAGE_TSX = _REPO_ROOT / "apps" / "dashboard" / "app" / "reports" / "page.tsx"
_FA_JSON = _REPO_ROOT / "apps" / "dashboard" / "locales" / "fa.json"

_BRIEF = {
    "goal": "افزایش آگاهی از برند",
    "audience": "مدیران میان‌رده",
    "channel": "تلگرام",
    "format": "پست متنی",
    "hook": None,
    "cta": None,
}


@pytest.fixture(autouse=True)
def _clear_fake_clicks():
    clicks._FAKE_CLICKS.clear()
    yield
    clicks._FAKE_CLICKS.clear()


def _register(client: TestClient, email: str, password: str, tenant_name: str) -> dict:
    resp = client.post(
        "/auth/register",
        json={"email": email, "password": password, "tenant_name": tenant_name},
    )
    assert resp.status_code == 201, f"register failed: {resp.text}"
    return resp.json()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _create_approved_draft(client: TestClient, token: str) -> str:
    resp = client.post("/content/drafts", json={"brief": _BRIEF}, headers=_auth(token))
    assert resp.status_code == 201, f"draft create failed: {resp.text}"
    draft_id = resp.json()["draft_id"]
    resp = client.post(f"/content/drafts/{draft_id}/approve", headers=_auth(token))
    assert resp.status_code == 200, f"approve failed: {resp.text}"
    return draft_id


def _create_job(client: TestClient, token: str, draft_id: str, campaign_code: str):
    return client.post(
        "/publish/jobs",
        json={
            "draft_id": draft_id,
            "channel": "telegram",
            "chat_id": "12345",
            "campaign_code": campaign_code,
        },
        headers=_auth(token),
    )


def _this_month() -> str:
    return datetime.now(UTC).strftime("%Y-%m")


# ===========================================================================
# 1. Auth + validation
# ===========================================================================


def test_m9c_trend_requires_auth(client: TestClient):
    resp = client.get("/reports/trend")
    assert resp.status_code == 401, f"expected 401, got {resp.status_code}: {resp.text}"


def test_m9c_trend_months_bounds(client: TestClient):
    token = _register(client, "trend-bounds@example.com", "Password123!", "TrendBounds")[
        "access_token"
    ]
    for bad in (0, 13, -1):
        resp = client.get(f"/reports/trend?months={bad}", headers=_auth(token))
        assert resp.status_code == 422, (
            f"months={bad} must be rejected with 422, got {resp.status_code}"
        )
    resp = client.get("/reports/trend?until=2026-13", headers=_auth(token))
    assert resp.status_code == 422, f"bad until must 422, got {resp.status_code}"


# ===========================================================================
# 2. Shape — N ascending buckets ending at `until`
# ===========================================================================


def test_m9c_trend_default_shape(client: TestClient):
    token = _register(client, "trend-shape@example.com", "Password123!", "TrendShape")[
        "access_token"
    ]
    resp = client.get("/reports/trend", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    months = resp.json()["months"]
    assert len(months) == 6, f"default window is 6 months, got {len(months)}"
    keys = [m["month"] for m in months]
    assert keys == sorted(keys), f"buckets must ascend chronologically: {keys}"
    assert keys[-1] == _this_month(), f"window must end at current month: {keys}"
    for bucket in months:
        assert set(bucket) == {"month", "drafts_created", "drafts_approved", "sent", "clicks"}, (
            f"unexpected bucket shape: {bucket}"
        )


def test_m9c_trend_until_pins_window(client: TestClient):
    """`until` pins the window end (reproducible reports); data created NOW
    must not leak into a window that ends before this month."""
    token = _register(client, "trend-until@example.com", "Password123!", "TrendUntil")[
        "access_token"
    ]
    _create_approved_draft(client, token)
    resp = client.get("/reports/trend?months=3&until=2020-03", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    months = resp.json()["months"]
    assert [m["month"] for m in months] == ["2020-01", "2020-02", "2020-03"], months
    assert all(
        m["drafts_created"] == 0 and m["sent"] == 0 and m["clicks"] == 0 for m in months
    ), f"a 2020 window must not contain today's data: {months}"


def test_m9c_trend_year_boundary(client: TestClient):
    token = _register(client, "trend-year@example.com", "Password123!", "TrendYear")[
        "access_token"
    ]
    resp = client.get("/reports/trend?months=4&until=2026-02", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    keys = [m["month"] for m in resp.json()["months"]]
    assert keys == ["2025-11", "2025-12", "2026-01", "2026-02"], (
        f"window must cross the year boundary correctly: {keys}"
    )


# ===========================================================================
# 3. Aggregation — current-month bucket carries the funnel counts
# ===========================================================================


def test_m9c_trend_counts_current_month_funnel(client: TestClient):
    token = _register(client, "trend-funnel@example.com", "Password123!", "TrendFunnel")[
        "access_token"
    ]
    draft_id = _create_approved_draft(client, token)
    resp = _create_job(client, token, draft_id, "camp_trend_a")
    assert resp.status_code == 201, f"job create failed: {resp.text}"
    clicks._FAKE_CLICKS["camp_trend_a"] = 9

    resp = client.get("/reports/trend?months=2", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    months = resp.json()["months"]
    last = months[-1]
    assert last["month"] == _this_month()
    assert last["drafts_created"] == 1, last
    assert last["drafts_approved"] == 1, last
    assert last["clicks"] == 9, f"clicks for this tenant's campaign must count: {last}"
    prev = months[0]
    assert prev["drafts_created"] == 0 and prev["clicks"] == 0, (
        f"previous month must stay empty: {prev}"
    )


def test_m9c_trend_foreign_campaign_clicks_never_leak(client: TestClient):
    """rule 6: click counts for campaign codes that do NOT belong to this
    tenant's jobs must not surface in its trend."""
    token = _register(client, "trend-leak@example.com", "Password123!", "TrendLeak")[
        "access_token"
    ]
    draft_id = _create_approved_draft(client, token)
    assert _create_job(client, token, draft_id, "camp_mine").status_code == 201
    clicks._FAKE_CLICKS["camp_mine"] = 3
    clicks._FAKE_CLICKS["camp_foreign"] = 500

    resp = client.get("/reports/trend?months=1", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["months"][-1]["clicks"] == 3, (
        f"foreign campaign clicks leaked into the tenant trend: {resp.json()}"
    )


def test_m9c_trend_cross_tenant_isolation(client: TestClient):
    """rule 6: tenant B's drafts/jobs never appear in tenant A's trend."""
    token_a = _register(client, "trend-a@example.com", "Password123!", "TrendA")[
        "access_token"
    ]
    token_b = _register(client, "trend-b@example.com", "Password123!", "TrendB")[
        "access_token"
    ]
    draft_b = _create_approved_draft(client, token_b)
    assert _create_job(client, token_b, draft_b, "camp_b_only").status_code == 201
    clicks._FAKE_CLICKS["camp_b_only"] = 42

    resp = client.get("/reports/trend?months=1", headers=_auth(token_a))
    assert resp.status_code == 200, resp.text
    bucket = resp.json()["months"][-1]
    assert bucket["drafts_created"] == 0, f"tenant B draft leaked: {bucket}"
    assert bucket["sent"] == 0, f"tenant B job leaked: {bucket}"
    assert bucket["clicks"] == 0, f"tenant B campaign clicks leaked: {bucket}"


# ===========================================================================
# 4. Dashboard static contract (mirrors test_m9b_dashboard_locale)
# ===========================================================================

_NEW_LOCALE_KEYS = {
    "tile_edited",
    "tile_rejected",
    "tile_queued",
    "ctr",
    "ctr_none",
    "percent",
    "trend_heading",
    "trend_table_aria",
    "chart_trend_clicks",
}

_PERSIAN_RE = re.compile(r"[؀-ۿ]")


def test_m9c_dashboard_calls_trend_endpoint():
    src = _PAGE_TSX.read_text("utf-8")
    assert "/reports/trend" in src, (
        "reports page must fetch GET /reports/trend for the multi-month view"
    )


def test_m9c_dashboard_renders_full_draft_funnel_and_ctr():
    """The backend has always computed edited/rejected/queued and per-campaign
    sent+clicks; the page must finally render them (locale keys only)."""
    src = _PAGE_TSX.read_text("utf-8")
    for key in ("tile_edited", "tile_rejected", "tile_queued", "ctr"):
        assert f"fa.reports.{key}" in src, f"page must render fa.reports.{key}"


def test_m9c_locale_carries_new_keys_in_persian():
    fa = json.loads(_FA_JSON.read_text("utf-8"))
    reports = fa["reports"]
    for key in _NEW_LOCALE_KEYS:
        assert key in reports, f"fa.reports.{key} missing"
        assert reports[key], f"fa.reports.{key} empty"
    assert not _PERSIAN_RE.search(_PAGE_TSX.read_text("utf-8")), (
        "reports page must stay free of hardcoded Persian (locale-only rule)"
    )

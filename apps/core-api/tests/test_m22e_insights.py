"""
M22 slice E acceptance tests — tenant insights surfaces (metrics + learnings).

Contract (ADR 0045):
  Backend — GET /metrics/summary (tenant-facing, bearer auth):
    - Reuses the distiller's evidence loader (ONE source of window truth):
      trailing 28 days on the app clock (ADR 0032 — never a hardcoded zone).
    - {window_days, campaigns: [{campaign, clicks, posts_sent, ctr}],
      rejects: {reason: count}} — campaigns sorted clicks-desc; ctr is
      clicks/posts_sent or null when the denominator is 0 (rule 6 scoped).
  Dashboard — /insights page (concept: summary cards + learnings list with
  an expandable evidence detail; the chosen UI comparison lives in the ADR):
    - Persian ONLY from fa.json (insights section + nav.insights).
    - MotionConfig reducedMotion="user" (ADR 0040), aria attributes for
      the retire control, empty/loading/error states from locale keys.
    - Retire wires to POST /learnings/{version}/retire behind an explicit
      in-UI confirm step (human approval; API stays owner-only per M24).

All tests named test_m22e_<criterion>.
"""

from __future__ import annotations

import json
import os
import re
import secrets as _secrets
from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient

os.environ.setdefault("EMBED_MODE", "fake")
os.environ.setdefault("COMPLETE_MODE", "fake")
os.environ.setdefault("PUBLISH_MODE", "fake")
os.environ.setdefault("INTERNAL_TOKEN", _secrets.token_hex(32))

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PAGE_TSX = _REPO_ROOT / "apps" / "dashboard" / "app" / "insights" / "page.tsx"
_SIDEBAR_TSX = _REPO_ROOT / "apps" / "dashboard" / "components" / "Sidebar.tsx"
_FA_JSON = _REPO_ROOT / "apps" / "dashboard" / "locales" / "fa.json"

_PERSIAN_RE = re.compile(r"[؀-ۿ]")


def _session():
    from sqlalchemy.orm import Session  # noqa: PLC0415

    from rpim_core_api import db as db_module  # noqa: PLC0415

    return Session(db_module.engine)


def _register(client: TestClient, email: str, name: str) -> tuple[str, str]:
    resp = client.post(
        "/auth/register",
        json={"email": email, "password": "Password123!", "tenant_name": name},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"], resp.json()["tenant_id"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _seed_metric(
    tenant_id: str, campaign: str, clicks: int, posts_sent: int, days_ago: int = 2
) -> None:
    from rpim_core_api.models import CampaignChannelMetric  # noqa: PLC0415
    from rpim_shared.tz import now_app  # noqa: PLC0415

    with _session() as session:
        session.add(
            CampaignChannelMetric(
                tenant_id=tenant_id,
                campaign_code=campaign,
                channel="web",
                source="umami",
                day=(now_app() - timedelta(days=days_ago)).strftime("%Y-%m-%d"),
                clicks=clicks,
                posts_sent=posts_sent,
            )
        )
        session.commit()


def _seed_reject(tenant_id: str, reason: str) -> None:
    from rpim_core_api.models import ApprenticeEvent  # noqa: PLC0415

    with _session() as session:
        session.add(
            ApprenticeEvent(
                tenant_id=tenant_id,
                kind="rejected",
                payload={"reason_code": reason},
            )
        )
        session.commit()


# ===========================================================================
# 1. GET /metrics/summary — the tenant-facing evidence window
# ===========================================================================


def test_m22e_summary_requires_auth(client: TestClient):
    assert client.get("/metrics/summary").status_code == 401


def test_m22e_summary_shape_ctr_and_sorting(client: TestClient):
    token, tenant_id = _register(client, "m22e-sum@example.com", "M22eSum")
    _seed_metric(tenant_id, "camp-strong", clicks=30, posts_sent=3)
    _seed_metric(tenant_id, "camp-weak", clicks=2, posts_sent=0)
    _seed_reject(tenant_id, "tone")

    body = client.get("/metrics/summary", headers=_auth(token)).json()
    assert body["window_days"] == 28
    assert [c["campaign"] for c in body["campaigns"]] == ["camp-strong", "camp-weak"], (
        "campaigns sort clicks-desc for a stable operational read"
    )
    strong = body["campaigns"][0]
    assert strong["clicks"] == 30 and strong["posts_sent"] == 3
    assert strong["ctr"] == 10.0
    assert body["campaigns"][1]["ctr"] is None, "zero denominator → null, never a crash"
    assert body["rejects"] == {"tone": 1}


def test_m22e_summary_is_tenant_isolated(client: TestClient):
    _token_a, tenant_a = _register(client, "m22e-iso-a@example.com", "M22eIsoA")
    token_b, _tenant_b = _register(client, "m22e-iso-b@example.com", "M22eIsoB")
    _seed_metric(tenant_a, "camp-a", clicks=9, posts_sent=3)

    body = client.get("/metrics/summary", headers=_auth(token_b)).json()
    assert body["campaigns"] == [], "rule 6: no cross-tenant bleed"


def test_m22e_summary_window_rides_the_app_clock(client: TestClient):
    token, tenant_id = _register(client, "m22e-win@example.com", "M22eWin")
    _seed_metric(tenant_id, "camp-old", clicks=50, posts_sent=5, days_ago=40)
    _seed_metric(tenant_id, "camp-new", clicks=5, posts_sent=1, days_ago=2)

    body = client.get("/metrics/summary", headers=_auth(token)).json()
    assert [c["campaign"] for c in body["campaigns"]] == ["camp-new"], (
        "the 28-day window rides now_app() (ADR 0032) — old rows drop out"
    )


# ===========================================================================
# 2. The /insights page — locale-only, motion-safe, accessible, wired
# ===========================================================================


def test_m22e_insights_page_exists_and_is_locale_only():
    assert _PAGE_TSX.exists(), "apps/dashboard/app/insights/page.tsx must exist"
    src = _PAGE_TSX.read_text("utf-8")
    assert not _PERSIAN_RE.search(src), (
        "user-facing Persian lives ONLY in locales/fa.json (constitution)"
    )
    assert "fa.insights." in src, "the page must consume the fa.insights section"


def test_m22e_insights_page_wires_the_vertical():
    src = _PAGE_TSX.read_text("utf-8")
    assert "/metrics/summary" in src, "metrics cards ride GET /metrics/summary"
    assert "/learnings" in src, "learnings list rides GET /learnings"
    assert "/retire" in src, "retire wires to POST /learnings/{version}/retire"
    assert "retire_confirm" in src, (
        "retiring the learned voice takes an explicit in-UI confirm step"
    )


def test_m22e_insights_page_is_motion_safe_and_accessible():
    src = _PAGE_TSX.read_text("utf-8")
    assert "MotionConfig" in src and 'reducedMotion="user"' in src, "ADR 0040"
    assert "aria-" in src, "the page carries aria attributes (a11y baseline)"


def test_m22e_sidebar_links_insights():
    src = _SIDEBAR_TSX.read_text("utf-8")
    assert '"/insights"' in src and "fa.nav.insights" in src


def test_m22e_fa_locale_carries_the_insights_section():
    fa = json.loads(_FA_JSON.read_text("utf-8"))
    assert fa.get("nav", {}).get("insights"), "fa.nav.insights missing/empty"
    section = fa.get("insights", {})
    for key in (
        "title",
        "hint",
        "loading",
        "error",
        "empty_metrics",
        "empty_learnings",
        "card_clicks",
        "card_campaigns",
        "card_rejects",
        "th_campaign",
        "th_clicks",
        "th_posts",
        "th_ctr",
        "learnings_title",
        "version_label",
        "status_active",
        "status_retired",
        "evidence",
        "retire",
        "retire_confirm",
        "retire_done",
    ):
        assert section.get(key), f"fa.insights.{key} missing/empty"
        assert _PERSIAN_RE.search(section[key]), f"fa.insights.{key} must be Persian"

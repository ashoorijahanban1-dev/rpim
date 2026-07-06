"""
M9 slice B acceptance tests — Clicks (Umami seam) + report page.

Blueprint §6.4 M9: «پست → کلیک → لندینگ» visible end-to-end in the report.

Slice A (merged): UTM links + /reports/monthly with
drafts/publish/campaigns[{campaign_code,jobs,sent}]/costs.

Slice B (this file): adds rpim_core_api.measurement.clicks module and wires
its output into the report response so the full «post → click → landing» chain
is visible end-to-end.

The import uses a try/except so collection succeeds even before the module
exists; individual tests call _require_clicks() which emits a clear pytest.fail
rather than an ImportError abort.  This is the standard pattern for cross-
milestone test layering in this repo.

All tests named test_m9b_<criterion>.
"""

from __future__ import annotations

import os
import secrets
from datetime import UTC, datetime

import pytest

# Must be set BEFORE any import of rpim_core_api.measurement — same pattern as
# LEDGER_MODE (see test_m9_measurement.py).
os.environ.setdefault("CLICKS_MODE", "fake")
os.environ.setdefault("LEDGER_MODE", "fake")
os.environ["PUBLISH_MODE"] = "fake"
os.environ.setdefault("EMBED_MODE", "fake")
os.environ.setdefault("COMPLETE_MODE", "fake")

# setdefault: whichever test module is collected first wins; all share the
# same token within one process (mirrors M7/M9 pattern).
_INTERNAL_TOKEN: str = os.environ.setdefault("INTERNAL_TOKEN", secrets.token_hex(32))

from fastapi.testclient import TestClient  # noqa: E402

# ---------------------------------------------------------------------------
# Guarded import: collection succeeds before the module exists; tests fail
# individually via _require_clicks() rather than aborting the full suite.
# ---------------------------------------------------------------------------
try:
    from rpim_core_api.measurement import clicks  # type: ignore[import]

    _clicks_available = True
except ImportError:
    clicks = None  # type: ignore[assignment]
    _clicks_available = False


def _require_clicks() -> None:
    """Fail the calling test clearly if the clicks module is not yet implemented."""
    if not _clicks_available:
        pytest.fail(
            "rpim_core_api.measurement.clicks is not importable — "
            "implement the module first (M9B acceptance criterion)"
        )


# ---------------------------------------------------------------------------
# Brief template (mirrors test_m9_measurement.py)
# ---------------------------------------------------------------------------
_BRIEF = {
    "goal": "افزایش فروش",
    "audience": "مشتریان وفادار",
    "channel": "telegram",
    "format": "پست متنی",
    "hook": None,
    "cta": None,
}


# ---------------------------------------------------------------------------
# Autouse fixture: ensure _FAKE_CLICKS is cleared before and after each test.
# Constitution rule 6: tests must be fully isolated from each other.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_fake_clicks():
    """Reset clicks._FAKE_CLICKS before and after every test (when available)."""
    if _clicks_available:
        clicks._FAKE_CLICKS.clear()
    yield
    if _clicks_available:
        clicks._FAKE_CLICKS.clear()


# ---------------------------------------------------------------------------
# Helpers (mirror M9 pattern exactly)
# ---------------------------------------------------------------------------


def _register(client: TestClient, email: str, password: str, tenant_name: str) -> dict:
    resp = client.post(
        "/auth/register",
        json={"email": email, "password": password, "tenant_name": tenant_name},
    )
    assert resp.status_code == 201, f"register failed: {resp.text}"
    return resp.json()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _setup_tenant(client: TestClient, email: str, password: str, tenant_name: str) -> str:
    return _register(client, email, password, tenant_name)["access_token"]


def _create_draft(client: TestClient, token: str) -> str:
    resp = client.post(
        "/content/drafts",
        json={"brief": _BRIEF},
        headers=_auth(token),
    )
    assert resp.status_code == 201, f"draft create failed: {resp.text}"
    return resp.json()["draft_id"]


def _approve_draft(client: TestClient, token: str, draft_id: str) -> None:
    resp = client.post(f"/content/drafts/{draft_id}/approve", headers=_auth(token))
    assert resp.status_code == 200, f"approve failed: {resp.text}"


def _create_approved_draft(client: TestClient, token: str) -> str:
    draft_id = _create_draft(client, token)
    _approve_draft(client, token, draft_id)
    return draft_id


def _create_job(
    client: TestClient,
    token: str,
    draft_id: str,
    channel: str = "telegram",
    chat_id: str = "12345",
    campaign_code: str = "camp_test_001",
    landing_url: str | None = None,
):
    payload: dict = {
        "draft_id": draft_id,
        "channel": channel,
        "chat_id": chat_id,
        "campaign_code": campaign_code,
    }
    if landing_url is not None:
        payload["landing_url"] = landing_url
    return client.post("/publish/jobs", json=payload, headers=_auth(token))


def _internal_header() -> dict:
    return {"X-Internal-Token": _INTERNAL_TOKEN}


# ===========================================================================
# 1. clicks.fetch_clicks_by_campaign — fake mode seam
# ===========================================================================


def test_m9b_fake_mode_default_empty():
    """CLICKS_MODE=fake, _FAKE_CLICKS empty → fetch_clicks_by_campaign returns {}."""
    _require_clicks()
    # _FAKE_CLICKS is cleared by the autouse fixture above.
    result = clicks.fetch_clicks_by_campaign("2026-07")
    assert result == {}, (
        f"fake mode with empty _FAKE_CLICKS must return {{}}, got {result!r}"
    )


def test_m9b_fake_mode_returns_copy_of_fake_clicks():
    """CLICKS_MODE=fake, _FAKE_CLICKS = {"camp_x": 7} → fetch returns {"camp_x": 7}."""
    _require_clicks()
    clicks._FAKE_CLICKS["camp_x"] = 7
    result = clicks.fetch_clicks_by_campaign("2026-07")
    assert result == {"camp_x": 7}, (
        f"fake mode must return copy of _FAKE_CLICKS, got {result!r}"
    )


def test_m9b_fake_mode_returns_copy_not_same_object():
    """fetch_clicks_by_campaign returns a copy; mutating it must not affect _FAKE_CLICKS."""
    _require_clicks()
    clicks._FAKE_CLICKS["camp_copy"] = 3
    result = clicks.fetch_clicks_by_campaign("2026-07")
    result["camp_copy"] = 999
    assert clicks._FAKE_CLICKS.get("camp_copy") == 3, (
        "fetch_clicks_by_campaign must return a copy; "
        "mutating the returned dict must not affect _FAKE_CLICKS"
    )


def test_m9b_umami_mode_without_url_raises():
    """CLICKS_MODE=umami without UMAMI_URL env → RuntimeError naming 'UMAMI_URL'.

    Umami remote mode is NOT network-tested; only the env-var guard is tested
    (mirrors LEDGER_MODE=remote pattern in ledger_client.py).
    """
    _require_clicks()
    saved_mode = os.environ.get("CLICKS_MODE")
    saved_url = os.environ.pop("UMAMI_URL", None)
    os.environ["CLICKS_MODE"] = "umami"
    try:
        with pytest.raises(RuntimeError, match="UMAMI_URL"):
            clicks.fetch_clicks_by_campaign("2026-07")
    finally:
        if saved_mode is not None:
            os.environ["CLICKS_MODE"] = saved_mode
        else:
            os.environ.pop("CLICKS_MODE", None)
        if saved_url is not None:
            os.environ["UMAMI_URL"] = saved_url


# ===========================================================================
# 2. GET /reports/monthly gains "clicks" per campaign entry
# ===========================================================================


def test_m9b_report_campaign_entry_has_clicks_field(client: TestClient):
    """Each campaign entry in GET /reports/monthly must have a 'clicks' int field."""
    _require_clicks()
    token = _setup_tenant(client, "m9b-camp-shape@test.com", "pw123456", "M9BCampShape")
    draft_id = _create_approved_draft(client, token)
    r = _create_job(
        client,
        token,
        draft_id,
        channel="telegram",
        campaign_code="camp_shape_test",
        landing_url="https://brand.ir/lp",
    )
    assert r.status_code == 201, f"job creation failed: {r.text}"
    client.post("/publish/dispatch", headers=_internal_header())

    current_month = datetime.now(UTC).strftime("%Y-%m")
    rpt = client.get(
        "/reports/monthly", params={"month": current_month}, headers=_auth(token)
    )
    assert rpt.status_code == 200, f"report must be 200: {rpt.text}"
    body = rpt.json()

    campaigns = body.get("campaigns", [])
    assert len(campaigns) >= 1, f"must have at least one campaign entry: {body}"
    for camp in campaigns:
        assert "clicks" in camp, (
            f"each campaign entry must have a 'clicks' key: {camp}"
        )
        assert isinstance(camp["clicks"], int), (
            f"campaign 'clicks' must be int, got {type(camp['clicks'])!r}: {camp}"
        )


def test_m9b_report_campaign_clicks_absent_code_is_zero(client: TestClient):
    """Campaign entries whose code is absent from fetch_clicks_by_campaign get clicks==0."""
    _require_clicks()
    # _FAKE_CLICKS is empty (autouse fixture cleared it).
    token = _setup_tenant(client, "m9b-zero-clicks@test.com", "pw123456", "M9BZeroClicks")
    draft_id = _create_approved_draft(client, token)
    r = _create_job(
        client, token, draft_id, channel="telegram", campaign_code="camp_no_clicks"
    )
    assert r.status_code == 201, f"job creation failed: {r.text}"
    client.post("/publish/dispatch", headers=_internal_header())

    current_month = datetime.now(UTC).strftime("%Y-%m")
    rpt = client.get(
        "/reports/monthly", params={"month": current_month}, headers=_auth(token)
    )
    assert rpt.status_code == 200, f"report must be 200: {rpt.text}"
    body = rpt.json()

    camp = next(
        (c for c in body.get("campaigns", []) if c["campaign_code"] == "camp_no_clicks"),
        None,
    )
    assert camp is not None, (
        f"camp_no_clicks must appear in campaigns: {body.get('campaigns')}"
    )
    assert camp["clicks"] == 0, (
        f"clicks must be 0 when campaign_code absent from fetch_clicks_by_campaign, "
        f"got {camp['clicks']!r}: {camp}"
    )


# ===========================================================================
# 3. GET /reports/monthly gains top-level "clicks" object
# ===========================================================================


def test_m9b_report_has_top_level_clicks(client: TestClient):
    """GET /reports/monthly must have top-level 'clicks': {'total': int, 'by_campaign': dict}."""
    _require_clicks()
    token = _setup_tenant(client, "m9b-toplevel@test.com", "pw123456", "M9BTopLevel")
    draft_id = _create_approved_draft(client, token)
    r = _create_job(client, token, draft_id, campaign_code="camp_toplevel")
    assert r.status_code == 201, f"job creation failed: {r.text}"
    client.post("/publish/dispatch", headers=_internal_header())

    current_month = datetime.now(UTC).strftime("%Y-%m")
    rpt = client.get(
        "/reports/monthly", params={"month": current_month}, headers=_auth(token)
    )
    assert rpt.status_code == 200
    body = rpt.json()

    assert "clicks" in body, (
        f"top-level 'clicks' key must be present in report: {list(body.keys())}"
    )
    clicks_section = body["clicks"]
    assert "total" in clicks_section, (
        f"clicks.total must be present: {clicks_section}"
    )
    assert isinstance(clicks_section["total"], int), (
        f"clicks.total must be int: {clicks_section}"
    )
    assert "by_campaign" in clicks_section, (
        f"clicks.by_campaign must be present: {clicks_section}"
    )
    assert isinstance(clicks_section["by_campaign"], dict), (
        f"clicks.by_campaign must be dict: {clicks_section}"
    )


# ===========================================================================
# 4. End-to-end: «پست → کلیک → لندینگ» visible in report
# ===========================================================================


def test_m9b_e2e_clicks_in_report(client: TestClient):
    """Full M9B e2e: create → approve → job(camp_m9b + landing_url) → dispatch →
    set _FAKE_CLICKS={"camp_m9b": 7, "unrelated": 3} → report asserts:
      - campaigns[camp_m9b].clicks == 7
      - clicks.by_campaign == {"camp_m9b": 7}  (no "unrelated" leakage)
      - clicks.total == 7
    """
    _require_clicks()
    token = _setup_tenant(client, "m9b-e2e@test.com", "pw123456", "M9BE2E")
    draft_id = _create_approved_draft(client, token)

    r = _create_job(
        client,
        token,
        draft_id,
        channel="telegram",
        chat_id="10001",
        campaign_code="camp_m9b",
        landing_url="https://brand.ir/lp",
    )
    assert r.status_code == 201, f"job creation failed: {r.text}"

    dispatch = client.post("/publish/dispatch", headers=_internal_header())
    assert dispatch.status_code == 200, f"dispatch failed: {dispatch.text}"

    # Set fake click counts. "unrelated" must NOT appear in the report because
    # it is not among this tenant's campaigns this month.
    clicks._FAKE_CLICKS["camp_m9b"] = 7
    clicks._FAKE_CLICKS["unrelated"] = 3

    current_month = datetime.now(UTC).strftime("%Y-%m")
    rpt = client.get(
        "/reports/monthly", params={"month": current_month}, headers=_auth(token)
    )
    assert rpt.status_code == 200, f"report must be 200: {rpt.text}"
    body = rpt.json()

    # Campaign entry clicks
    campaigns = body.get("campaigns", [])
    camp_m9b = next((c for c in campaigns if c["campaign_code"] == "camp_m9b"), None)
    assert camp_m9b is not None, f"camp_m9b must appear in campaigns: {campaigns}"
    assert camp_m9b["clicks"] == 7, (
        f"camp_m9b.clicks must == 7, got {camp_m9b['clicks']}: {camp_m9b}"
    )

    # Top-level clicks section
    clicks_section = body.get("clicks", {})
    assert clicks_section.get("by_campaign") == {"camp_m9b": 7}, (
        "clicks.by_campaign must be {'camp_m9b': 7} — "
        f"'unrelated' must not leak into tenant's report. "
        f"got {clicks_section.get('by_campaign')!r}"
    )
    assert clicks_section.get("total") == 7, (
        f"clicks.total must == 7 (sum of tenant campaigns only), "
        f"got {clicks_section.get('total')!r}: {clicks_section}"
    )


# ===========================================================================
# 5. Cross-tenant isolation for clicks (constitution rule 6)
# ===========================================================================


def test_m9b_clicks_cross_tenant_isolation(client: TestClient):
    """Tenant B's clicks.by_campaign must not contain Tenant A's campaign code,
    even when _FAKE_CLICKS holds counts for Tenant A's campaign.

    Constitution rule 6: tenant isolation is absolute; every new table ships
    with a test proving cross-tenant isolation.
    """
    _require_clicks()
    MARKER = "CLICKS_ISOLATION_MARKER_M9B_UNIQUE_DO_NOT_LEAK"

    token_a = _setup_tenant(client, "m9b-iso-a@test.com", "pw123456", "M9BIsoA")
    token_b = _setup_tenant(client, "m9b-iso-b@test.com", "pw123456", "M9BIsoB")

    # Tenant A: job with an unmistakable campaign marker
    draft_a = _create_approved_draft(client, token_a)
    ra = _create_job(
        client, token_a, draft_a, channel="telegram", campaign_code=MARKER
    )
    assert ra.status_code == 201, f"Tenant A job creation failed: {ra.text}"
    client.post("/publish/dispatch", headers=_internal_header())

    # Tenant B: own job with a different campaign code
    draft_b = _create_approved_draft(client, token_b)
    rb = _create_job(
        client, token_b, draft_b, channel="bale", campaign_code="camp_b_clicks"
    )
    assert rb.status_code == 201, f"Tenant B job creation failed: {rb.text}"
    client.post("/publish/dispatch", headers=_internal_header())

    # _FAKE_CLICKS contains counts for BOTH campaigns; the report must filter by
    # tenant scope (only campaigns belonging to that tenant's jobs this month).
    clicks._FAKE_CLICKS[MARKER] = 5
    clicks._FAKE_CLICKS["camp_b_clicks"] = 2

    current_month = datetime.now(UTC).strftime("%Y-%m")

    # Tenant B's report must NOT expose Tenant A's campaign data
    resp_b = client.get(
        "/reports/monthly",
        params={"month": current_month},
        headers=_auth(token_b),
    )
    assert resp_b.status_code == 200, (
        f"Tenant B GET /reports/monthly must return 200: "
        f"got {resp_b.status_code}: {resp_b.text}"
    )
    body_b = resp_b.json()

    by_campaign_b = body_b.get("clicks", {}).get("by_campaign", {})
    assert MARKER not in by_campaign_b, (
        f"Tenant B's clicks.by_campaign must not contain Tenant A's marker.\n"
        f"marker={MARKER!r}\nby_campaign={by_campaign_b!r}"
    )
    # Belt-and-suspenders: full response body must not contain the marker
    assert MARKER not in resp_b.text, (
        f"Tenant B's full report response must not contain Tenant A's marker.\n"
        f"marker={MARKER!r}\nresponse={resp_b.text!r}"
    )

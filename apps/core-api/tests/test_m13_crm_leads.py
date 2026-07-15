"""
M13 acceptance tests — CRM lead bridge (UTM click deltas → lead events).

Contract:
  POST /crm/sync  (X-InternAL-Token trust boundary, same as /publish/dispatch)
    - 403 without/with wrong internal token
    - For every (tenant, campaign, current month): clicks beyond the stored
      watermark become ONE lead event {tenant_id, campaign_code, month,
      clicks_new, clicks_total}; the watermark row (crm_lead_syncs) advances.
    - Replay with unchanged counts emits NOTHING (rule 8 idempotency).
    - Click counts for campaign codes not owned by the tenant's jobs never
      emit (rule 6 containment); tenant B's campaigns never emit as tenant A.

  crm.bridge.deliver(event)
    - CRM_MODE=fake (default) appends to the _LEAD_OUTBOX seam
    - CRM_MODE=live: missing CRM_WEBHOOK_URL/CRM_WEBHOOK_TOKEN → clean
      LeadDeliveryError naming the env VAR (rule 4); success POSTs the event
      as JSON with Authorization: Bearer; errors never echo the URL.

All tests named test_m13_<criterion>.
"""

from __future__ import annotations

import os
import secrets as _secrets

import pytest
from fastapi.testclient import TestClient

from rpim_core_api.crm import bridge
from rpim_core_api.measurement import clicks

# Modes are read at call time (not import time), so setting them after the
# imports is safe — and keeps ruff E402 happy (test_m7_publish.py pattern).
os.environ.setdefault("EMBED_MODE", "fake")
os.environ.setdefault("COMPLETE_MODE", "fake")
os.environ.setdefault("CLICKS_MODE", "fake")
os.environ.setdefault("CRM_MODE", "fake")
_INTERNAL_TOKEN: str = os.environ.setdefault("INTERNAL_TOKEN", _secrets.token_hex(32))

_BRIEF = {
    "goal": "افزایش آگاهی از برند",
    "audience": "مدیران میان‌رده",
    "channel": "تلگرام",
    "format": "پست متنی",
    "hook": None,
    "cta": None,
}


@pytest.fixture(autouse=True)
def _clean_seams():
    clicks._FAKE_CLICKS.clear()
    bridge._LEAD_OUTBOX.clear()
    yield
    clicks._FAKE_CLICKS.clear()
    bridge._LEAD_OUTBOX.clear()


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


def _tenant_with_campaign(client: TestClient, email: str, name: str, campaign: str) -> str:
    token = _register(client, email, "Password123!", name)["access_token"]
    resp = client.post("/content/drafts", json={"brief": _BRIEF}, headers=_auth(token))
    assert resp.status_code == 201, resp.text
    draft_id = resp.json()["draft_id"]
    assert (
        client.post(f"/content/drafts/{draft_id}/approve", headers=_auth(token)).status_code
        == 200
    )
    resp = client.post(
        "/publish/jobs",
        json={
            "draft_id": draft_id,
            "channel": "telegram",
            "chat_id": "123",
            "campaign_code": campaign,
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    return token


# ===========================================================================
# 1. Trust boundary
# ===========================================================================


def test_m13_sync_requires_internal_token(client: TestClient):
    resp = client.post("/crm/sync")
    assert resp.status_code == 403, f"expected 403, got {resp.status_code}: {resp.text}"
    resp = client.post("/crm/sync", headers={"X-Internal-Token": "wrong"})
    assert resp.status_code == 403, f"expected 403, got {resp.status_code}: {resp.text}"


# ===========================================================================
# 2. Delta → lead event, watermark advances, replay is silent (rule 8)
# ===========================================================================


def test_m13_first_sync_emits_full_count_as_new_leads(client: TestClient):
    _tenant_with_campaign(client, "crm-first@example.com", "CrmFirst", "camp_crm_a")
    clicks._FAKE_CLICKS["camp_crm_a"] = 5

    resp = client.post("/crm/sync", headers=_internal_header())
    assert resp.status_code == 200, resp.text
    events = [e for e in bridge._LEAD_OUTBOX if e["campaign_code"] == "camp_crm_a"]
    assert len(events) == 1, f"exactly one lead event expected: {bridge._LEAD_OUTBOX}"
    assert events[0]["clicks_new"] == 5 and events[0]["clicks_total"] == 5, events[0]


def test_m13_replay_without_new_clicks_emits_nothing(client: TestClient):
    _tenant_with_campaign(client, "crm-replay@example.com", "CrmReplay", "camp_crm_b")
    clicks._FAKE_CLICKS["camp_crm_b"] = 4

    assert client.post("/crm/sync", headers=_internal_header()).status_code == 200
    bridge._LEAD_OUTBOX.clear()
    assert client.post("/crm/sync", headers=_internal_header()).status_code == 200
    assert bridge._LEAD_OUTBOX == [], (
        f"replay with unchanged counts must be silent (rule 8): {bridge._LEAD_OUTBOX}"
    )


def test_m13_delta_only_the_new_clicks(client: TestClient):
    _tenant_with_campaign(client, "crm-delta@example.com", "CrmDelta", "camp_crm_c")
    clicks._FAKE_CLICKS["camp_crm_c"] = 4
    assert client.post("/crm/sync", headers=_internal_header()).status_code == 200
    bridge._LEAD_OUTBOX.clear()

    clicks._FAKE_CLICKS["camp_crm_c"] = 9
    assert client.post("/crm/sync", headers=_internal_header()).status_code == 200
    events = [e for e in bridge._LEAD_OUTBOX if e["campaign_code"] == "camp_crm_c"]
    assert len(events) == 1 and events[0]["clicks_new"] == 5, (
        f"only the delta beyond the watermark is new: {bridge._LEAD_OUTBOX}"
    )
    assert events[0]["clicks_total"] == 9, events[0]


# ===========================================================================
# 3. Containment + tenant isolation (rule 6)
# ===========================================================================


def test_m13_foreign_campaign_clicks_never_become_leads(client: TestClient):
    _tenant_with_campaign(client, "crm-own@example.com", "CrmOwn", "camp_crm_mine")
    clicks._FAKE_CLICKS["camp_crm_mine"] = 2
    clicks._FAKE_CLICKS["camp_nobody_owns"] = 999

    assert client.post("/crm/sync", headers=_internal_header()).status_code == 200
    codes = {e["campaign_code"] for e in bridge._LEAD_OUTBOX}
    assert "camp_nobody_owns" not in codes, (
        f"unowned campaign clicks must never emit lead events: {bridge._LEAD_OUTBOX}"
    )


def test_m13_events_carry_the_owning_tenant_only(client: TestClient):
    _tenant_with_campaign(client, "crm-ta@example.com", "CrmTa", "camp_of_a")
    _tenant_with_campaign(client, "crm-tb@example.com", "CrmTb", "camp_of_b")
    clicks._FAKE_CLICKS["camp_of_a"] = 3
    clicks._FAKE_CLICKS["camp_of_b"] = 7

    assert client.post("/crm/sync", headers=_internal_header()).status_code == 200
    by_code = {e["campaign_code"]: e for e in bridge._LEAD_OUTBOX}
    assert by_code["camp_of_a"]["tenant_id"] != by_code["camp_of_b"]["tenant_id"], (
        f"each event must carry its OWN tenant (rule 6): {bridge._LEAD_OUTBOX}"
    )
    assert by_code["camp_of_a"]["clicks_new"] == 3
    assert by_code["camp_of_b"]["clicks_new"] == 7


# ===========================================================================
# 4. bridge.deliver — fake seam + live webhook (rule 4)
# ===========================================================================


def test_m13_bridge_live_missing_env_names_the_var(monkeypatch):
    monkeypatch.setenv("CRM_MODE", "live")
    monkeypatch.delenv("CRM_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("CRM_WEBHOOK_TOKEN", raising=False)
    with pytest.raises(bridge.LeadDeliveryError) as excinfo:
        bridge.deliver({"tenant_id": "t", "campaign_code": "c", "clicks_new": 1})
    assert "CRM_WEBHOOK_URL" in str(excinfo.value), (
        f"error must NAME the missing env var (rule 4): {excinfo.value}"
    )


def test_m13_bridge_live_posts_bearer_json(monkeypatch):
    import httpx  # noqa: PLC0415

    captured: dict = {}

    class _Resp:
        def raise_for_status(self):
            return None

    def fake_post(url, json=None, headers=None, timeout=None):  # noqa: A002
        captured.update(url=url, json=json, headers=headers)
        return _Resp()

    monkeypatch.setenv("CRM_MODE", "live")
    monkeypatch.setenv("CRM_WEBHOOK_URL", "https://crm.example.com/hooks/rpim-leads")
    monkeypatch.setenv("CRM_WEBHOOK_TOKEN", "secret-token")
    monkeypatch.setattr(httpx, "post", fake_post)

    event = {"tenant_id": "t1", "campaign_code": "camp_x", "clicks_new": 2}
    bridge.deliver(event)
    assert captured["url"] == "https://crm.example.com/hooks/rpim-leads", captured
    assert captured["json"] == event, captured
    assert captured["headers"]["Authorization"] == "Bearer secret-token", captured

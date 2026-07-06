"""
M10 / DoD acceptance tests — Silence-mode simulated national-event.

Acceptance criteria (DoD §13.1: «silence-mode simulated event passes acceptance»):
  1. A national-event feed signal causes the global silence flag to AUTO-SET
     (all tenants' publishing halts without manual per-tenant intervention).
  2. After the auto-set, ALL tenants' dispatch is blocked.
  3. Resume is MANUAL-ONLY: an automatic/feed-driven resume attempt must be
     REJECTED (the silence flag must remain active after a feed-driven
     deactivation attempt).

What exists (verified):
  - POST /governance/silence: sets SILENCE per-tenant (scope = tenant_id).
  - POST /governance/kill: sets KILL globally (scope = "global").
  - is_publishing_halted() checks both global and per-tenant scope.
  - There is NO global silence (only global kill).
  - There is NO national-event feed endpoint.

Missing pieces encoded here:
  a) POST /governance/national-event (internal-token auth) accepts an event
     payload and auto-sets a GLOBAL silence flag (scope="global", kind="silence")
     so that all tenants' queues halt without requiring per-tenant calls.
  b) The national-event endpoint must REJECT a "deactivation" event payload
     (auto-resume must not be allowed — constitution rule 7 / CLAUDE.md §7).
  c) POST /governance/silence with active=false is the ONLY valid resume path;
     attempting to resume via the national-event feed must fail.

FAILS TODAY: the national-event endpoint does not exist (404/405).

All tests named test_m10_<criterion>.
"""

from __future__ import annotations

import os
import secrets

os.environ["PUBLISH_MODE"] = "fake"
os.environ.setdefault("EMBED_MODE", "fake")
os.environ.setdefault("COMPLETE_MODE", "fake")

_INTERNAL_TOKEN: str = os.environ.setdefault("INTERNAL_TOKEN", secrets.token_hex(32))

from fastapi.testclient import TestClient  # noqa: E402

import rpim_core_api.publisher.channels as _channels  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_NATIONAL_EVENT_URL = "/governance/national-event"
_SILENCE_URL = "/governance/silence"
_KILL_URL = "/governance/kill"
_DISPATCH_URL = "/publish/dispatch"

_BRIEF = {
    "goal": "افزایش فروش",
    "audience": "عموم مردم",
    "channel": "telegram",
    "format": "پست متنی",
    "hook": None,
    "cta": None,
}


# ---------------------------------------------------------------------------
# Helpers
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


def _internal_header() -> dict:
    return {"X-Internal-Token": os.environ.get("INTERNAL_TOKEN", "")}


def _setup_tenant(client: TestClient, email: str, password: str, name: str) -> str:
    return _register(client, email, password, name)["access_token"]


def _create_approved_draft(client: TestClient, token: str) -> str:
    resp = client.post("/content/drafts", json={"brief": _BRIEF}, headers=_auth(token))
    assert resp.status_code == 201, f"draft failed: {resp.text}"
    draft_id = resp.json()["draft_id"]
    app = client.post(f"/content/drafts/{draft_id}/approve", headers=_auth(token))
    assert app.status_code == 200, f"approve failed: {app.text}"
    return draft_id


def _create_job(client: TestClient, token: str, draft_id: str, idx: int = 0) -> str:
    resp = client.post(
        "/publish/jobs",
        json={
            "draft_id": draft_id,
            "channel": "telegram",
            "chat_id": f"8888{idx}",
            "campaign_code": f"m10_silence_{idx}",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201, f"job failed: {resp.text}"
    return resp.json()["job_id"]


def _clear_outbox() -> None:
    _channels._OUTBOX.clear()
    _channels._FAIL_NEXT.clear()


def _reset_global_silence(client: TestClient) -> None:
    """Best-effort cleanup: deactivate kill and try to clear national-event silence."""
    # Release global kill if active (cleanup from other tests)
    client.post(
        _KILL_URL,
        json={"active": False, "reason": "cleanup"},
        headers=_internal_header(),
    )
    # Attempt to deactivate global silence via national-event endpoint (if it exists)
    client.post(
        _NATIONAL_EVENT_URL,
        json={"event_type": "mourning_end", "active": False, "reason": "cleanup"},
        headers=_internal_header(),
    )


# ===========================================================================
# 1. National-event endpoint exists and requires internal token.
#    FAILS today: endpoint not found (404/405), so any status-code check fails.
# ===========================================================================


def test_m10_national_event_endpoint_exists_with_auth_guard(client: TestClient) -> None:
    """POST /governance/national-event without internal token → 401 or 403.

    The endpoint must exist and require the internal token, not tenant auth.
    FAILS today because the endpoint does not exist — we get 404/405, not 401/403.
    """
    resp = client.post(
        _NATIONAL_EVENT_URL,
        json={"event_type": "national_mourning", "active": True, "reason": "test"},
    )
    # Endpoint must exist (not 404/405) and must reject unauthenticated calls
    assert resp.status_code not in (404, 405), (
        f"POST /governance/national-event must exist (not 404/405); "
        f"got {resp.status_code} — implement the endpoint for M10."
    )
    assert resp.status_code in (401, 403), (
        f"POST /governance/national-event without token must return 401 or 403, "
        f"got {resp.status_code}: {resp.text}"
    )


# ===========================================================================
# 2. National-event signal → global silence auto-sets → ALL tenants blocked.
#    FAILS today: endpoint does not exist.
# ===========================================================================


def test_m10_national_event_auto_sets_global_silence_all_tenants_blocked(
    client: TestClient,
) -> None:
    """POST /governance/national-event → global silence active → all dispatches blocked.

    Seeds 2 tenants × 1 queued job each.  Sends a national-event signal via the
    feed endpoint (internal token).  Runs dispatch for all tenants.
    Asserts: sent=0, blocked=2.  Neither tenant's individual silence flag needs
    to have been set — the global silence suffices.

    FAILS today: the national-event endpoint does not exist.
    """
    _clear_outbox()

    token_a = _setup_tenant(client, "m10-ne-a@test.com", "pw123456", "M10NEA")
    token_b = _setup_tenant(client, "m10-ne-b@test.com", "pw123456", "M10NEB")

    draft_a = _create_approved_draft(client, token_a)
    draft_b = _create_approved_draft(client, token_b)
    _create_job(client, token_a, draft_a, idx=1)
    _create_job(client, token_b, draft_b, idx=2)

    # Simulate national-event feed signal → should auto-set global silence
    ne_resp = client.post(
        _NATIONAL_EVENT_URL,
        json={
            "event_type": "national_mourning",
            "active": True,
            "reason": "درگذشت مسئول ارشد",
        },
        headers=_internal_header(),
    )
    assert ne_resp.status_code == 200, (
        f"POST /governance/national-event must return 200 with valid internal token; "
        f"got {ne_resp.status_code}: {ne_resp.text}"
    )

    # Verify that dispatch is now blocked for ALL tenants
    dispatch_resp = client.post(_DISPATCH_URL, headers=_internal_header())
    assert dispatch_resp.status_code == 200
    body = dispatch_resp.json()
    assert body["sent"] == 0, (
        f"After national-event signal, all dispatches must be blocked; "
        f"got sent={body['sent']}: {body}"
    )
    assert body["blocked"] >= 2, (
        f"Both tenant jobs must be blocked after national-event; "
        f"got blocked={body['blocked']}: {body}"
    )
    assert _channels._OUTBOX == [], (
        f"_OUTBOX must be empty after national-event signal; got: {_channels._OUTBOX}"
    )

    _reset_global_silence(client)


# ===========================================================================
# 3. National-event deactivation attempt must be REJECTED (manual-only resume).
#    FAILS today: endpoint does not exist.
# ===========================================================================


def test_m10_national_event_auto_resume_is_rejected(client: TestClient) -> None:
    """Sending active=false via the national-event feed must NOT lift the silence.

    Constitution rule 7 / CLAUDE.md §7: silence mode → auto-halt,
    MANUAL-ONLY resume.  A feed-driven deactivation (active=false via the
    national-event endpoint) must be REJECTED so that a compromised or
    erroneous feed cannot accidentally re-enable publishing.

    The silence must remain active; only POST /governance/silence active=false
    via tenant auth is a valid resume path.

    FAILS today: endpoint does not exist.
    """
    _clear_outbox()

    token = _setup_tenant(client, "m10-ne-resume@test.com", "pw123456", "M10NEResume")
    draft_id = _create_approved_draft(client, token)
    _create_job(client, token, draft_id, idx=9)

    # Activate global silence via national-event
    activate_resp = client.post(
        _NATIONAL_EVENT_URL,
        json={"event_type": "national_mourning", "active": True, "reason": "عزای ملی"},
        headers=_internal_header(),
    )
    assert activate_resp.status_code == 200, (
        f"national-event activation must return 200; "
        f"got {activate_resp.status_code}: {activate_resp.text}"
    )

    # Attempt auto-resume via same feed endpoint (active=false) — must be REJECTED
    auto_resume_resp = client.post(
        _NATIONAL_EVENT_URL,
        json={"event_type": "mourning_end", "active": False, "reason": "پایان عزا"},
        headers=_internal_header(),
    )
    assert auto_resume_resp.status_code in (400, 403, 409, 422), (
        f"Feed-driven deactivation (active=false via national-event) must be rejected "
        f"with 400/403/409/422 (manual-only resume rule); "
        f"got {auto_resume_resp.status_code}: {auto_resume_resp.text}"
    )

    # Confirm silence is STILL active after the rejected auto-resume
    dispatch_resp = client.post(_DISPATCH_URL, headers=_internal_header())
    body = dispatch_resp.json()
    assert body["sent"] == 0, (
        f"Silence must remain active after rejected auto-resume; "
        f"dispatch must still return sent=0, got: {body}"
    )

    _reset_global_silence(client)


# ===========================================================================
# 4. Only manual resume (POST /governance/silence active=false per tenant) works.
#    This verifies the existing per-tenant manual-resume path still functions,
#    plus that global silence from national-event is also clearable manually.
#    FAILS today: national-event endpoint doesn't exist so activation step fails.
# ===========================================================================


def test_m10_manual_resume_after_national_event_restores_dispatch(
    client: TestClient,
) -> None:
    """After national-event silence, manual per-tenant resume via /governance/silence
    clears the block for that tenant.  Global silence must also be explicitly cleared
    via an operator action; automatic clearing by the feed is not permitted.

    FAILS today: national-event endpoint does not exist.
    """
    _clear_outbox()

    token = _setup_tenant(client, "m10-ne-manual@test.com", "pw123456", "M10NEManual")
    draft_id = _create_approved_draft(client, token)
    _create_job(client, token, draft_id, idx=5)

    # Activate global silence via national-event feed
    act_resp = client.post(
        _NATIONAL_EVENT_URL,
        json={"event_type": "national_mourning", "active": True, "reason": "تست"},
        headers=_internal_header(),
    )
    assert act_resp.status_code == 200, (
        f"national-event activation must succeed; got {act_resp.status_code}"
    )

    # Verify blocked
    d1 = client.post(_DISPATCH_URL, headers=_internal_header()).json()
    assert d1["sent"] == 0, f"must be blocked after national event; {d1}"

    # Manual resume: operator explicitly clears global silence
    # (the exact mechanism — e.g. POST /governance/global/silence active=false —
    # is what the implementer must build; we call it here so the test documents
    # the required behavior even before the endpoint name is finalised)
    manual_resp = client.post(
        "/governance/global/silence",
        json={"active": False, "reason": "عزا به پایان رسید — دستی"},
        headers=_internal_header(),
    )
    assert manual_resp.status_code == 200, (
        f"POST /governance/global/silence active=false must succeed (manual resume); "
        f"got {manual_resp.status_code}: {manual_resp.text}"
    )

    # After manual resume, dispatch should send
    d2 = client.post(_DISPATCH_URL, headers=_internal_header()).json()
    assert d2["sent"] >= 1, (
        f"After manual resume, dispatch must send the queued job; got: {d2}"
    )
    assert _channels._OUTBOX, (
        f"_OUTBOX must have an entry after manual resume; got: {_channels._OUTBOX}"
    )

    _clear_outbox()


# ===========================================================================
# 5. National-event does NOT set per-tenant silence — it uses global scope.
#    Verifies that GET /governance/status for a new tenant (with no per-tenant
#    silence) STILL shows silence=True after national-event, proving global scope.
#    FAILS today: national-event endpoint does not exist.
# ===========================================================================


def test_m10_national_event_uses_global_scope_visible_to_all_tenants(
    client: TestClient,
) -> None:
    """After a national-event signal, ANY tenant's governance/status shows silence=True.

    Proves the event sets a GLOBAL scope flag, not a per-tenant one.
    A brand-new tenant (registered after the event) must also see silence=True.

    FAILS today: national-event endpoint does not exist.
    """
    # Activate global silence via national-event
    ne_resp = client.post(
        _NATIONAL_EVENT_URL,
        json={"event_type": "national_mourning", "active": True, "reason": "ملی"},
        headers=_internal_header(),
    )
    assert ne_resp.status_code == 200, (
        f"national-event endpoint must return 200; got {ne_resp.status_code}: {ne_resp.text}"
    )

    # Register a brand-new tenant AFTER the national event
    new_token = _setup_tenant(
        client, "m10-new-after-event@test.com", "pw123456", "M10NewAfterEvent"
    )
    status_resp = client.get("/governance/status", headers=_auth(new_token))
    assert status_resp.status_code == 200, (
        f"GET /governance/status must return 200; got {status_resp.status_code}"
    )
    status = status_resp.json()
    assert status.get("silence") is True, (
        f"A tenant registered after national-event must see silence=True "
        f"(global scope); got: {status}"
    )

    _reset_global_silence(client)

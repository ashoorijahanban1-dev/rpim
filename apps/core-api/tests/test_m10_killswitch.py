"""
M10 acceptance tests — Kill switch operational safety.

Acceptance criteria (DoD §6.4 M10):
  - Activating the global kill switch stops ALL publish queues in <5 seconds.
  - Zero sends occur after activation including already-queued jobs.
  - Elapsed time from flag-set to dispatch-refusal is under 5 seconds.

What exists (verified):
  - POST /governance/kill uses GLOBAL_SCOPE and halts all tenants via the
    is_publishing_halted() per-job check in engine.py.  The <5 s guarantee is
    trivially satisfied because the check is a synchronous DB read.

Missing piece encoded here:
  - There is no operator-accessible route that reads the CURRENT global
    governance state (kill + silence active status) without a tenant JWT.
    GET /governance/status requires tenant auth; an operator without a
    tenant token cannot verify the kill switch is active after setting it.
    M10 requires a GET /governance/global/status endpoint authenticated by
    X-Internal-Token (same trust boundary as POST /governance/kill).
  - POST /governance/kill returns only {"kill": bool}; there is no
    confirmation of scope="global" or how many tenant queues were halted.

All tests named test_m10_<criterion>.
"""

from __future__ import annotations

import os
import secrets
import time

os.environ["PUBLISH_MODE"] = "fake"
os.environ.setdefault("EMBED_MODE", "fake")
os.environ.setdefault("COMPLETE_MODE", "fake")

_INTERNAL_TOKEN: str = os.environ.setdefault("INTERNAL_TOKEN", secrets.token_hex(32))

from fastapi.testclient import TestClient  # noqa: E402

import rpim_core_api.publisher.channels as _channels  # noqa: E402

# ---------------------------------------------------------------------------
# Constants / helpers
# ---------------------------------------------------------------------------

_BRIEF = {
    "goal": "افزایش آگاهی از برند",
    "audience": "مدیران میان‌رده",
    "channel": "telegram",
    "format": "پست متنی",
    "hook": None,
    "cta": None,
}

_KILL_SWITCH_LATENCY_BUDGET_SECONDS: float = 5.0


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
    assert resp.status_code == 201, f"draft create failed: {resp.text}"
    draft_id = resp.json()["draft_id"]
    app_resp = client.post(f"/content/drafts/{draft_id}/approve", headers=_auth(token))
    assert app_resp.status_code == 200, f"approve failed: {app_resp.text}"
    return draft_id


def _create_job(client: TestClient, token: str, draft_id: str, idx: int = 0) -> str:
    resp = client.post(
        "/publish/jobs",
        json={
            "draft_id": draft_id,
            "channel": "telegram",
            "chat_id": f"9999{idx}",
            "campaign_code": f"m10_kill_test_{idx}",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201, f"job create failed: {resp.text}"
    return resp.json()["job_id"]


def _clear_outbox() -> None:
    _channels._OUTBOX.clear()
    _channels._FAIL_NEXT.clear()


def _activate_kill(client: TestClient) -> None:
    resp = client.post(
        "/governance/kill",
        json={"active": True, "reason": "M10 kill switch test"},
        headers=_internal_header(),
    )
    assert resp.status_code == 200, f"kill activate failed: {resp.text}"


def _deactivate_kill(client: TestClient) -> None:
    client.post(
        "/governance/kill",
        json={"active": False, "reason": "M10 kill switch test cleanup"},
        headers=_internal_header(),
    )


# ===========================================================================
# 1. Multi-tenant: ALL queued jobs blocked after global kill (timing ≤5 s)
#    Seeds 3 tenants × 2 jobs each; activates kill; runs dispatch.
#    Asserts: sent=0, blocked=6, elapsed < KILL_SWITCH_LATENCY_BUDGET_SECONDS.
# ===========================================================================


def test_m10_kill_switch_halts_all_tenants_within_5_seconds(client: TestClient) -> None:
    """Global kill switch → zero sends for all tenants; flag-to-refusal < 5 s.

    Encodes M10 DoD: 'kill switch <5 s' (blueprint §13.1).  The timing
    assertion is measured with time.monotonic from immediately before the
    kill is activated to when dispatch returns — covering the full halt path.
    Seeds 3 tenants × 2 queued jobs to exercise the cross-tenant guarantee.
    """
    _clear_outbox()

    tokens = [
        _setup_tenant(client, f"m10-ks-{i}@test.com", "pw123456", f"M10KSTenant{i}")
        for i in range(3)
    ]

    job_ids: list[str] = []
    for i, tok in enumerate(tokens):
        for j in range(2):
            draft_id = _create_approved_draft(client, tok)
            job_ids.append(_create_job(client, tok, draft_id, idx=i * 10 + j))

    assert len(job_ids) == 6, f"expected 6 seeded jobs, got {len(job_ids)}"

    # Start timing from the moment the kill switch is activated.
    t_kill = time.monotonic()
    _activate_kill(client)

    dispatch_resp = client.post("/publish/dispatch", headers=_internal_header())
    t_dispatch_done = time.monotonic()

    assert dispatch_resp.status_code == 200, (
        f"dispatch must return 200, got {dispatch_resp.status_code}: {dispatch_resp.text}"
    )
    body = dispatch_resp.json()

    assert body["sent"] == 0, (
        f"kill switch must prevent ALL sends across all tenants, got sent={body['sent']}: {body}"
    )
    assert body["blocked"] == 6, (
        f"all 6 queued jobs must be blocked, got blocked={body['blocked']}: {body}"
    )
    assert _channels._OUTBOX == [], (
        f"_OUTBOX must be empty under global kill switch, got: {_channels._OUTBOX}"
    )

    elapsed = t_dispatch_done - t_kill
    assert elapsed < _KILL_SWITCH_LATENCY_BUDGET_SECONDS, (
        f"kill-switch-to-dispatch-refusal elapsed {elapsed:.3f}s exceeds "
        f"{_KILL_SWITCH_LATENCY_BUDGET_SECONDS}s budget (rule 7 / DoD §13.1)"
    )

    _deactivate_kill(client)


# ===========================================================================
# 2. Kill endpoint must confirm global scope in its response.
#    Current implementation returns only {"kill": bool}.
#    M10 requires the response to include "scope": "global" so that operators
#    can confirm the kill was applied system-wide, not just per-tenant.
#    FAILS TODAY: response does not contain a "scope" key.
# ===========================================================================


def test_m10_kill_endpoint_response_confirms_global_scope(client: TestClient) -> None:
    """POST /governance/kill response must include scope='global'.

    An operator activating the kill switch must be able to confirm from the
    API response that the flag was set at global (all-tenant) scope, not
    accidentally at a single-tenant level.  The current implementation
    returns only {"kill": bool}; the scope field is absent.

    This test FAILS until the /governance/kill endpoint is updated to
    return {"kill": bool, "scope": "global"} (or equivalent).
    """
    resp = client.post(
        "/governance/kill",
        json={"active": True, "reason": "scope confirmation test"},
        headers=_internal_header(),
    )
    assert resp.status_code == 200, f"kill endpoint must return 200, got {resp.text}"
    body = resp.json()
    assert "scope" in body, (
        f"POST /governance/kill response must contain 'scope' key confirming "
        f"global application; got: {body}"
    )
    assert body["scope"] == "global", (
        f"scope must be 'global', got: {body['scope']!r}"
    )

    _deactivate_kill(client)


# ===========================================================================
# 3. Operator global status endpoint — readable without a tenant JWT.
#    Missing: GET /governance/global/status authenticated by X-Internal-Token.
#    Without this, operators cannot verify the kill state after activation
#    without impersonating a tenant.
#    FAILS TODAY: endpoint does not exist (404 or 405).
# ===========================================================================


def test_m10_global_governance_status_accessible_without_tenant_auth(
    client: TestClient,
) -> None:
    """GET /governance/global/status with X-Internal-Token returns global kill+silence state.

    After activating the kill switch an operator needs to verify it is active
    system-wide without needing a tenant JWT.  The existing GET
    /governance/status requires tenant auth and returns PER-TENANT flags.
    M10 requires a new ops-level endpoint authenticated by X-Internal-Token
    that returns the global flag state.

    This test FAILS today because no such endpoint exists — the request
    returns 404 or 405.
    """
    _activate_kill(client)
    try:
        resp = client.get("/governance/global/status", headers=_internal_header())
        assert resp.status_code == 200, (
            f"GET /governance/global/status must return 200 for valid internal token, "
            f"got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        assert "kill" in body, f"response must contain 'kill' key: {body}"
        assert body["kill"] is True, (
            f"kill must be True after activation via POST /governance/kill: {body}"
        )
        assert "silence" in body, f"response must contain 'silence' key: {body}"
    finally:
        _deactivate_kill(client)


# ===========================================================================
# 4. Global ops status endpoint must require internal token — no anonymous access.
#    Complementary auth guard for the new /governance/global/status route.
#    FAILS TODAY: endpoint does not exist (404/405 rather than 401/403).
# ===========================================================================


def test_m10_global_governance_status_requires_internal_token(client: TestClient) -> None:
    """GET /governance/global/status without token → 401 or 403.

    The global status endpoint must not be publicly accessible — it exposes
    whether the kill switch is active, which is sensitive ops information.
    FAILS today because the route doesn't exist.
    """
    resp = client.get("/governance/global/status")
    assert resp.status_code in (401, 403), (
        f"GET /governance/global/status without internal token must return 401 or 403, "
        f"got {resp.status_code}: {resp.text}"
    )

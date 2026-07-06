"""
M7 acceptance tests — Publisher core (channel-agnostic dispatch engine).

Routes under test:
  POST /publish/jobs
  GET  /publish/jobs
  POST /publish/dispatch

env PUBLISH_MODE=fake, EMBED_MODE=fake, COMPLETE_MODE=fake are set at module
level so the channel adapter uses the in-process fake seam rather than live
messenger APIs.  INTERNAL_TOKEN is generated per run (constitution rule 4:
no literal secrets in repo).

Module-level import of rpim_core_api.publisher.channels is intentional:
  - it causes a ModuleNotFoundError (collection error) until the publisher
    module exists — the expected failure mode during development.
  - once the module exists, _OUTBOX and _FAIL_NEXT are directly accessible
    as module-level lists for test-state control between cases.

All tests named test_m7_<criterion>.
"""

from __future__ import annotations

import os
import secrets

# Must be set BEFORE any import of rpim_core_api.* — same pattern as M5/M6.
# PUBLISH_MODE=fake routes all channel sends through the in-process fake seam.
os.environ["PUBLISH_MODE"] = "fake"
os.environ.setdefault("EMBED_MODE", "fake")
os.environ.setdefault("COMPLETE_MODE", "fake")

# setdefault: test_m5_qa.py may have set this already during collection;
# whichever module imports first wins so both hold the same token.
_INTERNAL_TOKEN: str = os.environ.setdefault("INTERNAL_TOKEN", secrets.token_hex(32))

from fastapi.testclient import TestClient  # noqa: E402

# ---------------------------------------------------------------------------
# This import will raise ModuleNotFoundError until rpim_core_api.publisher is
# implemented — the expected collection error for M7 pre-implementation.
# ---------------------------------------------------------------------------
import rpim_core_api.publisher.channels as _channels  # noqa: E402  # type: ignore[import]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BRIEF = {
    "goal": "افزایش آگاهی از برند",
    "audience": "مدیران میان‌رده",
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
    scheduled_at: str | None = None,
):
    payload: dict = {
        "draft_id": draft_id,
        "channel": channel,
        "chat_id": chat_id,
        "campaign_code": campaign_code,
    }
    if scheduled_at is not None:
        payload["scheduled_at"] = scheduled_at
    return client.post("/publish/jobs", json=payload, headers=_auth(token))


def _clear_outbox() -> None:
    """Clear fake channel seam state between test cases."""
    _channels._OUTBOX.clear()
    _channels._FAIL_NEXT.clear()


def _internal_header() -> dict:
    return {"X-Internal-Token": _INTERNAL_TOKEN}


# ===========================================================================
# 1. POST /publish/jobs — auth guard
# ===========================================================================


def test_m7_create_job_requires_auth(client: TestClient):
    """POST /publish/jobs without Bearer token → 401."""
    resp = client.post(
        "/publish/jobs",
        json={
            "draft_id": "some-id",
            "channel": "telegram",
            "chat_id": "12345",
            "campaign_code": "camp_x",
        },
    )
    assert resp.status_code == 401, (
        f"expected 401 for unauthenticated POST /publish/jobs, got {resp.status_code}"
    )


# ===========================================================================
# 2. POST /publish/jobs — 201 for approved draft with utm metadata
# ===========================================================================


def test_m7_create_job_201_approved_draft(client: TestClient):
    """POST /publish/jobs with an approved draft → 201 with job_id, status='queued', utm."""
    _clear_outbox()
    token = _setup_tenant(client, "m7-job-appr@test.com", "pw123456", "M7JobAppr")
    draft_id = _create_approved_draft(client, token)

    resp = _create_job(client, token, draft_id, channel="telegram", campaign_code="summer2026")
    assert resp.status_code == 201, (
        f"expected 201 for approved draft publish job, got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    assert "job_id" in body, f"'job_id' missing from response: {body}"
    assert body["status"] == "queued", f"status must be 'queued', got: {body}"
    assert "utm" in body, f"'utm' missing from response: {body}"


def test_m7_create_job_utm_metadata(client: TestClient):
    """utm object must contain non-empty utm_source==channel, utm_medium,
    utm_campaign==campaign_code.

    Constitution rule 3: no publish job without full metadata + campaign code.
    """
    _clear_outbox()
    token = _setup_tenant(client, "m7-utm@test.com", "pw123456", "M7UTM")
    draft_id = _create_approved_draft(client, token)

    resp = _create_job(client, token, draft_id, channel="bale", campaign_code="ramadan_1405")
    assert resp.status_code == 201, (
        f"expected 201, got {resp.status_code}: {resp.text}"
    )
    utm = resp.json()["utm"]
    assert utm.get("utm_source") == "bale", (
        f"utm_source must equal channel ('bale'), got: {utm}"
    )
    assert utm.get("utm_medium"), f"utm_medium must be non-empty: {utm}"
    assert utm.get("utm_campaign") == "ramadan_1405", (
        f"utm_campaign must equal campaign_code ('ramadan_1405'), got: {utm}"
    )


# ===========================================================================
# 3. POST /publish/jobs — 201 for edited draft
# ===========================================================================


def test_m7_create_job_201_edited_draft(client: TestClient):
    """POST /publish/jobs with an edited draft → 201 (edited status is also publishable)."""
    _clear_outbox()
    token = _setup_tenant(client, "m7-job-edit@test.com", "pw123456", "M7JobEdit")
    draft_id = _create_draft(client, token)

    # PUT /content/drafts/<id> sets status to 'edited'
    edit_resp = client.put(
        f"/content/drafts/{draft_id}",
        json={"edited_text": "متن ویرایش‌شده برای انتشار"},
        headers=_auth(token),
    )
    assert edit_resp.status_code == 200, f"edit draft failed: {edit_resp.text}"

    resp = _create_job(client, token, draft_id)
    assert resp.status_code == 201, (
        f"expected 201 for edited draft, got {resp.status_code}: {resp.text}"
    )
    assert resp.json()["status"] == "queued"


# ===========================================================================
# 4. POST /publish/jobs — 409 when draft is not approved/edited
# ===========================================================================


def test_m7_create_job_409_draft_not_approved(client: TestClient):
    """POST /publish/jobs when draft status is 'draft' (not approved/edited) → 409."""
    _clear_outbox()
    token = _setup_tenant(client, "m7-job-409@test.com", "pw123456", "M7Job409")
    draft_id = _create_draft(client, token)  # status remains 'draft'

    resp = _create_job(client, token, draft_id)
    assert resp.status_code == 409, (
        f"expected 409 for unapproved draft, got {resp.status_code}: {resp.text}"
    )


# ===========================================================================
# 5. POST /publish/jobs — 422 for empty/whitespace campaign_code
# ===========================================================================


def test_m7_create_job_422_empty_campaign_code(client: TestClient):
    """POST /publish/jobs with empty campaign_code → 422.

    Constitution rule 3: no publish job without full metadata + campaign code.
    """
    _clear_outbox()
    token = _setup_tenant(client, "m7-422-cc@test.com", "pw123456", "M7422CC")
    draft_id = _create_approved_draft(client, token)

    resp = _create_job(client, token, draft_id, campaign_code="")
    assert resp.status_code == 422, (
        f"empty campaign_code must return 422, got {resp.status_code}: {resp.text}"
    )


def test_m7_create_job_422_whitespace_campaign_code(client: TestClient):
    """POST /publish/jobs with whitespace-only campaign_code → 422.

    Constitution rule 3: no publish job without full metadata + campaign code.
    """
    _clear_outbox()
    token = _setup_tenant(client, "m7-422-ws@test.com", "pw123456", "M7422WS")
    draft_id = _create_approved_draft(client, token)

    resp = _create_job(client, token, draft_id, campaign_code="   ")
    assert resp.status_code == 422, (
        f"whitespace-only campaign_code must return 422, got {resp.status_code}: {resp.text}"
    )


# ===========================================================================
# 6. POST /publish/jobs — 422 for invalid channel
# ===========================================================================


def test_m7_create_job_422_invalid_channel(client: TestClient):
    """POST /publish/jobs with channel not in {telegram, bale, eitaa} → 422."""
    _clear_outbox()
    token = _setup_tenant(client, "m7-422-chan@test.com", "pw123456", "M7422Chan")
    draft_id = _create_approved_draft(client, token)

    resp = _create_job(client, token, draft_id, channel="whatsapp")
    assert resp.status_code == 422, (
        f"invalid channel must return 422, got {resp.status_code}: {resp.text}"
    )


# ===========================================================================
# 7. POST /publish/jobs — 404 cross-tenant isolation (CLAUDE.md rule 6)
# ===========================================================================


def test_m7_create_job_404_cross_tenant_draft(client: TestClient):
    """Tenant B cannot compile a publish job for Tenant A's draft → 404.

    Constitution rule 6: tenant isolation is absolute.
    """
    _clear_outbox()
    token_a = _setup_tenant(client, "m7-xt-a@test.com", "pw123456", "M7XTenantA")
    token_b = _setup_tenant(client, "m7-xt-b@test.com", "pw123456", "M7XTenantB")

    draft_id_a = _create_approved_draft(client, token_a)

    # Tenant B tries to create a publish job for Tenant A's draft
    resp = _create_job(client, token_b, draft_id_a)
    assert resp.status_code == 404, (
        f"Tenant B must get 404 for Tenant A's draft, got {resp.status_code}: {resp.text}"
    )


# ===========================================================================
# 8. POST /publish/dispatch — internal token guard
# ===========================================================================


def test_m7_dispatch_requires_internal_token(client: TestClient):
    """POST /publish/dispatch without X-Internal-Token → 403."""
    resp = client.post("/publish/dispatch")
    assert resp.status_code == 403, (
        f"expected 403 for POST /publish/dispatch without token, got {resp.status_code}"
    )


def test_m7_dispatch_wrong_internal_token(client: TestClient):
    """POST /publish/dispatch with wrong X-Internal-Token → 403."""
    resp = client.post(
        "/publish/dispatch",
        headers={"X-Internal-Token": "this-is-definitely-wrong-token"},
    )
    assert resp.status_code == 403, (
        f"expected 403 for wrong X-Internal-Token, got {resp.status_code}"
    )


# ===========================================================================
# 9. POST /publish/dispatch — sends queued jobs
# ===========================================================================


def test_m7_dispatch_sends_queued_jobs(client: TestClient):
    """dispatch → sends due queued jobs; job status becomes 'sent'; _OUTBOX has one entry.

    Each _OUTBOX entry must contain at least: channel, chat_id, text, job_id.
    """
    _clear_outbox()
    token = _setup_tenant(client, "m7-disp-send@test.com", "pw123456", "M7DispSend")
    draft_id = _create_approved_draft(client, token)

    job_resp = _create_job(client, token, draft_id, channel="telegram", chat_id="99001")
    assert job_resp.status_code == 201, f"job creation failed: {job_resp.text}"
    job_id = job_resp.json()["job_id"]

    dispatch_resp = client.post("/publish/dispatch", headers=_internal_header())
    assert dispatch_resp.status_code == 200, (
        f"dispatch must return 200, got {dispatch_resp.status_code}: {dispatch_resp.text}"
    )
    body = dispatch_resp.json()
    assert "sent" in body and "blocked" in body and "failed" in body, (
        f"dispatch response must have sent/blocked/failed keys: {body}"
    )
    assert body["sent"] >= 1, f"at least 1 job should have been sent, got: {body}"

    # _OUTBOX must have exactly one entry for this job
    job_entries = [e for e in _channels._OUTBOX if e.get("job_id") == job_id]
    assert len(job_entries) == 1, (
        f"_OUTBOX must have exactly 1 entry for job {job_id}, "
        f"got {len(job_entries)}: {_channels._OUTBOX}"
    )
    entry = job_entries[0]
    for field in ("channel", "chat_id", "text", "job_id"):
        assert field in entry, f"_OUTBOX entry missing '{field}': {entry}"
    assert entry["channel"] == "telegram", f"channel mismatch in _OUTBOX entry: {entry}"
    assert entry["chat_id"] == "99001", f"chat_id mismatch in _OUTBOX entry: {entry}"


# ===========================================================================
# 10. POST /publish/dispatch — idempotent, no double-send
# ===========================================================================


def test_m7_dispatch_idempotent_no_double_send(client: TestClient):
    """Calling dispatch twice → second call returns sent=0; _OUTBOX has exactly 1 entry.

    Blueprint acceptance: «نه دوباره‌فرستادن» (no double-send after tunnel reconnect).
    """
    _clear_outbox()
    token = _setup_tenant(client, "m7-disp-idem@test.com", "pw123456", "M7DispIdem")
    draft_id = _create_approved_draft(client, token)

    job_resp = _create_job(client, token, draft_id, channel="telegram", chat_id="99002")
    assert job_resp.status_code == 201
    job_id = job_resp.json()["job_id"]

    # First dispatch — must send
    r1 = client.post("/publish/dispatch", headers=_internal_header())
    assert r1.status_code == 200
    assert r1.json()["sent"] >= 1, f"first dispatch must send, got: {r1.json()}"

    # Second dispatch — same job must NOT be sent again
    r2 = client.post("/publish/dispatch", headers=_internal_header())
    assert r2.status_code == 200
    assert r2.json()["sent"] == 0, (
        f"second dispatch must return sent=0 (idempotent), got: {r2.json()}"
    )

    # _OUTBOX must still have exactly 1 entry for this job
    job_entries = [e for e in _channels._OUTBOX if e.get("job_id") == job_id]
    assert len(job_entries) == 1, (
        f"_OUTBOX must have exactly 1 entry after two dispatches (no double-send), "
        f"got {len(job_entries)}: {_channels._OUTBOX}"
    )


# ===========================================================================
# 11. Silence flag inside send path blocks queued jobs (constitution rule 2)
# ===========================================================================


def test_m7_dispatch_silence_blocks_queued_jobs(client: TestClient):
    """Silence flag set → dispatch blocked>=1, _OUTBOX EMPTY, job still 'queued'.

    Constitution rule 2: the silence flag check lives INSIDE the publisher
    send path, not only in the scheduler — queued jobs stop too.
    Blueprint acceptance: «فعال‌سازی پرچم سکوت → توقف فوری حتی برای جاب‌های در صف»
    """
    _clear_outbox()
    token = _setup_tenant(client, "m7-sil-block@test.com", "pw123456", "M7SilBlock")
    draft_id = _create_approved_draft(client, token)
    job_resp = _create_job(client, token, draft_id, channel="telegram", chat_id="99003")
    assert job_resp.status_code == 201
    job_id = job_resp.json()["job_id"]

    # Activate tenant silence via governance API
    sil_resp = client.post(
        "/governance/silence",
        json={"active": True, "reason": "عزای عمومی"},
        headers=_auth(token),
    )
    assert sil_resp.status_code == 200, f"silence activate failed: {sil_resp.text}"

    # Dispatch must NOT send the job
    dispatch_resp = client.post("/publish/dispatch", headers=_internal_header())
    assert dispatch_resp.status_code == 200
    body = dispatch_resp.json()
    assert body["blocked"] >= 1, (
        f"dispatch under silence must return blocked>=1, got: {body}"
    )
    # _OUTBOX must be empty — no send happened
    assert _channels._OUTBOX == [], (
        f"_OUTBOX must be empty when silence is active, got: {_channels._OUTBOX}"
    )

    # Job status must still be 'queued' (not lost, not sent)
    jobs_resp = client.get("/publish/jobs", headers=_auth(token))
    assert jobs_resp.status_code == 200
    jobs = jobs_resp.json()["jobs"]
    target = next((j for j in jobs if j["job_id"] == job_id), None)
    assert target is not None, f"job {job_id} must still exist after blocked dispatch: {jobs}"
    assert target["status"] == "queued", (
        f"job must remain 'queued' after blocked dispatch (not lost), "
        f"got status: {target['status']}"
    )

    # Release silence so the test does not pollute subsequent tests
    client.post(
        "/governance/silence",
        json={"active": False, "reason": "پایان سکوت"},
        headers=_auth(token),
    )


def test_m7_dispatch_silence_cleared_then_sends(client: TestClient):
    """After silence is cleared, dispatch sends the previously-queued job.

    Proves that clearing the flag re-enables the send path (manual-only
    resume, constitution rule 7).
    """
    _clear_outbox()
    token = _setup_tenant(client, "m7-sil-clear@test.com", "pw123456", "M7SilClear")
    draft_id = _create_approved_draft(client, token)
    job_resp = _create_job(client, token, draft_id, channel="telegram", chat_id="99004")
    assert job_resp.status_code == 201
    job_id = job_resp.json()["job_id"]

    # Activate then immediately release silence
    client.post(
        "/governance/silence",
        json={"active": True, "reason": "عزا"},
        headers=_auth(token),
    )
    client.post(
        "/governance/silence",
        json={"active": False, "reason": "پایان"},
        headers=_auth(token),
    )

    # Dispatch should now send
    dispatch_resp = client.post("/publish/dispatch", headers=_internal_header())
    assert dispatch_resp.status_code == 200
    body = dispatch_resp.json()
    assert body["sent"] >= 1, (
        f"dispatch after silence cleared must send, got: {body}"
    )
    job_entries = [e for e in _channels._OUTBOX if e.get("job_id") == job_id]
    assert len(job_entries) == 1, (
        f"after silence cleared, _OUTBOX must have 1 entry for the job, "
        f"got: {_channels._OUTBOX}"
    )


# ===========================================================================
# 12. Global kill switch blocks ALL tenants (constitution rule 7)
# ===========================================================================


def test_m7_dispatch_kill_switch_blocks_all_tenants(client: TestClient):
    """Global kill switch → dispatch sends nothing for any tenant.

    Constitution rule 7: kill switch stops all publish queues in <5s.
    """
    _clear_outbox()
    token_a = _setup_tenant(client, "m7-kill-a@test.com", "pw123456", "M7KillA")
    token_b = _setup_tenant(client, "m7-kill-b@test.com", "pw123456", "M7KillB")

    draft_id_a = _create_approved_draft(client, token_a)
    draft_id_b = _create_approved_draft(client, token_b)

    job_a = _create_job(client, token_a, draft_id_a, channel="telegram", chat_id="99005")
    job_b = _create_job(client, token_b, draft_id_b, channel="bale", chat_id="99006")
    assert job_a.status_code == 201
    assert job_b.status_code == 201

    # Activate global kill switch
    kill_resp = client.post(
        "/governance/kill",
        json={"active": True, "reason": "اضطرار سراسری"},
        headers={"X-Internal-Token": _INTERNAL_TOKEN},
    )
    assert kill_resp.status_code == 200, f"kill activate failed: {kill_resp.text}"

    # Dispatch must send nothing for any tenant
    dispatch_resp = client.post("/publish/dispatch", headers=_internal_header())
    assert dispatch_resp.status_code == 200
    body = dispatch_resp.json()
    assert body["sent"] == 0, (
        f"kill switch must prevent all sends for all tenants, got sent={body['sent']}: {body}"
    )
    assert _channels._OUTBOX == [], (
        f"_OUTBOX must be empty under global kill switch, got: {_channels._OUTBOX}"
    )

    # Release kill switch so test does not pollute subsequent tests
    client.post(
        "/governance/kill",
        json={"active": False, "reason": "پایان اضطرار"},
        headers={"X-Internal-Token": _INTERNAL_TOKEN},
    )


# ===========================================================================
# 13. Transient failure → no data loss, no double-send (tunnel-drop acceptance)
# ===========================================================================


def test_m7_dispatch_transient_failure_retry(client: TestClient):
    """Transient channel error → job not lost (status='queued'), attempts==1, _OUTBOX empty.
    Second dispatch (no injected error) → sends exactly once, _OUTBOX has 1 entry.

    Blueprint acceptance (Persian): «قطع تونل وسط انتشار → نه گم شدن، نه دوباره‌فرستادن»
    (tunnel drop mid-publish → no data loss, no double-send on retry).
    """
    _clear_outbox()
    token = _setup_tenant(client, "m7-retry@test.com", "pw123456", "M7Retry")
    draft_id = _create_approved_draft(client, token)
    job_resp = _create_job(client, token, draft_id, channel="telegram", chat_id="99007")
    assert job_resp.status_code == 201
    job_id = job_resp.json()["job_id"]

    # Inject a transient failure: next send on "telegram" will raise an error.
    # _FAIL_NEXT is consumed one at a time.
    _channels._FAIL_NEXT.append("telegram")

    # First dispatch — transient failure expected
    r1 = client.post("/publish/dispatch", headers=_internal_header())
    assert r1.status_code == 200
    body1 = r1.json()
    assert body1["failed"] >= 1, (
        f"first dispatch with injected failure must report failed>=1, got: {body1}"
    )
    # No entry must be added to _OUTBOX (send did not complete)
    assert _channels._OUTBOX == [], (
        f"_OUTBOX must be empty after failed send, got: {_channels._OUTBOX}"
    )

    # Job must still exist as 'queued' — NOT lost
    jobs_resp = client.get("/publish/jobs", headers=_auth(token))
    assert jobs_resp.status_code == 200
    jobs = jobs_resp.json()["jobs"]
    target = next((j for j in jobs if j["job_id"] == job_id), None)
    assert target is not None, (
        f"job must still exist after transient failure (not lost), id={job_id}: {jobs}"
    )
    assert target["status"] == "queued", (
        f"job must remain 'queued' after transient failure (not lost), "
        f"got: {target['status']}"
    )
    assert target.get("attempts") == 1, (
        f"attempts must be 1 after first failed dispatch, got: {target.get('attempts')}"
    )

    # Second dispatch — no injected error → must send exactly once (not twice)
    r2 = client.post("/publish/dispatch", headers=_internal_header())
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["sent"] >= 1, (
        f"second dispatch (after transient error cleared) must send, got: {body2}"
    )
    job_entries = [e for e in _channels._OUTBOX if e.get("job_id") == job_id]
    assert len(job_entries) == 1, (
        f"after retry, _OUTBOX must have exactly 1 entry (no double-send), "
        f"got {len(job_entries)}: {_channels._OUTBOX}"
    )


# ===========================================================================
# 14. GET /publish/jobs — auth guard
# ===========================================================================


def test_m7_list_jobs_requires_auth(client: TestClient):
    """GET /publish/jobs without Bearer token → 401."""
    resp = client.get("/publish/jobs")
    assert resp.status_code == 401, (
        f"expected 401 for unauthenticated GET /publish/jobs, got {resp.status_code}"
    )


# ===========================================================================
# 15. GET /publish/jobs — cross-tenant isolation (CLAUDE.md rule 6)
# ===========================================================================


def test_m7_list_jobs_cross_tenant_isolation(client: TestClient):
    """Tenant B's GET /publish/jobs must not contain Tenant A's jobs.

    Constitution rule 6: every query scoped by tenant_id; every new table ships
    with a test proving cross-tenant isolation.
    """
    _clear_outbox()
    MARKER = "ISOLATION_MARKER_M7_UNIQUE_TENANT_A_JOB"

    token_a = _setup_tenant(client, "m7-iso-a@test.com", "pw123456", "M7IsoA")
    token_b = _setup_tenant(client, "m7-iso-b@test.com", "pw123456", "M7IsoB")

    draft_id_a = _create_approved_draft(client, token_a)

    # Tenant A creates a job with an isolation marker embedded in campaign_code
    job_resp = _create_job(
        client,
        token_a,
        draft_id_a,
        channel="telegram",
        campaign_code=MARKER,
    )
    assert job_resp.status_code == 201, (
        f"Tenant A job creation failed: {job_resp.text}"
    )

    # Tenant B creates their own job (so their list is non-empty)
    draft_id_b = _create_approved_draft(client, token_b)
    _create_job(client, token_b, draft_id_b, channel="bale", campaign_code="b_camp")

    # Tenant B's list must not contain Tenant A's marker anywhere in the body
    resp_b = client.get("/publish/jobs", headers=_auth(token_b))
    assert resp_b.status_code == 200, (
        f"Tenant B GET /publish/jobs must return 200, "
        f"got {resp_b.status_code}: {resp_b.text}"
    )
    assert MARKER not in resp_b.text, (
        f"Tenant B's job list must not contain Tenant A's marker.\n"
        f"marker={MARKER!r}\nresponse={resp_b.text!r}"
    )

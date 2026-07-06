"""
M10 acceptance tests — Kill switch operational safety drill.

Blueprint §6.4 acceptance criteria:
  - kill switch confirmed < 5 s
  - manual-only resume (no auto-release)

Constitution rules:
  - Rule 2: silence/kill check lives INSIDE the publisher send path
  - Rule 7: kill switch stops all publish queues in <5 s; auto-halt, manual-only resume

Env pattern mirrors test_m7_publish.py: PUBLISH_MODE=fake forced before any
rpim_core_api import; INTERNAL_TOKEN ensured present via setdefault (so M10
works when run in isolation), but _internal_header() reads os.environ at CALL
TIME rather than caching a module-level value — this is necessary because
test_m5_qa.py overwrites INTERNAL_TOKEN with a fresh token during collection
(it runs after this file alphabetically), and the server always reads the
current os.environ value.  Reading dynamically keeps test and server in sync
regardless of collection order.

All tests named test_m10_<criterion>.
"""

from __future__ import annotations

import os
import secrets
import time

# Must be set BEFORE any import of rpim_core_api.* (same pattern as M7).
os.environ["PUBLISH_MODE"] = "fake"
os.environ.setdefault("EMBED_MODE", "fake")
os.environ.setdefault("COMPLETE_MODE", "fake")

# Ensure INTERNAL_TOKEN is present when M10 runs in isolation.
# Do NOT cache the value: test_m5_qa.py (collected later) overwrites the env
# var with a fresh token, so we must read os.environ at call time.
os.environ.setdefault("INTERNAL_TOKEN", secrets.token_hex(32))

from fastapi.testclient import TestClient  # noqa: E402

# This import will raise ModuleNotFoundError until rpim_core_api.publisher is
# implemented — the expected collection error for missing modules.
import rpim_core_api.publisher.channels as _channels  # noqa: E402

# ---------------------------------------------------------------------------
# Brief constant (same shape as M7 helpers to keep the full setup chain valid)
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
# Helpers (self-contained; no cross-module imports from test_m7_publish)
# ---------------------------------------------------------------------------


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _internal_header() -> dict:
    # Read at call time, not at module level — see module docstring.
    return {"X-Internal-Token": os.environ.get("INTERNAL_TOKEN", "")}


def _register(client: TestClient, email: str, password: str, tenant_name: str) -> str:
    resp = client.post(
        "/auth/register",
        json={"email": email, "password": password, "tenant_name": tenant_name},
    )
    assert resp.status_code == 201, f"register failed: {resp.text}"
    return resp.json()["access_token"]


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
    campaign_code: str = "camp_m10",
) -> str:
    resp = client.post(
        "/publish/jobs",
        json={
            "draft_id": draft_id,
            "channel": channel,
            "chat_id": chat_id,
            "campaign_code": campaign_code,
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201, f"job create failed: {resp.text}"
    return resp.json()["job_id"]


def _clear_outbox() -> None:
    _channels._OUTBOX.clear()
    _channels._FAIL_NEXT.clear()


def _kill(client: TestClient, *, active: bool) -> None:
    resp = client.post(
        "/governance/kill",
        json={
            "active": active,
            "reason": "اضطرار عملیاتی M10" if active else "پایان اضطرار M10",
        },
        headers=_internal_header(),
    )
    assert resp.status_code == 200, f"kill toggle (active={active}) failed: {resp.text}"


def _dispatch(client: TestClient) -> dict:
    resp = client.post("/publish/dispatch", headers=_internal_header())
    assert resp.status_code == 200, f"dispatch failed: {resp.text}"
    return resp.json()


# ===========================================================================
# 1. Full kill-switch drill in-process — timing must be < 5 s
# ===========================================================================


def test_m10_kill_switch_under_5s(client: TestClient):
    """Full drill: create tenant → approved draft → queued job → activate kill →
    dispatch → assert sent==0, _OUTBOX empty, elapsed < 5.0 s.
    Then release kill (explicit call) → dispatch → job sends (manual-only resume proven).

    Blueprint §6.4: kill switch confirmed < 5 s.
    Constitution rule 7: kill switch stops all publish queues in <5 s.
    """
    _clear_outbox()
    token = _register(client, "m10-ks5s@test.com", "pw123456", "M10KS5s")
    draft_id = _create_approved_draft(client, token)
    job_id = _create_job(
        client, token, draft_id, channel="telegram", chat_id="m10-5s-001", campaign_code="ks5s"
    )

    # ---- timed kill + dispatch ----
    t0 = time.monotonic()
    _kill(client, active=True)
    body = _dispatch(client)
    elapsed = time.monotonic() - t0
    # --------------------------------

    assert body["sent"] == 0, (
        f"kill switch must prevent all sends; expected sent==0, got: {body}"
    )
    assert _channels._OUTBOX == [], (
        f"_OUTBOX must be empty under active kill switch, got: {_channels._OUTBOX}"
    )
    assert elapsed < 5.0, (
        f"kill activation + dispatch round-trip took {elapsed:.3f}s — must be < 5.0s"
    )

    # Release kill — manual-only resume; proves no publish happens before explicit release
    _kill(client, active=False)
    body2 = _dispatch(client)
    assert body2["sent"] >= 1, (
        f"dispatch after explicit kill release must send the queued job, got: {body2}"
    )
    sent_entries = [e for e in _channels._OUTBOX if e.get("job_id") == job_id]
    assert len(sent_entries) == 1, (
        f"job must appear exactly once in _OUTBOX after kill release (no double-send): "
        f"{_channels._OUTBOX}"
    )


# ===========================================================================
# 2. Two tenants each with a queued job — kill blocks BOTH; release sends BOTH
# ===========================================================================


def test_m10_kill_blocks_mid_queue(client: TestClient):
    """Global kill switch halts publish for ALL tenants simultaneously.

    Two tenants each with one queued job:
      kill on  → dispatch → sent==0 (both blocked, _OUTBOX empty)
      release  → dispatch → both jobs sent (sent>=2, one _OUTBOX entry each)

    Constitution rule 7: kill switch stops all publish queues.
    """
    _clear_outbox()
    token_a = _register(client, "m10-kbq-a@test.com", "pw123456", "M10KBQa")
    token_b = _register(client, "m10-kbq-b@test.com", "pw123456", "M10KBQb")

    draft_a = _create_approved_draft(client, token_a)
    draft_b = _create_approved_draft(client, token_b)
    job_a = _create_job(
        client, token_a, draft_a, channel="telegram", chat_id="m10-kbq-a01", campaign_code="kbq_a"
    )
    job_b = _create_job(
        client, token_b, draft_b, channel="bale", chat_id="m10-kbq-b01", campaign_code="kbq_b"
    )

    # ---- kill on → dispatch must block BOTH ----
    _kill(client, active=True)
    body = _dispatch(client)
    assert body["sent"] == 0, (
        f"kill must block ALL tenants; expected sent==0, got: {body}"
    )
    assert _channels._OUTBOX == [], (
        f"_OUTBOX must be empty under global kill (two tenants), got: {_channels._OUTBOX}"
    )

    # ---- release → dispatch must send BOTH ----
    _kill(client, active=False)
    body2 = _dispatch(client)
    assert body2["sent"] >= 2, (
        f"after kill release, both tenant jobs must send; expected sent>=2, got: {body2}"
    )
    a_entries = [e for e in _channels._OUTBOX if e.get("job_id") == job_a]
    b_entries = [e for e in _channels._OUTBOX if e.get("job_id") == job_b]
    assert len(a_entries) == 1, (
        f"Tenant A job must appear exactly once in _OUTBOX after release: {_channels._OUTBOX}"
    )
    assert len(b_entries) == 1, (
        f"Tenant B job must appear exactly once in _OUTBOX after release: {_channels._OUTBOX}"
    )


# ===========================================================================
# 3. Kill is not auto-released — repeated dispatch under kill still sends nothing
# ===========================================================================


def test_m10_kill_release_requires_explicit_call(client: TestClient):
    """After kill is activated, it is NEVER auto-released by time or repeated dispatch.

    Two consecutive dispatches under kill, WITHOUT any release call between them,
    must BOTH return sent==0.

    Constitution rule 7: «auto-halt, manual-only resume».
    Blueprint: kill switch released only by an explicit POST /governance/kill {active:false}.
    """
    _clear_outbox()
    token = _register(client, "m10-knorel@test.com", "pw123456", "M10KNoRel")
    draft_id = _create_approved_draft(client, token)
    _create_job(
        client, token, draft_id,
        channel="telegram", chat_id="m10-norel-001", campaign_code="norel",
    )

    _kill(client, active=True)

    # First dispatch under kill → nothing sent
    body1 = _dispatch(client)
    assert body1["sent"] == 0, (
        f"first dispatch under active kill must send nothing, got: {body1}"
    )
    assert _channels._OUTBOX == [], (
        "_OUTBOX must be empty after first dispatch under kill"
    )

    # Second dispatch WITHOUT any release call → still nothing sent (no auto-release)
    body2 = _dispatch(client)
    assert body2["sent"] == 0, (
        f"second dispatch under active kill (no release between dispatches) must "
        f"still send nothing — kill is never auto-released. got: {body2}"
    )
    assert _channels._OUTBOX == [], (
        f"_OUTBOX must still be empty after second dispatch under kill (no auto-release): "
        f"{_channels._OUTBOX}"
    )

    # Cleanup: release so this test does not pollute subsequent tests
    _kill(client, active=False)

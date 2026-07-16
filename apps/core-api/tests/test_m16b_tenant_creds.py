"""
M16b acceptance tests — the publish engine uses per-brand hub credentials.

Contract:
  - Dispatch resolves the job tenant's ChannelConnection: connected →
    the send uses the TENANT credential; not connected → safe fallback to
    the global env credential (the pre-M16 behavior).
  - Connected but unsealable (vault key rotated/lost) → the job STAYS
    QUEUED (transient), never silently falls back to the global identity.
  - Live adapters: bale/eitaa use the tenant token in the bot URL;
    wordpress uses tenant base_url/user/secret; telegram forwards
    bot_token to the us-leg gateway payload (env fallback = no field).
  - Secrets still never leak into error strings or job rows.

All tests named test_m16b_<criterion>.
"""

from __future__ import annotations

import os
import secrets as _secrets

import pytest
from fastapi.testclient import TestClient

from rpim_core_api.publisher import channels

os.environ.setdefault("EMBED_MODE", "fake")
os.environ.setdefault("COMPLETE_MODE", "fake")
os.environ.setdefault("PUBLISH_MODE", "fake")
_INTERNAL_TOKEN: str = os.environ.setdefault("INTERNAL_TOKEN", _secrets.token_hex(32))

_TENANT_TOKEN = "bot777:TENANT-test-token"  # noqa: S105 — inoperable test fixture
_BRIEF = {
    "goal": "افزایش آگاهی از برند",
    "audience": "مدیران میان‌رده",
    "channel": "بله",
    "format": "پست متنی",
    "hook": None,
    "cta": None,
}


@pytest.fixture(autouse=True)
def _seams(monkeypatch):
    from cryptography.fernet import Fernet  # noqa: PLC0415

    monkeypatch.setenv("CHANNEL_SECRET_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("PUBLISH_MODE", "fake")
    channels._OUTBOX.clear()
    channels._FAIL_NEXT.clear()
    yield
    channels._OUTBOX.clear()
    channels._FAIL_NEXT.clear()


def _register(client: TestClient, email: str, name: str) -> str:
    resp = client.post(
        "/auth/register",
        json={"email": email, "password": "Password123!", "tenant_name": name},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _internal_header() -> dict:
    return {"X-Internal-Token": _INTERNAL_TOKEN}


def _queued_bale_job(client: TestClient, token: str) -> str:
    resp = client.post("/content/drafts", json={"brief": _BRIEF}, headers=_auth(token))
    assert resp.status_code == 201, resp.text
    draft_id = resp.json()["draft_id"]
    approve = client.post(f"/content/drafts/{draft_id}/approve", headers=_auth(token))
    assert approve.status_code == 200, approve.text
    resp = client.post(
        "/publish/jobs",
        json={
            "draft_id": draft_id,
            "channel": "bale",
            "chat_id": "@beewaz",
            "campaign_code": "camp_m16b",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["job_id"]


def _connect_bale(client: TestClient, token: str) -> None:
    resp = client.put(
        "/channels/bale",
        json={"secret": _TENANT_TOKEN, "config": {"chat_id": "@beewaz"}},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text


# ===========================================================================
# 1. Engine end-to-end through the fake seam
# ===========================================================================


def test_m16b_dispatch_uses_tenant_creds_when_connected(client: TestClient):
    token = _register(client, "m16b-tenant@example.com", "M16bTenant")
    _connect_bale(client, token)
    _queued_bale_job(client, token)

    resp = client.post("/publish/dispatch", headers=_internal_header())
    assert resp.status_code == 200, resp.text
    assert resp.json()["sent"] == 1, resp.json()
    assert channels._OUTBOX[0]["creds_source"] == "tenant", channels._OUTBOX


def test_m16b_dispatch_falls_back_to_env_when_not_connected(client: TestClient):
    token = _register(client, "m16b-env@example.com", "M16bEnv")
    _queued_bale_job(client, token)

    resp = client.post("/publish/dispatch", headers=_internal_header())
    assert resp.status_code == 200, resp.text
    assert resp.json()["sent"] == 1, resp.json()
    assert channels._OUTBOX[0]["creds_source"] == "env", channels._OUTBOX


def test_m16b_unseal_failure_keeps_job_queued_never_wrong_identity(
    client: TestClient, monkeypatch
):
    """A brand that DID connect its own bot must never publish through the
    global identity: rotated/lost vault key → transient failure, job waits."""
    from cryptography.fernet import Fernet  # noqa: PLC0415

    token = _register(client, "m16b-rot@example.com", "M16bRot")
    _connect_bale(client, token)
    _queued_bale_job(client, token)

    monkeypatch.setenv("CHANNEL_SECRET_KEY", Fernet.generate_key().decode())  # rotate

    resp = client.post("/publish/dispatch", headers=_internal_header())
    assert resp.status_code == 200, resp.text
    assert resp.json()["sent"] == 0 and resp.json()["failed"] == 1, resp.json()
    assert channels._OUTBOX == [], "nothing may be sent through the wrong identity"

    jobs = client.get("/publish/jobs", headers=_auth(token)).json()["jobs"]
    assert jobs[0]["status"] == "queued", f"job must stay queued: {jobs[0]}"
    assert _TENANT_TOKEN not in (jobs[0].get("last_error") or ""), (
        "secrets must never leak into job rows"
    )


# ===========================================================================
# 2. Live adapters — tenant token vs env fallback (unit level)
# ===========================================================================


class _Resp:
    def raise_for_status(self):
        return None


def test_m16b_live_bale_prefers_tenant_token(monkeypatch):
    import httpx  # noqa: PLC0415

    captured: dict = {}

    def fake_post(url, json=None, headers=None, timeout=None, auth=None, data=None, files=None):  # noqa: A002
        captured["url"] = url
        return _Resp()

    monkeypatch.setenv("PUBLISH_MODE", "live")
    monkeypatch.setenv("BALE_BOT_TOKEN", "env-global-token")
    monkeypatch.setattr(httpx, "post", fake_post)

    channels.send("bale", "@x", "متن", "job-1", creds={"secret": _TENANT_TOKEN, "config": {}})
    assert _TENANT_TOKEN in captured["url"], captured
    assert "env-global-token" not in captured["url"], captured

    channels.send("bale", "@x", "متن", "job-2", creds=None)
    assert "env-global-token" in captured["url"], captured


def test_m16b_live_wordpress_uses_tenant_connection(monkeypatch):
    import httpx  # noqa: PLC0415

    captured: dict = {}

    def fake_post(url, json=None, headers=None, timeout=None, auth=None):  # noqa: A002
        captured.update(url=url, auth=auth)
        return _Resp()

    monkeypatch.setenv("PUBLISH_MODE", "live")
    for var in ("WORDPRESS_BASE_URL", "WORDPRESS_USER", "WORDPRESS_APP_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(httpx, "post", fake_post)

    channels.send(
        "wordpress",
        "-",
        "متن پست",
        "job-3",
        creds={
            "secret": "tenant-app-pass",
            "config": {"base_url": "https://brand.ir", "user": "beewaz"},
        },
    )
    assert captured["url"] == "https://brand.ir/wp-json/wp/v2/posts", captured
    assert captured["auth"] == ("beewaz", "tenant-app-pass"), captured


def test_m16b_live_telegram_forwards_bot_token_cross_leg(monkeypatch):
    import httpx  # noqa: PLC0415

    captured: dict = {}

    def fake_post(url, json=None, headers=None, timeout=None):  # noqa: A002
        captured.update(url=url, json=json)
        return _Resp()

    monkeypatch.setenv("PUBLISH_MODE", "live")
    monkeypatch.setenv("GATEWAY_URL", "http://gateway.test:8080")
    monkeypatch.setenv("INTERNAL_TOKEN", "itok")
    monkeypatch.setattr(httpx, "post", fake_post)

    channels.send(
        "telegram", "@x", "متن", "job-4", creds={"secret": _TENANT_TOKEN, "config": {}}
    )
    assert captured["json"].get("bot_token") == _TENANT_TOKEN, captured

    channels.send("telegram", "@x", "متن", "job-5", creds=None)
    assert "bot_token" not in captured["json"], (
        f"env fallback must not send a bot_token field: {captured}"
    )

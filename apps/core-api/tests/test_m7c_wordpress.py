"""
M7 slice C acceptance tests — WordPress REST publishing adapter (rule 5:
the last ALLOWED channel that had no adapter; official wp-json REST only).

Contract:
  - channels.SUPPORTED_CHANNELS includes "wordpress"
  - POST /publish/jobs accepts channel="wordpress" (schema Literal)
  - PUBLISH_MODE=fake: send() routes to the _OUTBOX seam like other channels
  - PUBLISH_MODE=live:
      * missing WORDPRESS_BASE_URL / WORDPRESS_USER / WORDPRESS_APP_PASSWORD
        → ChannelSendError naming the env VAR (rule 4: names, never values)
      * posts to {base}/wp-json/wp/v2/posts with HTTP Basic auth
        (application password), body {title, content, status="publish"} —
        title = first non-empty line of the text
  - send_photo("wordpress", ...) raises ChannelSendError (transient — the
    media two-step is a follow-up slice; job stays queued, same precedent
    as telegram photos before the gateway passthrough)
  - Dashboard: publish page offers the channel; fa.publish.channels has a
    Persian label (locale-only rule)

All tests named test_m7c_<criterion>. EMBED/COMPLETE fake at module level.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

os.environ.setdefault("EMBED_MODE", "fake")
os.environ.setdefault("COMPLETE_MODE", "fake")
os.environ.setdefault("PUBLISH_MODE", "fake")

import pytest
from fastapi.testclient import TestClient

from rpim_core_api.publisher import channels

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PUBLISH_TSX = _REPO_ROOT / "apps" / "dashboard" / "app" / "publish" / "page.tsx"
_FA_JSON = _REPO_ROOT / "apps" / "dashboard" / "locales" / "fa.json"

_BRIEF = {
    "goal": "افزایش آگاهی از برند",
    "audience": "مدیران میان‌رده",
    "channel": "وردپرس",
    "format": "پست متنی",
    "hook": None,
    "cta": None,
}


@pytest.fixture(autouse=True)
def _clean_channel_seams(monkeypatch):
    channels._OUTBOX.clear()
    channels._FAIL_NEXT.clear()
    monkeypatch.setenv("PUBLISH_MODE", "fake")
    yield
    channels._OUTBOX.clear()
    channels._FAIL_NEXT.clear()


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


# ===========================================================================
# 1. Channel registration + job schema
# ===========================================================================


def test_m7c_wordpress_in_supported_channels():
    assert "wordpress" in channels.SUPPORTED_CHANNELS


def test_m7c_publish_job_accepts_wordpress(client: TestClient):
    token = _register(client, "wp-job@example.com", "Password123!", "WpJob")[
        "access_token"
    ]
    draft_id = _create_approved_draft(client, token)
    resp = client.post(
        "/publish/jobs",
        json={
            "draft_id": draft_id,
            "channel": "wordpress",
            "chat_id": "-",
            "campaign_code": "camp_wp_001",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201, f"wordpress job must be accepted: {resp.text}"


# ===========================================================================
# 2. Fake mode — same _OUTBOX seam as every other channel
# ===========================================================================


def test_m7c_fake_mode_routes_to_outbox():
    channels.send("wordpress", "-", "متن پست وبلاگ", "job-wp-1")
    assert channels._OUTBOX == [
        {
            "channel": "wordpress",
            "chat_id": "-",
            "text": "متن پست وبلاگ",
            "job_id": "job-wp-1",
            "creds_source": "env",
        }
    ], f"fake mode must use the outbox seam: {channels._OUTBOX}"


# ===========================================================================
# 3. Live mode — env guard (rule 4) and the wp-json call
# ===========================================================================


def test_m7c_live_mode_missing_env_names_the_var(monkeypatch):
    monkeypatch.setenv("PUBLISH_MODE", "live")
    for var in ("WORDPRESS_BASE_URL", "WORDPRESS_USER", "WORDPRESS_APP_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(channels.ChannelSendError) as excinfo:
        channels.send("wordpress", "-", "متن", "job-wp-2")
    assert "WORDPRESS_BASE_URL" in str(excinfo.value), (
        f"error must NAME the missing env var (rule 4): {excinfo.value}"
    )


def test_m7c_live_mode_posts_to_wp_json_with_basic_auth(monkeypatch):
    import httpx  # noqa: PLC0415

    captured: dict = {}

    class _Resp:
        def raise_for_status(self):
            return None

    def fake_post(url, json=None, headers=None, timeout=None, auth=None):  # noqa: A002
        captured.update(url=url, json=json, auth=auth)
        return _Resp()

    monkeypatch.setenv("PUBLISH_MODE", "live")
    monkeypatch.setenv("WORDPRESS_BASE_URL", "https://blog.example.com/")
    monkeypatch.setenv("WORDPRESS_USER", "publisher")
    monkeypatch.setenv("WORDPRESS_APP_PASSWORD", "xxxx yyyy zzzz")
    monkeypatch.setattr(httpx, "post", fake_post)

    text = "عنوان پست وبلاگ\n\nبدنه‌ی کامل پست با جزئیات."
    channels.send("wordpress", "-", text, "job-wp-3")

    assert captured["url"] == "https://blog.example.com/wp-json/wp/v2/posts", captured
    assert captured["auth"] == ("publisher", "xxxx yyyy zzzz"), (
        "wordpress must authenticate with HTTP Basic (application password)"
    )
    assert captured["json"]["title"] == "عنوان پست وبلاگ", captured["json"]
    assert captured["json"]["content"] == text, captured["json"]
    assert captured["json"]["status"] == "publish", captured["json"]


def test_m7c_photo_jobs_stay_queued_as_transient(monkeypatch):
    """Media upload is a two-step wp flow — follow-up slice. Until then a
    wordpress photo send fails TRANSIENTLY so the job waits (the telegram
    photo precedent), never a silent drop or a fake 'sent'."""
    monkeypatch.setenv("PUBLISH_MODE", "live")
    monkeypatch.setenv("WORDPRESS_BASE_URL", "https://blog.example.com")
    monkeypatch.setenv("WORDPRESS_USER", "publisher")
    monkeypatch.setenv("WORDPRESS_APP_PASSWORD", "x")
    with pytest.raises(channels.ChannelSendError):
        channels.send_photo("wordpress", "-", "کپشن", b"png-bytes", "job-wp-4")


# ===========================================================================
# 4. Dashboard static contract (locale-only rule)
# ===========================================================================


def test_m7c_dashboard_offers_wordpress_channel():
    src = _PUBLISH_TSX.read_text("utf-8")
    assert '"wordpress"' in src, "publish page CHANNELS must include wordpress"
    assert not re.compile(r"[؀-ۿ]").search(src), (
        "publish page must stay free of hardcoded Persian (locale-only rule)"
    )


def test_m7c_locale_has_wordpress_label():
    fa = json.loads(_FA_JSON.read_text("utf-8"))
    label = fa["publish"]["channels"].get("wordpress", "")
    assert label, "fa.publish.channels.wordpress missing"


# ===========================================================================
# 5. Env templates carry the names (rule 4: names only, iran leg)
# ===========================================================================


def test_m7c_env_example_names_wordpress_credentials():
    text = (_REPO_ROOT / ".env.iran.example").read_text("utf-8")
    for var in ("WORDPRESS_BASE_URL", "WORDPRESS_USER", "WORDPRESS_APP_PASSWORD"):
        assert re.search(rf"^{var}=$", text, re.MULTILINE), (
            f".env.iran.example must name {var} with an EMPTY value (rule 4)"
        )

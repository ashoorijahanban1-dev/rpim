"""
M21 acceptance tests (delivery slice) — WordPress 2-stage upload + the
24-hour time-based dead-letter.

Contract (design §1 0016 + §3.2 + §4.4):
  WordPress photos (finally closing the M7c stub):
    - Stage 1 uploads to {base}/wp-json/wp/v2/media (multipart, filename,
      alt_text) and the wp_media_id RECEIPT commits on the asset BEFORE
      stage 2 (rule 8) — a crash between stages resumes at stage 2 with the
      SAME media id: no orphan media, no double upload.
    - Stage 2 creates the post with featured_media.
  Dead-letter (replaces infinite retry):
    - first ChannelSendError stamps publish_jobs.first_failed_at (app-TZ
      clock); success clears it; silence-blocked passes never touch it.
    - a job older than MAX_PUBLISH_RETRY_HOURS (default 24) since its first
      failure moves to status='stalled' and leaves the retry loop.
    - POST /publish/jobs/{id}/requeue (editor+) revives ONLY stalled jobs.
    - /reports/monthly publish block counts stalled.
  Dashboard: stalled chip + requeue on the publish page (locale-only).

All tests named test_m21_<criterion>.
"""

from __future__ import annotations

import os
import re
import secrets as _secrets
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rpim_core_api.publisher import channels

os.environ.setdefault("EMBED_MODE", "fake")
os.environ.setdefault("COMPLETE_MODE", "fake")
os.environ.setdefault("PUBLISH_MODE", "fake")
os.environ.setdefault("IMAGE_MODE", "fake")
_INTERNAL_TOKEN: str = os.environ.setdefault("INTERNAL_TOKEN", _secrets.token_hex(32))

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PUBLISH_TSX = _REPO_ROOT / "apps" / "dashboard" / "app" / "publish" / "page.tsx"


@pytest.fixture(autouse=True)
def _seams(monkeypatch, tmp_path):
    monkeypatch.setenv("PUBLISH_MODE", "fake")
    monkeypatch.setenv("IMAGE_MODE", "fake")
    monkeypatch.setenv("MEDIA_STORAGE_DIR", str(tmp_path / "media"))
    channels._OUTBOX.clear()
    channels._FAIL_NEXT.clear()
    yield
    channels._OUTBOX.clear()
    channels._FAIL_NEXT.clear()


def _session():
    from sqlalchemy.orm import Session  # noqa: PLC0415

    from rpim_core_api import db as db_module  # noqa: PLC0415

    return Session(db_module.engine)


def _register(client: TestClient, email: str, name: str) -> str:
    resp = client.post(
        "/auth/register",
        json={"email": email, "password": "Password123!", "tenant_name": name},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _internal() -> dict:
    return {"X-Internal-Token": _INTERNAL_TOKEN}


def _queued_job(client: TestClient, token: str, channel: str = "bale") -> str:
    brief = {
        "goal": "هدف",
        "audience": "مخاطب",
        "channel": "بله",
        "format": "پست",
        "hook": None,
        "cta": None,
    }
    resp = client.post("/content/drafts", json={"brief": brief}, headers=_auth(token))
    draft_id = resp.json()["draft_id"]
    client.post(f"/content/drafts/{draft_id}/approve", headers=_auth(token))
    resp = client.post(
        "/publish/jobs",
        json={
            "draft_id": draft_id,
            "channel": channel,
            "chat_id": "@x",
            "campaign_code": "camp_dl",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["job_id"]


def _job_row(job_id: str):
    from rpim_core_api.models import PublishJob  # noqa: PLC0415

    with _session() as session:
        return session.get(PublishJob, job_id)


# ===========================================================================
# 1. WordPress two-stage upload with receipt resume
# ===========================================================================


def test_m21_wp_upload_then_attach_with_receipt_resume(client: TestClient, monkeypatch):
    """Stage 2 fails on the first pass → the wp_media_id receipt is already
    committed; the retry pass calls /media ZERO more times and succeeds."""
    import httpx  # noqa: PLC0415

    token = _register(client, "m21-wp@example.com", "M21Wp")
    media_id = None
    # generated asset via the studio
    prompt = client.post(
        "/studio/prompts",
        json={"kind": "image", "brief": {"subject": "دزدگیر BH10"}},
        headers=_auth(token),
    ).json()["prompt_id"]
    media_id = client.post(
        "/studio/media", json={"prompt_id": prompt}, headers=_auth(token)
    ).json()["media_id"]
    client.post(f"/studio/media/{media_id}/approve", headers=_auth(token))

    brief = {
        "goal": "هدف",
        "audience": "مخاطب",
        "channel": "وردپرس",
        "format": "پست",
        "hook": None,
        "cta": None,
    }
    draft_id = client.post(
        "/content/drafts", json={"brief": brief}, headers=_auth(token)
    ).json()["draft_id"]
    client.post(f"/content/drafts/{draft_id}/approve", headers=_auth(token))
    resp = client.post(
        "/publish/jobs",
        json={
            "draft_id": draft_id,
            "channel": "wordpress",
            "chat_id": "-",
            "campaign_code": "camp_wp21",
            "image": {"kind": "generated", "media_asset_id": media_id},
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text

    calls: list[str] = []
    fail_attach_once = {"armed": True}

    class _Resp:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    def fake_post(url, json=None, headers=None, timeout=None, auth=None, data=None, files=None):  # noqa: A002
        calls.append(url)
        if url.endswith("/wp-json/wp/v2/media"):
            return _Resp({"id": 4242})
        if fail_attach_once["armed"]:
            fail_attach_once["armed"] = False
            raise httpx.ConnectError("tunnel dropped mid-flight")
        return _Resp({"id": 1})

    monkeypatch.setenv("PUBLISH_MODE", "live")
    monkeypatch.setenv("WORDPRESS_BASE_URL", "https://blog.example.com")
    monkeypatch.setenv("WORDPRESS_USER", "publisher")
    monkeypatch.setenv("WORDPRESS_APP_PASSWORD", "x")
    monkeypatch.setattr(httpx, "post", fake_post)

    first = client.post("/publish/dispatch", headers=_internal())
    assert first.status_code == 200 and first.json()["failed"] == 1, first.text
    media_calls_after_first = sum(1 for u in calls if u.endswith("/wp/v2/media"))
    assert media_calls_after_first == 1

    items = client.get("/studio/media", headers=_auth(token)).json()["items"]
    assert items[0]["wp_media_id"] == 4242, (
        "the receipt must commit BEFORE stage 2 (rule 8)"
    )

    second = client.post("/publish/dispatch", headers=_internal())
    assert second.status_code == 200 and second.json()["sent"] == 1, second.text
    assert sum(1 for u in calls if u.endswith("/wp/v2/media")) == 1, (
        "retry must resume at stage 2 — no orphan media, no double upload"
    )
    attach = [u for u in calls if u.endswith("/wp/v2/posts")]
    assert attach, "stage 2 must create the post with featured_media"


# ===========================================================================
# 2. Time-based dead-letter
# ===========================================================================


def test_m21_first_failure_stamps_clock_success_clears_it(client: TestClient):
    token = _register(client, "m21-clock@example.com", "M21Clock")
    job_id = _queued_job(client, token)

    channels._FAIL_NEXT.append("bale")
    client.post("/publish/dispatch", headers=_internal())
    assert _job_row(job_id).first_failed_at is not None, "first failure stamps the clock"

    client.post("/publish/dispatch", headers=_internal())
    row = _job_row(job_id)
    assert row.status == "sent" and row.first_failed_at is None, (
        "success must clear the dead-letter clock"
    )


def test_m21_silence_blocked_passes_do_not_stamp(client: TestClient):
    token = _register(client, "m21-quiet@example.com", "M21Quiet")
    job_id = _queued_job(client, token)
    assert (
        client.post(
            "/governance/silence",
            json={"active": True, "reason": "آزمون"},
            headers=_auth(token),
        ).status_code
        == 200
    )
    client.post("/publish/dispatch", headers=_internal())
    assert _job_row(job_id).first_failed_at is None, (
        "blocked passes are governance, not failure — the clock stays untouched"
    )


def test_m21_old_failure_dead_letters_to_stalled(client: TestClient):
    from rpim_core_api.models import PublishJob  # noqa: PLC0415
    from rpim_shared.tz import now_app  # noqa: PLC0415

    token = _register(client, "m21-stall@example.com", "M21Stall")
    job_id = _queued_job(client, token)
    with _session() as session:
        row = session.get(PublishJob, job_id)
        row.first_failed_at = now_app() - timedelta(hours=25)
        session.commit()

    resp = client.post("/publish/dispatch", headers=_internal())
    assert resp.status_code == 200, resp.text
    assert resp.json().get("stalled") == 1, resp.json()
    assert _job_row(job_id).status == "stalled"
    assert channels._OUTBOX == [], "a stalled job must not be sent"

    # And it leaves the retry loop entirely.
    again = client.post("/publish/dispatch", headers=_internal())
    assert again.json().get("stalled") == 0, again.json()


def test_m21_requeue_revives_only_stalled(client: TestClient):
    from rpim_core_api.models import PublishJob  # noqa: PLC0415
    from rpim_shared.tz import now_app  # noqa: PLC0415

    token = _register(client, "m21-req@example.com", "M21Req")
    job_id = _queued_job(client, token)
    resp = client.post(f"/publish/jobs/{job_id}/requeue", headers=_auth(token))
    assert resp.status_code == 409, "only stalled jobs can requeue"

    with _session() as session:
        row = session.get(PublishJob, job_id)
        row.status = "stalled"
        row.first_failed_at = now_app() - timedelta(hours=30)
        session.commit()
    resp = client.post(f"/publish/jobs/{job_id}/requeue", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    row = _job_row(job_id)
    assert row.status == "queued" and row.first_failed_at is None

    dispatch = client.post("/publish/dispatch", headers=_internal())
    assert dispatch.json()["sent"] == 1, "a requeued job publishes normally"


def test_m21_requeue_is_tenant_scoped(client: TestClient):
    from rpim_core_api.models import PublishJob  # noqa: PLC0415

    token_a = _register(client, "m21-rqa@example.com", "M21RqA")
    token_b = _register(client, "m21-rqb@example.com", "M21RqB")
    job_b = _queued_job(client, token_b)
    with _session() as session:
        row = session.get(PublishJob, job_b)
        row.status = "stalled"
        session.commit()
    resp = client.post(f"/publish/jobs/{job_b}/requeue", headers=_auth(token_a))
    assert resp.status_code == 404, "tenant A must not requeue B's job (rule 6)"


def test_m21_monthly_report_counts_stalled(client: TestClient):
    from rpim_core_api.models import PublishJob  # noqa: PLC0415
    from rpim_shared.tz import now_app  # noqa: PLC0415

    token = _register(client, "m21-rep@example.com", "M21Rep")
    job_id = _queued_job(client, token)
    with _session() as session:
        row = session.get(PublishJob, job_id)
        row.status = "stalled"
        session.commit()
    month = now_app().strftime("%Y-%m")
    body = client.get(
        "/reports/monthly", params={"month": month}, headers=_auth(token)
    ).json()
    assert body["publish"].get("stalled") == 1, body["publish"]


# ===========================================================================
# 3. Dashboard static contract
# ===========================================================================


def test_m21_publish_page_has_stalled_and_requeue():
    src = _PUBLISH_TSX.read_text("utf-8")
    assert "status_stalled" in src, "publish page must label stalled jobs"
    assert "requeue" in src, "publish page must offer requeue for stalled jobs"
    assert not re.compile(r"[؀-ۿ]").search(src), "locale-only rule"

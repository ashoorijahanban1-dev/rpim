"""
DoD §13.1 item 2 acceptance — the first 7-asset content batch (ADR 0048).

The 24h clock is an operational SLA (docs/ops/runbook.md); what CODE must
prove is that the system produces and ships a 7-asset batch in ONE
session: 7 briefs → 7 drafts (RAG + learnings path) → 7 human approvals
(rule 1) → publish jobs spread across the 3 messengers with full
campaign metadata (rule 3) → one dispatch pass sends all 7 (fake seam) →
the one-click export carries the whole batch. Previously only
single-asset generation had acceptance coverage — this closes the gap
found by the DoD audit.
"""

from __future__ import annotations

import os
import secrets as _secrets

from fastapi.testclient import TestClient

os.environ.setdefault("EMBED_MODE", "fake")
os.environ.setdefault("COMPLETE_MODE", "fake")
os.environ.setdefault("PUBLISH_MODE", "fake")
_INTERNAL_TOKEN: str = os.environ.setdefault("INTERNAL_TOKEN", _secrets.token_hex(32))

import rpim_core_api.publisher.channels as _channels  # noqa: E402

# 7 assets across formats and channels — the real launch-week shape.
_GOALS_AUDIENCES: list[tuple[str, str, str]] = [
    ("معرفی محصول اصلی", "خانواده‌ها", "تلگرام"),
    ("پیشنهاد ویژه هفته", "مشتریان فعلی", "بله"),
    ("پشت صحنه تولید", "علاقه‌مندان برند", "ایتا"),
    ("پرسش و پاسخ پرتکرار", "مشتریان جدید", "تلگرام"),
    ("معرفی تیم", "مخاطبان عمومی", "بله"),
    ("راهنمای استفاده", "خریداران", "ایتا"),
    ("دعوت به نظرسنجی", "مشتریان وفادار", "تلگرام"),
]
_BATCH: list[dict] = [
    {"goal": goal, "audience": audience, "channel": channel, "format": "پست متنی"}
    for goal, audience, channel in _GOALS_AUDIENCES
]

# Batch spread over the three DoD messengers: 3 + 2 + 2.
_CHANNELS = ["telegram", "bale", "eitaa", "telegram", "bale", "eitaa", "telegram"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_dod_seven_asset_batch_ships_end_to_end(client: TestClient):
    resp = client.post(
        "/auth/register",
        json={
            "email": "dod-batch@example.com",
            "password": "Password123!",
            "tenant_name": "DodBatch",
        },
    )
    assert resp.status_code == 201, resp.text
    token = resp.json()["access_token"]

    _channels._OUTBOX.clear()
    _channels._FAIL_NEXT.clear()

    # 7 briefs → 7 drafts → 7 approvals (rule 1: every asset human-gated).
    draft_ids: list[str] = []
    for brief in _BATCH:
        full = {**brief, "hook": None, "cta": None}
        create = client.post("/content/drafts", json={"brief": full}, headers=_auth(token))
        assert create.status_code == 201, create.text
        draft_ids.append(create.json()["draft_id"])
    for draft_id in draft_ids:
        approve = client.post(f"/content/drafts/{draft_id}/approve", headers=_auth(token))
        assert approve.status_code == 200, approve.text

    # 7 publish jobs across the 3 messengers, full metadata (rule 3).
    for index, (draft_id, channel) in enumerate(zip(draft_ids, _CHANNELS, strict=True)):
        job = client.post(
            "/publish/jobs",
            json={
                "draft_id": draft_id,
                "channel": channel,
                "chat_id": f"chat-{index}",
                "campaign_code": f"launch_week_{index:02d}",
            },
            headers=_auth(token),
        )
        assert job.status_code == 201, f"job {index} ({channel}): {job.text}"

    # One dispatch pass ships the whole batch through the fake seam.
    dispatch = client.post(
        "/publish/dispatch", headers={"X-Internal-Token": _INTERNAL_TOKEN}
    )
    assert dispatch.status_code == 200, dispatch.text
    assert dispatch.json()["sent"] == 7, dispatch.json()

    sent_channels = sorted(entry["channel"] for entry in _channels._OUTBOX)
    assert sent_channels == sorted(_CHANNELS), (
        "all 3 messengers must have received their share of the batch"
    )

    # The one-click export carries the full batch (DoD item 7 closes item 2).
    export = client.get("/export", headers=_auth(token)).json()
    assert len(export["drafts"]) == 7
    assert len(export["publish_jobs"]) == 7
    assert all(job["campaign_code"] for job in export["publish_jobs"]), (
        "no asset ships without its campaign metadata (rule 3)"
    )
    _channels._OUTBOX.clear()

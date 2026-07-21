"""M22 slice C beat test — distill_learnings pokes the internal endpoint."""

from __future__ import annotations

import os
import secrets as _secrets

os.environ.setdefault("INTERNAL_TOKEN", _secrets.token_hex(32))
os.environ.setdefault("CORE_API_URL", "http://core-api.test:8000")

import rpim_workers.tasks as _tasks  # noqa: E402


def test_m22c_task_registered_with_daily_cadence():
    assert "rpim_workers.distill_learnings" in _tasks.celery_app.tasks
    entry = _tasks.celery_app.conf.beat_schedule.get("distill-learnings")
    assert entry is not None and entry["schedule"] >= 86400.0


def test_m22c_task_pokes_distill_endpoint(monkeypatch):
    captured: dict = {}

    def fake_post(url: str, headers: dict) -> dict:
        captured.update(url=url, headers=headers)
        return {"updated": 0}

    monkeypatch.setattr(_tasks, "_post", fake_post)
    assert _tasks.distill_learnings.apply().get() == {"updated": 0}
    assert captured["url"].endswith("/learnings/distill"), captured

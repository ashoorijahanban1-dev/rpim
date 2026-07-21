"""M23a beat test — agent_scan pokes the internal watchdog endpoint."""

from __future__ import annotations

import os
import secrets as _secrets

os.environ.setdefault("INTERNAL_TOKEN", _secrets.token_hex(32))
os.environ.setdefault("CORE_API_URL", "http://core-api.test:8000")

import rpim_workers.tasks as _tasks  # noqa: E402


def test_m23_task_registered_with_half_hour_cadence():
    assert "rpim_workers.agent_scan" in _tasks.celery_app.tasks
    entry = _tasks.celery_app.conf.beat_schedule.get("agent-scan")
    assert entry is not None and entry["schedule"] == 1800.0


def test_m23_task_pokes_scan_endpoint(monkeypatch):
    captured: dict = {}

    def fake_post(url: str, headers: dict) -> dict:
        captured.update(url=url, headers=headers)
        return {"proposed": 0}

    monkeypatch.setattr(_tasks, "_post", fake_post)
    assert _tasks.agent_scan.apply().get() == {"proposed": 0}
    assert captured["url"].endswith("/agent/scan"), captured

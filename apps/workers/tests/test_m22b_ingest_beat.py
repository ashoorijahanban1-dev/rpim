"""M22 slice B beat test — ingest_analytics pokes the internal endpoint."""

from __future__ import annotations

import os
import secrets as _secrets

os.environ.setdefault("INTERNAL_TOKEN", _secrets.token_hex(32))
os.environ.setdefault("CORE_API_URL", "http://core-api.test:8000")

import rpim_workers.tasks as _tasks  # noqa: E402


def test_m22b_task_registered_with_slow_cadence():
    assert "rpim_workers.ingest_analytics" in _tasks.celery_app.tasks
    entry = _tasks.celery_app.conf.beat_schedule.get("ingest-analytics")
    assert entry is not None and entry["schedule"] >= 3600.0


def test_m22b_task_pokes_ingest_endpoint(monkeypatch):
    captured: dict = {}

    def fake_post(url: str, headers: dict) -> dict:
        captured.update(url=url, headers=headers)
        return {"rows": 0}

    monkeypatch.setattr(_tasks, "_post", fake_post)
    assert _tasks.ingest_analytics.apply().get() == {"rows": 0}
    assert captured["url"].endswith("/metrics/ingest"), captured

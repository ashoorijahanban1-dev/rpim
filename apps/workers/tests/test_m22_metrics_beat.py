"""M22 beat test — snapshot_metrics pokes the internal snapshot endpoint."""

from __future__ import annotations

import os
import secrets as _secrets

import pytest

os.environ.setdefault("INTERNAL_TOKEN", _secrets.token_hex(32))
os.environ.setdefault("CORE_API_URL", "http://core-api.test:8000")

import rpim_workers.tasks as _tasks  # noqa: E402


def test_m22_task_registered():
    assert "rpim_workers.snapshot_metrics" in _tasks.celery_app.tasks


def test_m22_task_pokes_snapshot_endpoint(monkeypatch):
    captured: dict = {}

    def fake_post(url: str, headers: dict) -> dict:
        captured.update(url=url, headers=headers)
        return {"rows": 1}

    monkeypatch.setattr(_tasks, "_post", fake_post)
    result = _tasks.snapshot_metrics.apply().get()
    assert captured["url"].endswith("/metrics/snapshot"), captured
    assert captured["headers"]["X-Internal-Token"] == os.environ["INTERNAL_TOKEN"]
    assert result == {"rows": 1}


def test_m22_task_missing_core_url_names_the_var(monkeypatch):
    monkeypatch.delenv("CORE_API_URL", raising=False)
    with pytest.raises(RuntimeError) as excinfo:
        _tasks.snapshot_metrics.apply().get()
    assert "CORE_API_URL" in str(excinfo.value)


def test_m22_beat_schedule_cadence():
    entry = _tasks.celery_app.conf.beat_schedule.get("snapshot-metrics")
    assert entry is not None and entry["schedule"] >= 3600.0

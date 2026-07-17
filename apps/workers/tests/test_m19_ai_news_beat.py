"""
M19 acceptance tests — Celery beat task for the AI-industry news radar.

Contract for rpim_workers.tasks.refresh_ai_news:
  - registered as "rpim_workers.refresh_ai_news"
  - reads CORE_API_URL at call time (RuntimeError naming the var if unset)
  - POSTs to {CORE_API_URL}/admin/ai-news/refresh with X-Internal-Token
    through the module _post seam
  - beat entry "refresh-ai-news" with a slow cadence (>= 1h — public
    industry feeds, not a hot queue)

All tests named test_m19_<criterion>.
"""

from __future__ import annotations

import os
import secrets as _secrets

import pytest

os.environ.setdefault("INTERNAL_TOKEN", _secrets.token_hex(32))
os.environ.setdefault("CORE_API_URL", "http://core-api.test:8000")

import rpim_workers.tasks as _tasks  # noqa: E402


def test_m19_task_registered():
    assert "rpim_workers.refresh_ai_news" in _tasks.celery_app.tasks


def test_m19_task_pokes_internal_endpoint(monkeypatch):
    captured: dict = {}

    def fake_post(url: str, headers: dict) -> dict:
        captured.update(url=url, headers=headers)
        return {"upserted": 2}

    monkeypatch.setattr(_tasks, "_post", fake_post)
    result = _tasks.refresh_ai_news.apply().get()
    assert captured["url"].endswith("/admin/ai-news/refresh"), captured
    assert captured["headers"]["X-Internal-Token"] == os.environ["INTERNAL_TOKEN"]
    assert result == {"upserted": 2}


def test_m19_task_missing_core_url_names_the_var(monkeypatch):
    monkeypatch.delenv("CORE_API_URL", raising=False)
    with pytest.raises(RuntimeError) as excinfo:
        _tasks.refresh_ai_news.apply().get()
    assert "CORE_API_URL" in str(excinfo.value)


def test_m19_beat_schedule_slow_cadence():
    entry = _tasks.celery_app.conf.beat_schedule.get("refresh-ai-news")
    assert entry is not None, "beat entry refresh-ai-news missing"
    assert entry["task"] == "rpim_workers.refresh_ai_news"
    assert entry["schedule"] >= 3600.0, (
        f"industry feeds need a slow cadence, got {entry['schedule']}"
    )

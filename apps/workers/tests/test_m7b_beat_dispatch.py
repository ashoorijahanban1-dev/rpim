"""
M7B acceptance tests — Celery beat dispatch task for the publish queue.

Contract for rpim_workers.tasks.dispatch_publish_queue.

The task must:
  - be registered in the celery app as "rpim_workers.dispatch_publish_queue"
  - read CORE_API_URL from env at call time (raises RuntimeError if unset)
  - POST to {CORE_API_URL}/publish/dispatch with X-Internal-Token from INTERNAL_TOKEN
  - route the HTTP call through a module-level seam: _post(url, headers) -> dict
  - return whatever dict the seam returns
  - be scheduled in celery beat as "dispatch-publish-queue" with interval <= 60s

Module-level import of rpim_workers.tasks is intentional:
  - it causes ModuleNotFoundError (collection error) until the tasks module is
    implemented — the expected failure mode during development.
  - once the module exists, _post is accessible as a module-level attribute for
    test-state control and seam monkeypatching.
  - importing also registers the beat schedule entry on celery_app.

No literal secrets — INTERNAL_TOKEN generated per run via secrets.token_hex
(CLAUDE.md rule 4).

All tests named test_m7b_<criterion>.
"""

from __future__ import annotations

import os
import secrets as _secrets

# Set env vars before any import of rpim_workers (pattern from existing tests).
# INTERNAL_TOKEN generated per run — no literal in repo.
os.environ.setdefault("INTERNAL_TOKEN", _secrets.token_hex(32))
# CORE_API_URL default for tests that don't override it.
os.environ.setdefault("CORE_API_URL", "http://core-api.test:8000")

import pytest  # noqa: E402

import rpim_workers.tasks as _tasks  # noqa: E402
from rpim_workers.celery_app import celery_app  # noqa: E402

# ---------------------------------------------------------------------------
# This import will raise ModuleNotFoundError until rpim_workers.tasks is
# implemented — the expected collection error for M7B pre-implementation.
# Importing the module also auto-registers the beat schedule on celery_app.
# ---------------------------------------------------------------------------
from rpim_workers.tasks import dispatch_publish_queue  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VALID_TOKEN: str = os.environ["INTERNAL_TOKEN"]


# ===========================================================================
# 1. Task registration in celery app
# ===========================================================================


def test_m7b_dispatch_task_is_registered():
    """'rpim_workers.dispatch_publish_queue' must appear in celery_app.tasks.

    Celery discovers tasks when their defining module is imported; importing
    rpim_workers.tasks at collection time ensures registration happens before
    any test runs.
    """
    assert "rpim_workers.dispatch_publish_queue" in celery_app.tasks, (
        f"task 'rpim_workers.dispatch_publish_queue' not registered; "
        f"found tasks: {sorted(celery_app.tasks.keys())}"
    )


# ===========================================================================
# 2. _post seam called with correct URL and X-Internal-Token header
# ===========================================================================


def test_m7b_dispatch_posts_via_post_seam_with_internal_token(monkeypatch):
    """dispatch_publish_queue() must call _post with:
      url  == f"{CORE_API_URL}/publish/dispatch"
      headers == {"X-Internal-Token": <value of INTERNAL_TOKEN env>}

    Both values are read from env at call time (not at import time).
    No literal secrets — token generated per test run.
    """
    core_url = "http://core-api.test:9000"
    token = _secrets.token_hex(16)
    monkeypatch.setenv("CORE_API_URL", core_url)
    monkeypatch.setenv("INTERNAL_TOKEN", token)

    captured: dict = {}

    def fake_post(url: str, headers: dict) -> dict:
        captured["url"] = url
        captured["headers"] = dict(headers)
        return {"sent": 0, "blocked": 0, "failed": 0}

    monkeypatch.setattr(_tasks, "_post", fake_post)

    dispatch_publish_queue()

    expected_url = f"{core_url}/publish/dispatch"
    assert captured.get("url") == expected_url, (
        f"_post must be called with url={expected_url!r}, "
        f"got {captured.get('url')!r}"
    )
    assert captured.get("headers", {}).get("X-Internal-Token") == token, (
        f"_post must receive X-Internal-Token == INTERNAL_TOKEN env value; "
        f"got headers: {captured.get('headers')!r} "
        f"(env var name: INTERNAL_TOKEN)"
    )


# ===========================================================================
# 3. dispatch_publish_queue returns the dict the seam returns
# ===========================================================================


def test_m7b_dispatch_returns_seam_dict(monkeypatch):
    """dispatch_publish_queue() must return whatever dict _post returns.

    The caller (Celery beat) inspects the return value for metrics; the task
    must not swallow or transform the response.
    """
    monkeypatch.setenv("CORE_API_URL", "http://core-api.test:8000")
    monkeypatch.setenv("INTERNAL_TOKEN", _secrets.token_hex(16))

    expected = {"sent": 3, "blocked": 1, "failed": 0}

    def fake_post(url: str, headers: dict) -> dict:
        return expected

    monkeypatch.setattr(_tasks, "_post", fake_post)

    result = dispatch_publish_queue()
    assert result == expected, (
        f"dispatch_publish_queue must return the dict from _post, "
        f"expected {expected!r}, got {result!r}"
    )


# ===========================================================================
# 4. Beat schedule entry exists with correct task name
# ===========================================================================


def test_m7b_beat_schedule_entry_named_correctly():
    """celery_app.conf.beat_schedule must contain 'dispatch-publish-queue'
    with task='rpim_workers.dispatch_publish_queue'.

    Importing rpim_workers.tasks at module level registers the beat schedule.
    """
    sched = getattr(celery_app.conf, "beat_schedule", {})
    assert "dispatch-publish-queue" in sched, (
        f"beat_schedule must contain entry 'dispatch-publish-queue'; "
        f"found keys: {list(sched.keys())}"
    )
    entry = sched["dispatch-publish-queue"]
    assert entry.get("task") == "rpim_workers.dispatch_publish_queue", (
        f"beat entry 'dispatch-publish-queue' must have "
        f"task='rpim_workers.dispatch_publish_queue', got: {entry.get('task')!r}"
    )


# ===========================================================================
# 5. Beat schedule interval <= 60 seconds (kill switch semantics)
# ===========================================================================


def test_m7b_beat_schedule_interval_at_most_60s():
    """Beat schedule interval for 'dispatch-publish-queue' must be <= 60.0 s.

    Constitution rule 7: kill switch stops all publish queues in <5s. Frequent
    dispatch passes (at most every 60s) ensure queued jobs are checked and
    halted quickly when the silence flag or kill switch is active.
    """
    sched = getattr(celery_app.conf, "beat_schedule", {})
    assert "dispatch-publish-queue" in sched, (
        "beat_schedule entry 'dispatch-publish-queue' must exist (see test 4)"
    )
    schedule = sched["dispatch-publish-queue"].get("schedule")

    if hasattr(schedule, "total_seconds"):
        # datetime.timedelta
        interval = schedule.total_seconds()
    elif isinstance(schedule, (int, float)):
        interval = float(schedule)
    else:
        # crontab or unknown type — cannot assert numerically
        pytest.fail(
            f"beat schedule for 'dispatch-publish-queue' must use a numeric "
            f"interval (int/float/timedelta), got type {type(schedule).__name__!r}"
        )

    assert interval <= 60.0, (
        f"beat schedule interval must be <= 60.0s (kill switch semantics), "
        f"got {interval}s"
    )


# ===========================================================================
# 6. CORE_API_URL unset → RuntimeError naming the env var
# ===========================================================================


def test_m7b_dispatch_core_api_url_unset_raises_runtime_error(monkeypatch):
    """CORE_API_URL unset → dispatch_publish_queue raises RuntimeError with
    'CORE_API_URL' in the message (var name only, never a URL value).

    Constitution rule 4: error messages must name the ENV VAR, not the value,
    so operators know what to set without exposing internal topology.
    """
    monkeypatch.delenv("CORE_API_URL", raising=False)

    with pytest.raises(RuntimeError) as exc_info:
        dispatch_publish_queue()

    err_str = str(exc_info.value)
    assert "CORE_API_URL" in err_str, (
        f"RuntimeError message must name env var 'CORE_API_URL', got: {err_str!r}"
    )

"""Publish-queue beat task.

This task only pokes core-api's internal dispatch endpoint on a short
interval. The halt check (silence flag / kill switch) lives INSIDE the
core-api send path (rule 2) — so a hijacked or misbehaving beat can never
bypass governance; the worst it can do is call dispatch more often.
"""

import os

import httpx

from rpim_workers.celery_app import celery_app


def _post(url: str, headers: dict) -> dict:
    response = httpx.post(url, headers=headers, timeout=55)
    response.raise_for_status()
    return response.json()


@celery_app.task(name="rpim_workers.dispatch_publish_queue")
def dispatch_publish_queue() -> dict:
    core_url = os.environ.get("CORE_API_URL", "")
    if not core_url:
        # Name the env var, never a value (rule 4).
        raise RuntimeError("env var CORE_API_URL is not set")
    headers = {"X-Internal-Token": os.environ.get("INTERNAL_TOKEN", "")}
    return _post(f"{core_url.rstrip('/')}/publish/dispatch", headers)


# <=60s so a raised silence/kill flag stops queued jobs within one pass
# (the <5s guarantee itself is the in-path check, not this cadence).
celery_app.conf.beat_schedule = {
    **(getattr(celery_app.conf, "beat_schedule", None) or {}),
    "dispatch-publish-queue": {
        "task": "rpim_workers.dispatch_publish_queue",
        "schedule": 30.0,
    },
}


@celery_app.task(name="rpim_workers.sync_crm_leads")
def sync_crm_leads() -> dict:
    """Pokes core-api's internal CRM lead sync (M13). Idempotency lives
    INSIDE core-api (watermark rows) — a misbehaving beat can only sync
    more often, never double-deliver a lead."""
    core_url = os.environ.get("CORE_API_URL", "")
    if not core_url:
        # Name the env var, never a value (rule 4).
        raise RuntimeError("env var CORE_API_URL is not set")
    headers = {"X-Internal-Token": os.environ.get("INTERNAL_TOKEN", "")}
    return _post(f"{core_url.rstrip('/')}/crm/sync", headers)


celery_app.conf.beat_schedule = {
    **(getattr(celery_app.conf, "beat_schedule", None) or {}),
    "sync-crm-leads": {
        "task": "rpim_workers.sync_crm_leads",
        "schedule": 300.0,
    },
}

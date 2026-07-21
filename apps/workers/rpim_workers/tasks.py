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


@celery_app.task(name="rpim_workers.refresh_trends")
def refresh_trends() -> dict:
    """Pokes core-api's internal trend refresh (M14). Upsert semantics live
    INSIDE core-api — a misbehaving beat can only refresh more often."""
    core_url = os.environ.get("CORE_API_URL", "")
    if not core_url:
        # Name the env var, never a value (rule 4).
        raise RuntimeError("env var CORE_API_URL is not set")
    headers = {"X-Internal-Token": os.environ.get("INTERNAL_TOKEN", "")}
    return _post(f"{core_url.rstrip('/')}/trends/refresh", headers)


celery_app.conf.beat_schedule = {
    **(getattr(celery_app.conf, "beat_schedule", None) or {}),
    "refresh-trends": {
        "task": "rpim_workers.refresh_trends",
        "schedule": 3600.0,
    },
}


@celery_app.task(name="rpim_workers.refresh_ai_news")
def refresh_ai_news() -> dict:
    """Pokes core-api's internal AI-news refresh (M19). Upsert-by-url lives
    INSIDE core-api — a misbehaving beat can only poll more often."""
    core_url = os.environ.get("CORE_API_URL", "")
    if not core_url:
        # Name the env var, never a value (rule 4).
        raise RuntimeError("env var CORE_API_URL is not set")
    headers = {"X-Internal-Token": os.environ.get("INTERNAL_TOKEN", "")}
    return _post(f"{core_url.rstrip('/')}/admin/ai-news/refresh", headers)


# Public industry feeds change slowly — every 6h is plenty.
celery_app.conf.beat_schedule = {
    **(getattr(celery_app.conf, "beat_schedule", None) or {}),
    "refresh-ai-news": {
        "task": "rpim_workers.refresh_ai_news",
        "schedule": 21600.0,
    },
}


@celery_app.task(name="rpim_workers.snapshot_metrics")
def snapshot_metrics() -> dict:
    """Pokes core-api's internal metrics snapshot (M22). Upsert semantics
    live INSIDE core-api — a misbehaving beat can only snapshot more often."""
    core_url = os.environ.get("CORE_API_URL", "")
    if not core_url:
        # Name the env var, never a value (rule 4).
        raise RuntimeError("env var CORE_API_URL is not set")
    headers = {"X-Internal-Token": os.environ.get("INTERNAL_TOKEN", "")}
    return _post(f"{core_url.rstrip('/')}/metrics/snapshot", headers)


celery_app.conf.beat_schedule = {
    **(getattr(celery_app.conf, "beat_schedule", None) or {}),
    "snapshot-metrics": {
        "task": "rpim_workers.snapshot_metrics",
        "schedule": 21600.0,
    },
}


@celery_app.task(name="rpim_workers.ingest_analytics")
def ingest_analytics() -> dict:
    """Pokes core-api's cursor-based analytics ingestion (M22 slice B).
    Cursors + upserts live INSIDE core-api — a misbehaving beat can only
    poke more often, never double-ingest."""
    core_url = os.environ.get("CORE_API_URL", "")
    if not core_url:
        # Name the env var, never a value (rule 4).
        raise RuntimeError("env var CORE_API_URL is not set")
    headers = {"X-Internal-Token": os.environ.get("INTERNAL_TOKEN", "")}
    return _post(f"{core_url.rstrip('/')}/metrics/ingest", headers)


celery_app.conf.beat_schedule = {
    **(getattr(celery_app.conf, "beat_schedule", None) or {}),
    "ingest-analytics": {
        "task": "rpim_workers.ingest_analytics",
        "schedule": 21600.0,
    },
}


@celery_app.task(name="rpim_workers.distill_learnings")
def distill_learnings() -> dict:
    """Pokes core-api's deterministic learning distiller (M22 slice C).
    Hash-gated versioning lives INSIDE core-api — a misbehaving beat can
    only distill more often, never append a duplicate version."""
    core_url = os.environ.get("CORE_API_URL", "")
    if not core_url:
        # Name the env var, never a value (rule 4).
        raise RuntimeError("env var CORE_API_URL is not set")
    headers = {"X-Internal-Token": os.environ.get("INTERNAL_TOKEN", "")}
    return _post(f"{core_url.rstrip('/')}/learnings/distill", headers)


# Learnings move on human-feedback timescales — once a day is the design.
celery_app.conf.beat_schedule = {
    **(getattr(celery_app.conf, "beat_schedule", None) or {}),
    "distill-learnings": {
        "task": "rpim_workers.distill_learnings",
        "schedule": 86400.0,
    },
}


@celery_app.task(name="rpim_workers.agent_scan")
def agent_scan() -> dict:
    """Pokes core-api's watchdog scan (M23). Autonomy gates, halt checks,
    caps and dedupe all live INSIDE core-api — a misbehaving beat can only
    scan more often, never over-propose (rule 8)."""
    core_url = os.environ.get("CORE_API_URL", "")
    if not core_url:
        # Name the env var, never a value (rule 4).
        raise RuntimeError("env var CORE_API_URL is not set")
    headers = {"X-Internal-Token": os.environ.get("INTERNAL_TOKEN", "")}
    return _post(f"{core_url.rstrip('/')}/agent/scan", headers)


celery_app.conf.beat_schedule = {
    **(getattr(celery_app.conf, "beat_schedule", None) or {}),
    "agent-scan": {
        "task": "rpim_workers.agent_scan",
        "schedule": 1800.0,
    },
}

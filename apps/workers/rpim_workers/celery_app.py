import os

from celery import Celery

# Broker URL comes from the environment; cross-leg jobs must be idempotent and
# resumable (CLAUDE.md). include= makes the worker/beat import task modules
# (and their beat_schedule registration) at startup.
celery_app = Celery(
    "rpim",
    broker=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
    include=["rpim_workers.tasks"],
)
celery_app.conf.task_default_queue = "rpim"
celery_app.conf.broker_connection_retry_on_startup = True


@celery_app.task(name="rpim.ping")
def ping() -> str:
    return "pong"

# App timezone for any wall-clock beat entries (ADR 0032, env-reversible).
celery_app.conf.timezone = os.environ.get("RPIM_TIMEZONE", "America/Los_Angeles")

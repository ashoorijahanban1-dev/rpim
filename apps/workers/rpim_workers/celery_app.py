import os

from celery import Celery

# Broker URL comes from the environment; cross-leg jobs must be idempotent and
# resumable (CLAUDE.md) — real task definitions land in M2+.
celery_app = Celery(
    "rpim",
    broker=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
)
celery_app.conf.task_default_queue = "rpim"
celery_app.conf.broker_connection_retry_on_startup = True


@celery_app.task(name="rpim.ping")
def ping() -> str:
    return "pong"

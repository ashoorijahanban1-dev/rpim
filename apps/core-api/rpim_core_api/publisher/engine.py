"""Dispatch engine for queued publish jobs.

The silence/kill check runs INSIDE the send loop for every single job
(constitution rule 2) — a flag raised after a job was queued still stops it
right here, not only at scheduling time.

Delivery is at-least-once with a per-job commit directly after each send, so
a crash or tunnel drop mid-run loses nothing and re-sends nothing already
committed; the only double-send window is a crash between the channel call
and its commit (see docs/decisions/ ADR for M7).
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from rpim_core_api.models import PublishJob, Tenant
from rpim_core_api.publisher import channels
from rpim_core_api.qa.governance import is_publishing_halted


def _as_utc(dt: datetime) -> datetime:
    # SQLite returns naive datetimes even for timezone=True columns.
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def dispatch_due_jobs(session: Session) -> dict:
    now = datetime.now(UTC)
    # Fan-out over the tenant REGISTRY (not tenant data), then run every
    # publish_jobs query tenant-scoped (rule 6) — the engine serves all
    # tenants but never touches the jobs table without a tenant_id filter.
    tenant_ids = session.scalars(select(Tenant.id)).all()

    sent = blocked = failed = 0
    for tenant_id in tenant_ids:
        jobs = session.scalars(
            select(PublishJob)
            .where(
                PublishJob.tenant_id == tenant_id,  # rule 6
                PublishJob.status == "queued",
            )
            .order_by(PublishJob.created_at)
        ).all()
        for job in jobs:
            if job.scheduled_at is not None and _as_utc(job.scheduled_at) > now:
                continue
            # Rule 2: halt check per job, inside the send path — queued jobs
            # stop too, and a flag raised mid-run halts the rest of the batch.
            if is_publishing_halted(session, tenant_id):
                blocked += 1
                continue
            job.attempts += 1
            try:
                channels.send(job.channel, job.chat_id, job.text, job.id)
            except channels.ChannelSendError as exc:
                job.last_error = str(exc)[:500]
                # Status stays 'queued': the job is never lost, only retried.
                session.commit()
                failed += 1
                continue
            job.status = "sent"
            job.sent_at = datetime.now(UTC)
            job.last_error = None
            session.commit()
            sent += 1
    return {"sent": sent, "blocked": blocked, "failed": failed}

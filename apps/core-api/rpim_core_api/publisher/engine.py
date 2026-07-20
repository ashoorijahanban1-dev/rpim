"""Dispatch engine for queued publish jobs.

The silence/kill check runs INSIDE the send loop for every single job
(constitution rule 2) — a flag raised after a job was queued still stops it
right here, not only at scheduling time.

Delivery is at-least-once with a per-job commit directly after each send, so
a crash or tunnel drop mid-run loses nothing and re-sends nothing already
committed; the only double-send window is a crash between the channel call
and its commit (see docs/decisions/ ADR for M7).

M21 adds the TIME-based dead-letter: the first ChannelSendError stamps
first_failed_at (app-TZ clock), success clears it, and only after
MAX_PUBLISH_RETRY_HOURS (default 24 — "assume the tunnel WILL drop") does a
job move to 'stalled' and leave the loop; the operator requeues it from the
dashboard. Silence/kill-blocked passes never touch the clock.
"""

import os
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from rpim_core_api.media import service as media_service
from rpim_core_api.models import MediaAsset, PublishJob, Tenant
from rpim_core_api.publisher import channels, renderer_client, tenant_creds
from rpim_core_api.qa.governance import is_publishing_halted
from rpim_shared.tz import app_timezone, now_app


def _as_utc(dt: datetime) -> datetime:
    # SQLite returns naive datetimes even for timezone=True columns.
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _as_app(dt: datetime) -> datetime:
    # first_failed_at is written with now_app(); sqlite strips the tz —
    # reattach the LEVER's zone (ADR 0032), never a hardcoded one.
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=app_timezone())


def _retry_window_hours() -> float:
    return float(os.environ.get("MAX_PUBLISH_RETRY_HOURS", "24"))


def _load_job_asset(session: Session, job: PublishJob) -> MediaAsset:
    """Tenant-scoped asset load + status re-verify — defense in depth for
    rules 1 and 6 (the compile gate already enforced both)."""
    asset_id = (job.image_spec or {}).get("media_asset_id", "")
    asset = session.scalar(
        select(MediaAsset).where(
            MediaAsset.tenant_id == job.tenant_id,  # rule 6
            MediaAsset.id == asset_id,
        )
    )
    if asset is None or asset.status not in ("approved", "attached"):
        raise channels.ChannelSendError("media asset unavailable or not approved")
    return asset


def _send_wordpress_photo(
    session: Session,
    job: PublishJob,
    asset: MediaAsset,
    image_png: bytes,
    creds: dict | None,
) -> None:
    """The two-stage WP flow (M21). Stage-1 receipt commits BEFORE stage 2 so
    a crash between stages resumes at stage 2 — no orphan media (rule 8)."""
    if asset.wp_media_id is None:
        wp_media_id = channels.wordpress_upload_media(
            image_png, asset.alt_text, job.id, creds=creds
        )
        asset.wp_media_id = wp_media_id
        session.commit()  # the receipt survives any stage-2 crash
    channels.wordpress_attach_post(job.text, asset.wp_media_id, job.id, creds=creds)


def dispatch_due_jobs(session: Session) -> dict:
    now = now_app()
    # Fan-out over the tenant REGISTRY (not tenant data), then run every
    # publish_jobs query tenant-scoped (rule 6) — the engine serves all
    # tenants but never touches the jobs table without a tenant_id filter.
    tenant_ids = session.scalars(select(Tenant.id)).all()

    sent = blocked = failed = stalled = 0
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
            # Blocked passes never touch the dead-letter clock: governance is
            # not failure.
            if is_publishing_halted(session, tenant_id):
                blocked += 1
                continue
            # M21 dead-letter: a job failing for longer than the retry window
            # leaves the loop instead of retrying forever.
            if job.first_failed_at is not None:
                age_hours = (now - _as_app(job.first_failed_at)).total_seconds() / 3600
                if age_hours > _retry_window_hours():
                    job.status = "stalled"
                    session.commit()
                    stalled += 1
                    continue
            job.attempts += 1
            try:
                # M16b: a connected brand publishes through ITS credential;
                # unresolvable tenant creds raise inside the try, so the job
                # stays queued exactly like any transient send failure.
                creds = tenant_creds.resolve(session, tenant_id, job.channel)
                spec = job.image_spec or {}
                if spec.get("kind") == "generated":
                    asset = _load_job_asset(session, job)
                    image_png = media_service.load_bytes(asset)
                    if job.channel == "wordpress":
                        _send_wordpress_photo(session, job, asset, image_png, creds)
                    else:
                        channels.send_photo(
                            job.channel, job.chat_id, job.text, image_png, job.id, creds=creds
                        )
                elif job.image_spec:
                    # Render AFTER the halt check — silenced tenants get no
                    # renders either; a failed render is transient like a
                    # failed send (job stays queued).
                    image_png = renderer_client.render_for_job(job)
                    if job.channel == "wordpress":
                        # Rendered outputs get an asset row too, so the WP
                        # receipt flow covers them identically (rule 8).
                        asset = media_service.get_or_create_rendered(
                            session, tenant_id, image_png, job.text
                        )
                        _send_wordpress_photo(session, job, asset, image_png, creds)
                    else:
                        channels.send_photo(
                            job.channel, job.chat_id, job.text, image_png, job.id, creds=creds
                        )
                else:
                    channels.send(job.channel, job.chat_id, job.text, job.id, creds=creds)
            except (channels.ChannelSendError, media_service.MediaGenerationError) as exc:
                job.last_error = str(exc)[:500]
                if job.first_failed_at is None:
                    job.first_failed_at = now_app()  # the dead-letter clock starts
                # Status stays 'queued': the job is never lost, only retried.
                session.commit()
                failed += 1
                continue
            job.status = "sent"
            job.sent_at = now_app()
            job.last_error = None
            job.first_failed_at = None  # success wipes the clock
            session.commit()
            sent += 1
    return {"sent": sent, "blocked": blocked, "failed": failed, "stalled": stalled}

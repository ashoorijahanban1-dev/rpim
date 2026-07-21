"""Metrics snapshot (M22 slice A) — internal, beat-driven, tenant-keyed."""

import os

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from rpim_core_api.db import get_session
from rpim_core_api.measurement import attribution
from rpim_core_api.models import CampaignChannelMetric, PublishJob, Tenant
from rpim_shared.tz import now_app

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.post("/snapshot")
def snapshot_metrics(
    x_internal_token: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> dict:
    # Internal trust boundary — beat-driven like /publish/dispatch (rule 2's
    # engine pattern: fan out over the registry, every write tenant-scoped).
    expected = os.environ.get("INTERNAL_TOKEN", "")
    if not expected or x_internal_token != expected:
        raise HTTPException(status_code=403, detail="invalid internal token")

    day = now_app().strftime("%Y-%m-%d")  # app-TZ lever (ADR 0032)
    tenant_ids = session.scalars(select(Tenant.id)).all()
    rows = 0
    skipped = 0
    for tenant_id in tenant_ids:
        try:
            clicks_by_campaign = attribution.fetch_tenant_clicks(
                attribution.tenant_key(tenant_id), day
            )
        except Exception:  # noqa: BLE001 — a dead source must not crash-loop
            # the beat (rule 8); count it and move on to the next tenant.
            skipped += 1
            continue
        for campaign_code, clicks in clicks_by_campaign.items():
            posts_sent = session.scalar(
                select(func.count())
                .select_from(PublishJob)
                .where(
                    PublishJob.tenant_id == tenant_id,  # rule 6
                    PublishJob.campaign_code == campaign_code,
                    PublishJob.status == "sent",
                )
            )
            row = session.scalar(
                select(CampaignChannelMetric).where(
                    CampaignChannelMetric.tenant_id == tenant_id,  # rule 6
                    CampaignChannelMetric.campaign_code == campaign_code,
                    CampaignChannelMetric.channel == "web",
                    CampaignChannelMetric.source == "umami",
                    CampaignChannelMetric.day == day,
                )
            )
            if row is None:
                row = CampaignChannelMetric(
                    tenant_id=tenant_id,
                    campaign_code=campaign_code,
                    channel="web",
                    source="umami",
                    day=day,
                )
                session.add(row)
            row.clicks = int(clicks)
            row.posts_sent = int(posts_sent or 0)
            row.captured_at = now_app()
            rows += 1
    session.commit()
    return {"tenants": len(tenant_ids), "rows": rows, "skipped": skipped}


def _next_day(day: str) -> str:
    from datetime import datetime, timedelta  # noqa: PLC0415

    return (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")


@router.post("/ingest")
def ingest_analytics(
    x_internal_token: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> dict:
    """Pull-with-cursor analytics ingestion (M22 slice B, ADR 0042).

    Per connected tenant: walk days from cursor+1 up to YESTERDAY on the
    app clock (PT lever); commit per day and advance the cursor ONLY after
    the day fully lands — a crash or malformed payload resumes exactly at
    the failed day (rule 8). Response carries COUNTS only (no PII)."""
    expected = os.environ.get("INTERNAL_TOKEN", "")
    if not expected or x_internal_token != expected:
        raise HTTPException(status_code=403, detail="invalid internal token")

    from datetime import timedelta  # noqa: PLC0415

    from rpim_core_api.measurement import analytics_providers  # noqa: PLC0415
    from rpim_core_api.models import AnalyticsCursor, ChannelConnection  # noqa: PLC0415

    yesterday = (now_app() - timedelta(days=1)).strftime("%Y-%m-%d")
    backfill = max(1, int(os.environ.get("INGEST_BACKFILL_DAYS", "7")))
    first_start = (now_app() - timedelta(days=backfill)).strftime("%Y-%m-%d")

    connections = session.scalars(
        select(ChannelConnection).where(ChannelConnection.channel == "ga4")
    ).all()
    tenants_total = len(session.scalars(select(Tenant.id)).all())
    connected = days_done = rows = failed = 0

    for conn in connections:
        property_id = str((conn.config or {}).get("property_id", "")).strip()
        if not property_id:
            continue
        connected += 1
        tenant_id = conn.tenant_id
        cursor_row = session.scalar(
            select(AnalyticsCursor).where(
                AnalyticsCursor.tenant_id == tenant_id,  # rule 6
                AnalyticsCursor.provider == "ga4",
            )
        )
        day = _next_day(cursor_row.cursor) if cursor_row else first_start
        while day <= yesterday:
            try:
                day_rows = analytics_providers.ANALYTICS_PROVIDERS["ga4"](
                    property_id, day
                )
            except analytics_providers.AnalyticsProviderError:
                # Stop THIS tenant at its cursor; others continue and the
                # beat never crash-loops (rule 8). Counts only — no values.
                failed += 1
                break
            for entry in day_rows:
                posts_sent = session.scalar(
                    select(func.count())
                    .select_from(PublishJob)
                    .where(
                        PublishJob.tenant_id == tenant_id,  # rule 6
                        PublishJob.campaign_code == entry["campaign"],
                        PublishJob.status == "sent",
                    )
                )
                row = session.scalar(
                    select(CampaignChannelMetric).where(
                        CampaignChannelMetric.tenant_id == tenant_id,  # rule 6
                        CampaignChannelMetric.campaign_code == entry["campaign"],
                        CampaignChannelMetric.channel == "web",
                        CampaignChannelMetric.source == "ga4",
                        CampaignChannelMetric.day == day,
                    )
                )
                if row is None:
                    row = CampaignChannelMetric(
                        tenant_id=tenant_id,
                        campaign_code=entry["campaign"],
                        channel="web",
                        source="ga4",
                        day=day,
                    )
                    session.add(row)
                row.clicks = int(entry["clicks"])
                row.sessions = int(entry["sessions"])
                row.posts_sent = int(posts_sent or 0)
                row.captured_at = now_app()
                rows += 1
            if cursor_row is None:
                cursor_row = AnalyticsCursor(
                    tenant_id=tenant_id, provider="ga4", cursor=day
                )
                session.add(cursor_row)
            else:
                cursor_row.cursor = day
            session.commit()  # per-day commit = the exact-resume point
            days_done += 1
            day = _next_day(day)

    return {
        "tenants": tenants_total,
        "connected": connected,
        "days": days_done,
        "rows": rows,
        "failed": failed,
    }

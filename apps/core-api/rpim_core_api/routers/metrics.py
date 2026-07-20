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

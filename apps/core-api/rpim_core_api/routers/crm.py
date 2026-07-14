"""CRM lead sync (M13) — internal ops surface, beat-driven like /publish/dispatch."""

import os
from collections import defaultdict
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from rpim_core_api.crm import bridge
from rpim_core_api.db import get_session
from rpim_core_api.measurement import clicks as clicks_client
from rpim_core_api.models import CrmLeadSync, PublishJob, Tenant

router = APIRouter(prefix="/crm", tags=["crm"])


@router.post("/sync")
def sync_leads(
    x_internal_token: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> dict:
    # Internal trust boundary — same as /publish/dispatch: the beat scheduler
    # pokes this; a hijacked beat can only sync more often, never leak across
    # tenants (every event is derived from tenant-scoped job rows).
    expected = os.environ.get("INTERNAL_TOKEN", "")
    if not expected or x_internal_token != expected:
        raise HTTPException(status_code=403, detail="invalid internal token")

    month = datetime.now(UTC).strftime("%Y-%m")
    # Engine pattern: enumerate tenants, then per-tenant SCOPED queries —
    # the jobs table is never touched without a tenant_id filter (rule 6).
    tenant_ids = session.scalars(select(Tenant.id)).all()
    campaigns_by_tenant: dict[str, set[str]] = defaultdict(set)
    for tenant_id in tenant_ids:
        tenant_jobs = session.scalars(
            select(PublishJob).where(PublishJob.tenant_id == tenant_id)  # rule 6
        ).all()
        for job in tenant_jobs:
            if job.created_at is not None and job.created_at.strftime("%Y-%m") == month:
                campaigns_by_tenant[tenant_id].add(job.campaign_code)

    click_counts = clicks_client.fetch_clicks_by_campaign(month)
    events = 0
    for tenant_id, campaign_codes in campaigns_by_tenant.items():
        for code in sorted(campaign_codes):
            total = int(click_counts.get(code, 0))
            row = session.scalar(
                select(CrmLeadSync).where(
                    CrmLeadSync.tenant_id == tenant_id,  # rule 6
                    CrmLeadSync.campaign_code == code,
                    CrmLeadSync.month == month,
                )
            )
            already = row.last_count if row else 0
            delta = total - already
            if delta <= 0:
                continue
            # Deliver BEFORE advancing the watermark: a crash between the two
            # re-sends the same delta next pass (at-least-once), never drops
            # a lead — the cheap failure mode for the tenant (rule 8).
            bridge.deliver(
                {
                    "tenant_id": tenant_id,
                    "campaign_code": code,
                    "month": month,
                    "clicks_new": delta,
                    "clicks_total": total,
                    "source": "rpim-utm",
                }
            )
            if row is None:
                row = CrmLeadSync(tenant_id=tenant_id, campaign_code=code, month=month)
                session.add(row)
            row.last_count = total
            events += 1
    session.commit()
    return {"month": month, "events": events, "tenants": len(campaigns_by_tenant)}

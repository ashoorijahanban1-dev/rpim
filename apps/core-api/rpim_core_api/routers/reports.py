from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from rpim_core_api.db import get_session
from rpim_core_api.deps import Identity, get_identity
from rpim_core_api.measurement import ledger_client
from rpim_core_api.models import ContentDraft, PublishJob

router = APIRouter(prefix="/reports", tags=["reports"])

_MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"


def _in_month(stamp: datetime | None, month: str) -> bool:
    return stamp is not None and stamp.strftime("%Y-%m") == month


@router.get("/monthly")
def monthly_report(
    month: str = Query(pattern=_MONTH_PATTERN),
    identity: Identity = Depends(get_identity),
    session: Session = Depends(get_session),
) -> dict:
    # MVP scale: month slices are small enough to aggregate in-process, which
    # also sidesteps naive-vs-aware datetime comparisons across dialects.
    drafts = session.scalars(
        select(ContentDraft).where(ContentDraft.tenant_id == identity.tenant_id)  # rule 6
    ).all()
    month_drafts = [d for d in drafts if _in_month(d.created_at, month)]

    jobs = session.scalars(
        select(PublishJob).where(PublishJob.tenant_id == identity.tenant_id)  # rule 6
    ).all()
    month_jobs = [j for j in jobs if _in_month(j.created_at, month)]

    by_channel: dict[str, int] = defaultdict(int)
    campaigns: dict[str, dict] = {}
    for job in month_jobs:
        camp = campaigns.setdefault(
            job.campaign_code, {"campaign_code": job.campaign_code, "jobs": 0, "sent": 0}
        )
        camp["jobs"] += 1
        if job.status == "sent":
            camp["sent"] += 1
            by_channel[job.channel] += 1

    entries = ledger_client.fetch_entries(identity.tenant_id)
    by_provider: dict[str, float] = defaultdict(float)
    for entry in entries:
        by_provider[str(entry.get("provider", "unknown"))] += float(entry.get("cost_usd", 0.0))
    total_usd = round(sum(by_provider.values()), 6)

    return {
        "month": month,
        "drafts": {
            "created": len(month_drafts),
            "approved": sum(1 for d in month_drafts if d.status == "approved"),
            "edited": sum(1 for d in month_drafts if d.status == "edited"),
            "rejected": sum(1 for d in month_drafts if d.status == "rejected"),
        },
        "publish": {
            "queued": sum(1 for j in month_jobs if j.status == "queued"),
            "sent": sum(1 for j in month_jobs if j.status == "sent"),
            "by_channel": dict(by_channel),
        },
        "campaigns": sorted(campaigns.values(), key=lambda c: c["campaign_code"]),
        "costs": {
            "total_usd": total_usd,
            "by_provider": {k: round(v, 6) for k, v in by_provider.items()},
        },
    }

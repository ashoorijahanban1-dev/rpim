from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from rpim_core_api.db import get_session
from rpim_core_api.deps import Identity, get_identity
from rpim_core_api.measurement import clicks as clicks_client
from rpim_core_api.measurement import ledger_client
from rpim_core_api.models import ContentDraft, PublishJob
from rpim_shared.tz import month_key, now_app

router = APIRouter(prefix="/reports", tags=["reports"])

_MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"


def _in_month(stamp: datetime | None, month: str) -> bool:
    return month_key(stamp) == month


def _month_keys(until: str, months: int) -> list[str]:
    """The `months` month-keys ending at `until`, ascending (year-safe)."""
    year, mon = (int(part) for part in until.split("-"))
    keys: list[str] = []
    for _ in range(months):
        keys.append(f"{year:04d}-{mon:02d}")
        mon -= 1
        if mon == 0:
            year, mon = year - 1, 12
    return list(reversed(keys))


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

    # Clicks are keyed by utm_campaign; only THIS tenant's campaigns are
    # surfaced (rule 6) — foreign campaign codes in the counter never leak in.
    click_counts = clicks_client.fetch_clicks_by_campaign(month)
    for camp in campaigns.values():
        camp["clicks"] = int(click_counts.get(camp["campaign_code"], 0))
    clicks_by_campaign = {c["campaign_code"]: c["clicks"] for c in campaigns.values()}

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
        "clicks": {
            "total": sum(clicks_by_campaign.values()),
            "by_campaign": clicks_by_campaign,
        },
        "costs": {
            "total_usd": total_usd,
            "by_provider": {k: round(v, 6) for k, v in by_provider.items()},
        },
    }


@router.get("/trend")
def trend_report(
    months: int = Query(default=6, ge=1, le=12),
    until: str | None = Query(default=None, pattern=_MONTH_PATTERN),
    identity: Identity = Depends(get_identity),
    session: Session = Depends(get_session),
) -> dict:
    """Per-month funnel counts for the last `months` months, ascending.
    `until` pins the window end so a report is reproducible; default = now.
    Same rule-6 containment as /monthly: click counts only surface for
    campaign codes carried by THIS tenant's jobs in that month."""
    end = until or now_app().strftime("%Y-%m")

    drafts = session.scalars(
        select(ContentDraft).where(ContentDraft.tenant_id == identity.tenant_id)  # rule 6
    ).all()
    jobs = session.scalars(
        select(PublishJob).where(PublishJob.tenant_id == identity.tenant_id)  # rule 6
    ).all()

    buckets: list[dict] = []
    for key in _month_keys(end, months):
        month_drafts = [d for d in drafts if _in_month(d.created_at, key)]
        month_jobs = [j for j in jobs if _in_month(j.created_at, key)]
        tenant_campaigns = {j.campaign_code for j in month_jobs}
        click_counts = clicks_client.fetch_clicks_by_campaign(key)
        buckets.append(
            {
                "month": key,
                "drafts_created": len(month_drafts),
                "drafts_approved": sum(1 for d in month_drafts if d.status == "approved"),
                "sent": sum(1 for j in month_jobs if j.status == "sent"),
                "clicks": sum(
                    int(count)
                    for code, count in click_counts.items()
                    if code in tenant_campaigns
                ),
            }
        )
    return {"months": buckets}

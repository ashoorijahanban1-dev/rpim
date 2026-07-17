"""Trend Radar (M14) — internal refresh + tenant-facing radar list."""

import os

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from rpim_core_api.db import get_session
from rpim_core_api.deps import Identity, get_identity
from rpim_core_api.models import BrandProfile, Tenant, TrendItem
from rpim_core_api.trends import radar

router = APIRouter(prefix="/trends", tags=["trends"])


@router.post("/refresh")
def refresh_trends(
    x_internal_token: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> dict:
    # Internal trust boundary — beat-driven like /publish/dispatch, /crm/sync.
    expected = os.environ.get("INTERNAL_TOKEN", "")
    if not expected or x_internal_token != expected:
        raise HTTPException(status_code=403, detail="invalid internal token")

    # Engine pattern: enumerate tenants, per-tenant scoped writes (rule 6).
    tenant_ids = session.scalars(select(Tenant.id)).all()
    upserted = 0
    for tenant_id in tenant_ids:
        profile = session.scalar(
            select(BrandProfile).where(BrandProfile.tenant_id == tenant_id)  # rule 6
        )
        lexicon = list((profile.lexicon or {}).keys()) if profile else []
        try:
            batch = radar.fetch_trends(tenant_id, lexicon)
        except radar.TrendSourceError:
            # A dead source must not wipe the existing radar (rule 8).
            continue
        for entry in batch:
            source = str(entry.get("source", "simulated"))[:40]
            row = session.scalar(
                select(TrendItem).where(
                    TrendItem.tenant_id == tenant_id,  # rule 6
                    TrendItem.keyword == entry["keyword"],
                    TrendItem.source == source,
                )
            )
            if row is None:
                row = TrendItem(
                    tenant_id=tenant_id, keyword=entry["keyword"], source=source
                )
                session.add(row)
            row.score = int(entry["score"])
            upserted += 1
    session.commit()
    return {"tenants": len(tenant_ids), "upserted": upserted}


@router.get("")
def list_trends(
    identity: Identity = Depends(get_identity),
    session: Session = Depends(get_session),
) -> dict:
    items = session.scalars(
        select(TrendItem)
        .where(TrendItem.tenant_id == identity.tenant_id)  # rule 6
        .order_by(TrendItem.score.desc(), TrendItem.keyword)
    ).all()
    return {
        "items": [
            {
                "keyword": i.keyword,
                "source": i.source,
                "score": i.score,
                "captured_at": i.captured_at.isoformat() if i.captured_at else None,
            }
            for i in items
        ]
    }

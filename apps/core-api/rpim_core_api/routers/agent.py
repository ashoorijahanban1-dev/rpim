"""Autonomous watchdog (M23, ADR 0046) — propose, never publish.

The scan turns hot trends into ORDINARY approval-queue drafts tagged
origin="agent" (rule 1: a human approves everything). Heat alone never
spends: the brand-relevance gate (§3.6) must pass first. L0 is the
shipped default — the watchdog is inert until the owner raises the dial.
"""

import os
from datetime import timedelta

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from rpim_core_api.brain.service import BrandBrain
from rpim_core_api.content.service import GenerationUnavailable, generate_draft
from rpim_core_api.db import get_session
from rpim_core_api.deps import Identity, require_owner
from rpim_core_api.models import AgentAction, Tenant, TrendItem
from rpim_core_api.qa.governance import is_publishing_halted
from rpim_shared.tz import app_timezone, now_app

router = APIRouter(prefix="/agent", tags=["agent"])


class AutonomyIn(BaseModel):
    level: int = Field(ge=0, le=3)  # blueprint §5: L0..L3


@router.put("/autonomy")
def set_autonomy(
    body: AutonomyIn,
    identity: Identity = Depends(require_owner),
    session: Session = Depends(get_session),
) -> dict:
    """Owner-only (M24 RBAC): raising autonomy is a governance act."""
    tenant = session.get(Tenant, identity.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="tenant not found")
    tenant.autonomy_level = body.level
    session.commit()
    return {"autonomy_level": body.level}


def _proposed_today(session: Session, tenant_id: str) -> int:
    """Agent proposals since the app-clock midnight (ADR 0032 — the cap
    day boundary rides the PT lever, never a hardcoded zone)."""
    midnight = now_app().replace(hour=0, minute=0, second=0, microsecond=0)
    count = 0
    rows = session.scalars(
        select(AgentAction).where(AgentAction.tenant_id == tenant_id)  # rule 6
    ).all()
    for row in rows:
        created = row.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=app_timezone())  # sqlite naive
        if created >= midnight:
            count += 1
    return count


@router.post("/scan")
def agent_scan(
    x_internal_token: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> dict:
    """The 30-min beat entry point. Counts only — no tenant content in the
    response. Per tenant: opt-in (autonomy>=L1), halt-aware, capped,
    relevance-gated, deduped (rule 8)."""
    expected = os.environ.get("INTERNAL_TOKEN", "")
    if not expected or x_internal_token != expected:
        raise HTTPException(status_code=403, detail="invalid internal token")

    min_relevance = int(os.environ.get("AGENT_MIN_RELEVANCE", "35"))
    daily_cap = max(1, int(os.environ.get("AGENT_DAILY_DRAFTS", "3")))
    window_start = now_app() - timedelta(days=7)  # stale trends never propose

    tenants = session.scalars(
        select(Tenant).where(Tenant.autonomy_level >= 1)
    ).all()
    tenants_total = session.scalar(select(func.count()).select_from(Tenant)) or 0
    proposed = halted = gated = deduped = capped = failed = 0

    for tenant in tenants:
        if is_publishing_halted(session, tenant.id):
            # Rule 2 spirit: silence/kill halts proposal spend too — the
            # publisher's own in-path check stays the publish guarantee.
            halted += 1
            continue
        budget = daily_cap - _proposed_today(session, tenant.id)
        if budget <= 0:
            capped += 1
            continue
        trends = session.scalars(
            select(TrendItem)
            .where(TrendItem.tenant_id == tenant.id)  # rule 6
            .order_by(TrendItem.score.desc(), TrendItem.id)
            .limit(20)
        ).all()
        brain = BrandBrain(session, tenant.id)
        for trend in trends:
            if budget <= 0:
                capped += 1
                break
            captured = trend.captured_at
            if captured.tzinfo is None:
                captured = captured.replace(tzinfo=app_timezone())  # sqlite naive
            if captured < window_start:
                continue
            exists = session.scalar(
                select(AgentAction).where(
                    AgentAction.tenant_id == tenant.id,  # rule 6
                    AgentAction.trend_item_id == trend.id,
                    AgentAction.kind == "brief_proposal",
                )
            )
            if exists is not None:
                deduped += 1
                continue
            try:
                # §3.6: heat alone must not spend money or reviewer
                # attention — grounding hits on product/claim decide.
                hits = brain.retrieve(trend.keyword, k=3, kinds=("product", "claim"))
            except Exception:  # noqa: BLE001 — a dead embed leg must not
                # crash-loop the beat (rule 8); skip the tenant this pass.
                failed += 1
                break
            relevance = int(100 * max((h["score"] for h in hits), default=0.0))
            relevance = max(0, min(100, relevance))
            if relevance < min_relevance:
                gated += 1
                continue
            brief = {
                "goal": f"واکنش سریع برند به ترند «{trend.keyword}»",
                "audience": "مخاطبان اصلی برند",
                "channel": "telegram",
                "format": "پست متنی",
                "hook": trend.keyword,
                "cta": None,
            }
            try:
                # commit=False: the draft and its audit row land in ONE
                # transaction below — a crash between them can never leave
                # an orphan draft that dodges the dedupe (rule 8).
                draft = generate_draft(
                    session, tenant.id, brief, origin="agent", commit=False
                )
            except GenerationUnavailable:
                session.rollback()
                failed += 1
                break
            session.add(
                AgentAction(
                    tenant_id=tenant.id,
                    kind="brief_proposal",
                    trend_item_id=trend.id,
                    draft_id=draft.id,
                    score=int(trend.score),
                    relevance=relevance,
                    # Fixed fa template + numbers — the audit trail shows
                    # WHY every proposal exists (design §3.6).
                    rationale=(
                        f"ترند داغ (امتیاز {int(trend.score)}) و مرتبط با برند"
                        f" (تناسب {relevance} از ۱۰۰): «{trend.keyword}»"
                    ),
                    status="proposed",
                )
            )
            session.commit()
            proposed += 1
            budget -= 1

    return {
        "tenants": tenants_total,
        "eligible": len(tenants),
        "proposed": proposed,
        "halted": halted,
        "gated": gated,
        "deduped": deduped,
        "capped": capped,
        "failed": failed,
    }

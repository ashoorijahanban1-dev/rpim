"""One-click full data export — §13.1 Definition of Done.

The tenant owns every byte: brand profile, onboarding answers, brain texts,
drafts, the A0 apprentice log (rule 8 — those signals are the tenant's
property), publish jobs, and (v4) the measurement loop — campaign metrics,
learned directives with evidence, and ingestion cursors. Embeddings are
derived data and are NOT exported; re-ingesting the texts regenerates them.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from rpim_core_api.db import get_session
from rpim_core_api.deps import Identity, require_owner
from rpim_core_api.models import (
    AgentAction,
    AnalyticsCursor,
    ApprenticeEvent,
    BrainChunk,
    BrainSource,
    BrandProfile,
    CampaignChannelMetric,
    ContentDraft,
    MediaAsset,
    OnboardingInterview,
    PublishJob,
    Tenant,
    TenantLearning,
)
from rpim_shared.tz import now_app

router = APIRouter(tags=["export"])


def _iso(stamp: datetime | None) -> str | None:
    return stamp.isoformat() if stamp is not None else None


@router.get("/export")
def full_export(
    identity: Identity = Depends(require_owner),
    session: Session = Depends(get_session),
) -> JSONResponse:
    tenant_id = identity.tenant_id
    tenant = session.get(Tenant, tenant_id)
    if tenant is None:
        # A valid JWT pointing at a deleted tenant must not 500.
        raise HTTPException(status_code=404, detail="tenant not found")

    profile = session.scalar(
        select(BrandProfile).where(BrandProfile.tenant_id == tenant_id)  # rule 6
    )
    onboarding = session.scalar(
        select(OnboardingInterview).where(OnboardingInterview.tenant_id == tenant_id)
    )

    sources = session.scalars(
        select(BrainSource)
        .where(BrainSource.tenant_id == tenant_id)
        .order_by(BrainSource.created_at)
    ).all()
    chunks = session.scalars(
        select(BrainChunk).where(BrainChunk.tenant_id == tenant_id).order_by(BrainChunk.seq)
    ).all()
    chunks_by_source: dict[str, list[dict]] = {}
    for chunk in chunks:
        chunks_by_source.setdefault(chunk.source_id, []).append(
            {"seq": chunk.seq, "text": chunk.text, "kind": chunk.kind}
        )

    drafts = session.scalars(
        select(ContentDraft)
        .where(ContentDraft.tenant_id == tenant_id)
        .order_by(ContentDraft.created_at)
    ).all()
    events = session.scalars(
        select(ApprenticeEvent)
        .where(ApprenticeEvent.tenant_id == tenant_id)
        .order_by(ApprenticeEvent.created_at)
    ).all()
    jobs = session.scalars(
        select(PublishJob).where(PublishJob.tenant_id == tenant_id).order_by(PublishJob.created_at)
    ).all()
    media = session.scalars(
        select(MediaAsset).where(MediaAsset.tenant_id == tenant_id).order_by(MediaAsset.created_at)
    ).all()
    metric_rows = session.scalars(
        select(CampaignChannelMetric)
        .where(CampaignChannelMetric.tenant_id == tenant_id)  # rule 6
        .order_by(CampaignChannelMetric.day, CampaignChannelMetric.campaign_code)
    ).all()
    learnings = session.scalars(
        select(TenantLearning)
        .where(TenantLearning.tenant_id == tenant_id)  # rule 6
        .order_by(TenantLearning.version)
    ).all()
    cursors = session.scalars(
        select(AnalyticsCursor)
        .where(AnalyticsCursor.tenant_id == tenant_id)  # rule 6
        .order_by(AnalyticsCursor.provider)
    ).all()

    agent_actions = session.scalars(
        select(AgentAction)
        .where(AgentAction.tenant_id == tenant_id)  # rule 6
        .order_by(AgentAction.created_at)
    ).all()

    payload = {
        "export_version": 5,  # M23a: + draft origin, agent_actions
        "generated_at": now_app().isoformat(),
        "tenant": {
            "id": tenant.id,
            "name": tenant.name,
            "created_at": _iso(tenant.created_at),
        },
        "brand_profile": (
            {
                "tone": profile.tone,
                "personas": profile.personas,
                "lexicon": profile.lexicon,
                "allowed_claims": profile.allowed_claims,
                "forbidden_claims": profile.forbidden_claims,
                "red_lines": profile.red_lines,
                "updated_at": _iso(profile.updated_at),
            }
            if profile
            else None
        ),
        "onboarding": (
            {"answers": onboarding.answers, "status": onboarding.status} if onboarding else None
        ),
        "brain": {
            "sources": [
                {
                    "id": source.id,
                    "title": source.title,
                    "kind": source.kind,
                    "meta": source.meta,
                    "status": source.status,
                    "created_at": _iso(source.created_at),
                    "chunks": chunks_by_source.get(source.id, []),
                }
                for source in sources
            ],
            "chunks_count": len(chunks),
        },
        "media_assets": [
            {
                "id": asset.id,
                "kind": asset.kind,
                "status": asset.status,
                "alt_text": asset.alt_text,
                "sha256": asset.sha256,
                "provider": asset.provider,
                "model": asset.model,
                "wp_media_id": asset.wp_media_id,
                "cost_usd": asset.cost_usd,
                "created_at": _iso(asset.created_at),
            }
            for asset in media
        ],
        "drafts": [
            {
                "draft_id": draft.id,
                "brief": draft.brief,
                "text": draft.text,
                "edited_text": draft.edited_text,
                "status": draft.status,
                "flag_unsourced": draft.flag_unsourced,
                "qa": draft.qa,
                "context_refs": draft.context_refs,
                "origin": draft.origin,
                "created_at": _iso(draft.created_at),
            }
            for draft in drafts
        ],
        "apprentice_events": [
            {
                "kind": event.kind,
                "schema_version": event.schema_version,
                "payload": event.payload,
                "created_at": _iso(event.created_at),
            }
            for event in events
        ],
        "publish_jobs": [
            {
                "job_id": job.id,
                "draft_id": job.draft_id,
                "channel": job.channel,
                "chat_id": job.chat_id,
                "campaign_code": job.campaign_code,
                "utm": job.utm,
                "landing_url": job.landing_url,
                # The frozen dispatched text — the canonical record of what
                # actually shipped, distinct from the (later-editable) draft.
                "text": job.text,
                "status": job.status,
                "attempts": job.attempts,
                "last_error": job.last_error,
                "scheduled_at": _iso(job.scheduled_at),
                "sent_at": _iso(job.sent_at),
                "created_at": _iso(job.created_at),
            }
            for job in jobs
        ],
        "campaign_channel_metrics": [
            {
                "campaign_code": row.campaign_code,
                "channel": row.channel,
                "source": row.source,
                "day": row.day,
                "clicks": row.clicks,
                "sessions": row.sessions,
                "impressions": row.impressions,
                "posts_sent": row.posts_sent,
                "captured_at": _iso(row.captured_at),
            }
            for row in metric_rows
        ],
        "tenant_learnings": [
            {
                "version": learning.version,
                "directives": learning.directives,
                "evidence": learning.evidence,
                "content_hash": learning.content_hash,
                "status": learning.status,
                "created_at": _iso(learning.created_at),
            }
            for learning in learnings
        ],
        "analytics_cursors": [
            {
                "provider": cursor.provider,
                "cursor": cursor.cursor,
                "updated_at": _iso(cursor.updated_at),
            }
            for cursor in cursors
        ],
        "agent_actions": [
            {
                "kind": action.kind,
                "status": action.status,
                "score": action.score,
                "relevance": action.relevance,
                "rationale": action.rationale,
                "trend_item_id": action.trend_item_id,
                "draft_id": action.draft_id,
                "created_at": _iso(action.created_at),
            }
            for action in agent_actions
        ],
    }
    stamp = now_app().strftime("%Y%m%d")
    return JSONResponse(
        payload,
        headers={
            "Content-Disposition": f'attachment; filename="rpim-export-{stamp}.json"',
        },
    )

"""One-click full data export — §13.1 Definition of Done.

The tenant owns every byte: brand profile, onboarding answers, brain texts,
drafts, the A0 apprentice log (rule 8 — those signals are the tenant's
property), and publish jobs. Embeddings are derived data and are NOT
exported; re-ingesting the texts regenerates them.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from rpim_core_api.db import get_session
from rpim_core_api.deps import Identity, require_owner
from rpim_core_api.models import (
    ApprenticeEvent,
    BrainChunk,
    BrainSource,
    BrandProfile,
    ContentDraft,
    OnboardingInterview,
    PublishJob,
    Tenant,
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

    payload = {
        "export_version": 2,  # M20: brain meta + chunk kinds
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
    }
    stamp = now_app().strftime("%Y%m%d")
    return JSONResponse(
        payload,
        headers={
            "Content-Disposition": f'attachment; filename="rpim-export-{stamp}.json"',
        },
    )

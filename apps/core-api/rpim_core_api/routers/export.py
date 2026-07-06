"""One-click full data export (DoD §13.1).

Every section is scoped by the verified token's tenant_id (rule 6) and the
response is one self-contained JSON document: brand profile, brain sources
with chunk texts (embeddings excluded — they are derived data), content
drafts with QA results, publish jobs, apprentice A0 events (rule 8), and the
onboarding interview.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from rpim_core_api.db import get_session
from rpim_core_api.deps import Identity, get_identity
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

router = APIRouter(prefix="/export", tags=["export"])


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


@router.get("")
def export_all(
    identity: Identity = Depends(get_identity),
    session: Session = Depends(get_session),
) -> dict:
    tenant_id = identity.tenant_id

    tenant = session.get(Tenant, tenant_id)
    profile = session.scalar(
        select(BrandProfile).where(BrandProfile.tenant_id == tenant_id)
    )
    interview = session.scalar(
        select(OnboardingInterview).where(OnboardingInterview.tenant_id == tenant_id)
    )
    sources = session.scalars(
        select(BrainSource).where(BrainSource.tenant_id == tenant_id)
    ).all()
    chunks = session.scalars(
        select(BrainChunk).where(BrainChunk.tenant_id == tenant_id)
    ).all()
    drafts = session.scalars(
        select(ContentDraft).where(ContentDraft.tenant_id == tenant_id)
    ).all()
    jobs = session.scalars(
        select(PublishJob).where(PublishJob.tenant_id == tenant_id)
    ).all()
    events = session.scalars(
        select(ApprenticeEvent).where(ApprenticeEvent.tenant_id == tenant_id)
    ).all()

    chunks_by_source: dict[str, list[dict]] = {}
    for chunk in chunks:
        chunks_by_source.setdefault(chunk.source_id, []).append(
            {"chunk_id": chunk.id, "seq": chunk.seq, "text": chunk.text}
        )

    return {
        "export_version": 1,
        "exported_at": _iso(datetime.now(UTC)),
        "tenant": (
            {"tenant_id": tenant.id, "name": tenant.name, "created_at": _iso(tenant.created_at)}
            if tenant is not None
            else None
        ),
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
            if profile is not None
            else None
        ),
        "onboarding_interview": (
            {
                "answers": interview.answers,
                "status": interview.status,
                "updated_at": _iso(interview.updated_at),
            }
            if interview is not None
            else None
        ),
        "brain_documents": [
            {
                "source_id": source.id,
                "title": source.title,
                "kind": source.kind,
                "status": source.status,
                "content_hash": source.content_hash,
                "created_at": _iso(source.created_at),
                "chunks": sorted(
                    chunks_by_source.get(source.id, []), key=lambda c: c["seq"]
                ),
            }
            for source in sources
        ],
        "content_drafts": [
            {
                "draft_id": draft.id,
                "brief": draft.brief,
                "context_refs": draft.context_refs,
                "text": draft.text,
                "edited_text": draft.edited_text,
                "flag_unsourced": draft.flag_unsourced,
                "status": draft.status,
                "qa": draft.qa,
                "created_at": _iso(draft.created_at),
            }
            for draft in drafts
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
                "text": job.text,
                "status": job.status,
                "attempts": job.attempts,
                "scheduled_at": _iso(job.scheduled_at),
                "sent_at": _iso(job.sent_at),
                "last_error": job.last_error,
                "created_at": _iso(job.created_at),
            }
            for job in jobs
        ],
        "apprentice_events": [
            {
                "event_id": event.id,
                "kind": event.kind,
                "schema_version": event.schema_version,
                "payload": event.payload,
                "created_at": _iso(event.created_at),
            }
            for event in events
        ],
    }

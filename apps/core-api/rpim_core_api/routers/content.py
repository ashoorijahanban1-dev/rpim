from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from rpim_core_api.content.service import GenerationUnavailable, generate_draft
from rpim_core_api.db import get_session
from rpim_core_api.deps import Identity, get_identity, require_editor
from rpim_core_api.models import ApprenticeEvent, ContentDraft
from rpim_core_api.schemas import BriefIn, DraftOut, EditIn, RejectIn

router = APIRouter(prefix="/content", tags=["content"])


def _get_draft(session: Session, tenant_id: str, draft_id: str) -> ContentDraft:
    draft = session.scalar(
        select(ContentDraft).where(
            ContentDraft.tenant_id == tenant_id,  # rule 6: absolute scoping
            ContentDraft.id == draft_id,
        )
    )
    if draft is None:
        raise HTTPException(status_code=404, detail="draft not found")
    return draft


def _log_apprentice(session: Session, tenant_id: str, kind: str, payload: dict) -> None:
    session.add(ApprenticeEvent(tenant_id=tenant_id, kind=kind, schema_version=1, payload=payload))


def _draft_out(draft: ContentDraft) -> DraftOut:
    return DraftOut(
        draft_id=draft.id,
        text=draft.text,
        context_refs=draft.context_refs,
        flag_unsourced=draft.flag_unsourced,
        status=draft.status,
        origin=draft.origin,
    )


@router.post("/drafts", response_model=DraftOut, status_code=201)
def create_draft(
    body: BriefIn,
    identity: Identity = Depends(require_editor),
    session: Session = Depends(get_session),
) -> DraftOut:
    # The generation pipeline lives in content/service.py (M23, §3.3) —
    # the watchdog rides the SAME path with origin="agent"; this route
    # keeps only the HTTP contract (stage-specific 503s, unchanged).
    try:
        draft = generate_draft(
            session, identity.tenant_id, body.brief.model_dump(), origin="human"
        )
    except GenerationUnavailable as exc:
        detail = (
            "embedding service unavailable — try again shortly"
            if exc.stage == "embed"
            else "model gateway unavailable — try again shortly"
        )
        raise HTTPException(status_code=503, detail=detail) from exc
    return _draft_out(draft)


@router.get("/drafts")
def list_drafts(
    status: Literal["draft", "approved", "edited", "rejected"] | None = None,
    identity: Identity = Depends(get_identity),
    session: Session = Depends(get_session),
) -> dict:
    query = (
        select(ContentDraft)
        .where(ContentDraft.tenant_id == identity.tenant_id)  # rule 6
        .order_by(ContentDraft.created_at.desc(), ContentDraft.id.desc())
        .limit(100)
    )
    if status is not None:
        query = query.where(ContentDraft.status == status)
    drafts = session.scalars(query).all()
    return {
        "drafts": [
            {
                "draft_id": d.id,
                "text": d.text,
                "status": d.status,
                "flag_unsourced": d.flag_unsourced,
                "created_at": d.created_at.isoformat(),
                "brief": d.brief,
                "qa": d.qa,
                "origin": d.origin,
            }
            for d in drafts
        ]
    }


@router.get("/drafts/{draft_id}", response_model=DraftOut)
def get_draft(
    draft_id: str,
    identity: Identity = Depends(get_identity),
    session: Session = Depends(get_session),
) -> DraftOut:
    return _draft_out(_get_draft(session, identity.tenant_id, draft_id))


@router.post("/drafts/{draft_id}/approve")
def approve_draft(
    draft_id: str,
    identity: Identity = Depends(require_editor),
    session: Session = Depends(get_session),
) -> dict:
    draft = _get_draft(session, identity.tenant_id, draft_id)
    draft.status = "approved"
    # A0 signal 1: brief + injected context → approved output.
    _log_apprentice(
        session,
        identity.tenant_id,
        "approved",
        {"brief": draft.brief, "context_refs": draft.context_refs, "output": draft.text},
    )
    session.commit()
    return {"status": "approved"}


@router.put("/drafts/{draft_id}")
def edit_draft(
    draft_id: str,
    body: EditIn,
    identity: Identity = Depends(require_editor),
    session: Session = Depends(get_session),
) -> dict:
    draft = _get_draft(session, identity.tenant_id, draft_id)
    draft.edited_text = body.edited_text
    draft.status = "edited"
    # A0 signal 2 — the most valuable one: draft → human-edited version.
    _log_apprentice(
        session,
        identity.tenant_id,
        "edited",
        {"brief": draft.brief, "draft": draft.text, "edited": body.edited_text},
    )
    session.commit()
    return {"status": "edited"}


@router.post("/drafts/{draft_id}/reject")
def reject_draft(
    draft_id: str,
    body: RejectIn,
    identity: Identity = Depends(require_editor),
    session: Session = Depends(get_session),
) -> dict:
    draft = _get_draft(session, identity.tenant_id, draft_id)
    draft.status = "rejected"
    # A0 signal 3: structured rejection reason.
    _log_apprentice(
        session,
        identity.tenant_id,
        "rejected",
        {
            "brief": draft.brief,
            "draft": draft.text,
            "reason_code": body.reason_code,
            "note": body.note,
        },
    )
    session.commit()
    return {"status": "rejected"}


@router.get("/apprentice-log")
def apprentice_log(
    identity: Identity = Depends(get_identity),
    session: Session = Depends(get_session),
) -> dict:
    events = session.scalars(
        select(ApprenticeEvent)
        .where(ApprenticeEvent.tenant_id == identity.tenant_id)
        .order_by(ApprenticeEvent.created_at.desc())
        .limit(200)
    ).all()
    return {
        "entries": [
            {
                "kind": e.kind,
                "schema_version": e.schema_version,
                "payload": e.payload,
                "created_at": e.created_at.isoformat(),
            }
            for e in events
        ]
    }

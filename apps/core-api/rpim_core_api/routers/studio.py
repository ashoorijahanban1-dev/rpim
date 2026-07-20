"""Visual Prompt Studio (M15) — brief → professional generative prompt."""

from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from rpim_core_api.brain.service import BrandBrain
from rpim_core_api.db import get_session
from rpim_core_api.deps import Identity, get_identity, require_editor
from rpim_core_api.media import service as media_service
from rpim_core_api.models import BrandProfile, MediaAsset, VisualPrompt
from rpim_core_api.studio.expander import expand

router = APIRouter(prefix="/studio", tags=["studio"])


class StudioBrief(BaseModel):
    subject: str = Field(min_length=1, max_length=300)
    mood: str | None = Field(default=None, max_length=120)
    channel: str | None = Field(default=None, max_length=40)


class StudioIn(BaseModel):
    kind: Literal["image", "video"]
    brief: StudioBrief


@router.post("/prompts", status_code=201)
def create_prompt(
    body: StudioIn,
    identity: Identity = Depends(require_editor),
    session: Session = Depends(get_session),
) -> dict:
    if not body.brief.subject.strip():
        raise HTTPException(status_code=422, detail="subject must not be blank")
    profile = session.scalar(
        select(BrandProfile).where(BrandProfile.tenant_id == identity.tenant_id)  # rule 6
    )
    # M20: the studio asks the brain — product/tone knowledge grounds the
    # visual prompt (falls back to doc chunks; empty brain = no grounding).
    brain = BrandBrain(session, identity.tenant_id)
    try:
        chunks = brain.retrieve(body.brief.subject, k=3, kinds=("product", "tone"))
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503, detail="embedding service unavailable — try again shortly"
        ) from exc
    grounding = brain.compose_context(chunks, budget_chars=800)
    prompt_text = expand(
        body.kind,
        body.brief.model_dump(),
        profile.tone if profile else None,
        context=grounding or None,
    )
    row = VisualPrompt(
        tenant_id=identity.tenant_id,
        kind=body.kind,
        brief=body.brief.model_dump(),
        prompt_text=prompt_text,
    )
    session.add(row)
    session.commit()
    return {"prompt_id": row.id, "kind": row.kind, "prompt_text": row.prompt_text}


@router.get("/prompts")
def list_prompts(
    identity: Identity = Depends(get_identity),
    session: Session = Depends(get_session),
) -> dict:
    rows = session.scalars(
        select(VisualPrompt)
        .where(VisualPrompt.tenant_id == identity.tenant_id)  # rule 6
        .order_by(VisualPrompt.created_at.desc(), VisualPrompt.id.desc())
    ).all()
    return {
        "items": [
            {
                "prompt_id": r.id,
                "kind": r.kind,
                "prompt_text": r.prompt_text,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }


class MediaGenerateIn(BaseModel):
    prompt_id: str = Field(min_length=1, max_length=64)


def _media_out(asset: MediaAsset) -> dict:
    return {
        "media_id": asset.id,
        "kind": asset.kind,
        "status": asset.status,
        "alt_text": asset.alt_text,
        "sha256": asset.sha256,
        "provider": asset.provider,
        "wp_media_id": asset.wp_media_id,
        "created_at": asset.created_at.isoformat() if asset.created_at else None,
    }


@router.post("/media", status_code=201)
def generate_media(
    body: MediaGenerateIn,
    identity: Identity = Depends(require_editor),
    session: Session = Depends(get_session),
) -> dict:
    """M21: execute a visual prompt into a stored media asset (status=draft —
    rule 1 covers images: a human approves before anything can attach)."""
    prompt = session.scalar(
        select(VisualPrompt).where(
            VisualPrompt.tenant_id == identity.tenant_id,  # rule 6
            VisualPrompt.id == body.prompt_id,
        )
    )
    if prompt is None:
        raise HTTPException(status_code=404, detail="prompt not found")
    try:
        asset, _created = media_service.generate_for_prompt(
            session, identity.tenant_id, prompt
        )
    except media_service.MediaGenerationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _media_out(asset)


@router.get("/media")
def list_media(
    identity: Identity = Depends(get_identity),
    session: Session = Depends(get_session),
) -> dict:
    rows = session.scalars(
        select(MediaAsset)
        .where(MediaAsset.tenant_id == identity.tenant_id)  # rule 6
        .order_by(MediaAsset.created_at.desc(), MediaAsset.id.desc())
        .limit(100)
    ).all()
    return {"items": [_media_out(r) for r in rows]}


@router.post("/media/{media_id}/approve")
def approve_media(
    media_id: str,
    identity: Identity = Depends(require_editor),
    session: Session = Depends(get_session),
) -> dict:
    asset = session.scalar(
        select(MediaAsset).where(
            MediaAsset.tenant_id == identity.tenant_id,  # rule 6
            MediaAsset.id == media_id,
        )
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="media not found")
    asset.status = "approved"
    session.commit()
    return {"media_id": asset.id, "status": asset.status}

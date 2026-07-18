"""Visual Prompt Studio (M15) — brief → professional generative prompt."""

from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from rpim_core_api.brain.service import BrandBrain
from rpim_core_api.db import get_session
from rpim_core_api.deps import Identity, get_identity
from rpim_core_api.models import BrandProfile, VisualPrompt
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
    identity: Identity = Depends(get_identity),
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

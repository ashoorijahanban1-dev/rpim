import os

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from rpim_core_api.db import get_session
from rpim_core_api.deps import Identity, get_identity
from rpim_core_api.models import BrainChunk, ContentDraft
from rpim_core_api.qa import checks
from rpim_core_api.qa.governance import GLOBAL_SCOPE, get_flags, set_flag

qa_router = APIRouter(prefix="/qa", tags=["qa"])
gov_router = APIRouter(prefix="/governance", tags=["governance"])


@qa_router.post("/check/{draft_id}")
def qa_check(
    draft_id: str,
    identity: Identity = Depends(get_identity),
    session: Session = Depends(get_session),
) -> dict:
    draft = session.scalar(
        select(ContentDraft).where(
            ContentDraft.tenant_id == identity.tenant_id,  # rule 6
            ContentDraft.id == draft_id,
        )
    )
    if draft is None:
        raise HTTPException(status_code=404, detail="draft not found")

    # Claims verify against the WHOLE brand brain (blueprint M6), not just the
    # slice injected at generation time.
    chunk_texts = session.scalars(
        select(BrainChunk.text).where(BrainChunk.tenant_id == identity.tenant_id).limit(500)
    ).all()
    context = "\n".join(chunk_texts)

    text = draft.edited_text or draft.text
    channel = str((draft.brief or {}).get("channel", ""))
    flags = checks.run_all(text, context, channel)
    requires_human = any(f["level"] == "block" for f in flags)

    draft.qa = {"flags": flags, "requires_human": requires_human}
    session.commit()
    return {"flags": flags, "requires_human": requires_human}


class SilenceIn(BaseModel):
    active: bool
    reason: str = Field(min_length=1, max_length=500)


@gov_router.get("/status")
def governance_status(
    identity: Identity = Depends(get_identity),
    session: Session = Depends(get_session),
) -> dict:
    return get_flags(session, identity.tenant_id)


@gov_router.post("/silence")
def set_silence(
    body: SilenceIn,
    identity: Identity = Depends(get_identity),
    session: Session = Depends(get_session),
) -> dict:
    # Tenant-scoped silence; release is this same explicit call with
    # active=false — manual-only resume, nothing automatic (constitution).
    set_flag(session, identity.tenant_id, "silence", body.active, body.reason)
    return get_flags(session, identity.tenant_id)


@gov_router.post("/kill")
def set_kill(
    body: SilenceIn,
    x_internal_token: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> dict:
    # Global kill switch is an OPS action: internal token, not tenant auth.
    expected = os.environ.get("INTERNAL_TOKEN", "")
    if not expected or x_internal_token != expected:
        raise HTTPException(status_code=401, detail="invalid internal token")
    set_flag(session, GLOBAL_SCOPE, "kill", body.active, body.reason)
    return {"kill": body.active}

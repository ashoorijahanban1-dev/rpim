import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from rpim_core_api.brain.embed_client import embed_texts
from rpim_core_api.brain.retrieval import search_chunks
from rpim_core_api.content.complete_client import complete
from rpim_core_api.db import get_session
from rpim_core_api.deps import Identity, get_identity
from rpim_core_api.models import ApprenticeEvent, BrandProfile, ContentDraft
from rpim_core_api.schemas import BriefIn, DraftOut, EditIn, RejectIn

router = APIRouter(prefix="/content", tags=["content"])

_NUM_RE = re.compile(r"[0-9۰-۹]{2,}")


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
    )


@router.post("/drafts", response_model=DraftOut, status_code=201)
def create_draft(
    body: BriefIn,
    identity: Identity = Depends(get_identity),
    session: Session = Depends(get_session),
) -> DraftOut:
    profile = session.scalar(
        select(BrandProfile).where(BrandProfile.tenant_id == identity.tenant_id)
    )

    query = " ".join(filter(None, [body.brief.goal, body.brief.audience, body.brief.hook or ""]))
    query_vector = embed_texts([query], tenant_id=identity.tenant_id)[0]
    chunks = search_chunks(session, identity.tenant_id, query_vector, k=5)

    context_block = "\n\n".join(f"[{c['source_title']}] {c['text']}" for c in chunks)
    system = (
        "تو نویسنده محتوای برند هستی. لحن برند: "
        + ((profile.tone or "رسمی و روشن") if profile else "رسمی و روشن")
        + "\nفقط از «زمینه برند» استفاده کن؛ هیچ ادعا، قیمت یا مشخصه‌ای خارج از زمینه نیاور."
        + (
            "\nادعاهای ممنوع: " + "، ".join(profile.forbidden_claims)
            if profile and profile.forbidden_claims
            else ""
        )
    )
    prompt = (
        f"زمینه برند:\n{context_block}\n\n"
        f"بریف: هدف={body.brief.goal} | مخاطب={body.brief.audience} | "
        f"کانال={body.brief.channel} | قالب={body.brief.format}"
        + (f" | قلاب={body.brief.hook}" if body.brief.hook else "")
        + (f" | فراخوان={body.brief.cta}" if body.brief.cta else "")
        + "\n\nپیش‌نویس کامل بنویس."
    )
    text = complete(prompt, system=system, tenant_id=identity.tenant_id, task="t1")

    # Cheap unsourced-claim tripwire (full claim-check is M5 QA): any multi-
    # digit number in the draft that never appears in the context gets flagged.
    context_numbers = set(_NUM_RE.findall(context_block))
    flag_unsourced = any(n not in context_numbers for n in _NUM_RE.findall(text))

    draft = ContentDraft(
        tenant_id=identity.tenant_id,
        brief=body.brief.model_dump(),
        context_refs=[c["source_title"] for c in chunks],
        text=text,
        flag_unsourced=flag_unsourced,
        status="draft",
    )
    session.add(draft)
    session.commit()
    return _draft_out(draft)


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
    identity: Identity = Depends(get_identity),
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
    identity: Identity = Depends(get_identity),
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
    identity: Identity = Depends(get_identity),
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

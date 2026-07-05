from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from rpim_core_api.db import get_session
from rpim_core_api.deps import Identity, get_identity
from rpim_core_api.models import BrandProfile
from rpim_core_api.schemas import BrandProfileIn, BrandProfileOut

router = APIRouter(prefix="/brand-profile", tags=["brand-profile"])


def _get_scoped(session: Session, tenant_id: str) -> BrandProfile | None:
    # tenant_id scoping is absolute (CLAUDE.md rule 6) — no unscoped access.
    return session.scalar(select(BrandProfile).where(BrandProfile.tenant_id == tenant_id))


@router.get("", response_model=BrandProfileOut)
def get_profile(
    identity: Identity = Depends(get_identity),
    session: Session = Depends(get_session),
) -> BrandProfileOut:
    profile = _get_scoped(session, identity.tenant_id)
    if profile is None:
        return BrandProfileOut()
    return BrandProfileOut(
        tone=profile.tone,
        personas=profile.personas,
        lexicon=profile.lexicon,
        allowed_claims=profile.allowed_claims or [],
        forbidden_claims=profile.forbidden_claims,
        red_lines=profile.red_lines,
    )


@router.put("", response_model=BrandProfileOut)
def put_profile(
    body: BrandProfileIn,
    identity: Identity = Depends(get_identity),
    session: Session = Depends(get_session),
) -> BrandProfileOut:
    profile = _get_scoped(session, identity.tenant_id)
    if profile is None:
        profile = BrandProfile(tenant_id=identity.tenant_id)
        session.add(profile)
    profile.tone = body.tone
    profile.personas = body.personas
    profile.lexicon = body.lexicon
    profile.allowed_claims = body.allowed_claims
    profile.forbidden_claims = body.forbidden_claims
    profile.red_lines = body.red_lines
    session.commit()
    return BrandProfileOut(**body.model_dump())

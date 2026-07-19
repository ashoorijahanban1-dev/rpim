import hashlib
import secrets
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from rpim_core_api.db import get_session
from rpim_core_api.deps import Identity, require_owner
from rpim_core_api.models import Tenant, TenantInvite, User
from rpim_core_api.schemas import LoginIn, LoginOut, RegisterIn, RegisterOut
from rpim_core_api.security import create_token, hash_password, verify_password
from rpim_shared.tz import app_timezone, now_app

router = APIRouter(prefix="/auth", tags=["auth"])

_INVITE_TTL_DAYS = 7


@router.post("/register", response_model=RegisterOut, status_code=201)
def register(body: RegisterIn, session: Session = Depends(get_session)) -> RegisterOut:
    email = body.email.lower()
    existing = session.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise HTTPException(status_code=409, detail="email already registered")

    tenant = Tenant(name=body.tenant_name)
    session.add(tenant)
    session.flush()
    # The registrant founds the tenant → its OWNER (M24 RBAC, ADR 0038).
    user = User(
        email=email,
        password_hash=hash_password(body.password),
        tenant_id=tenant.id,
        role="owner",
    )
    session.add(user)
    session.commit()

    return RegisterOut(tenant_id=tenant.id, access_token=create_token(user.id, tenant.id))


class InviteIn(BaseModel):
    email: EmailStr
    role: Literal["editor", "observer"]  # owner is never invited (ADR 0038)


class InviteAcceptIn(BaseModel):
    token: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=200)


@router.post("/invites", status_code=201)
def create_invite(
    body: InviteIn,
    identity: Identity = Depends(require_owner),
    session: Session = Depends(get_session),
) -> dict:
    """Multi-seat v1 (M24): the raw token is returned exactly ONCE — only its
    sha256 is stored, so a DB leak never yields usable invites."""
    raw = secrets.token_urlsafe(32)
    session.add(
        TenantInvite(
            tenant_id=identity.tenant_id,  # rule 6: invites bind to the caller
            email=body.email.lower(),
            role=body.role,
            token_hash=hashlib.sha256(raw.encode()).hexdigest(),
            expires_at=now_app() + timedelta(days=_INVITE_TTL_DAYS),
        )
    )
    session.commit()
    return {"token": raw, "role": body.role, "expires_in_days": _INVITE_TTL_DAYS}


@router.post("/invites/accept", status_code=201)
def accept_invite(body: InviteAcceptIn, session: Session = Depends(get_session)) -> dict:
    # One uniform 410 for unknown/used/expired — no probing oracle.
    token_hash = hashlib.sha256(body.token.encode()).hexdigest()
    invite = session.scalar(
        select(TenantInvite).where(TenantInvite.token_hash == token_hash)
    )
    expires_at = invite.expires_at if invite else None
    if expires_at is not None and expires_at.tzinfo is None:
        # sqlite returns naive stamps; they were written in app-TZ wall time
        # (ADR 0032 lever) — reattach, never hardcode a zone.
        expires_at = expires_at.replace(tzinfo=app_timezone())
    if (
        invite is None
        or invite.used_at is not None
        or expires_at is None
        or now_app() > expires_at
    ):
        raise HTTPException(status_code=410, detail="invite invalid or expired")

    existing = session.scalar(select(User).where(User.email == invite.email))
    if existing is not None:
        # v1 collision rule (ADR 0038): accounts NEVER move across tenants
        # (rule 6) — an already-registered email cannot accept an invite.
        raise HTTPException(status_code=409, detail="email already registered")

    user = User(
        email=invite.email,
        password_hash=hash_password(body.password),
        tenant_id=invite.tenant_id,
        role=invite.role,
    )
    session.add(user)
    invite.used_at = now_app()
    session.commit()
    return {
        "tenant_id": invite.tenant_id,
        "access_token": create_token(user.id, invite.tenant_id),
    }


@router.post("/login", response_model=LoginOut)
def login(body: LoginIn, session: Session = Depends(get_session)) -> LoginOut:
    user = session.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid credentials")
    return LoginOut(access_token=create_token(user.id, user.tenant_id))

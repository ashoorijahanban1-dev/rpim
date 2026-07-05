from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from rpim_core_api.db import get_session
from rpim_core_api.models import Tenant, User
from rpim_core_api.schemas import LoginIn, LoginOut, RegisterIn, RegisterOut
from rpim_core_api.security import create_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=RegisterOut, status_code=201)
def register(body: RegisterIn, session: Session = Depends(get_session)) -> RegisterOut:
    email = body.email.lower()
    existing = session.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise HTTPException(status_code=409, detail="email already registered")

    tenant = Tenant(name=body.tenant_name)
    session.add(tenant)
    session.flush()
    user = User(email=email, password_hash=hash_password(body.password), tenant_id=tenant.id)
    session.add(user)
    session.commit()

    return RegisterOut(tenant_id=tenant.id, access_token=create_token(user.id, tenant.id))


@router.post("/login", response_model=LoginOut)
def login(body: LoginIn, session: Session = Depends(get_session)) -> LoginOut:
    user = session.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid credentials")
    return LoginOut(access_token=create_token(user.id, user.tenant_id))

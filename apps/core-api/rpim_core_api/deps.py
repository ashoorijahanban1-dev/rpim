import os

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from rpim_core_api.db import get_session
from rpim_core_api.security import decode_token

_bearer = HTTPBearer(auto_error=False)


class Identity:
    def __init__(self, user_id: str, tenant_id: str):
        self.user_id = user_id
        self.tenant_id = tenant_id


def get_identity(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Identity:
    """Every tenant-scoped route depends on this; tenant_id comes ONLY from
    the verified token — never from client-supplied params (rule 6)."""
    if creds is None:
        raise HTTPException(status_code=401, detail="missing bearer token")
    try:
        payload = decode_token(creds.credentials)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="invalid token") from exc
    return Identity(user_id=payload["sub"], tenant_id=payload["tenant_id"])


def get_admin_identity(
    identity: Identity = Depends(get_identity),
    session: Session = Depends(get_session),
) -> Identity:
    """The single cross-tenant gate (M18). Admins are NAMED by ADMIN_EMAILS
    (rule 4: env names carry config, values live in the deploy) and checked
    against the VERIFIED user row at request time, so revocation is one env
    edit away. An empty/unset list means NOBODY is admin — the safe default."""
    from rpim_core_api.models import User  # noqa: PLC0415 — avoids models↔deps cycle

    allowlist = {
        email.strip().lower()
        for email in os.environ.get("ADMIN_EMAILS", "").split(",")
        if email.strip()
    }
    user = session.get(User, identity.user_id)
    if not allowlist or user is None or user.email.lower() not in allowlist:
        raise HTTPException(status_code=403, detail="admin access required")
    return identity

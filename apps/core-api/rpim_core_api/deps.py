import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

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

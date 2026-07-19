"""Per-brand Social Media Hub (M16) — connect/view/manage channel credentials.

Secrets are WRITE-ONLY through this API: they are sealed at the door
(ADR 0033) and no response shape carries them back. Instagram has no slot
here on purpose — rule 5 keeps it assisted-only, never credentialed
automation.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from rpim_core_api import vault
from rpim_core_api.db import get_session
from rpim_core_api.deps import Identity, require_editor, require_owner
from rpim_core_api.models import ChannelConnection
from rpim_core_api.publisher.channels import SUPPORTED_CHANNELS

router = APIRouter(prefix="/channels", tags=["channels"])


class ConnectionIn(BaseModel):
    # secret omitted/None = keep the stored one (config-only update).
    secret: str | None = Field(default=None, max_length=1000)
    config: dict = Field(default_factory=dict)


def _get_row(session: Session, tenant_id: str, channel: str) -> ChannelConnection | None:
    return session.scalar(
        select(ChannelConnection).where(
            ChannelConnection.tenant_id == tenant_id,  # rule 6
            ChannelConnection.channel == channel,
        )
    )


def _require_channel(channel: str) -> None:
    if channel not in SUPPORTED_CHANNELS:
        raise HTTPException(status_code=404, detail="unsupported channel")


@router.get("")
def list_channels(
    identity: Identity = Depends(require_editor),
    session: Session = Depends(get_session),
) -> dict:
    rows = {
        row.channel: row
        for row in session.scalars(
            select(ChannelConnection).where(
                ChannelConnection.tenant_id == identity.tenant_id  # rule 6
            )
        ).all()
    }
    return {
        "channels": [
            {
                "channel": channel,
                "status": rows[channel].status if channel in rows else "disconnected",
                "secret_set": bool(rows[channel].secret_sealed) if channel in rows else False,
                "config": (rows[channel].config or {}) if channel in rows else {},
            }
            for channel in SUPPORTED_CHANNELS
        ]
    }


@router.put("/{channel}")
def upsert_channel(
    channel: str,
    body: ConnectionIn,
    identity: Identity = Depends(require_owner),
    session: Session = Depends(get_session),
) -> dict:
    _require_channel(channel)
    row = _get_row(session, identity.tenant_id, channel)
    if row is None:
        row = ChannelConnection(tenant_id=identity.tenant_id, channel=channel)
        session.add(row)
    if body.secret is not None and body.secret.strip():
        try:
            row.secret_sealed = vault.seal(
                body.secret.strip(), tenant_id=identity.tenant_id, channel=channel
            )
        except vault.VaultKeyError as exc:
            raise HTTPException(
                status_code=503, detail="channel vault key missing — try again shortly"
            ) from exc
    row.config = dict(body.config)
    row.status = "connected" if row.secret_sealed else "disconnected"
    session.commit()
    return {"channel": channel, "status": row.status, "secret_set": bool(row.secret_sealed)}


@router.delete("/{channel}")
def disconnect_channel(
    channel: str,
    identity: Identity = Depends(require_owner),
    session: Session = Depends(get_session),
) -> dict:
    _require_channel(channel)
    row = _get_row(session, identity.tenant_id, channel)
    if row is not None:
        row.secret_sealed = None
        row.status = "disconnected"
        session.commit()
    return {"channel": channel, "status": "disconnected", "secret_set": False}

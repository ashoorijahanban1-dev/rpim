"""Super Admin panel (M18) — the ONE authorized cross-tenant read surface.

Rule 6 makes tenant scoping absolute for tenant-facing routes; platform
operation still needs oversight. This router is the deliberate, gated
exception (ADR 0035): every route hangs on get_admin_identity, exposes
usage/status aggregates only, and NEVER carries secret material or tenant
channel config — oversight is status-only.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from rpim_core_api.db import get_session
from rpim_core_api.deps import Identity, get_admin_identity
from rpim_core_api.measurement import ledger_client
from rpim_core_api.models import ChannelConnection, Tenant, User
from rpim_core_api.publisher.channels import SUPPORTED_CHANNELS

router = APIRouter(prefix="/admin", tags=["admin"])


def _entry_tokens(entry: dict) -> int:
    # fake-mode entries carry "tokens"; gateway entries carry "units".
    return int(entry.get("tokens", entry.get("units", 0)) or 0)


@router.get("/tenants")
def list_tenants(
    _admin: Identity = Depends(get_admin_identity),
    session: Session = Depends(get_session),
) -> dict:
    tenants = session.scalars(select(Tenant).order_by(Tenant.created_at.desc())).all()
    user_counts: dict[str, int] = {}
    for user in session.scalars(select(User)).all():
        user_counts[user.tenant_id] = user_counts.get(user.tenant_id, 0) + 1
    connections = {
        (conn.tenant_id, conn.channel): conn
        for conn in session.scalars(select(ChannelConnection)).all()
    }

    items: list[dict] = []
    for tenant in tenants:
        entries = ledger_client.fetch_entries(tenant.id)
        channels = []
        for channel in SUPPORTED_CHANNELS:
            conn = connections.get((tenant.id, channel))
            # Status + secret_set ONLY: config may carry chat ids and site
            # URLs the brand considers private — the admin view never sees it.
            channels.append(
                {
                    "channel": channel,
                    "status": conn.status if conn else "disconnected",
                    "secret_set": bool(conn is not None and conn.secret_sealed),
                }
            )
        items.append(
            {
                "tenant_id": tenant.id,
                "name": tenant.name,
                "created_at": tenant.created_at.isoformat() if tenant.created_at else None,
                "users": user_counts.get(tenant.id, 0),
                "channels": channels,
                "costs": {
                    "total_usd": round(
                        sum(float(e.get("cost_usd", 0.0) or 0.0) for e in entries), 6
                    ),
                    "tokens": sum(_entry_tokens(e) for e in entries),
                },
            }
        )
    return {"tenants": items}

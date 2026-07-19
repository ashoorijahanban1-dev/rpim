"""Per-tenant channel credentials for the publish engine (M16b, ADR 0033).

Resolution semantics:
- No connection / no sealed secret → None (safe fallback to the global env
  credential — the pre-M16 behavior).
- Connected but unsealable (vault key rotated/lost) → ChannelSendError:
  a brand that connected its OWN bot must never publish through the global
  identity, so the job stays queued until the vault is healthy again.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from rpim_core_api import vault
from rpim_core_api.models import ChannelConnection
from rpim_core_api.publisher.channels import ChannelSendError


def resolve(session: Session, tenant_id: str, channel: str) -> dict | None:
    row = session.scalar(
        select(ChannelConnection).where(
            ChannelConnection.tenant_id == tenant_id,  # rule 6
            ChannelConnection.channel == channel,
        )
    )
    if row is None or not row.secret_sealed:
        return None
    try:
        secret = vault.unseal(row.secret_sealed, tenant_id=tenant_id, channel=channel)
    except vault.VaultKeyError as exc:
        # Transient by design — never echoes the sealed value (rule 4).
        raise ChannelSendError(f"tenant credential unavailable: {exc}") from exc
    if not vault.is_v2(row.secret_sealed):
        # Lazy v1→v2 upgrade (M24, ADR 0038) — BEST-EFFORT: a missing/invalid
        # V2 key keeps the working v1 blob untouched; re-seal must never turn
        # a readable credential into a publish outage. The write rides the
        # engine's per-job commit.
        try:
            resealed = vault.seal(secret, tenant_id=tenant_id, channel=channel)
            if vault.is_v2(resealed):
                row.secret_sealed = resealed
        except vault.VaultKeyError:
            pass
    return {"secret": secret, "config": dict(row.config or {})}

"""Publishing halt state. The M7 publisher MUST call is_publishing_halted()
INSIDE the send path for every job — not only in the scheduler (constitution
rule 2); queued jobs stop too because the check happens at send time."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from rpim_core_api.models import GovernanceFlag

GLOBAL_SCOPE = "global"


def get_flags(session: Session, tenant_id: str) -> dict:
    rows = session.scalars(
        select(GovernanceFlag).where(
            GovernanceFlag.scope.in_([GLOBAL_SCOPE, tenant_id]),
            GovernanceFlag.active,
        )
    ).all()
    kinds = {row.kind for row in rows}
    return {"silence": "silence" in kinds, "kill": "kill" in kinds}


def is_publishing_halted(session: Session, tenant_id: str) -> bool:
    flags = get_flags(session, tenant_id)
    return flags["silence"] or flags["kill"]


def set_flag(session: Session, scope: str, kind: str, active: bool, reason: str) -> None:
    row = session.scalar(
        select(GovernanceFlag).where(GovernanceFlag.scope == scope, GovernanceFlag.kind == kind)
    )
    if row is None:
        row = GovernanceFlag(scope=scope, kind=kind)
        session.add(row)
    row.active = active
    row.reason = reason
    session.commit()

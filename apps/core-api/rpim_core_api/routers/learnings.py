"""Tenant learnings (M22 slice C, ADR 0043) — distill, list, retire.

The daily beat pokes /learnings/distill; owners govern the result. Versions
are append-only: the distiller writes a new one ONLY when the content hash
moves (rule 8), and nothing here ever mutates a stored version's content.
"""

import os

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from rpim_core_api.db import get_session
from rpim_core_api.deps import Identity, get_identity, require_owner
from rpim_core_api.measurement import distiller
from rpim_core_api.models import Tenant, TenantLearning

router = APIRouter(prefix="/learnings", tags=["learnings"])


@router.post("/distill")
def distill_learnings(
    x_internal_token: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> dict:
    """Beat-driven distillation over every tenant. Counts only in the
    response — no campaign codes, no directive text, no PII."""
    expected = os.environ.get("INTERNAL_TOKEN", "")
    if not expected or x_internal_token != expected:
        raise HTTPException(status_code=403, detail="invalid internal token")

    tenant_ids = session.scalars(select(Tenant.id)).all()
    updated = unchanged = 0
    for tenant_id in tenant_ids:
        evidence = distiller.load_evidence(session, tenant_id)
        directives = distiller.distill_directives(evidence)
        digest = distiller.content_hash(directives, evidence)
        latest = session.scalar(
            select(TenantLearning)
            .where(TenantLearning.tenant_id == tenant_id)  # rule 6
            .order_by(TenantLearning.version.desc())
            .limit(1)
        )
        if latest is None and not directives:
            # Nothing learned yet — don't seed tenants with empty version-1s.
            unchanged += 1
            continue
        if latest is not None and latest.content_hash == digest:
            unchanged += 1
            continue
        session.add(
            TenantLearning(
                tenant_id=tenant_id,
                version=(latest.version + 1) if latest is not None else 1,
                directives=directives,
                evidence=evidence,
                content_hash=digest,
            )
        )
        updated += 1
    session.commit()
    return {"tenants": len(tenant_ids), "updated": updated, "unchanged": unchanged}


@router.get("")
def list_learnings(
    identity: Identity = Depends(get_identity),
    session: Session = Depends(get_session),
) -> dict:
    rows = session.scalars(
        select(TenantLearning)
        .where(TenantLearning.tenant_id == identity.tenant_id)  # rule 6
        .order_by(TenantLearning.version.desc())
        .limit(50)
    ).all()
    return {
        "items": [
            {
                "version": r.version,
                "directives": r.directives,
                "evidence": r.evidence,
                "status": r.status,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    }


@router.post("/{version}/retire")
def retire_learning(
    version: int,
    identity: Identity = Depends(require_owner),
    session: Session = Depends(get_session),
) -> dict:
    """Owner-only (M24 RBAC): retiring the brand's learned voice is a
    governance act, like rotating a channel credential. Retirement is
    permanent for the version — the injection path only reads ACTIVE rows,
    and a same-hash re-distill stays a no-op, so the beat can't undo it."""
    row = session.scalar(
        select(TenantLearning).where(
            TenantLearning.tenant_id == identity.tenant_id,  # rule 6
            TenantLearning.version == version,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="learning version not found")
    row.status = "retired"
    session.commit()
    return {"status": "retired", "version": version}

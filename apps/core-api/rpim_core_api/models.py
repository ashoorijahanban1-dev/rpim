import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from rpim_core_api.brain.vector_type import EmbeddingVector
from rpim_core_api.db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(UTC)


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    # M1: one user belongs to exactly one tenant; multi-seat comes with the
    # approval-queue milestone (see docs/decisions/).
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class BrandProfile(Base):
    __tablename__ = "brand_profiles"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), unique=True, index=True)
    tone: Mapped[str] = mapped_column(String(4000), default="")
    personas: Mapped[list] = mapped_column(JSON, default=list)
    lexicon: Mapped[dict] = mapped_column(JSON, default=dict)
    allowed_claims: Mapped[list] = mapped_column(JSON, default=list)
    forbidden_claims: Mapped[list] = mapped_column(JSON, default=list)
    red_lines: Mapped[list] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class BrainSource(Base):
    __tablename__ = "brain_sources"
    # Idempotency across the flaky iran↔us boundary (rule: cross-leg jobs are
    # idempotent): same tenant + same content hash = same source, no dupes.
    __table_args__ = (UniqueConstraint("tenant_id", "content_hash"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    title: Mapped[str] = mapped_column(String(500))
    kind: Mapped[str] = mapped_column(String(16), default="upload")
    status: Mapped[str] = mapped_column(String(16), default="ready")
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class BrainChunk(Base):
    __tablename__ = "brain_chunks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("brain_sources.id"), index=True)
    seq: Mapped[int] = mapped_column()
    text: Mapped[str] = mapped_column(String(4000))
    # pgvector vector(1024) on postgres, JSON on sqlite tests (ADR 0011).
    embedding: Mapped[list] = mapped_column(EmbeddingVector(1024), default=list)


class ContentDraft(Base):
    __tablename__ = "content_drafts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    brief: Mapped[dict] = mapped_column(JSON, default=dict)
    context_refs: Mapped[list] = mapped_column(JSON, default=list)
    text: Mapped[str] = mapped_column(String(8000))
    edited_text: Mapped[str | None] = mapped_column(String(8000), nullable=True)
    flag_unsourced: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    qa: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ApprenticeEvent(Base):
    """A0 apprentice signals (constitution rule 8): versioned, per-tenant,
    exportable — DB-backed with JSONL export at the data-export boundary."""

    __tablename__ = "apprentice_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # approved | edited | rejected
    schema_version: Mapped[int] = mapped_column(default=1)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class GovernanceFlag(Base):
    """Silence mode + kill switch state (constitution rules 2 & 7).
    scope is 'global' or a tenant_id; resume is MANUAL-ONLY by design —
    nothing anywhere auto-releases these flags."""

    __tablename__ = "governance_flags"
    __table_args__ = (UniqueConstraint("scope", "kind"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    scope: Mapped[str] = mapped_column(String(64), index=True)  # "global" | tenant_id
    kind: Mapped[str] = mapped_column(String(16))  # "silence" | "kill"
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str] = mapped_column(String(500), default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class OnboardingInterview(Base):
    __tablename__ = "onboarding_interviews"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), unique=True, index=True)
    answers: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from rpim_core_api.brain.vector_type import EmbeddingVector
from rpim_core_api.db import Base
from rpim_shared.tz import now_app


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    # App timezone (ADR 0032) — PT by operator mandate, env-reversible.
    return now_app()


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
    # M24 RBAC: owner | editor | observer. Backfill 'owner' is exact — every
    # pre-M24 user registered their own tenant and is its sole member.
    role: Mapped[str] = mapped_column(String(16), default="owner")
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
    # provenance: upload | crawl | pdf | catalog
    kind: Mapped[str] = mapped_column(String(16), default="upload")
    # M20: structured catalog fields for knowledge_kind=product rows
    # ({name, sku, price, features, url}) — provenance stays in `kind`.
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
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
    # M20 retrieval facet: product|tone|faq|claim|doc (kind-filtered RAG).
    kind: Mapped[str] = mapped_column(String(16), default="doc")
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


class PublishJob(Base):
    """Publish-queue entry. Compiled ONLY from approved/edited drafts and only
    with full metadata + campaign code (constitution rule 3); the text is
    frozen at compile time so what was approved is exactly what ships.
    Dispatch is idempotent and resumable — a transient channel failure leaves
    the job 'queued' with attempts incremented, never lost."""

    __tablename__ = "publish_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    draft_id: Mapped[str] = mapped_column(ForeignKey("content_drafts.id"), index=True)
    channel: Mapped[str] = mapped_column(String(16))  # telegram | bale | eitaa
    chat_id: Mapped[str] = mapped_column(String(128))
    campaign_code: Mapped[str] = mapped_column(String(120))
    utm: Mapped[dict] = mapped_column(JSON, default=dict)
    # Landing link with UTM params compiled in (M9) — null when the post
    # carries no link.
    landing_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    # Render request for image posts ({template, size}) — null for text posts.
    image_spec: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    text: Mapped[str] = mapped_column(String(8000))
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)  # queued|sent
    attempts: Mapped[int] = mapped_column(default=0)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # M21 dead-letter clock (ADR 0039): stamped on the FIRST ChannelSendError,
    # cleared on success; age > MAX_PUBLISH_RETRY_HOURS moves the job to
    # 'stalled' — silence/kill-blocked passes never touch it.
    first_failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class OnboardingInterview(Base):
    __tablename__ = "onboarding_interviews"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), unique=True, index=True)
    answers: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class CrmLeadSync(Base):
    """Per-tenant watermark for the CRM lead bridge (M13): the last click
    count already delivered per (campaign, month). Sync sends only the delta
    beyond the watermark, so replays after a drop are silent (rule 8)."""

    __tablename__ = "crm_lead_syncs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "campaign_code", "month", name="uq_crm_sync_scope"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    campaign_code: Mapped[str] = mapped_column(String(120))
    month: Mapped[str] = mapped_column(String(7))  # YYYY-MM
    last_count: Mapped[int] = mapped_column(default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class TrendItem(Base):
    """Trend Radar row (M14): one market keyword per tenant, upserted on
    (tenant_id, keyword, source) so a replayed refresh never duplicates
    (rule 8). فاز ۲ real source layers write through the same shape."""

    __tablename__ = "trend_items"
    __table_args__ = (
        UniqueConstraint("tenant_id", "keyword", "source", name="uq_trend_scope"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    keyword: Mapped[str] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(40), default="simulated")
    score: Mapped[int] = mapped_column(default=0)  # 0..100
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class VisualPrompt(Base):
    """Visual Prompt Studio row (M15): a marketing brief deterministically
    expanded into a professional image/video generative-model prompt."""

    __tablename__ = "visual_prompts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    kind: Mapped[str] = mapped_column(String(8))  # image | video
    brief: Mapped[dict] = mapped_column(JSON, default=dict)
    prompt_text: Mapped[str] = mapped_column(String(4000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ChannelConnection(Base):
    """Per-brand social channel connection (M16). The secret is sealed with
    the vault (ADR 0033) — plaintext never touches the row; non-secret
    settings live in config. One row per (tenant, channel)."""

    __tablename__ = "channel_connections"
    __table_args__ = (
        UniqueConstraint("tenant_id", "channel", name="uq_channel_scope"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    channel: Mapped[str] = mapped_column(String(16))  # telegram|bale|eitaa|wordpress
    status: Mapped[str] = mapped_column(String(16), default="disconnected")
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    secret_sealed: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class AiNewsItem(Base):
    """AI-industry headline for the operator (M19) — a GLOBAL platform table,
    deliberately tenant-free: it never holds tenant data, and only the admin
    gate can read it (ADR 0036). Upserted on url so a replayed poll never
    duplicates (rule 8)."""

    __tablename__ = "ai_news_items"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(500))
    url: Mapped[str] = mapped_column(String(1000), unique=True, index=True)
    source: Mapped[str] = mapped_column(String(200), default="simulated")
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class TenantInvite(Base):
    """Multi-seat invite (M24, ADR 0038). v1 rule: valid ONLY for emails with
    no existing user — accounts never move across tenants (rule 6). The raw
    token is shown once at creation; only its sha256 lands here."""

    __tablename__ = "tenant_invites"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[str] = mapped_column(String(16))  # editor | observer
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class MediaAsset(Base):
    """Generated/rendered visual (M21, ADR 0039). Bytes live under
    MEDIA_STORAGE_DIR (never in the DB); rule 1 covers images too — only an
    approved asset may attach to a publish job. wp_media_id is the stage-1
    receipt that makes the WordPress two-step resumable (rule 8)."""

    __tablename__ = "media_assets"
    __table_args__ = (UniqueConstraint("tenant_id", "sha256", name="uq_media_scope"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="generated")  # generated | rendered
    prompt_id: Mapped[str | None] = mapped_column(
        ForeignKey("visual_prompts.id"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(32), default="")
    model: Mapped[str] = mapped_column(String(64), default="")
    prompt_text: Mapped[str] = mapped_column(String(4000), default="")
    alt_text: Mapped[str] = mapped_column(String(300), default="")
    sha256: Mapped[str] = mapped_column(String(64))
    mime: Mapped[str] = mapped_column(String(32), default="image/png")
    width: Mapped[int | None] = mapped_column(nullable=True)
    height: Mapped[int | None] = mapped_column(nullable=True)
    storage_path: Mapped[str] = mapped_column(String(500))
    wp_media_id: Mapped[int | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft|approved|attached
    cost_usd: Mapped[float] = mapped_column(default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CampaignChannelMetric(Base):
    """Daily per-tenant metrics snapshot (M22, ADR 0041). One row per
    (tenant, campaign, channel, source, day) — the beat's replays upsert
    (rule 8). posts_sent carries the CTR denominator; day is app-TZ for
    umami rows and source-local for ga4 (documented, never mixed)."""

    __tablename__ = "campaign_channel_metrics"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "campaign_code", "channel", "source", "day",
            name="uq_metric_scope",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    campaign_code: Mapped[str] = mapped_column(String(120))
    channel: Mapped[str] = mapped_column(String(16))  # telegram|bale|eitaa|wordpress|web
    day: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD
    source: Mapped[str] = mapped_column(String(16))  # umami | ga4
    clicks: Mapped[int] = mapped_column(default=0)
    sessions: Mapped[int] = mapped_column(default=0)
    impressions: Mapped[int | None] = mapped_column(nullable=True)  # NULL = source can't know
    posts_sent: Mapped[int] = mapped_column(default=0)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TenantLearning(Base):
    """Versioned learned directives (M22). The distiller writes a new version
    ONLY when content_hash changes (rule-8 no-op replays); prompts inject
    the latest active version, capped — the owner can retire any version."""

    __tablename__ = "tenant_learnings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "version", name="uq_learning_scope"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    version: Mapped[int] = mapped_column()
    directives: Mapped[list] = mapped_column(JSON, default=list)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | retired
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AnalyticsCursor(Base):
    """Per-(tenant, provider) ingestion watermark (M22 slice B, ADR 0042):
    the last FULLY-ingested provider-local day. Advances only after a day
    lands completely, so a crash or malformed payload resumes exactly at
    the failed day (rule 8) — never a re-write, never a skip."""

    __tablename__ = "analytics_cursors"
    __table_args__ = (UniqueConstraint("tenant_id", "provider", name="uq_cursor_scope"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    provider: Mapped[str] = mapped_column(String(16))  # ga4 | umami (next)
    cursor: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD, provider-local
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

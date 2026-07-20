"""campaign metrics snapshots + tenant learnings (M22)

Revision ID: 0017
Revises: 0016
Create Date: 2026-07-20

Chain order is EXECUTION order (ADR 0038 precedent): … 0019 → 0016 → 0017.
campaign_channel_metrics: daily per-tenant snapshot, upsert-keyed
(tenant, campaign, channel, source, day) with the posts_sent CTR
denominator in-row. tenant_learnings: versioned distilled directives with
content_hash so replayed distill runs are no-ops (rule 8).
"""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "campaign_channel_metrics",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.String(32), sa.ForeignKey("tenants.id"), index=True),
        sa.Column("campaign_code", sa.String(120), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("day", sa.String(10), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("clicks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sessions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("impressions", sa.Integer(), nullable=True),
        sa.Column("posts_sent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "campaign_code", "channel", "source", "day",
            name="uq_metric_scope",
        ),
    )
    op.create_table(
        "tenant_learnings",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.String(32), sa.ForeignKey("tenants.id"), index=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("directives", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "version", name="uq_learning_scope"),
    )


def downgrade() -> None:
    op.drop_table("tenant_learnings")
    op.drop_table("campaign_channel_metrics")

"""publish jobs queue

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-06

"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "publish_jobs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.String(32), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "draft_id", sa.String(32), sa.ForeignKey("content_drafts.id"), nullable=False
        ),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("chat_id", sa.String(128), nullable=False),
        sa.Column("campaign_code", sa.String(120), nullable=False),
        sa.Column("utm", sa.JSON(), nullable=False),
        sa.Column("text", sa.String(8000), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_publish_jobs_tenant_id", "publish_jobs", ["tenant_id"])
    op.create_index("ix_publish_jobs_draft_id", "publish_jobs", ["draft_id"])
    op.create_index("ix_publish_jobs_status", "publish_jobs", ["status"])


def downgrade() -> None:
    op.drop_table("publish_jobs")

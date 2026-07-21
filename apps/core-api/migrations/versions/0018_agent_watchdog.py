"""M23 watchdog: autonomy dial, draft origin, agent_actions

Revision ID: 0018
Revises: 0020
Create Date: 2026-07-21

The number was reserved by the pentarchy design; the chain links in
EXECUTION order (ADR 0038 precedent), so 0018 lands after 0020.
autonomy_level server-defaults to 0 (L0): every existing tenant stays
fully manual until its owner explicitly raises the dial (rule 1).
"""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("autonomy_level", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "content_drafts",
        sa.Column("origin", sa.String(16), nullable=False, server_default="human"),
    )
    op.create_table(
        "agent_actions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(32),
            sa.ForeignKey("tenants.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("kind", sa.String(24), nullable=False, server_default="brief_proposal"),
        sa.Column(
            "trend_item_id",
            sa.String(32),
            sa.ForeignKey("trend_items.id"),
            nullable=False,
        ),
        sa.Column(
            "draft_id", sa.String(32), sa.ForeignKey("content_drafts.id"), nullable=True
        ),
        sa.Column("score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("relevance", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rationale", sa.String(1000), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="proposed"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "trend_item_id", "kind", name="uq_agent_scope"),
    )


def downgrade() -> None:
    op.drop_table("agent_actions")
    op.drop_column("content_drafts", "origin")
    op.drop_column("tenants", "autonomy_level")

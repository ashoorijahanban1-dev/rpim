"""content drafts + A0 apprentice events

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-06

"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "content_drafts",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.String(32), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("brief", sa.JSON(), nullable=False),
        sa.Column("context_refs", sa.JSON(), nullable=False),
        sa.Column("text", sa.String(8000), nullable=False),
        sa.Column("edited_text", sa.String(8000), nullable=True),
        sa.Column("flag_unsourced", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_content_drafts_tenant_id", "content_drafts", ["tenant_id"])
    op.create_table(
        "apprentice_events",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.String(32), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_apprentice_events_tenant_id", "apprentice_events", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("apprentice_events")
    op.drop_table("content_drafts")

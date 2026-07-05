"""brand brain: brain_sources + brain_chunks (embedding as JSON — slice A)

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-05

"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "brain_sources",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.String(32), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "content_hash"),
    )
    op.create_index("ix_brain_sources_tenant_id", "brain_sources", ["tenant_id"])
    op.create_index("ix_brain_sources_content_hash", "brain_sources", ["content_hash"])
    op.create_table(
        "brain_chunks",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.String(32), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("source_id", sa.String(32), sa.ForeignKey("brain_sources.id"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("text", sa.String(4000), nullable=False),
        sa.Column("embedding", sa.JSON(), nullable=False),
    )
    op.create_index("ix_brain_chunks_tenant_id", "brain_chunks", ["tenant_id"])
    op.create_index("ix_brain_chunks_source_id", "brain_chunks", ["source_id"])


def downgrade() -> None:
    op.drop_table("brain_chunks")
    op.drop_table("brain_sources")

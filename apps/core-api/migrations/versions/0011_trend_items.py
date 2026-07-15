"""trend radar items (M14)

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-15

"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trend_items",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.String(32), sa.ForeignKey("tenants.id"), index=True),
        sa.Column("keyword", sa.String(200), nullable=False),
        sa.Column("source", sa.String(40), nullable=False, server_default="simulated"),
        sa.Column("score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "keyword", "source", name="uq_trend_scope"),
    )


def downgrade() -> None:
    op.drop_table("trend_items")

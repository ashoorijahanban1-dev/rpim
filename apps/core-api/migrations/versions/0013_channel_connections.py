"""per-brand channel connections (M16 hub)

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-15

"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "channel_connections",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.String(32), sa.ForeignKey("tenants.id"), index=True),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="disconnected"),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.Column("secret_sealed", sa.String(2000), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "channel", name="uq_channel_scope"),
    )


def downgrade() -> None:
    op.drop_table("channel_connections")

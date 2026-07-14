"""crm lead sync watermarks (M13 lead bridge)

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-14

"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crm_lead_syncs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.String(32), sa.ForeignKey("tenants.id"), index=True),
        sa.Column("campaign_code", sa.String(120), nullable=False),
        sa.Column("month", sa.String(7), nullable=False),
        sa.Column("last_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "campaign_code", "month", name="uq_crm_sync_scope"),
    )


def downgrade() -> None:
    op.drop_table("crm_lead_syncs")

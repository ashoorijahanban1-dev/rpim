"""onboarding interview table + brand_profiles.allowed_claims

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-05

"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "brand_profiles",
        sa.Column("allowed_claims", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    op.create_table(
        "onboarding_interviews",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.String(32), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("answers", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_onboarding_interviews_tenant_id", "onboarding_interviews", ["tenant_id"], unique=True
    )


def downgrade() -> None:
    op.drop_table("onboarding_interviews")
    op.drop_column("brand_profiles", "allowed_claims")

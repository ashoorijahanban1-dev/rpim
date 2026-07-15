"""visual prompt studio (M15)

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-15

"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "visual_prompts",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.String(32), sa.ForeignKey("tenants.id"), index=True),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("brief", sa.JSON(), nullable=True),
        sa.Column("prompt_text", sa.String(4000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("visual_prompts")

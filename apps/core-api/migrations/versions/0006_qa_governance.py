"""governance flags (silence/kill) + content_drafts.qa

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-06

"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("content_drafts", sa.Column("qa", sa.JSON(), nullable=True))
    op.create_table(
        "governance_flags",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("scope", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("scope", "kind"),
    )
    op.create_index("ix_governance_flags_scope", "governance_flags", ["scope"])


def downgrade() -> None:
    op.drop_table("governance_flags")
    op.drop_column("content_drafts", "qa")

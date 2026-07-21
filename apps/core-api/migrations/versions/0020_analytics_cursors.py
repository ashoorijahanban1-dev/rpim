"""analytics ingestion cursors (M22 slice B)

Revision ID: 0020
Revises: 0017
Create Date: 2026-07-21

Chain continues in execution order (ADR 0038 precedent); 0018 stays
reserved for M23. One watermark row per (tenant, provider) — the pull
loop's exact-resume point (rule 8).
"""

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analytics_cursors",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.String(32), sa.ForeignKey("tenants.id"), index=True),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("cursor", sa.String(10), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "provider", name="uq_cursor_scope"),
    )


def downgrade() -> None:
    op.drop_table("analytics_cursors")

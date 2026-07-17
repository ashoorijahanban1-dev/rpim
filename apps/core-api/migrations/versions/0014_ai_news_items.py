"""global AI-industry news items (M19 radar)

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-17

"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_news_items",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("url", sa.String(1000), nullable=False, unique=True, index=True),
        sa.Column("source", sa.String(200), nullable=False, server_default="simulated"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("ai_news_items")

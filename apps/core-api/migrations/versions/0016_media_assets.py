"""media assets + publish dead-letter clock (M21)

Revision ID: 0016
Revises: 0019
Create Date: 2026-07-19

Chain order is EXECUTION order (ADR 0038 precedent): 0015 → 0019 → 0016.
media_assets holds visual metadata only — bytes live on the media volume;
wp_media_id is the WordPress stage-1 receipt (rule 8 resumability).
publish_jobs.first_failed_at backs the 24h time-based dead-letter.
"""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "media_assets",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.String(32), sa.ForeignKey("tenants.id"), index=True),
        sa.Column("kind", sa.String(16), nullable=False, server_default="generated"),
        sa.Column(
            "prompt_id", sa.String(32), sa.ForeignKey("visual_prompts.id"), nullable=True
        ),
        sa.Column("provider", sa.String(32), nullable=False, server_default=""),
        sa.Column("model", sa.String(64), nullable=False, server_default=""),
        sa.Column("prompt_text", sa.String(4000), nullable=False, server_default=""),
        sa.Column("alt_text", sa.String(300), nullable=False, server_default=""),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("mime", sa.String(32), nullable=False, server_default="image/png"),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("storage_path", sa.String(500), nullable=False),
        sa.Column("wp_media_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "sha256", name="uq_media_scope"),
    )
    op.add_column(
        "publish_jobs",
        sa.Column("first_failed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("publish_jobs", "first_failed_at")
    op.drop_table("media_assets")

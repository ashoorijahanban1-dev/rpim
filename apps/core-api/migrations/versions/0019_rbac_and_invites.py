"""RBAC roles + tenant invites (M24)

Revision ID: 0019
Revises: 0015
Create Date: 2026-07-18

Numbered 0019 per the pentarchy design's per-epic assignment (M24=0019);
execution order ran M24 right after M20, so 0016-0018 are intentionally
reserved for M21-M23 in DESIGN numbering but the alembic CHAIN continues
0015 → 0019 → 0020… (revision links, not filenames, define order).

users.role backfills 'owner' — semantically exact: every pre-M24 user
registered their own tenant and is its sole member. Vault v2 (AES-GCM-256)
ships in the same milestone but needs no schema change.
"""

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("role", sa.String(16), nullable=False, server_default="owner"),
    )
    op.create_table(
        "tenant_invites",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.String(32), sa.ForeignKey("tenants.id"), index=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("tenant_invites")
    op.drop_column("users", "role")

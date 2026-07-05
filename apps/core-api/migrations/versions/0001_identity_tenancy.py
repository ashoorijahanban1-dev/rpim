"""identity & tenancy: tenants, users, brand_profiles (+ pgvector extension)

Revision ID: 0001
Revises:
Create Date: 2026-07-05

"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ADR 0006: the extension is also bootstrapped by initdb on fresh volumes;
    # this idempotent statement covers databases not created via initdb.
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "tenants",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(200), nullable=False),
        sa.Column("tenant_id", sa.String(32), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])
    op.create_table(
        "brand_profiles",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.String(32), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("tone", sa.String(4000), nullable=False),
        sa.Column("personas", sa.JSON(), nullable=False),
        sa.Column("lexicon", sa.JSON(), nullable=False),
        sa.Column("forbidden_claims", sa.JSON(), nullable=False),
        sa.Column("red_lines", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_brand_profiles_tenant_id", "brand_profiles", ["tenant_id"], unique=True)


def downgrade() -> None:
    op.drop_table("brand_profiles")
    op.drop_table("users")
    op.drop_table("tenants")

"""kind-centric brand brain (M20)

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-18

brain_sources.meta stores the structured product catalog for
knowledge_kind=product rows; brain_chunks.kind is the retrieval facet
(product|tone|faq|claim|doc). Existing chunks backfill to 'doc' via the
server default — provenance in brain_sources.kind is untouched.
"""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("brain_sources", sa.Column("meta", sa.JSON(), nullable=True))
    op.add_column(
        "brain_chunks",
        sa.Column("kind", sa.String(16), nullable=False, server_default="doc"),
    )
    op.create_index(
        "ix_brain_chunks_tenant_kind", "brain_chunks", ["tenant_id", "kind"]
    )


def downgrade() -> None:
    op.drop_index("ix_brain_chunks_tenant_kind", table_name="brain_chunks")
    op.drop_column("brain_chunks", "kind")
    op.drop_column("brain_sources", "meta")

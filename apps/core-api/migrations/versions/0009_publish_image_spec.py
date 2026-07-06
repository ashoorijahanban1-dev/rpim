"""publish jobs image spec (image posts)

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-06

"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("publish_jobs", sa.Column("image_spec", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("publish_jobs", "image_spec")

"""publish jobs landing url (M9 measurement)

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-06

"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("publish_jobs", sa.Column("landing_url", sa.String(1000), nullable=True))


def downgrade() -> None:
    op.drop_column("publish_jobs", "landing_url")

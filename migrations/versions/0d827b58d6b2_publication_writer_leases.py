"""Fence independent writers of one workbook; expiry requires reconciliation."""

import sqlalchemy as sa
from alembic import op

revision = "0d827b58d6b2"
down_revision = "9b310e003c80"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("publications", sa.Column("lease_owner", sa.String(100), nullable=True))
    op.add_column("publications", sa.Column("lease_until", sa.String(40), nullable=True))
    op.add_column(
        "publications", sa.Column("state", sa.String(30), nullable=False, server_default="idle")
    )


def downgrade() -> None:
    op.drop_column("publications", "state")
    op.drop_column("publications", "lease_until")
    op.drop_column("publications", "lease_owner")

"""Add signal classification to stored signals."""

import sqlalchemy as sa
from alembic import op


revision = "b1a2c3d4e5f6"
down_revision = "9c4e7b2a1d6f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("signal", sa.Column("signal_type", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("signal", "signal_type")

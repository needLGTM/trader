"""Enable persisted extended-hours intent for day-trade alerts."""

import sqlalchemy as sa
from alembic import op


revision = "d3e4f5a6b7c8"
down_revision = "c2d3e4f5a6b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("order", sa.Column("fill_outside_rth", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("order", "fill_outside_rth")
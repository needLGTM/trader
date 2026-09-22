"""Add execution pairing and realized PnL fields."""

import sqlalchemy as sa
from alembic import op


revision = "c2d3e4f5a6b7"
down_revision = "b1a2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("execution", sa.Column("execution_type", sa.String(), nullable=False, server_default="ENTRY"))
    op.add_column("execution", sa.Column("matched_execution_ids", sa.String(), nullable=True))
    op.add_column("execution", sa.Column("realized_pnl", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("execution", "realized_pnl")
    op.drop_column("execution", "matched_execution_ids")
    op.drop_column("execution", "execution_type")
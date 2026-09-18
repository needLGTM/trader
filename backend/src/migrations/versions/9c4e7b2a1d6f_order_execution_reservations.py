"""Add persistent order execution state and risk reservations."""

import sqlalchemy as sa
from alembic import op


revision = "9c4e7b2a1d6f"
down_revision = "7f2d9a1c4e6b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("order", sa.Column("order_type", sa.String(), nullable=False, server_default="LIMIT"))
    op.add_column("order", sa.Column("tif", sa.String(), nullable=False, server_default="DAY"))
    op.add_column("order", sa.Column("acc_type", sa.String(), nullable=True))
    op.add_column("order", sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("order", sa.Column("submitted_at", sa.DateTime(), nullable=True))

    op.create_table(
        "riskreservation",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("broker_env", sa.String(), nullable=False, server_default="SIMULATE"),
        sa.Column("acc_type", sa.String(), nullable=False, server_default="MARGIN"),
        sa.Column("qty", sa.Float(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="RESERVED"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_riskreservation_order_id", "riskreservation", ["order_id"])
    op.create_index("ix_riskreservation_ticker", "riskreservation", ["ticker"])
    op.create_index("ix_riskreservation_broker_env", "riskreservation", ["broker_env"])
    op.create_index("ix_riskreservation_acc_type", "riskreservation", ["acc_type"])
    op.create_index("ix_riskreservation_status", "riskreservation", ["status"])


def downgrade() -> None:
    op.drop_index("ix_riskreservation_status", table_name="riskreservation")
    op.drop_index("ix_riskreservation_acc_type", table_name="riskreservation")
    op.drop_index("ix_riskreservation_broker_env", table_name="riskreservation")
    op.drop_index("ix_riskreservation_ticker", table_name="riskreservation")
    op.drop_index("ix_riskreservation_order_id", table_name="riskreservation")
    op.drop_table("riskreservation")
    op.drop_column("order", "submitted_at")
    op.drop_column("order", "attempts")
    op.drop_column("order", "acc_type")
    op.drop_column("order", "tif")
    op.drop_column("order", "order_type")
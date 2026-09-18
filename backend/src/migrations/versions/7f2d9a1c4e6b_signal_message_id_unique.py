"""Make signal ingestion idempotent under concurrent requests."""

from alembic import op


revision = "7f2d9a1c4e6b"
down_revision = "54dc401d91a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Preserve the oldest row before adding the constraint to existing databases.
    op.execute(
        """
        DELETE FROM signal
        WHERE id IN (
            SELECT id
            FROM (
                SELECT id,
                       ROW_NUMBER() OVER (PARTITION BY message_id ORDER BY id) AS duplicate_rank
                FROM signal
            ) duplicates
            WHERE duplicate_rank > 1
        )
        """
    )
    op.create_index("ix_signal_message_id_unique", "signal", ["message_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_signal_message_id_unique", table_name="signal")
"""add autopilot audit log

Revision ID: 1ef3c4d5a6b7
Revises: 54dc401d91a2
"""
from alembic import op
import sqlalchemy as sa

revision = "1ef3c4d5a6b7"
down_revision = "54dc401d91a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auditevent",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column("data", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("auditevent")

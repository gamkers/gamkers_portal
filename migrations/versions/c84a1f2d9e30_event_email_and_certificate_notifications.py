"""Add event details and certificate email status

Revision ID: c84a1f2d9e30
Revises: f45559f86783
Create Date: 2026-11-02 21:40:00
"""
from alembic import op
import sqlalchemy as sa


revision = "c84a1f2d9e30"
down_revision = "f45559f86783"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("form") as batch_op:
        batch_op.add_column(sa.Column("event_start_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("event_end_at", sa.DateTime(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "event_timezone",
                sa.String(length=64),
                server_default="Asia/Kolkata",
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("event_location", sa.String(length=255), nullable=True))

    with op.batch_alter_table("certificate_record") as batch_op:
        batch_op.add_column(
            sa.Column(
                "notification_status",
                sa.String(length=16),
                server_default="skipped",
                nullable=False,
            )
        )


def downgrade():
    with op.batch_alter_table("certificate_record") as batch_op:
        batch_op.drop_column("notification_status")

    with op.batch_alter_table("form") as batch_op:
        batch_op.drop_column("event_location")
        batch_op.drop_column("event_timezone")
        batch_op.drop_column("event_end_at")
        batch_op.drop_column("event_start_at")

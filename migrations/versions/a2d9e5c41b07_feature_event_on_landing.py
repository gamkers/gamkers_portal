"""Let admins feature one event in the landing page's next-event ticket.

Revision ID: a2d9e5c41b07
Revises: f3a710d9c642
"""
from alembic import op
import sqlalchemy as sa


revision = "a2d9e5c41b07"
down_revision = "f3a710d9c642"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "form",
        sa.Column("is_featured", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    op.drop_column("form", "is_featured")

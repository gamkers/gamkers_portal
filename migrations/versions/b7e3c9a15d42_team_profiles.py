"""Invite-only GAMKERS team profiles with shareable team IDs.

Revision ID: b7e3c9a15d42
Revises: a2d9e5c41b07
"""
from alembic import op
import sqlalchemy as sa


revision = "b7e3c9a15d42"
down_revision = "a2d9e5c41b07"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "team_profile",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organization.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("team_id", sa.String(length=16), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("role_title", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("bio", sa.Text(), nullable=False),
        sa.Column("photo_path", sa.String(length=80)),
        sa.Column("socials", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="invited"),
        sa.Column("invited_by_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("joined_at", sa.DateTime()),
        sa.Column("last_login_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organization_id", "email", name="uq_team_profile_email"),
    )
    op.create_index("ix_team_profile_organization_id", "team_profile", ["organization_id"])
    op.create_index("ix_team_profile_team_id", "team_profile", ["team_id"], unique=True)
    op.create_table(
        "team_profile_token",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "profile_id",
            sa.Integer(),
            sa.ForeignKey("team_profile.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("purpose", sa.String(length=12), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_team_profile_token_profile_id", "team_profile_token", ["profile_id"])


def downgrade():
    op.drop_index("ix_team_profile_token_profile_id", table_name="team_profile_token")
    op.drop_table("team_profile_token")
    op.drop_index("ix_team_profile_team_id", table_name="team_profile")
    op.drop_index("ix_team_profile_organization_id", table_name="team_profile")
    op.drop_table("team_profile")

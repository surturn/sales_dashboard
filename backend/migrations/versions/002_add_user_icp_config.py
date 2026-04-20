"""add user_icp_config table

Revision ID: 002_add_user_icp_config
Revises: 001_initial
Create Date: 2026-04-06
"""

from alembic import op
import sqlalchemy as sa


revision = "002_add_user_icp_config"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_icp_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, unique=True),
        sa.Column("icp_config", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("user_icp_config")

"""add user_support_config table

Revision ID: 004_add_user_support_config
Revises: 003_add_outreach_approval_queue
Create Date: 2026-04-16
"""

from alembic import op
import sqlalchemy as sa


revision = "004_add_user_support_config"
down_revision = "003_add_outreach_approval_queue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_support_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kb_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_user_support_config_user_id", "user_support_config", ["user_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_user_support_config_user_id", table_name="user_support_config")
    op.drop_table("user_support_config")

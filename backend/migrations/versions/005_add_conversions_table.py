"""add conversions table

Revision ID: 005_add_conversions
Revises: 004_add_user_support_config
Create Date: 2026-04-18
"""

from alembic import op
import sqlalchemy as sa


revision = "005_add_conversions"
down_revision = "004_add_user_support_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id"), nullable=True),
        sa.Column("recorded_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("revenue", sa.Numeric(12, 2), nullable=True),
    )
    op.create_index("ix_conversions_user_id", "conversions", ["user_id"])
    op.create_index("ix_conversions_lead_id", "conversions", ["lead_id"])


def downgrade() -> None:
    op.drop_index("ix_conversions_lead_id", table_name="conversions")
    op.drop_index("ix_conversions_user_id", table_name="conversions")
    op.drop_table("conversions")

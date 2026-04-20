"""add outreach_approval_queue table

Revision ID: 003_add_outreach_approval_queue
Revises: 002_add_user_icp_config
Create Date: 2026-04-10
"""

from alembic import op
import sqlalchemy as sa


revision = "003_add_outreach_approval_queue"
down_revision = "002_add_user_icp_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "outreach_approval_queue",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id"), nullable=True),
        sa.Column("lead_email", sa.String(length=255), nullable=False),
        sa.Column("draft", sa.Text(), nullable=False),
        sa.Column("final_draft", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("thread_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_outreach_approval_queue_user_id", "outreach_approval_queue", ["user_id"])
    op.create_index("ix_outreach_approval_queue_lead_id", "outreach_approval_queue", ["lead_id"])
    op.create_index("ix_outreach_approval_queue_lead_email", "outreach_approval_queue", ["lead_email"])
    op.create_index("ix_outreach_approval_queue_thread_id", "outreach_approval_queue", ["thread_id"])


def downgrade() -> None:
    op.drop_index("ix_outreach_approval_queue_thread_id", table_name="outreach_approval_queue")
    op.drop_index("ix_outreach_approval_queue_lead_email", table_name="outreach_approval_queue")
    op.drop_index("ix_outreach_approval_queue_lead_id", table_name="outreach_approval_queue")
    op.drop_index("ix_outreach_approval_queue_user_id", table_name="outreach_approval_queue")
    op.drop_table("outreach_approval_queue")

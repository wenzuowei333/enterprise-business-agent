"""add unique per-user exception case conversations

Revision ID: 20260901_0100
Revises: 20260831_0100
Create Date: 2026-09-01 09:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260901_0100"
down_revision = "20260831_0100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_ai_conversation_case_context",
        "ai_conversation",
        ["actor_user_id", "channel", "source_system", "context_type", "context_id"],
        unique=True,
        postgresql_where=sa.text("context_type = 'exception_case' AND actor_user_id IS NOT NULL"),
        sqlite_where=sa.text("context_type = 'exception_case' AND actor_user_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_ai_conversation_case_context", table_name="ai_conversation")

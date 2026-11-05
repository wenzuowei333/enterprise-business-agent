"""add streaming AI chat run lifecycle

Revision ID: 20260831_0100
Revises: 20260830_0200
Create Date: 2026-08-31 10:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260831_0100"
down_revision = "20260830_0200"
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "ai_chat_run",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_no", sa.String(120), nullable=False, unique=True),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("ai_conversation.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_message_id", sa.Integer(), sa.ForeignKey("ai_message.id", ondelete="CASCADE"), nullable=False),
        sa.Column("assistant_message_id", sa.Integer(), sa.ForeignKey("ai_message.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("client_request_id", sa.String(120), nullable=False),
        sa.Column("request_id", sa.String(160), nullable=False, unique=True),
        sa.Column("status", sa.String(40), nullable=False, server_default="created"),
        sa.Column("model_name", sa.String(160)),
        sa.Column("provider_request_id", sa.String(160)),
        sa.Column("usage_json", JSON),
        sa.Column("error_code", sa.String(120)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("actor_user_id", "client_request_id", name="uq_ai_chat_run_actor_client_request"),
        sa.CheckConstraint(
            "status IN ('created','streaming','completed','cancel_requested','cancelled','failed')",
            name="ck_ai_chat_run_status",
        ),
    )
    for column in (
        "run_no", "conversation_id", "user_message_id", "assistant_message_id",
        "actor_user_id", "client_request_id", "request_id", "status", "model_name",
        "provider_request_id", "error_code", "started_at", "completed_at", "cancelled_at",
    ):
        op.create_index(f"ix_ai_chat_run_{column}", "ai_chat_run", [column])
    op.create_index("ix_ai_chat_run_actor_created", "ai_chat_run", ["actor_user_id", "created_at"])


def downgrade() -> None:
    op.drop_table("ai_chat_run")

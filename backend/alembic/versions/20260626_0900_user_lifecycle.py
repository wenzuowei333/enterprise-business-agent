"""user lifecycle management

Revision ID: 20260626_0900
Revises: 20260624_0125
Create Date: 2026-06-26 09:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "20260626_0900"
down_revision = "20260624_0125"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("status", sa.String(length=40), nullable=False, server_default="active"))
    op.add_column("users", sa.Column("disabled_reason", sa.Text()))
    op.add_column("users", sa.Column("cancelled_reason", sa.Text()))
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True)))
    op.add_column("users", sa.Column("last_login_ip", sa.String(length=80)))
    op.add_column("users", sa.Column("password_updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()))
    op.add_column("users", sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")))
    op.add_column("users", sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")))
    op.add_column("users", sa.Column("cancelled_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")))
    op.add_column("users", sa.Column("cancelled_at", sa.DateTime(timezone=True)))
    op.create_index("ix_users_status", "users", ["status"])
    op.create_index("ix_users_created_by", "users", ["created_by"])
    op.create_index("ix_users_updated_by", "users", ["updated_by"])
    op.create_index("ix_users_cancelled_by", "users", ["cancelled_by"])
    op.execute("update users set status = case when is_active then 'active' else 'disabled' end")

    op.create_table(
        "user_status_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("old_status", sa.String(length=40)),
        sa.Column("new_status", sa.String(length=40), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("changed_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("changed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_user_status_history_user_id", "user_status_history", ["user_id"])
    op.create_index("ix_user_status_history_changed_by", "user_status_history", ["changed_by"])
    op.create_index("ix_user_status_history_changed_at", "user_status_history", ["changed_at"])


def downgrade() -> None:
    op.drop_table("user_status_history")
    op.drop_index("ix_users_cancelled_by", table_name="users")
    op.drop_index("ix_users_updated_by", table_name="users")
    op.drop_index("ix_users_created_by", table_name="users")
    op.drop_index("ix_users_status", table_name="users")
    op.drop_column("users", "cancelled_at")
    op.drop_column("users", "cancelled_by")
    op.drop_column("users", "updated_by")
    op.drop_column("users", "created_by")
    op.drop_column("users", "password_updated_at")
    op.drop_column("users", "last_login_ip")
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "cancelled_reason")
    op.drop_column("users", "disabled_reason")
    op.drop_column("users", "status")

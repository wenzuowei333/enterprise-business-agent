"""mobile sync operations and device metadata

Revision ID: 20260710_0200
Revises: 20260710_0100
Create Date: 2026-07-10 15:30:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260710_0200"
down_revision = "20260710_0100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("mobile_session", sa.Column("app_version", sa.String(length=40), nullable=True))
    op.add_column("mobile_session", sa.Column("android_version", sa.String(length=40), nullable=True))
    op.add_column("mobile_session", sa.Column("device_model", sa.String(length=160), nullable=True))
    op.add_column("mobile_session", sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("mobile_session", sa.Column("notification_preferences_json", sa.JSON(), nullable=True))

    op.create_table(
        "mobile_operation_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("device_id", sa.String(length=160), nullable=False),
        sa.Column("client_operation_id", sa.String(length=160), nullable=False),
        sa.Column("action_type", sa.String(length=80), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="processing"),
        sa.Column("resource_type", sa.String(length=80), nullable=True),
        sa.Column("resource_id", sa.String(length=160), nullable=True),
        sa.Column("request_json", sa.JSON(), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("error_json", sa.JSON(), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "user_id",
            "device_id",
            "client_operation_id",
            name="uq_mobile_operation_user_device_client",
        ),
    )
    for column in (
        "user_id",
        "device_id",
        "client_operation_id",
        "action_type",
        "status",
        "resource_type",
        "resource_id",
    ):
        op.create_index(f"ix_mobile_operation_log_{column}", "mobile_operation_log", [column])


def downgrade() -> None:
    op.drop_table("mobile_operation_log")
    op.drop_column("mobile_session", "notification_preferences_json")
    op.drop_column("mobile_session", "last_sync_at")
    op.drop_column("mobile_session", "device_model")
    op.drop_column("mobile_session", "android_version")
    op.drop_column("mobile_session", "app_version")

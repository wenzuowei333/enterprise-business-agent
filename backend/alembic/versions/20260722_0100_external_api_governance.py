"""external API governance, rotation, and usage logs

Revision ID: 20260722_0100
Revises: 20260721_0100
Create Date: 2026-07-22 01:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260722_0100"
down_revision = "20260721_0100"
branch_labels = None
depends_on = None


json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.add_column(
        "external_api_keys",
        sa.Column("can_read_changes", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("external_api_keys", sa.Column("permission_scopes", json_type, nullable=True))
    op.add_column(
        "external_api_keys",
        sa.Column("rate_limit_per_minute", sa.Integer(), nullable=False, server_default="60"),
    )
    op.add_column(
        "external_api_keys",
        sa.Column("daily_request_limit", sa.Integer(), nullable=False, server_default="10000"),
    )
    op.add_column("external_api_keys", sa.Column("previous_key_prefix", sa.String(length=32), nullable=True))
    op.add_column("external_api_keys", sa.Column("previous_key_hash", sa.String(length=128), nullable=True))
    op.add_column("external_api_keys", sa.Column("previous_key_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("external_api_keys", sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "external_api_keys",
        sa.Column("rotation_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_external_api_keys_previous_key_hash",
        "external_api_keys",
        ["previous_key_hash"],
        unique=True,
    )
    op.create_index(
        "ix_external_api_keys_previous_key_expires_at",
        "external_api_keys",
        ["previous_key_expires_at"],
    )
    op.create_index("ix_external_api_keys_rotated_at", "external_api_keys", ["rotated_at"])

    op.create_table(
        "external_api_usage_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "key_id",
            sa.String(length=120),
            sa.ForeignKey("external_api_keys.key_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("request_id", sa.String(length=120), nullable=False),
        sa.Column("endpoint", sa.String(length=255), nullable=False),
        sa.Column("method", sa.String(length=12), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("response_count", sa.Integer(), nullable=True),
        sa.Column("client_ip", sa.String(length=80), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_external_api_usage_log_key_id", "external_api_usage_log", ["key_id"])
    op.create_index("ix_external_api_usage_log_request_id", "external_api_usage_log", ["request_id"], unique=True)
    op.create_index("ix_external_api_usage_log_endpoint", "external_api_usage_log", ["endpoint"])
    op.create_index("ix_external_api_usage_log_status_code", "external_api_usage_log", ["status_code"])
    op.create_index("ix_external_api_usage_log_created_at", "external_api_usage_log", ["created_at"])
    op.create_index("ix_external_api_usage_key_created", "external_api_usage_log", ["key_id", "created_at"])


def downgrade() -> None:
    op.drop_table("external_api_usage_log")
    op.drop_index("ix_external_api_keys_rotated_at", table_name="external_api_keys")
    op.drop_index("ix_external_api_keys_previous_key_expires_at", table_name="external_api_keys")
    op.drop_index("ix_external_api_keys_previous_key_hash", table_name="external_api_keys")
    for name in (
        "rotation_count",
        "rotated_at",
        "previous_key_expires_at",
        "previous_key_hash",
        "previous_key_prefix",
        "daily_request_limit",
        "rate_limit_per_minute",
        "permission_scopes",
        "can_read_changes",
    ):
        op.drop_column("external_api_keys", name)

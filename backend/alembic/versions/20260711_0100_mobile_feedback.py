"""mobile feedback and adoption support

Revision ID: 20260711_0100
Revises: 20260710_0200
Create Date: 2026-07-11 10:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260711_0100"
down_revision = "20260710_0200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mobile_feedback",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("current_route", sa.String(length=240), nullable=True),
        sa.Column("request_id", sa.String(length=120), nullable=True),
        sa.Column("app_version", sa.String(length=40), nullable=True),
        sa.Column("android_version", sa.String(length=40), nullable=True),
        sa.Column("device_model", sa.String(length=160), nullable=True),
        sa.Column("screenshot_path", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="open"),
        sa.Column("handler_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    for column in ("user_id", "category", "request_id", "app_version", "status", "handler_user_id", "resolved_at"):
        op.create_index(f"ix_mobile_feedback_{column}", "mobile_feedback", [column])
    op.create_table(
        "mobile_telemetry_record",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("installation_hash", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("route", sa.String(length=240), nullable=True),
        sa.Column("code", sa.String(length=120), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("app_version", sa.String(length=40), nullable=True),
        sa.Column("device_model", sa.String(length=160), nullable=True),
        sa.Column("android_version", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    for column in ("installation_hash", "event_type", "occurred_at", "route", "code", "app_version", "created_at"):
        op.create_index(f"ix_mobile_telemetry_record_{column}", "mobile_telemetry_record", [column])


def downgrade() -> None:
    op.drop_table("mobile_telemetry_record")
    op.drop_table("mobile_feedback")

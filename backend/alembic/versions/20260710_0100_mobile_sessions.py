"""mobile device sessions

Revision ID: 20260710_0100
Revises: 20260706_0300
Create Date: 2026-07-10 09:30:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260710_0100"
down_revision = "20260706_0300"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mobile_session",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("device_id", sa.String(length=160), nullable=False),
        sa.Column("device_name", sa.String(length=200), nullable=True),
        sa.Column("refresh_token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_address", sa.String(length=80), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    for column in ("user_id", "device_id", "refresh_token_hash", "expires_at", "revoked_at"):
        op.create_index(f"ix_mobile_session_{column}", "mobile_session", [column])


def downgrade() -> None:
    op.drop_table("mobile_session")

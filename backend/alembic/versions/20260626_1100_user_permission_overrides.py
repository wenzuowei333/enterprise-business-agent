"""user permission overrides

Revision ID: 20260626_1100
Revises: 20260626_0900
Create Date: 2026-06-26 11:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "20260626_1100"
down_revision = "20260626_0900"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_permission_overrides",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("permission_id", sa.Integer(), sa.ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("effect", sa.String(length=20), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "permission_id", name="uq_user_permission_overrides_user_permission"),
    )
    op.create_index("ix_user_permission_overrides_user_id", "user_permission_overrides", ["user_id"])
    op.create_index("ix_user_permission_overrides_permission_id", "user_permission_overrides", ["permission_id"])
    op.create_index("ix_user_permission_overrides_effect", "user_permission_overrides", ["effect"])


def downgrade() -> None:
    op.drop_table("user_permission_overrides")

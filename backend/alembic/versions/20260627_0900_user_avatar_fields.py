"""user avatar fields

Revision ID: 20260627_0900
Revises: 20260626_1900
Create Date: 2026-06-27 09:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "20260627_0900"
down_revision = "20260626_1900"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("avatar_url", sa.String(length=500)))
    op.add_column("users", sa.Column("avatar_object_key", sa.String(length=500)))
    op.add_column("users", sa.Column("avatar_updated_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("users", "avatar_updated_at")
    op.drop_column("users", "avatar_object_key")
    op.drop_column("users", "avatar_url")

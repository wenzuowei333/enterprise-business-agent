"""customer profile fields

Revision ID: 20260626_1900
Revises: 20260626_1100
Create Date: 2026-06-26 19:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "20260626_1900"
down_revision = "20260626_1100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("customer_master", sa.Column("contact_channel", sa.String(length=255)))
    op.add_column("customer_master", sa.Column("customer_group_name", sa.String(length=255)))
    op.add_column("customer_master", sa.Column("profile_updated_at", sa.DateTime(timezone=True)))
    op.add_column("customer_master", sa.Column("base_remark", sa.Text()))
    op.create_index("ix_customer_master_customer_group_name", "customer_master", ["customer_group_name"])
    op.execute("UPDATE customer_master SET profile_updated_at = updated_at WHERE profile_updated_at IS NULL")


def downgrade() -> None:
    op.drop_index("ix_customer_master_customer_group_name", table_name="customer_master")
    op.drop_column("customer_master", "base_remark")
    op.drop_column("customer_master", "profile_updated_at")
    op.drop_column("customer_master", "customer_group_name")
    op.drop_column("customer_master", "contact_channel")

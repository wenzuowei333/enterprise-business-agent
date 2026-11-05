"""customer business update form fields

Revision ID: 20260630_1600
Revises: 20260630_1000
Create Date: 2026-06-30 16:00:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260630_1600"
down_revision = "20260630_1000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("customer_business_profile", sa.Column("filled_by", sa.String(length=120), nullable=True))
    op.add_column("customer_business_profile", sa.Column("update_type", sa.String(length=80), nullable=True))
    op.add_column("customer_business_profile", sa.Column("business_status_tags", postgresql.JSONB(), nullable=True))
    op.create_index("ix_customer_business_profile_filled_by", "customer_business_profile", ["filled_by"])
    op.create_index("ix_customer_business_profile_update_type", "customer_business_profile", ["update_type"])

    op.add_column("customer_business_product", sa.Column("change_type", sa.String(length=40), nullable=True))
    op.create_index("ix_customer_business_product_change_type", "customer_business_product", ["change_type"])

    op.add_column("customer_business_profile_history", sa.Column("update_type", sa.String(length=80), nullable=True))
    op.add_column("customer_business_profile_history", sa.Column("filled_by", sa.String(length=120), nullable=True))
    op.create_index("ix_customer_business_profile_history_update_type", "customer_business_profile_history", ["update_type"])
    op.create_index("ix_customer_business_profile_history_filled_by", "customer_business_profile_history", ["filled_by"])


def downgrade() -> None:
    op.drop_index("ix_customer_business_profile_history_filled_by", table_name="customer_business_profile_history")
    op.drop_index("ix_customer_business_profile_history_update_type", table_name="customer_business_profile_history")
    op.drop_column("customer_business_profile_history", "filled_by")
    op.drop_column("customer_business_profile_history", "update_type")

    op.drop_index("ix_customer_business_product_change_type", table_name="customer_business_product")
    op.drop_column("customer_business_product", "change_type")

    op.drop_index("ix_customer_business_profile_update_type", table_name="customer_business_profile")
    op.drop_index("ix_customer_business_profile_filled_by", table_name="customer_business_profile")
    op.drop_column("customer_business_profile", "business_status_tags")
    op.drop_column("customer_business_profile", "update_type")
    op.drop_column("customer_business_profile", "filled_by")

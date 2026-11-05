"""customer business profile tables

Revision ID: 20260630_1000
Revises: 20260629_1830
Create Date: 2026-06-30 10:00:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260630_1000"
down_revision = "20260629_1830"
branch_labels = None
depends_on = None


def created_at_column() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def updated_at_column() -> sa.Column:
    return sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "customer_business_profile",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_code", sa.String(length=120), sa.ForeignKey("customer_master.customer_code", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_name_snapshot", sa.String(length=255), nullable=False),
        sa.Column("business_customer_type", sa.String(length=120)),
        sa.Column("confirmed_at", sa.Date()),
        sa.Column("update_source", sa.String(length=80)),
        sa.Column("current_salesperson", sa.String(length=120)),
        sa.Column("sales_channels", postgresql.JSONB()),
        sa.Column("business_status_label", sa.String(length=160)),
        sa.Column("business_status_note", sa.Text()),
        sa.Column("other_status_label", sa.String(length=160)),
        sa.Column("other_status_note", sa.Text()),
        sa.Column("latest_update_note", sa.Text()),
        sa.Column("version_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("confirmed_by", sa.String(length=120)),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("updated_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        created_at_column(),
        updated_at_column(),
    )
    op.create_index("ix_customer_business_profile_customer_code", "customer_business_profile", ["customer_code"], unique=True)
    op.create_index("ix_customer_business_profile_business_customer_type", "customer_business_profile", ["business_customer_type"])
    op.create_index("ix_customer_business_profile_confirmed_at", "customer_business_profile", ["confirmed_at"])
    op.create_index("ix_customer_business_profile_update_source", "customer_business_profile", ["update_source"])
    op.create_index("ix_customer_business_profile_current_salesperson", "customer_business_profile", ["current_salesperson"])
    op.create_index("ix_customer_business_profile_business_status_label", "customer_business_profile", ["business_status_label"])
    op.create_index("ix_customer_business_profile_other_status_label", "customer_business_profile", ["other_status_label"])
    op.create_index("ix_customer_business_profile_version_no", "customer_business_profile", ["version_no"])
    op.create_index("ix_customer_business_profile_confirmed_by", "customer_business_profile", ["confirmed_by"])
    op.create_index("ix_customer_business_profile_created_by_user_id", "customer_business_profile", ["created_by_user_id"])
    op.create_index("ix_customer_business_profile_updated_by_user_id", "customer_business_profile", ["updated_by_user_id"])

    op.create_table(
        "customer_business_product",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_code", sa.String(length=120), sa.ForeignKey("customer_master.customer_code", ondelete="CASCADE"), nullable=False),
        sa.Column("product_category", sa.String(length=160)),
        sa.Column("spec", sa.String(length=255)),
        sa.Column("common_brand", sa.String(length=160)),
        sa.Column("monthly_usage", sa.String(length=120)),
        sa.Column("price_sensitivity", sa.String(length=40)),
        sa.Column("cooperation_status", sa.String(length=40)),
        sa.Column("opportunity_note", sa.Text()),
        sa.Column("last_confirmed_at", sa.Date()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        created_at_column(),
        updated_at_column(),
    )
    op.create_index("ix_customer_business_product_customer_code", "customer_business_product", ["customer_code"])
    op.create_index("ix_customer_business_product_product_category", "customer_business_product", ["product_category"])
    op.create_index("ix_customer_business_product_common_brand", "customer_business_product", ["common_brand"])
    op.create_index("ix_customer_business_product_price_sensitivity", "customer_business_product", ["price_sensitivity"])
    op.create_index("ix_customer_business_product_cooperation_status", "customer_business_product", ["cooperation_status"])
    op.create_index("ix_customer_business_product_last_confirmed_at", "customer_business_product", ["last_confirmed_at"])
    op.create_index("ix_customer_business_product_sort_order", "customer_business_product", ["sort_order"])
    op.create_index("ix_customer_business_product_is_active", "customer_business_product", ["is_active"])

    op.create_table(
        "customer_business_profile_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_code", sa.String(length=120), sa.ForeignKey("customer_master.customer_code", ondelete="CASCADE"), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("update_source", sa.String(length=80)),
        sa.Column("update_note", sa.Text()),
        sa.Column("confirmed_by", sa.String(length=120)),
        sa.Column("snapshot_json", postgresql.JSONB()),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        created_at_column(),
    )
    op.create_index("ix_customer_business_profile_history_customer_code", "customer_business_profile_history", ["customer_code"])
    op.create_index("ix_customer_business_profile_history_version_no", "customer_business_profile_history", ["version_no"])
    op.create_index("ix_customer_business_profile_history_update_source", "customer_business_profile_history", ["update_source"])
    op.create_index("ix_customer_business_profile_history_confirmed_by", "customer_business_profile_history", ["confirmed_by"])
    op.create_index("ix_customer_business_profile_history_created_by_user_id", "customer_business_profile_history", ["created_by_user_id"])
    op.create_index("ix_customer_business_profile_history_created_at", "customer_business_profile_history", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_customer_business_profile_history_created_at", table_name="customer_business_profile_history")
    op.drop_index("ix_customer_business_profile_history_created_by_user_id", table_name="customer_business_profile_history")
    op.drop_index("ix_customer_business_profile_history_confirmed_by", table_name="customer_business_profile_history")
    op.drop_index("ix_customer_business_profile_history_update_source", table_name="customer_business_profile_history")
    op.drop_index("ix_customer_business_profile_history_version_no", table_name="customer_business_profile_history")
    op.drop_index("ix_customer_business_profile_history_customer_code", table_name="customer_business_profile_history")
    op.drop_table("customer_business_profile_history")

    op.drop_index("ix_customer_business_product_is_active", table_name="customer_business_product")
    op.drop_index("ix_customer_business_product_sort_order", table_name="customer_business_product")
    op.drop_index("ix_customer_business_product_last_confirmed_at", table_name="customer_business_product")
    op.drop_index("ix_customer_business_product_cooperation_status", table_name="customer_business_product")
    op.drop_index("ix_customer_business_product_price_sensitivity", table_name="customer_business_product")
    op.drop_index("ix_customer_business_product_common_brand", table_name="customer_business_product")
    op.drop_index("ix_customer_business_product_product_category", table_name="customer_business_product")
    op.drop_index("ix_customer_business_product_customer_code", table_name="customer_business_product")
    op.drop_table("customer_business_product")

    op.drop_index("ix_customer_business_profile_updated_by_user_id", table_name="customer_business_profile")
    op.drop_index("ix_customer_business_profile_created_by_user_id", table_name="customer_business_profile")
    op.drop_index("ix_customer_business_profile_confirmed_by", table_name="customer_business_profile")
    op.drop_index("ix_customer_business_profile_version_no", table_name="customer_business_profile")
    op.drop_index("ix_customer_business_profile_other_status_label", table_name="customer_business_profile")
    op.drop_index("ix_customer_business_profile_business_status_label", table_name="customer_business_profile")
    op.drop_index("ix_customer_business_profile_current_salesperson", table_name="customer_business_profile")
    op.drop_index("ix_customer_business_profile_update_source", table_name="customer_business_profile")
    op.drop_index("ix_customer_business_profile_confirmed_at", table_name="customer_business_profile")
    op.drop_index("ix_customer_business_profile_business_customer_type", table_name="customer_business_profile")
    op.drop_index("ix_customer_business_profile_customer_code", table_name="customer_business_profile")
    op.drop_table("customer_business_profile")


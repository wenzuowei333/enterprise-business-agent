"""data calendar upload rules

Revision ID: 20260629_1830
Revises: 20260629_0100
Create Date: 2026-06-29 18:30:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260629_1830"
down_revision = "20260629_0100"
branch_labels = None
depends_on = None


def created_at_column() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def updated_at_column() -> sa.Column:
    return sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "data_calendar_rule",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rule_code", sa.String(length=120), nullable=False),
        sa.Column("file_type", sa.String(length=80), nullable=False),
        sa.Column("label", sa.String(length=160), nullable=False),
        sa.Column("action_layer", sa.String(length=40), nullable=False, server_default="blue"),
        sa.Column("frequency", sa.String(length=40), nullable=False, server_default="daily"),
        sa.Column("deadline_hour", sa.Integer()),
        sa.Column("owner_role", sa.String(length=120), nullable=False, server_default="数据中台"),
        sa.Column("owner_user_ids", postgresql.JSONB()),
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("remark", sa.Text()),
        created_at_column(),
        updated_at_column(),
    )
    op.create_index("ix_data_calendar_rule_rule_code", "data_calendar_rule", ["rule_code"], unique=True)
    op.create_index("ix_data_calendar_rule_file_type", "data_calendar_rule", ["file_type"])
    op.create_index("ix_data_calendar_rule_action_layer", "data_calendar_rule", ["action_layer"])
    op.create_index("ix_data_calendar_rule_frequency", "data_calendar_rule", ["frequency"])
    op.create_index("ix_data_calendar_rule_is_required", "data_calendar_rule", ["is_required"])
    op.create_index("ix_data_calendar_rule_is_enabled", "data_calendar_rule", ["is_enabled"])

    op.execute(
        """
        INSERT INTO data_calendar_rule
          (rule_code, file_type, label, action_layer, frequency, deadline_hour, owner_role, is_required, is_enabled, sort_order, remark)
        VALUES
          ('daily_sales_detail', 'sales_detail', '销售统计明细', 'blue', 'daily', 18, '数据中台', true, true, 10, '每日销售过程数据。'),
          ('daily_purchase_detail', 'purchase_detail', '采购明细', 'blue', 'daily', 18, '数据中台', true, true, 20, '每日采购过程数据。'),
          ('daily_account_balance', 'account_balance', '往来对账', 'blue', 'daily', 18, '数据中台', true, true, 30, '每日应收应付往来核验。'),
          ('daily_inventory_snapshot', 'inventory_snapshot', '库存状况快照', 'green', 'daily', 18, '数据中台', true, true, 40, '每日库存核验快照。'),
          ('ondemand_employee_profile', 'employee_profile', '员工档案', 'gray', 'ondemand', NULL, '数据中台', false, true, 110, '按需补录或批量更新。'),
          ('ondemand_customer_master', 'customer_master', '客户档案', 'gray', 'ondemand', NULL, '数据中台', false, true, 120, '按需补录或批量更新。'),
          ('ondemand_product_master', 'product_master', '商品档案', 'gray', 'ondemand', NULL, '数据中台', false, true, 130, '按需补录或批量更新。'),
          ('ondemand_supplier_master', 'supplier_master', '供应商档案', 'gray', 'ondemand', NULL, '数据中台', false, true, 140, '按需补录或批量更新。')
        ON CONFLICT (rule_code) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_data_calendar_rule_is_enabled", table_name="data_calendar_rule")
    op.drop_index("ix_data_calendar_rule_is_required", table_name="data_calendar_rule")
    op.drop_index("ix_data_calendar_rule_frequency", table_name="data_calendar_rule")
    op.drop_index("ix_data_calendar_rule_action_layer", table_name="data_calendar_rule")
    op.drop_index("ix_data_calendar_rule_file_type", table_name="data_calendar_rule")
    op.drop_index("ix_data_calendar_rule_rule_code", table_name="data_calendar_rule")
    op.drop_table("data_calendar_rule")

"""process data import tables

Revision ID: 20260628_0100
Revises: 20260627_0900
Create Date: 2026-06-28 01:00:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260628_0100"
down_revision = "20260627_0900"
branch_labels = None
depends_on = None


def created_at_column() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def base_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("import_batch.id", ondelete="CASCADE"), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("data_date", sa.Date()),
    ]


def money_column(name: str) -> sa.Column:
    return sa.Column(name, sa.Numeric(18, 2))


def quantity_column(name: str) -> sa.Column:
    return sa.Column(name, sa.Numeric(18, 4))


def upgrade() -> None:
    op.create_table(
        "sales_detail",
        *base_columns(),
        sa.Column("document_no", sa.String(length=160)),
        sa.Column("document_date", sa.Date()),
        sa.Column("posted_at", sa.DateTime(timezone=True)),
        sa.Column("document_type", sa.String(length=120)),
        sa.Column("branch_name", sa.String(length=160)),
        sa.Column("department_name", sa.String(length=160)),
        sa.Column("settlement_unit_code", sa.String(length=120)),
        sa.Column("settlement_unit_name", sa.String(length=255)),
        sa.Column("customer_code", sa.String(length=120)),
        sa.Column("customer_name", sa.String(length=255)),
        sa.Column("employee_name", sa.String(length=120)),
        sa.Column("warehouse_name", sa.String(length=160)),
        sa.Column("product_code", sa.String(length=120)),
        sa.Column("product_name", sa.String(length=255)),
        quantity_column("sale_qty_base"),
        quantity_column("sale_qty_unit"),
        quantity_column("sale_qty_float"),
        money_column("amount_before_discount"),
        sa.Column("unit_price_after_discount", sa.Numeric(18, 4)),
        money_column("amount_after_discount"),
        money_column("amount_tax_total"),
        money_column("tax_amount"),
        sa.Column("cost_unit_price", sa.Numeric(18, 4)),
        money_column("cost_amount"),
        money_column("expense_allocated_amount"),
        money_column("gross_profit"),
        sa.Column("gross_margin_rate", sa.Numeric(18, 4)),
        sa.Column("prepared_by", sa.String(length=120)),
        sa.Column("note", sa.Text()),
        sa.Column("summary", sa.Text()),
        sa.Column("reconciliation_mark", sa.String(length=80)),
        sa.Column("raw_row_json", postgresql.JSONB()),
        created_at_column(),
        sa.UniqueConstraint("batch_id", "row_number", name="uq_sales_detail_batch_row"),
    )
    op.create_index("ix_sales_detail_batch_id", "sales_detail", ["batch_id"])
    op.create_index("ix_sales_detail_data_date", "sales_detail", ["data_date"])
    op.create_index("ix_sales_detail_document_no", "sales_detail", ["document_no"])
    op.create_index("ix_sales_detail_document_date", "sales_detail", ["document_date"])
    op.create_index("ix_sales_detail_customer_code", "sales_detail", ["customer_code"])
    op.create_index("ix_sales_detail_product_code", "sales_detail", ["product_code"])
    op.create_index("ix_sales_detail_employee_name", "sales_detail", ["employee_name"])
    op.create_index("ix_sales_detail_warehouse_name", "sales_detail", ["warehouse_name"])

    op.create_table(
        "purchase_detail",
        *base_columns(),
        sa.Column("document_no", sa.String(length=160)),
        sa.Column("document_date", sa.Date()),
        sa.Column("posted_at", sa.DateTime(timezone=True)),
        sa.Column("document_type", sa.String(length=120)),
        sa.Column("branch_name", sa.String(length=160)),
        sa.Column("department_name", sa.String(length=160)),
        sa.Column("settlement_unit_code", sa.String(length=120)),
        sa.Column("settlement_unit_name", sa.String(length=255)),
        sa.Column("supplier_code", sa.String(length=120)),
        sa.Column("supplier_name", sa.String(length=255)),
        sa.Column("employee_name", sa.String(length=120)),
        sa.Column("warehouse_name", sa.String(length=160)),
        sa.Column("product_code", sa.String(length=120)),
        sa.Column("product_name", sa.String(length=255)),
        quantity_column("purchase_qty_base"),
        quantity_column("purchase_qty_unit"),
        quantity_column("purchase_qty_float"),
        sa.Column("unit_price", sa.Numeric(18, 4)),
        money_column("amount_after_discount"),
        money_column("amount_tax_total"),
        money_column("tax_amount"),
        sa.Column("tax_rate", sa.Numeric(18, 4)),
        money_column("purchase_amount"),
        money_column("discount_amount"),
        sa.Column("prepared_note", sa.Text()),
        sa.Column("summary", sa.Text()),
        sa.Column("remark", sa.Text()),
        sa.Column("reconciliation_mark", sa.String(length=80)),
        sa.Column("raw_row_json", postgresql.JSONB()),
        created_at_column(),
        sa.UniqueConstraint("batch_id", "row_number", name="uq_purchase_detail_batch_row"),
    )
    op.create_index("ix_purchase_detail_batch_id", "purchase_detail", ["batch_id"])
    op.create_index("ix_purchase_detail_data_date", "purchase_detail", ["data_date"])
    op.create_index("ix_purchase_detail_document_no", "purchase_detail", ["document_no"])
    op.create_index("ix_purchase_detail_document_date", "purchase_detail", ["document_date"])
    op.create_index("ix_purchase_detail_supplier_code", "purchase_detail", ["supplier_code"])
    op.create_index("ix_purchase_detail_product_code", "purchase_detail", ["product_code"])
    op.create_index("ix_purchase_detail_employee_name", "purchase_detail", ["employee_name"])
    op.create_index("ix_purchase_detail_warehouse_name", "purchase_detail", ["warehouse_name"])

    op.create_table(
        "inventory_snapshot",
        *base_columns(),
        sa.Column("product_code", sa.String(length=120)),
        sa.Column("product_name", sa.String(length=255)),
        sa.Column("barcode", sa.String(length=160)),
        sa.Column("default_supplier", sa.String(length=255)),
        sa.Column("unit_relation", sa.String(length=255)),
        quantity_column("stock_qty"),
        sa.Column("stock_base_unit", sa.String(length=80)),
        quantity_column("stock_inventory_qty"),
        sa.Column("stock_inventory_unit", sa.String(length=80)),
        quantity_column("locked_base_qty"),
        sa.Column("inventory_status", sa.String(length=80)),
        quantity_column("float_qty"),
        sa.Column("float_unit", sa.String(length=80)),
        sa.Column("average_cost", sa.Numeric(18, 4)),
        money_column("cost_amount"),
        quantity_column("auxiliary_qty"),
        sa.Column("raw_row_json", postgresql.JSONB()),
        created_at_column(),
        sa.UniqueConstraint("batch_id", "row_number", name="uq_inventory_snapshot_batch_row"),
    )
    op.create_index("ix_inventory_snapshot_batch_id", "inventory_snapshot", ["batch_id"])
    op.create_index("ix_inventory_snapshot_data_date", "inventory_snapshot", ["data_date"])
    op.create_index("ix_inventory_snapshot_product_code", "inventory_snapshot", ["product_code"])
    op.create_index("ix_inventory_snapshot_barcode", "inventory_snapshot", ["barcode"])
    op.create_index("ix_inventory_snapshot_default_supplier", "inventory_snapshot", ["default_supplier"])
    op.create_index("ix_inventory_snapshot_inventory_status", "inventory_snapshot", ["inventory_status"])

    op.create_table(
        "account_balance_snapshot",
        *base_columns(),
        sa.Column("settlement_unit_code", sa.String(length=120)),
        sa.Column("settlement_unit_name", sa.String(length=255)),
        money_column("current_opening_balance"),
        money_column("current_amount"),
        money_column("current_closing_balance"),
        money_column("ar_opening_balance"),
        money_column("ar_current_amount"),
        money_column("ar_balance"),
        money_column("ap_opening_balance"),
        money_column("ap_current_amount"),
        money_column("ap_balance"),
        money_column("advance_receipt_opening_balance"),
        money_column("advance_receipt_current_amount"),
        money_column("advance_receipt_balance"),
        money_column("advance_payment_opening_balance"),
        money_column("advance_payment_current_amount"),
        money_column("advance_payment_balance"),
        sa.Column("raw_row_json", postgresql.JSONB()),
        created_at_column(),
        sa.UniqueConstraint("batch_id", "row_number", name="uq_account_balance_snapshot_batch_row"),
    )
    op.create_index("ix_account_balance_snapshot_batch_id", "account_balance_snapshot", ["batch_id"])
    op.create_index("ix_account_balance_snapshot_data_date", "account_balance_snapshot", ["data_date"])
    op.create_index("ix_account_balance_snapshot_settlement_unit_code", "account_balance_snapshot", ["settlement_unit_code"])
    op.create_index("ix_account_balance_snapshot_settlement_unit_name", "account_balance_snapshot", ["settlement_unit_name"])


def downgrade() -> None:
    op.drop_table("account_balance_snapshot")
    op.drop_table("inventory_snapshot")
    op.drop_table("purchase_detail")
    op.drop_table("sales_detail")

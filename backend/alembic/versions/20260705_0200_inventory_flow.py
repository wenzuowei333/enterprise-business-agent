"""inventory flow ledger

Revision ID: 20260705_0200
Revises: 20260705_0100
Create Date: 2026-07-05 11:30:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260705_0200"
down_revision = "20260705_0100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("inventory_snapshot", sa.Column("warehouse_name", sa.String(length=160), nullable=True))
    op.add_column("inventory_snapshot", sa.Column("warehouse_scope", sa.String(length=40), nullable=False, server_default="unknown"))
    op.create_index("ix_inventory_snapshot_warehouse_name", "inventory_snapshot", ["warehouse_name"])
    op.create_index("ix_inventory_snapshot_warehouse_scope", "inventory_snapshot", ["warehouse_scope"])

    op.add_column("inventory_check_row", sa.Column("warehouse_name", sa.String(length=160), nullable=True))
    op.create_index("ix_inventory_check_row_warehouse_name", "inventory_check_row", ["warehouse_name"])
    op.add_column("inventory_check_result", sa.Column("warehouse_name", sa.String(length=160), nullable=True))
    op.add_column("inventory_check_result", sa.Column("warehouse_scope", sa.String(length=40), nullable=True))
    op.create_index("ix_inventory_check_result_warehouse_name", "inventory_check_result", ["warehouse_name"])
    op.create_index("ix_inventory_check_result_warehouse_scope", "inventory_check_result", ["warehouse_scope"])

    op.create_table(
        "inventory_flow_ledger",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("data_date", sa.Date(), nullable=False),
        sa.Column("warehouse_name", sa.String(length=160), nullable=False),
        sa.Column("warehouse_scope", sa.String(length=40), nullable=False, server_default="specific"),
        sa.Column("product_code", sa.String(length=120), nullable=False),
        sa.Column("product_name", sa.String(length=255), nullable=True),
        sa.Column("opening_stock_qty", sa.Numeric(18, 4), nullable=True),
        sa.Column("purchase_qty", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("sales_qty", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("calculated_closing_qty", sa.Numeric(18, 4), nullable=True),
        sa.Column("snapshot_stock_qty", sa.Numeric(18, 4), nullable=True),
        sa.Column("diff_qty", sa.Numeric(18, 4), nullable=True),
        sa.Column("anomaly_type", sa.String(length=80), nullable=False, server_default="normal"),
        sa.Column("anomaly_flags", postgresql.JSONB(), nullable=True),
        sa.Column("source_batch_ids", postgresql.JSONB(), nullable=True),
        sa.Column("source_counts", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("data_date", "warehouse_name", "warehouse_scope", "product_code", name="uq_inventory_flow_day_wh_product"),
    )
    op.create_index("ix_inventory_flow_ledger_data_date", "inventory_flow_ledger", ["data_date"])
    op.create_index("ix_inventory_flow_ledger_warehouse_name", "inventory_flow_ledger", ["warehouse_name"])
    op.create_index("ix_inventory_flow_ledger_warehouse_scope", "inventory_flow_ledger", ["warehouse_scope"])
    op.create_index("ix_inventory_flow_ledger_product_code", "inventory_flow_ledger", ["product_code"])
    op.create_index("ix_inventory_flow_ledger_product_name", "inventory_flow_ledger", ["product_name"])
    op.create_index("ix_inventory_flow_ledger_anomaly_type", "inventory_flow_ledger", ["anomaly_type"])


def downgrade() -> None:
    op.drop_table("inventory_flow_ledger")
    op.drop_index("ix_inventory_check_result_warehouse_scope", table_name="inventory_check_result")
    op.drop_index("ix_inventory_check_result_warehouse_name", table_name="inventory_check_result")
    op.drop_column("inventory_check_result", "warehouse_scope")
    op.drop_column("inventory_check_result", "warehouse_name")
    op.drop_index("ix_inventory_check_row_warehouse_name", table_name="inventory_check_row")
    op.drop_column("inventory_check_row", "warehouse_name")
    op.drop_index("ix_inventory_snapshot_warehouse_scope", table_name="inventory_snapshot")
    op.drop_index("ix_inventory_snapshot_warehouse_name", table_name="inventory_snapshot")
    op.drop_column("inventory_snapshot", "warehouse_scope")
    op.drop_column("inventory_snapshot", "warehouse_name")

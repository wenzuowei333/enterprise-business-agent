"""stage2 master data import

Revision ID: 20260624_0125
Revises: 20260624_0055
Create Date: 2026-06-24 01:25:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260624_0125"
down_revision = "20260624_0055"
branch_labels = None
depends_on = None


def timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "import_batch",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_no", sa.String(length=80), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("file_type", sa.String(length=80), nullable=False),
        sa.Column("data_date", sa.Date()),
        sa.Column("export_date", sa.Date()),
        sa.Column("uploaded_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="uploaded"),
        sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("amount_total", sa.Numeric(18, 2)),
        sa.Column("raw_file_path", sa.String(length=500), nullable=False),
        sa.Column("header_json", postgresql.JSONB()),
        sa.Column("preview_json", postgresql.JSONB()),
        sa.Column("mapping_json", postgresql.JSONB()),
        *timestamp_columns(),
    )
    op.create_index("ix_import_batch_batch_no", "import_batch", ["batch_no"], unique=True)
    op.create_index("ix_import_batch_file_type", "import_batch", ["file_type"])
    op.create_index("ix_import_batch_uploaded_by", "import_batch", ["uploaded_by"])
    op.create_index("ix_import_batch_status", "import_batch", ["status"])

    op.create_table(
        "import_error",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("import_batch.id", ondelete="CASCADE"), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("error_type", sa.String(length=120), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("raw_row_json", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_import_error_batch_id", "import_error", ["batch_id"])
    op.create_index("ix_import_error_error_type", "import_error", ["error_type"])

    op.create_table(
        "customer_master",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_code", sa.String(length=120), nullable=False),
        sa.Column("customer_name", sa.String(length=255), nullable=False),
        sa.Column("customer_short_name", sa.String(length=255)),
        sa.Column("customer_type", sa.String(length=120)),
        sa.Column("region", sa.String(length=120)),
        sa.Column("salesperson_employee_code", sa.String(length=80)),
        sa.Column("salesperson_name", sa.String(length=120)),
        sa.Column("contact_name", sa.String(length=120)),
        sa.Column("contact_phone", sa.String(length=120)),
        sa.Column("address", sa.Text()),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="active"),
        sa.Column("source", sa.String(length=120)),
        *timestamp_columns(),
    )
    op.create_index("ix_customer_master_customer_code", "customer_master", ["customer_code"], unique=True)
    op.create_index("ix_customer_master_customer_name", "customer_master", ["customer_name"])
    op.create_index("ix_customer_master_customer_type", "customer_master", ["customer_type"])
    op.create_index("ix_customer_master_region", "customer_master", ["region"])
    op.create_index("ix_customer_master_salesperson_employee_code", "customer_master", ["salesperson_employee_code"])
    op.create_index("ix_customer_master_salesperson_name", "customer_master", ["salesperson_name"])
    op.create_index("ix_customer_master_status", "customer_master", ["status"])

    op.create_table(
        "customer_alias",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customer_master.id", ondelete="CASCADE"), nullable=False),
        sa.Column("alias_name", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=120)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("customer_id", "alias_name", name="uq_customer_alias_customer_alias"),
    )
    op.create_index("ix_customer_alias_customer_id", "customer_alias", ["customer_id"])
    op.create_index("ix_customer_alias_alias_name", "customer_alias", ["alias_name"])

    op.create_table(
        "product_master",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_code", sa.String(length=120), nullable=False),
        sa.Column("product_name", sa.String(length=255), nullable=False),
        sa.Column("spec", sa.String(length=255)),
        sa.Column("unit", sa.String(length=80)),
        sa.Column("category", sa.String(length=160)),
        sa.Column("brand", sa.String(length=160)),
        sa.Column("barcode", sa.String(length=160)),
        sa.Column("reference_sale_price", sa.Numeric(18, 4)),
        sa.Column("reference_cost", sa.Numeric(18, 4)),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="active"),
        sa.Column("source", sa.String(length=120)),
        *timestamp_columns(),
    )
    op.create_index("ix_product_master_product_code", "product_master", ["product_code"], unique=True)
    op.create_index("ix_product_master_product_name", "product_master", ["product_name"])
    op.create_index("ix_product_master_category", "product_master", ["category"])
    op.create_index("ix_product_master_brand", "product_master", ["brand"])
    op.create_index("ix_product_master_barcode", "product_master", ["barcode"])
    op.create_index("ix_product_master_status", "product_master", ["status"])

    op.create_table(
        "product_alias",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("product_master.id", ondelete="CASCADE"), nullable=False),
        sa.Column("alias_name", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=120)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("product_id", "alias_name", name="uq_product_alias_product_alias"),
    )
    op.create_index("ix_product_alias_product_id", "product_alias", ["product_id"])
    op.create_index("ix_product_alias_alias_name", "product_alias", ["alias_name"])

    op.create_table(
        "supplier_master",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("supplier_code", sa.String(length=120), nullable=False),
        sa.Column("supplier_name", sa.String(length=255), nullable=False),
        sa.Column("supplier_short_name", sa.String(length=255)),
        sa.Column("supplier_type", sa.String(length=120)),
        sa.Column("region", sa.String(length=120)),
        sa.Column("contact_name", sa.String(length=120)),
        sa.Column("contact_phone", sa.String(length=120)),
        sa.Column("address", sa.Text()),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="active"),
        sa.Column("source", sa.String(length=120)),
        *timestamp_columns(),
    )
    op.create_index("ix_supplier_master_supplier_code", "supplier_master", ["supplier_code"], unique=True)
    op.create_index("ix_supplier_master_supplier_name", "supplier_master", ["supplier_name"])
    op.create_index("ix_supplier_master_supplier_type", "supplier_master", ["supplier_type"])
    op.create_index("ix_supplier_master_region", "supplier_master", ["region"])
    op.create_index("ix_supplier_master_status", "supplier_master", ["status"])

    op.create_table(
        "supplier_alias",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("supplier_master.id", ondelete="CASCADE"), nullable=False),
        sa.Column("alias_name", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=120)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("supplier_id", "alias_name", name="uq_supplier_alias_supplier_alias"),
    )
    op.create_index("ix_supplier_alias_supplier_id", "supplier_alias", ["supplier_id"])
    op.create_index("ix_supplier_alias_alias_name", "supplier_alias", ["alias_name"])


def downgrade() -> None:
    op.drop_table("supplier_alias")
    op.drop_table("supplier_master")
    op.drop_table("product_alias")
    op.drop_table("product_master")
    op.drop_table("customer_alias")
    op.drop_table("customer_master")
    op.drop_table("import_error")
    op.drop_table("import_batch")

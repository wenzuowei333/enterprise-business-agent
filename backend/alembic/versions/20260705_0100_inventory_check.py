"""inventory check batches

Revision ID: 20260705_0100
Revises: 20260704_0300
Create Date: 2026-07-05 10:10:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260705_0100"
down_revision = "20260704_0300"
branch_labels = None
depends_on = None


PERMISSIONS = [
    ("inventory_check.view", "查看库存校验", "inventory_check", "view"),
    ("inventory_check.upload", "上传库存校验", "inventory_check", "upload"),
    ("inventory_check.export", "导出库存校验", "inventory_check", "export"),
]

ROLE_GRANTS = {
    "admin": ["inventory_check.view", "inventory_check.upload", "inventory_check.export"],
    "boss": ["inventory_check.view", "inventory_check.upload", "inventory_check.export"],
    "business_middle_office": ["inventory_check.view", "inventory_check.upload", "inventory_check.export"],
    "data_middle_office": ["inventory_check.view", "inventory_check.upload", "inventory_check.export"],
    "viewer": ["inventory_check.view"],
}


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def _created_at() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "inventory_check_batch",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_no", sa.String(length=80), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("data_date", sa.Date()),
        sa.Column("uploaded_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="completed"),
        sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("matched_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("difference_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("missing_in_system_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("missing_in_upload_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("invalid_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicate_upload_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("raw_file_path", sa.String(length=500), nullable=False),
        sa.Column("header_json", postgresql.JSONB()),
        sa.Column("mapping_json", postgresql.JSONB()),
        *_timestamps(),
    )
    op.create_index("ix_inventory_check_batch_batch_no", "inventory_check_batch", ["batch_no"], unique=True)
    op.create_index("ix_inventory_check_batch_data_date", "inventory_check_batch", ["data_date"])
    op.create_index("ix_inventory_check_batch_uploaded_by", "inventory_check_batch", ["uploaded_by"])
    op.create_index("ix_inventory_check_batch_status", "inventory_check_batch", ["status"])

    op.create_table(
        "inventory_check_row",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("inventory_check_batch.id", ondelete="CASCADE"), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("product_code", sa.String(length=120)),
        sa.Column("product_name", sa.String(length=255)),
        sa.Column("platform_stock_qty", sa.Numeric(18, 4)),
        sa.Column("row_status", sa.String(length=40), nullable=False, server_default="valid"),
        sa.Column("error_message", sa.Text()),
        sa.Column("raw_row_json", postgresql.JSONB()),
        _created_at(),
        sa.UniqueConstraint("batch_id", "row_number", name="uq_inventory_check_row_batch_row"),
    )
    op.create_index("ix_inventory_check_row_batch", "inventory_check_row", ["batch_id"])
    op.create_index("ix_inventory_check_row_product_code", "inventory_check_row", ["product_code"])
    op.create_index("ix_inventory_check_row_product_name", "inventory_check_row", ["product_name"])
    op.create_index("ix_inventory_check_row_status", "inventory_check_row", ["row_status"])

    op.create_table(
        "inventory_check_result",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("inventory_check_batch.id", ondelete="CASCADE"), nullable=False),
        sa.Column("result_type", sa.String(length=60), nullable=False),
        sa.Column("product_code", sa.String(length=120)),
        sa.Column("product_name", sa.String(length=255)),
        sa.Column("platform_stock_qty", sa.Numeric(18, 4)),
        sa.Column("system_stock_qty", sa.Numeric(18, 4)),
        sa.Column("diff_qty", sa.Numeric(18, 4)),
        sa.Column("system_data_date", sa.Date()),
        sa.Column("duplicate_in_upload", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source_row_numbers", postgresql.JSONB()),
        sa.Column("platform_row_json", postgresql.JSONB()),
        sa.Column("system_snapshot_json", postgresql.JSONB()),
        _created_at(),
    )
    op.create_index("ix_inventory_check_result_batch", "inventory_check_result", ["batch_id"])
    op.create_index("ix_inventory_check_result_type", "inventory_check_result", ["result_type"])
    op.create_index("ix_inventory_check_result_product_code", "inventory_check_result", ["product_code"])
    op.create_index("ix_inventory_check_result_product_name", "inventory_check_result", ["product_name"])
    op.create_index("ix_inventory_check_result_system_data_date", "inventory_check_result", ["system_data_date"])
    op.create_index("ix_inventory_check_result_duplicate", "inventory_check_result", ["duplicate_in_upload"])

    for code, name, resource_type, action_type in PERMISSIONS:
        op.execute(
            sa.text(
                """
                INSERT INTO permissions (permission_code, permission_name, resource_type, action_type, created_at, updated_at)
                VALUES (:code, :name, :resource_type, :action_type, now(), now())
                ON CONFLICT (permission_code) DO NOTHING
                """
            ).bindparams(code=code, name=name, resource_type=resource_type, action_type=action_type)
        )
    for role_code, permission_codes in ROLE_GRANTS.items():
        for permission_code in permission_codes:
            op.execute(
                sa.text(
                    """
                    INSERT INTO role_permissions (role_id, permission_id, created_at)
                    SELECT roles.id, permissions.id, now()
                    FROM roles
                    JOIN permissions ON permissions.permission_code = :permission_code
                    WHERE roles.role_code = :role_code
                    ON CONFLICT ON CONSTRAINT uq_role_permissions_role_permission DO NOTHING
                    """
                ).bindparams(role_code=role_code, permission_code=permission_code)
            )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DELETE FROM role_permissions
            USING permissions
            WHERE role_permissions.permission_id = permissions.id
              AND permissions.permission_code IN ('inventory_check.view', 'inventory_check.upload', 'inventory_check.export')
            """
        )
    )
    op.execute(sa.text("DELETE FROM permissions WHERE permission_code IN ('inventory_check.view', 'inventory_check.upload', 'inventory_check.export')"))
    op.drop_table("inventory_check_result")
    op.drop_table("inventory_check_row")
    op.drop_table("inventory_check_batch")

"""receivable snapshot workflow

Revision ID: 20260705_0300
Revises: 20260705_0200
Create Date: 2026-07-05 17:30:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260705_0300"
down_revision = "20260705_0200"
branch_labels = None
depends_on = None


PERMISSIONS = [
    ("receivable.view", "查看应收账款", "receivable", "view"),
    ("receivable.import", "导入应收账款", "receivable", "import"),
    ("receivable.check", "校验应收账款", "receivable", "check"),
    ("receivable.export", "导出应收账款", "receivable", "export"),
]

ROLE_GRANTS = {
    "admin": ["receivable.view", "receivable.import", "receivable.check", "receivable.export"],
    "boss": ["receivable.view", "receivable.import", "receivable.check", "receivable.export"],
    "business_middle_office": ["receivable.view", "receivable.import", "receivable.check", "receivable.export"],
    "data_middle_office": ["receivable.view", "receivable.import", "receivable.check", "receivable.export"],
    "viewer": ["receivable.view"],
}


def _created_at() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "receivable_snapshot",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("import_batch.id", ondelete="CASCADE"), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("data_date", sa.Date(), nullable=True),
        sa.Column("customer_code", sa.String(length=120), nullable=True),
        sa.Column("customer_name", sa.String(length=255), nullable=True),
        sa.Column("matched_customer_code", sa.String(length=120), nullable=True),
        sa.Column("matched_customer_name", sa.String(length=255), nullable=True),
        sa.Column("match_status", sa.String(length=60), nullable=False, server_default="pending"),
        sa.Column("ar_opening_balance", sa.Numeric(18, 2), nullable=True),
        sa.Column("ar_current_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("received_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("unreceived_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("ar_balance", sa.Numeric(18, 2), nullable=True),
        sa.Column("aging_label", sa.String(length=120), nullable=True),
        sa.Column("overdue_days", sa.Integer(), nullable=True),
        sa.Column("salesperson_name", sa.String(length=120), nullable=True),
        sa.Column("department_name", sa.String(length=160), nullable=True),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("raw_row_json", postgresql.JSONB(), nullable=True),
        _created_at(),
        sa.UniqueConstraint("batch_id", "row_number", name="uq_receivable_snapshot_batch_row"),
    )
    op.create_index("ix_receivable_snapshot_batch_id", "receivable_snapshot", ["batch_id"])
    op.create_index("ix_receivable_snapshot_data_date", "receivable_snapshot", ["data_date"])
    op.create_index("ix_receivable_snapshot_customer_code", "receivable_snapshot", ["customer_code"])
    op.create_index("ix_receivable_snapshot_customer_name", "receivable_snapshot", ["customer_name"])
    op.create_index("ix_receivable_snapshot_matched_customer_code", "receivable_snapshot", ["matched_customer_code"])
    op.create_index("ix_receivable_snapshot_matched_customer_name", "receivable_snapshot", ["matched_customer_name"])
    op.create_index("ix_receivable_snapshot_match_status", "receivable_snapshot", ["match_status"])
    op.create_index("ix_receivable_snapshot_ar_balance", "receivable_snapshot", ["ar_balance"])
    op.create_index("ix_receivable_snapshot_aging_label", "receivable_snapshot", ["aging_label"])
    op.create_index("ix_receivable_snapshot_overdue_days", "receivable_snapshot", ["overdue_days"])
    op.create_index("ix_receivable_snapshot_salesperson_name", "receivable_snapshot", ["salesperson_name"])
    op.create_index("ix_receivable_snapshot_department_name", "receivable_snapshot", ["department_name"])

    op.create_table(
        "receivable_check_result",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("import_batch.id", ondelete="CASCADE"), nullable=False),
        sa.Column("receivable_snapshot_id", sa.Integer(), sa.ForeignKey("receivable_snapshot.id", ondelete="CASCADE"), nullable=True),
        sa.Column("result_type", sa.String(length=80), nullable=False),
        sa.Column("severity", sa.String(length=40), nullable=False, server_default="warning"),
        sa.Column("data_date", sa.Date(), nullable=True),
        sa.Column("customer_code", sa.String(length=120), nullable=True),
        sa.Column("customer_name", sa.String(length=255), nullable=True),
        sa.Column("matched_customer_code", sa.String(length=120), nullable=True),
        sa.Column("matched_customer_name", sa.String(length=255), nullable=True),
        sa.Column("receivable_ar_balance", sa.Numeric(18, 2), nullable=True),
        sa.Column("account_ar_balance", sa.Numeric(18, 2), nullable=True),
        sa.Column("previous_ar_balance", sa.Numeric(18, 2), nullable=True),
        sa.Column("diff_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("overdue_days", sa.Integer(), nullable=True),
        sa.Column("recent_sales_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("source_json", postgresql.JSONB(), nullable=True),
        _created_at(),
    )
    op.create_index("ix_receivable_check_result_batch_id", "receivable_check_result", ["batch_id"])
    op.create_index("ix_receivable_check_result_snapshot_id", "receivable_check_result", ["receivable_snapshot_id"])
    op.create_index("ix_receivable_check_result_type", "receivable_check_result", ["result_type"])
    op.create_index("ix_receivable_check_result_severity", "receivable_check_result", ["severity"])
    op.create_index("ix_receivable_check_result_data_date", "receivable_check_result", ["data_date"])
    op.create_index("ix_receivable_check_result_customer_code", "receivable_check_result", ["customer_code"])
    op.create_index("ix_receivable_check_result_customer_name", "receivable_check_result", ["customer_name"])
    op.create_index("ix_receivable_check_result_matched_customer_code", "receivable_check_result", ["matched_customer_code"])
    op.create_index("ix_receivable_check_result_matched_customer_name", "receivable_check_result", ["matched_customer_name"])
    op.create_index("ix_receivable_check_result_overdue_days", "receivable_check_result", ["overdue_days"])

    op.execute(
        sa.text(
            """
            INSERT INTO data_calendar_rule (
                rule_code, file_type, label, action_layer, frequency, deadline_hour,
                owner_role, is_required, is_enabled, sort_order, remark, created_at, updated_at
            )
            VALUES (
                'daily_receivable_snapshot', 'receivable_snapshot', '应收账款',
                'blue', 'daily', 18, '数据中台', true, true, 35,
                '每日客户应收余额核验。', now(), now()
            )
            ON CONFLICT (rule_code) DO NOTHING
            """
        )
    )

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
              AND permissions.permission_code IN ('receivable.view', 'receivable.import', 'receivable.check', 'receivable.export')
            """
        )
    )
    op.execute(sa.text("DELETE FROM permissions WHERE permission_code IN ('receivable.view', 'receivable.import', 'receivable.check', 'receivable.export')"))
    op.execute(sa.text("DELETE FROM data_calendar_rule WHERE rule_code = 'daily_receivable_snapshot'"))
    op.drop_table("receivable_check_result")
    op.drop_table("receivable_snapshot")

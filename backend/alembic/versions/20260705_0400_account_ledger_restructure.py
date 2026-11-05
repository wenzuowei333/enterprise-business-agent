"""account ledger receivable restructure

Revision ID: 20260705_0400
Revises: 20260705_0300
Create Date: 2026-07-05 22:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260705_0400"
down_revision = "20260705_0300"
branch_labels = None
depends_on = None


ACCOUNT_LEDGER_PERMISSIONS = [
    ("account_ledger.view", "查看往来明细", "account_ledger", "view"),
    ("account_ledger.import", "导入往来明细", "account_ledger", "import"),
    ("account_ledger.edit", "编辑往来明细", "account_ledger", "edit"),
    ("account_ledger.export", "导出往来明细", "account_ledger", "export"),
]

ROLE_GRANTS = {
    "admin": ["account_ledger.view", "account_ledger.import", "account_ledger.edit", "account_ledger.export"],
    "boss": ["account_ledger.view", "account_ledger.import", "account_ledger.edit", "account_ledger.export"],
    "business_middle_office": ["account_ledger.view", "account_ledger.import", "account_ledger.edit", "account_ledger.export"],
    "data_middle_office": ["account_ledger.view", "account_ledger.import", "account_ledger.edit", "account_ledger.export"],
    "viewer": ["account_ledger.view"],
}


def _created_at() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "account_ledger_entry",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("import_batch.id", ondelete="CASCADE"), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("data_date", sa.Date(), nullable=True),
        sa.Column("settlement_unit_code", sa.String(length=120), nullable=True),
        sa.Column("settlement_unit_name", sa.String(length=255), nullable=True),
        sa.Column("document_type", sa.String(length=120), nullable=True),
        sa.Column("document_date", sa.Date(), nullable=True),
        sa.Column("document_no", sa.String(length=160), nullable=True),
        sa.Column("handler_name", sa.String(length=120), nullable=True),
        sa.Column("counterparty_name", sa.String(length=255), nullable=True),
        sa.Column("amount_before_discount", sa.Numeric(18, 2), nullable=True),
        sa.Column("document_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("discount_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("received_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("ar_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("paid_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("ap_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("advance_receipt_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("advance_payment_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("current_balance", sa.Numeric(18, 2), nullable=True),
        sa.Column("uninvoiced_qty", sa.Numeric(18, 4), nullable=True),
        sa.Column("uninvoiced_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("invoice_participation", sa.String(length=80), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("reconciliation_date", sa.Date(), nullable=True),
        sa.Column("reconciliation_mark", sa.String(length=120), nullable=True),
        sa.Column("row_role", sa.String(length=40), nullable=False, server_default="transaction"),
        sa.Column("raw_row_json", postgresql.JSONB(), nullable=True),
        _created_at(),
        sa.UniqueConstraint("batch_id", "row_number", name="uq_account_ledger_entry_batch_row"),
    )
    for column in [
        "batch_id",
        "data_date",
        "settlement_unit_code",
        "settlement_unit_name",
        "document_type",
        "document_date",
        "document_no",
        "handler_name",
        "counterparty_name",
        "reconciliation_date",
        "reconciliation_mark",
        "row_role",
    ]:
        op.create_index(f"ix_account_ledger_entry_{column}", "account_ledger_entry", [column])

    op.execute(
        sa.text(
            """
            INSERT INTO data_calendar_rule (
                rule_code, file_type, label, action_layer, frequency, deadline_hour,
                owner_role, is_required, is_enabled, sort_order, remark, created_at, updated_at
            )
            VALUES (
                'daily_account_ledger', 'account_ledger', '往来明细',
                'blue', 'daily', 18, '数据中台', true, true, 34,
                '每日往来明细过程账款。', now(), now()
            )
            ON CONFLICT (rule_code) DO NOTHING
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE data_calendar_rule
            SET label = '应收底数',
                remark = '应收查询表作为应收核验底数。'
            WHERE rule_code = 'daily_receivable_snapshot'
            """
        )
    )

    for code, name, resource_type, action_type in ACCOUNT_LEDGER_PERMISSIONS:
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

    for role_code, scope_mode in [
        ("admin", "all"),
        ("boss", "all"),
        ("business_middle_office", "all"),
        ("data_middle_office", "all"),
        ("viewer", "own"),
    ]:
        op.execute(
            sa.text(
                """
                INSERT INTO data_scope_rules
                  (subject_type, subject_id, resource_type, scope_mode, scope_value, is_active, created_at, updated_at)
                VALUES ('role', :role_code, 'account_ledger', :scope_mode, NULL, true, now(), now())
                ON CONFLICT DO NOTHING
                """
            ).bindparams(role_code=role_code, scope_mode=scope_mode)
        )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DELETE FROM role_permissions
            USING permissions
            WHERE role_permissions.permission_id = permissions.id
              AND permissions.permission_code IN (
                'account_ledger.view',
                'account_ledger.import',
                'account_ledger.edit',
                'account_ledger.export'
              )
            """
        )
    )
    op.execute(
        sa.text(
            """
            DELETE FROM permissions
            WHERE permission_code IN (
                'account_ledger.view',
                'account_ledger.import',
                'account_ledger.edit',
                'account_ledger.export'
            )
            """
        )
    )
    op.execute(sa.text("DELETE FROM data_scope_rules WHERE resource_type = 'account_ledger'"))
    op.execute(sa.text("DELETE FROM data_calendar_rule WHERE rule_code = 'daily_account_ledger'"))
    op.drop_table("account_ledger_entry")

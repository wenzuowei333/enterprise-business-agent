"""account ledger balance dates

Revision ID: 20260705_0500
Revises: 20260705_0400
Create Date: 2026-07-05 23:30:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260705_0500"
down_revision = "20260705_0400"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("account_ledger_entry", sa.Column("period_start", sa.Date(), nullable=True))
    op.add_column("account_ledger_entry", sa.Column("period_end", sa.Date(), nullable=True))
    op.add_column("account_ledger_entry", sa.Column("balance_date", sa.Date(), nullable=True))
    for column in ["period_start", "period_end", "balance_date"]:
        op.create_index(f"ix_account_ledger_entry_{column}", "account_ledger_entry", [column])

    op.execute(sa.text("UPDATE account_ledger_entry SET period_end = data_date, balance_date = data_date WHERE balance_date IS NULL"))
    op.execute(
        sa.text(
            """
            UPDATE data_calendar_rule
            SET label = '应收查询',
                remark = '应收查询表作为往来明细应收校验对照来源。'
            WHERE rule_code = 'daily_receivable_snapshot'
            """
        )
    )


def downgrade() -> None:
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
    for column in ["balance_date", "period_end", "period_start"]:
        op.drop_index(f"ix_account_ledger_entry_{column}", table_name="account_ledger_entry")
        op.drop_column("account_ledger_entry", column)

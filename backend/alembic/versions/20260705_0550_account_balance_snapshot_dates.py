"""add balance dates to legacy account balance snapshot

Revision ID: 20260705_0550
Revises: 20260705_0500
Create Date: 2026-07-05 23:50:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260705_0550"
down_revision = "20260705_0500"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column in ["period_start", "period_end", "balance_date"]:
        op.add_column("account_balance_snapshot", sa.Column(column, sa.Date(), nullable=True))
        op.create_index(f"ix_account_balance_snapshot_{column}", "account_balance_snapshot", [column])

    op.execute(
        sa.text(
            """
            UPDATE account_balance_snapshot
            SET period_end = COALESCE(period_end, data_date),
                balance_date = COALESCE(balance_date, data_date)
            WHERE period_end IS NULL OR balance_date IS NULL
            """
        )
    )


def downgrade() -> None:
    for column in ["balance_date", "period_end", "period_start"]:
        op.drop_index(f"ix_account_balance_snapshot_{column}", table_name="account_balance_snapshot")
        op.drop_column("account_balance_snapshot", column)

"""add CRM lead address and customer group fields

Revision ID: 20260801_0100
Revises: 20260729_0500
Create Date: 2026-08-01 01:30:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260801_0100"
down_revision = "20260729_0500"
branch_labels = None
depends_on = None


def _column_names() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if "crm_lead" not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns("crm_lead")}


def upgrade() -> None:
    columns = _column_names()
    if not columns:
        return
    if "address" not in columns:
        op.add_column("crm_lead", sa.Column("address", sa.Text(), nullable=True))
    if "customer_group_name" not in columns:
        op.add_column("crm_lead", sa.Column("customer_group_name", sa.String(length=255), nullable=True))


def downgrade() -> None:
    columns = _column_names()
    if "customer_group_name" in columns:
        op.drop_column("crm_lead", "customer_group_name")
    if "address" in columns:
        op.drop_column("crm_lead", "address")

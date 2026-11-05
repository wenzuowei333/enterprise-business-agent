"""external API stage 3 read permissions

Revision ID: 20260721_0100
Revises: 20260720_0100
Create Date: 2026-07-21 01:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260721_0100"
down_revision = "20260720_0100"
branch_labels = None
depends_on = None


PERMISSION_COLUMNS = [
    "can_read_products",
    "can_read_suppliers",
    "can_read_sales_summary",
    "can_read_purchase_summary",
    "can_read_inventory_summary",
    "can_read_receivables",
    "can_read_data_quality",
]


def upgrade() -> None:
    for name in PERMISSION_COLUMNS:
        op.add_column(
            "external_api_keys",
            sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    for name in reversed(PERMISSION_COLUMNS):
        op.drop_column("external_api_keys", name)

"""customer tags and feedback flow refinements

Revision ID: 20260706_0200
Revises: 20260706_0100
Create Date: 2026-07-06 02:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260706_0200"
down_revision = "20260706_0100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("customer_master", sa.Column("customer_tags", postgresql.JSONB(), nullable=True))
    op.add_column("crm_followup", sa.Column("business_profile_approval_id", sa.Integer(), nullable=True))
    op.create_index(
        "ix_crm_followup_business_profile_approval_id",
        "crm_followup",
        ["business_profile_approval_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_crm_followup_business_profile_approval_id_approval_instance",
        "crm_followup",
        "approval_instance",
        ["business_profile_approval_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_crm_followup_business_profile_approval_id_approval_instance", "crm_followup", type_="foreignkey")
    op.drop_index("ix_crm_followup_business_profile_approval_id", table_name="crm_followup")
    op.drop_column("crm_followup", "business_profile_approval_id")
    op.drop_column("customer_master", "customer_tags")

"""add crm followup business profile update flag

Revision ID: 20260704_0200
Revises: 20260704_0100
Create Date: 2026-07-04 20:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260704_0200"
down_revision = "20260704_0100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "crm_followup",
        sa.Column("business_profile_updated", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_index(
        "ix_crm_followup_business_profile_updated",
        "crm_followup",
        ["business_profile_updated"],
    )
    op.alter_column("crm_followup", "business_profile_updated", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_crm_followup_business_profile_updated", table_name="crm_followup")
    op.drop_column("crm_followup", "business_profile_updated")

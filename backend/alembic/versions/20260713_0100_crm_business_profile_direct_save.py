"""rename CRM business profile permission for direct-save workflow

Revision ID: 20260713_0100
Revises: 20260711_0200
Create Date: 2026-07-13 23:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260713_0100"
down_revision = "20260711_0200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE permissions
            SET permission_name = '保存项目客户经营资料'
            WHERE permission_code = 'crm_business_profile.submit'
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE permissions
            SET permission_name = '提交项目客户经营资料'
            WHERE permission_code = 'crm_business_profile.submit'
            """
        )
    )

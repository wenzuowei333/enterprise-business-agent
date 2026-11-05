"""crm project flow role fields

Revision ID: 20260706_0300
Revises: 20260706_0200
Create Date: 2026-07-06 03:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260706_0300"
down_revision = "20260706_0200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("crm_project", sa.Column("applicant_user_id", sa.Integer(), nullable=True))
    op.add_column("crm_project", sa.Column("landing_approver_user_id", sa.Integer(), nullable=True))
    op.add_column("crm_project", sa.Column("progress_cc_user_ids", postgresql.JSONB(), nullable=True))
    op.create_foreign_key(
        "fk_crm_project_applicant_user_id_users",
        "crm_project",
        "users",
        ["applicant_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_crm_project_landing_approver_user_id_users",
        "crm_project",
        "users",
        ["landing_approver_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_crm_project_applicant_user_id", "crm_project", ["applicant_user_id"], unique=False)
    op.create_index("ix_crm_project_landing_approver_user_id", "crm_project", ["landing_approver_user_id"], unique=False)

    op.execute(
        sa.text(
            """
            UPDATE crm_project
            SET applicant_user_id = created_by_user_id
            WHERE applicant_user_id IS NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE crm_project
            SET landing_approver_user_id = (
                SELECT id FROM users
                WHERE username = 'admin' AND status = 'active' AND is_active = true
                ORDER BY id
                LIMIT 1
            )
            WHERE landing_approver_user_id IS NULL
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_crm_project_landing_approver_user_id", table_name="crm_project")
    op.drop_index("ix_crm_project_applicant_user_id", table_name="crm_project")
    op.drop_constraint("fk_crm_project_landing_approver_user_id_users", "crm_project", type_="foreignkey")
    op.drop_constraint("fk_crm_project_applicant_user_id_users", "crm_project", type_="foreignkey")
    op.drop_column("crm_project", "progress_cc_user_ids")
    op.drop_column("crm_project", "landing_approver_user_id")
    op.drop_column("crm_project", "applicant_user_id")

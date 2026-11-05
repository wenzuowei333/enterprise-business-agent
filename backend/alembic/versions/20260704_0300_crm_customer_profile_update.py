"""crm customer profile scoped approval

Revision ID: 20260704_0300
Revises: 20260704_0200
Create Date: 2026-07-04 23:30:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260704_0300"
down_revision = "20260704_0200"
branch_labels = None
depends_on = None


PERMISSIONS = [
    ("crm_customer_profile.view", "查看项目客户基本资料", "crm_customer_profile", "view"),
    ("crm_customer_profile.submit", "提交项目客户基本资料更新", "crm_customer_profile", "submit"),
]

ROLE_GRANTS = {
    "admin": ["crm_customer_profile.view", "crm_customer_profile.submit"],
    "boss": ["crm_customer_profile.view", "crm_customer_profile.submit"],
    "business_middle_office": ["crm_customer_profile.view", "crm_customer_profile.submit"],
    "salesperson": ["crm_customer_profile.view", "crm_customer_profile.submit"],
    "viewer": ["crm_customer_profile.view"],
}


def _insert_permission(conn, code: str, name: str, resource_type: str, action_type: str) -> None:
    conn.execute(
        sa.text(
            """
            INSERT INTO permissions (permission_code, permission_name, resource_type, action_type, created_at, updated_at)
            SELECT
                CAST(:code AS VARCHAR(160)),
                CAST(:name AS VARCHAR(255)),
                CAST(:resource_type AS VARCHAR(80)),
                CAST(:action_type AS VARCHAR(80)),
                now(),
                now()
            WHERE NOT EXISTS (
                SELECT 1 FROM permissions WHERE permission_code = CAST(:code AS VARCHAR(160))
            )
            """
        ),
        {"code": code, "name": name, "resource_type": resource_type, "action_type": action_type},
    )


def _grant_permission(conn, role_code: str, permission_code: str) -> None:
    conn.execute(
        sa.text(
            """
            INSERT INTO role_permissions (role_id, permission_id, created_at)
            SELECT roles.id, permissions.id, now()
            FROM roles
            JOIN permissions ON permissions.permission_code = CAST(:permission_code AS VARCHAR(160))
            WHERE roles.role_code = CAST(:role_code AS VARCHAR(80))
              AND NOT EXISTS (
                SELECT 1
                FROM role_permissions
                WHERE role_permissions.role_id = roles.id
                  AND role_permissions.permission_id = permissions.id
              )
            """
        ),
        {"permission_code": permission_code, "role_code": role_code},
    )


def upgrade() -> None:
    op.add_column(
        "crm_followup",
        sa.Column("customer_profile_updated", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "crm_followup",
        sa.Column("customer_profile_approval_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_crm_followup_customer_profile_updated",
        "crm_followup",
        ["customer_profile_updated"],
    )
    op.create_index(
        "ix_crm_followup_customer_profile_approval_id",
        "crm_followup",
        ["customer_profile_approval_id"],
    )
    op.create_foreign_key(
        "fk_crm_followup_customer_profile_approval_id",
        "crm_followup",
        "approval_instance",
        ["customer_profile_approval_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.alter_column("crm_followup", "customer_profile_updated", server_default=None)

    conn = op.get_bind()
    for code, name, resource_type, action_type in PERMISSIONS:
        _insert_permission(conn, code, name, resource_type, action_type)
    for role_code, permission_codes in ROLE_GRANTS.items():
        for permission_code in permission_codes:
            _grant_permission(conn, role_code, permission_code)


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            DELETE FROM role_permissions
            USING permissions
            WHERE role_permissions.permission_id = permissions.id
              AND permissions.permission_code IN ('crm_customer_profile.view', 'crm_customer_profile.submit')
            """
        )
    )
    conn.execute(sa.text("DELETE FROM permissions WHERE permission_code IN ('crm_customer_profile.view', 'crm_customer_profile.submit')"))
    op.drop_constraint("fk_crm_followup_customer_profile_approval_id", "crm_followup", type_="foreignkey")
    op.drop_index("ix_crm_followup_customer_profile_approval_id", table_name="crm_followup")
    op.drop_index("ix_crm_followup_customer_profile_updated", table_name="crm_followup")
    op.drop_column("crm_followup", "customer_profile_approval_id")
    op.drop_column("crm_followup", "customer_profile_updated")

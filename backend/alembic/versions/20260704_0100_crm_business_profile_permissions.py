"""crm business profile scoped permissions

Revision ID: 20260704_0100
Revises: 20260702_0100
Create Date: 2026-07-04 01:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260704_0100"
down_revision = "20260702_0100"
branch_labels = None
depends_on = None


PERMISSIONS = [
    ("crm_business_profile.view", "查看项目客户经营资料", "crm_business_profile", "view"),
    ("crm_business_profile.submit", "提交项目客户经营资料", "crm_business_profile", "submit"),
]

ROLE_GRANTS = {
    "admin": ["crm_business_profile.view", "crm_business_profile.submit"],
    "boss": ["crm_business_profile.view", "crm_business_profile.submit"],
    "business_middle_office": ["crm_business_profile.view", "crm_business_profile.submit"],
    "salesperson": ["crm_business_profile.view", "crm_business_profile.submit"],
}

REVOKED_ROLE_GRANTS = {
    "salesperson": [
        "customer.view",
        "customer_business.view",
        "customer_business.edit",
        "customer_business.history",
        "customer_portrait.view",
    ],
}


def _insert_permission(conn, code: str, name: str, resource_type: str, action_type: str) -> None:
    conn.execute(
        sa.text(
            """
            INSERT INTO permissions (permission_code, permission_name, resource_type, action_type, created_at, updated_at)
            SELECT
                CAST(:code AS varchar),
                CAST(:name AS varchar),
                CAST(:resource_type AS varchar),
                CAST(:action_type AS varchar),
                now(),
                now()
            WHERE NOT EXISTS (
                SELECT 1 FROM permissions WHERE permission_code = CAST(:code AS varchar)
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
            JOIN permissions ON permissions.permission_code = :permission_code
            WHERE roles.role_code = :role_code
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


def _revoke_permission(conn, role_code: str, permission_code: str) -> None:
    conn.execute(
        sa.text(
            """
            DELETE FROM role_permissions
            USING roles, permissions
            WHERE role_permissions.role_id = roles.id
              AND role_permissions.permission_id = permissions.id
              AND roles.role_code = :role_code
              AND permissions.permission_code = :permission_code
            """
        ),
        {"permission_code": permission_code, "role_code": role_code},
    )


def upgrade() -> None:
    conn = op.get_bind()
    for code, name, resource_type, action_type in PERMISSIONS:
        _insert_permission(conn, code, name, resource_type, action_type)
    for role_code, permission_codes in ROLE_GRANTS.items():
        for permission_code in permission_codes:
            _grant_permission(conn, role_code, permission_code)
    for role_code, permission_codes in REVOKED_ROLE_GRANTS.items():
        for permission_code in permission_codes:
            _revoke_permission(conn, role_code, permission_code)


def downgrade() -> None:
    conn = op.get_bind()
    for role_code, permission_codes in REVOKED_ROLE_GRANTS.items():
        for permission_code in permission_codes:
            _grant_permission(conn, role_code, permission_code)
    conn.execute(
        sa.text(
            """
            DELETE FROM role_permissions
            USING permissions
            WHERE role_permissions.permission_id = permissions.id
              AND permissions.permission_code IN ('crm_business_profile.view', 'crm_business_profile.submit')
            """
        )
    )
    conn.execute(sa.text("DELETE FROM permissions WHERE permission_code IN ('crm_business_profile.view', 'crm_business_profile.submit')"))

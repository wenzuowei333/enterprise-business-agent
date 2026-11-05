"""sidebar entry permissions

Revision ID: 20260702_0100
Revises: 20260701_0500
Create Date: 2026-07-02 01:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260702_0100"
down_revision = "20260701_0500"
branch_labels = None
depends_on = None


PERMISSIONS = [
    ("dashboard.view", "查看首页工作台", "dashboard", "view"),
    ("settings.view", "查看系统设置", "system_config", "view"),
]

DASHBOARD_ROLES = ["admin", "boss", "business_middle_office", "data_middle_office", "salesperson", "viewer"]
SETTINGS_ROLES = ["admin"]


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


def _grant_permission(conn, role_codes: list[str], permission_code: str) -> None:
    for role_code in role_codes:
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


def upgrade() -> None:
    conn = op.get_bind()
    for code, name, resource_type, action_type in PERMISSIONS:
        _insert_permission(conn, code, name, resource_type, action_type)
    _grant_permission(conn, DASHBOARD_ROLES, "dashboard.view")
    _grant_permission(conn, SETTINGS_ROLES, "settings.view")


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            DELETE FROM role_permissions
            USING permissions
            WHERE role_permissions.permission_id = permissions.id
              AND permissions.permission_code IN ('dashboard.view', 'settings.view')
            """
        )
    )
    conn.execute(sa.text("DELETE FROM permissions WHERE permission_code IN ('dashboard.view', 'settings.view')"))

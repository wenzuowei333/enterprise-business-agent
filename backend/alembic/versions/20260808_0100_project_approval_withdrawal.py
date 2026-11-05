"""add approved project withdrawal controls

Revision ID: 20260808_0100
Revises: 20260801_0100
Create Date: 2026-08-08 01:00:00
"""

from alembic import context, op
import sqlalchemy as sa


revision = "20260808_0100"
down_revision = "20260801_0100"
branch_labels = None
depends_on = None


PERMISSIONS = (
    ("crm_project.approval_withdraw", "撤回已通过项目审批", "approval_withdraw"),
    ("crm_project.approval_withdraw_override", "越权撤回已通过项目审批", "approval_withdraw_override"),
)


def upgrade() -> None:
    connection = op.get_bind()
    offline = context.is_offline_mode()
    inspector = None if offline else sa.inspect(connection)
    has_project_table = offline or bool(inspector and inspector.has_table("crm_project"))
    has_users_table = offline or bool(inspector and inspector.has_table("users"))
    if has_project_table:
        op.add_column("crm_project", sa.Column("approval_withdrawn_at", sa.DateTime(timezone=True), nullable=True))
        op.add_column("crm_project", sa.Column("approval_withdrawn_by_user_id", sa.Integer(), nullable=True))
        op.add_column("crm_project", sa.Column("approval_withdrawn_reason", sa.Text(), nullable=True))
        op.add_column("crm_project", sa.Column("pre_withdraw_status", sa.String(length=40), nullable=True))
        if has_users_table:
            op.create_foreign_key(
                "fk_crm_project_approval_withdrawn_by_user_id_users",
                "crm_project",
                "users",
                ["approval_withdrawn_by_user_id"],
                ["id"],
                ondelete="SET NULL",
            )
        op.create_index("ix_crm_project_approval_withdrawn_at", "crm_project", ["approval_withdrawn_at"], unique=False)
        op.create_index(
            "ix_crm_project_approval_withdrawn_by_user_id",
            "crm_project",
            ["approval_withdrawn_by_user_id"],
            unique=False,
        )

    if not offline and not all(
        inspector and inspector.has_table(table_name)
        for table_name in ("permissions", "roles", "role_permissions")
    ):
        return
    for code, name, action in PERMISSIONS:
        connection.execute(
            sa.text(
                f"""
                INSERT INTO permissions (
                    permission_code, permission_name, resource_type, action_type, created_at, updated_at
                )
                VALUES ('{code}', '{name}', 'crm_project', '{action}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT (permission_code) DO UPDATE
                SET permission_name = EXCLUDED.permission_name,
                    resource_type = EXCLUDED.resource_type,
                    action_type = EXCLUDED.action_type
                """
            )
        )

    for role_code in ("business_middle_office", "boss", "admin"):
        connection.execute(
            sa.text(
                f"""
                INSERT INTO role_permissions (role_id, permission_id, created_at)
                SELECT roles.id, permissions.id, CURRENT_TIMESTAMP
                FROM roles
                CROSS JOIN permissions
                WHERE roles.role_code = '{role_code}'
                  AND permissions.permission_code = 'crm_project.approval_withdraw'
                ON CONFLICT DO NOTHING
                """
            )
        )
        if role_code == "admin":
            connection.execute(
                sa.text(
                    f"""
                    INSERT INTO role_permissions (role_id, permission_id, created_at)
                    SELECT roles.id, permissions.id, CURRENT_TIMESTAMP
                    FROM roles
                    CROSS JOIN permissions
                    WHERE roles.role_code = '{role_code}'
                      AND permissions.permission_code = 'crm_project.approval_withdraw_override'
                    ON CONFLICT DO NOTHING
                    """
                )
            )


def downgrade() -> None:
    connection = op.get_bind()
    offline = context.is_offline_mode()
    inspector = None if offline else sa.inspect(connection)
    has_permissions = offline or bool(inspector and inspector.has_table("permissions"))
    has_role_permissions = offline or bool(inspector and inspector.has_table("role_permissions"))
    if has_role_permissions and has_permissions:
        connection.execute(
            sa.text(
                """
                DELETE FROM role_permissions
                WHERE permission_id IN (
                    SELECT id FROM permissions
                    WHERE permission_code IN (
                        'crm_project.approval_withdraw',
                        'crm_project.approval_withdraw_override'
                    )
                )
                """
            )
        )
    if has_permissions:
        connection.execute(
            sa.text(
                """
                DELETE FROM permissions
                WHERE permission_code IN (
                    'crm_project.approval_withdraw',
                    'crm_project.approval_withdraw_override'
                )
                """
            )
        )
    if offline or bool(inspector and inspector.has_table("crm_project")):
        foreign_keys = (
            {"fk_crm_project_approval_withdrawn_by_user_id_users"}
            if offline
            else {item.get("name") for item in inspector.get_foreign_keys("crm_project")}
        )
        op.drop_index("ix_crm_project_approval_withdrawn_by_user_id", table_name="crm_project")
        op.drop_index("ix_crm_project_approval_withdrawn_at", table_name="crm_project")
        if "fk_crm_project_approval_withdrawn_by_user_id_users" in foreign_keys:
            op.drop_constraint("fk_crm_project_approval_withdrawn_by_user_id_users", "crm_project", type_="foreignkey")
        op.drop_column("crm_project", "pre_withdraw_status")
        op.drop_column("crm_project", "approval_withdrawn_reason")
        op.drop_column("crm_project", "approval_withdrawn_by_user_id")
        op.drop_column("crm_project", "approval_withdrawn_at")

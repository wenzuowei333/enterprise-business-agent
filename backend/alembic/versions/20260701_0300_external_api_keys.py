"""external api keys and readonly access permissions

Revision ID: 20260701_0300
Revises: 20260701_0200
Create Date: 2026-07-01 03:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260701_0300"
down_revision = "20260701_0200"
branch_labels = None
depends_on = None


def created_at_column() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def updated_at_column() -> sa.Column:
    return sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


EXTERNAL_API_PERMISSIONS = [
    ("external_api_key.view", "查看外部 API Key", "external_api_key", "view"),
    ("external_api_key.create", "创建外部 API Key", "external_api_key", "create"),
    ("external_api_key.revoke", "撤销外部 API Key", "external_api_key", "revoke"),
]


def _grant(role_code: str, permission_codes: list[str]) -> None:
    quoted_codes = ", ".join(f"'{code}'" for code in permission_codes)
    op.execute(
        f"""
        INSERT INTO role_permissions (role_id, permission_id, created_at)
        SELECT r.id, p.id, now()
        FROM roles r
        JOIN permissions p ON p.permission_code IN ({quoted_codes})
        WHERE r.role_code = '{role_code}'
        ON CONFLICT ON CONSTRAINT uq_role_permissions_role_permission DO NOTHING
        """
    )


def upgrade() -> None:
    op.create_table(
        "external_api_keys",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key_id", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("owner_name", sa.String(length=120)),
        sa.Column("key_prefix", sa.String(length=32), nullable=False),
        sa.Column("key_hash", sa.String(length=128), nullable=False),
        sa.Column("scope_region", sa.String(length=120)),
        sa.Column("scope_project_ids", postgresql.JSONB()),
        sa.Column(
            "allowed_customer_fields",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text(
                '\'["customer_code", "customer_name", "customer_short_name", "customer_type", "region", "salesperson_name", "status"]\'::jsonb'
            ),
        ),
        sa.Column("can_read_projects", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("can_read_customers", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("can_read_followups", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("can_read_judgements", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("can_read_tasks", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("can_read_approvals", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("can_read_audit_summary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("allowed_ips", postgresql.JSONB()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("revoked_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_reason", sa.Text()),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("last_used_ip", sa.String(length=80)),
        created_at_column(),
        updated_at_column(),
    )
    op.create_index("ix_external_api_keys_key_id", "external_api_keys", ["key_id"], unique=True)
    op.create_index("ix_external_api_keys_name", "external_api_keys", ["name"])
    op.create_index("ix_external_api_keys_key_prefix", "external_api_keys", ["key_prefix"], unique=True)
    op.create_index("ix_external_api_keys_key_hash", "external_api_keys", ["key_hash"], unique=True)
    op.create_index("ix_external_api_keys_scope_region", "external_api_keys", ["scope_region"])
    op.create_index("ix_external_api_keys_active", "external_api_keys", ["active", "updated_at"])
    op.create_index("ix_external_api_keys_created_by", "external_api_keys", ["created_by_user_id"])
    op.create_index("ix_external_api_keys_revoked_by", "external_api_keys", ["revoked_by_user_id"])
    op.create_index("ix_external_api_keys_revoked_at", "external_api_keys", ["revoked_at"])
    op.create_index("ix_external_api_keys_expires_at", "external_api_keys", ["expires_at"])
    op.create_index("ix_external_api_keys_last_used_at", "external_api_keys", ["last_used_at"])

    for code, name, resource_type, action_type in EXTERNAL_API_PERMISSIONS:
        op.execute(
            sa.text(
                """
                INSERT INTO permissions (permission_code, permission_name, resource_type, action_type, created_at, updated_at)
                VALUES (:code, :name, :resource_type, :action_type, now(), now())
                ON CONFLICT (permission_code) DO NOTHING
                """
            ).bindparams(code=code, name=name, resource_type=resource_type, action_type=action_type)
        )

    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id, created_at)
        SELECT r.id, p.id, now()
        FROM roles r
        CROSS JOIN permissions p
        WHERE r.role_code = 'admin'
          AND p.resource_type = 'external_api_key'
        ON CONFLICT ON CONSTRAINT uq_role_permissions_role_permission DO NOTHING
        """
    )
    _grant("data_middle_office", ["external_api_key.view", "external_api_key.create", "external_api_key.revoke"])
    _grant("boss", ["external_api_key.view"])
    _grant("business_middle_office", ["external_api_key.view"])

    for role_code, scope_mode in [
        ("admin", "all"),
        ("data_middle_office", "all"),
        ("boss", "all"),
        ("business_middle_office", "all"),
    ]:
        op.execute(
            sa.text(
                """
                INSERT INTO data_scope_rules
                  (subject_type, subject_id, resource_type, scope_mode, scope_value, is_active, created_at, updated_at)
                VALUES ('role', :role_code, 'external_api_key', :scope_mode, NULL, true, now(), now())
                ON CONFLICT DO NOTHING
                """
            ).bindparams(role_code=role_code, scope_mode=scope_mode)
        )


def downgrade() -> None:
    op.execute("DELETE FROM data_scope_rules WHERE resource_type = 'external_api_key'")
    op.execute(
        """
        DELETE FROM role_permissions
        WHERE permission_id IN (SELECT id FROM permissions WHERE resource_type = 'external_api_key')
        """
    )
    op.execute("DELETE FROM permissions WHERE resource_type = 'external_api_key'")
    op.drop_table("external_api_keys")

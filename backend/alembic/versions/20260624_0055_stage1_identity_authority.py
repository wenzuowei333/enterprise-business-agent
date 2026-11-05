"""stage1 identity authority

Revision ID: 20260624_0055
Revises: None
Create Date: 2026-06-24 00:55:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260624_0055"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("role_code", sa.String(length=80), nullable=False),
        sa.Column("role_name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("is_system_role", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_roles_role_code", "roles", ["role_code"], unique=True)

    op.create_table(
        "permission_modules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("module_code", sa.String(length=120), nullable=False),
        sa.Column("module_name", sa.String(length=160), nullable=False),
        sa.Column("parent_module_code", sa.String(length=120)),
        sa.Column("description", sa.Text()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_permission_modules_module_code", "permission_modules", ["module_code"], unique=True)

    op.create_table(
        "permissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("permission_code", sa.String(length=160), nullable=False),
        sa.Column("permission_name", sa.String(length=160), nullable=False),
        sa.Column("resource_type", sa.String(length=80), nullable=False),
        sa.Column("action_type", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_permissions_permission_code", "permissions", ["permission_code"], unique=True)
    op.create_index("ix_permissions_resource_type", "permissions", ["resource_type"])
    op.create_index("ix_permissions_action_type", "permissions", ["action_type"])

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(length=80), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("real_name", sa.String(length=120), nullable=False),
        sa.Column("employee_code", sa.String(length=80)),
        sa.Column("role", sa.String(length=80), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)
    op.create_index("ix_users_employee_code", "users", ["employee_code"])
    op.create_index("ix_users_role", "users", ["role"])

    op.create_table(
        "role_permissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("role_id", sa.Integer(), sa.ForeignKey("roles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("permission_id", sa.Integer(), sa.ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("role_id", "permission_id", name="uq_role_permissions_role_permission"),
    )

    op.create_table(
        "employee_profile",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("employee_code", sa.String(length=80), nullable=False),
        sa.Column("employee_name", sa.String(length=120), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("department", sa.String(length=120)),
        sa.Column("position", sa.String(length=120)),
        sa.Column("role_code", sa.String(length=80)),
        sa.Column("manager_employee_code", sa.String(length=80)),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="active"),
        sa.Column("phone", sa.String(length=80)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_employee_profile_employee_code", "employee_profile", ["employee_code"], unique=True)
    op.create_index("ix_employee_profile_user_id", "employee_profile", ["user_id"])
    op.create_index("ix_employee_profile_role_code", "employee_profile", ["role_code"])
    op.create_index("ix_employee_profile_manager_employee_code", "employee_profile", ["manager_employee_code"])
    op.create_index("ix_employee_profile_status", "employee_profile", ["status"])

    op.create_table(
        "customer_owner_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_code", sa.String(length=120), nullable=False),
        sa.Column("old_employee_code", sa.String(length=80)),
        sa.Column("new_employee_code", sa.String(length=80), nullable=False),
        sa.Column("change_reason", sa.Text()),
        sa.Column("changed_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("changed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_customer_owner_history_customer_code", "customer_owner_history", ["customer_code"])
    op.create_index("ix_customer_owner_history_old_employee_code", "customer_owner_history", ["old_employee_code"])
    op.create_index("ix_customer_owner_history_new_employee_code", "customer_owner_history", ["new_employee_code"])

    op.create_table(
        "user_scope_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scope_type", sa.String(length=80), nullable=False),
        sa.Column("scope_value", sa.Text()),
        sa.Column("description", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_user_scope_rules_user_id", "user_scope_rules", ["user_id"])
    op.create_index("ix_user_scope_rules_scope_type", "user_scope_rules", ["scope_type"])

    op.create_table(
        "data_scope_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("subject_type", sa.String(length=40), nullable=False),
        sa.Column("subject_id", sa.String(length=120), nullable=False),
        sa.Column("resource_type", sa.String(length=80), nullable=False),
        sa.Column("scope_mode", sa.String(length=40), nullable=False),
        sa.Column("scope_value", postgresql.JSONB()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_data_scope_rules_subject_type", "data_scope_rules", ["subject_type"])
    op.create_index("ix_data_scope_rules_subject_id", "data_scope_rules", ["subject_id"])
    op.create_index("ix_data_scope_rules_resource_type", "data_scope_rules", ["resource_type"])
    op.create_index("ix_data_scope_rules_is_active", "data_scope_rules", ["is_active"])

    op.create_table(
        "field_permission_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("subject_type", sa.String(length=40), nullable=False),
        sa.Column("subject_id", sa.String(length=120), nullable=False),
        sa.Column("resource_type", sa.String(length=80), nullable=False),
        sa.Column("field_name", sa.String(length=120), nullable=False),
        sa.Column("permission_type", sa.String(length=40), nullable=False),
        sa.Column("mask_rule", sa.String(length=120)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_field_permission_rules_subject_type", "field_permission_rules", ["subject_type"])
    op.create_index("ix_field_permission_rules_subject_id", "field_permission_rules", ["subject_id"])
    op.create_index("ix_field_permission_rules_resource_type", "field_permission_rules", ["resource_type"])

    op.create_table(
        "approval_flow_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("flow_code", sa.String(length=120), nullable=False),
        sa.Column("flow_name", sa.String(length=160), nullable=False),
        sa.Column("resource_type", sa.String(length=80), nullable=False),
        sa.Column("trigger_condition", postgresql.JSONB()),
        sa.Column("approval_mode", sa.String(length=40), nullable=False),
        sa.Column("steps", postgresql.JSONB()),
        sa.Column("reject_to_status", sa.String(length=80)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_approval_flow_rules_flow_code", "approval_flow_rules", ["flow_code"], unique=True)
    op.create_index("ix_approval_flow_rules_resource_type", "approval_flow_rules", ["resource_type"])
    op.create_index("ix_approval_flow_rules_is_active", "approval_flow_rules", ["is_active"])

    op.create_table(
        "business_control_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rule_code", sa.String(length=120), nullable=False),
        sa.Column("rule_name", sa.String(length=160), nullable=False),
        sa.Column("resource_type", sa.String(length=80), nullable=False),
        sa.Column("condition_expr", postgresql.JSONB()),
        sa.Column("control_level", sa.String(length=80), nullable=False),
        sa.Column("escalate_to_role", sa.String(length=80)),
        sa.Column("message_template", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_business_control_rules_rule_code", "business_control_rules", ["rule_code"], unique=True)
    op.create_index("ix_business_control_rules_resource_type", "business_control_rules", ["resource_type"])
    op.create_index("ix_business_control_rules_is_active", "business_control_rules", ["is_active"])

    op.create_table(
        "authority_root_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rule_code", sa.String(length=160), nullable=False),
        sa.Column("rule_name", sa.String(length=200), nullable=False),
        sa.Column("resource_type", sa.String(length=80), nullable=False),
        sa.Column("action_type", sa.String(length=80), nullable=False),
        sa.Column("allowed_roles", postgresql.JSONB(), nullable=False),
        sa.Column("allowed_scope", postgresql.JSONB()),
        sa.Column("requires_approval", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("approver_role", sa.String(length=80)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("description", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_authority_root_rules_rule_code", "authority_root_rules", ["rule_code"], unique=True)
    op.create_index("ix_authority_root_rules_resource_type", "authority_root_rules", ["resource_type"])
    op.create_index("ix_authority_root_rules_action_type", "authority_root_rules", ["action_type"])
    op.create_index("ix_authority_root_rules_is_active", "authority_root_rules", ["is_active"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("role_code", sa.String(length=80)),
        sa.Column("action_type", sa.String(length=80), nullable=False),
        sa.Column("resource_type", sa.String(length=80), nullable=False),
        sa.Column("resource_id", sa.String(length=160)),
        sa.Column("before_data", postgresql.JSONB()),
        sa.Column("after_data", postgresql.JSONB()),
        sa.Column("ip_address", sa.String(length=80)),
        sa.Column("user_agent", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_audit_log_user_id", "audit_log", ["user_id"])
    op.create_index("ix_audit_log_role_code", "audit_log", ["role_code"])
    op.create_index("ix_audit_log_action_type", "audit_log", ["action_type"])
    op.create_index("ix_audit_log_resource_type", "audit_log", ["resource_type"])
    op.create_index("ix_audit_log_resource_id", "audit_log", ["resource_id"])


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("authority_root_rules")
    op.drop_table("business_control_rules")
    op.drop_table("approval_flow_rules")
    op.drop_table("field_permission_rules")
    op.drop_table("data_scope_rules")
    op.drop_table("user_scope_rules")
    op.drop_table("customer_owner_history")
    op.drop_table("employee_profile")
    op.drop_table("role_permissions")
    op.drop_table("users")
    op.drop_table("permissions")
    op.drop_table("permission_modules")
    op.drop_table("roles")

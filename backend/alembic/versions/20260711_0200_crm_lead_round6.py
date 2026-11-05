"""crm lead domain and permissions

Revision ID: 20260711_0200
Revises: 20260711_0100
Create Date: 2026-07-11 02:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260711_0200"
down_revision = "20260711_0100"
branch_labels = None
depends_on = None


LEAD_PERMISSIONS = [
    ("crm_lead.view", "查看客户线索", "view"),
    ("crm_lead.create", "创建客户线索", "create"),
    ("crm_lead.edit", "编辑客户线索", "edit"),
    ("crm_lead.assign", "分配客户线索", "assign"),
    ("crm_lead.convert", "发起客户线索转正", "convert"),
    ("crm_lead.approve", "审批客户线索转正", "approve"),
]

ROLE_GRANTS = {
    "admin": [permission[0] for permission in LEAD_PERMISSIONS],
    "boss": ["crm_lead.view"],
    "business_middle_office": ["crm_lead.view", "crm_lead.create", "crm_lead.edit", "crm_lead.assign", "crm_lead.convert"],
    "salesperson": ["crm_lead.view", "crm_lead.create", "crm_lead.edit", "crm_lead.convert"],
    "viewer": ["crm_lead.view"],
}

SCOPE_RULES = [
    ("admin", "all"),
    ("boss", "all"),
    ("business_middle_office", "all"),
    ("salesperson", "own"),
    ("viewer", "assigned"),
]


def _timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "crm_lead",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lead_no", sa.String(length=120), nullable=False),
        sa.Column("lead_name", sa.String(length=255), nullable=False),
        sa.Column("normalized_name", sa.String(length=255), nullable=False),
        sa.Column("company_name", sa.String(length=255)),
        sa.Column("contact_name", sa.String(length=120)),
        sa.Column("contact_phone", sa.String(length=80)),
        sa.Column("normalized_phone", sa.String(length=80)),
        sa.Column("source", sa.String(length=120)),
        sa.Column("region", sa.String(length=120)),
        sa.Column("business_line", sa.String(length=120)),
        sa.Column("intent_summary", sa.Text()),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="draft"),
        sa.Column("qualification_note", sa.Text()),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("assigned_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("assigned_at", sa.DateTime(timezone=True)),
        sa.Column("last_followup_at", sa.DateTime(timezone=True)),
        sa.Column("next_followup_at", sa.DateTime(timezone=True)),
        sa.Column("current_approval_id", sa.Integer(), sa.ForeignKey("approval_instance.id", ondelete="SET NULL")),
        sa.Column("converted_customer_code", sa.String(length=120), sa.ForeignKey("customer_master.customer_code", ondelete="SET NULL")),
        sa.Column("converted_at", sa.DateTime(timezone=True)),
        sa.Column("converted_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("updated_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        *_timestamp_columns(),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'qualified', 'conversion_pending', 'converted', 'closed', 'rejected')",
            name="ck_crm_lead_status",
        ),
    )
    op.create_index("ix_crm_lead_lead_no", "crm_lead", ["lead_no"], unique=True)
    op.create_index("ix_crm_lead_normalized_name", "crm_lead", ["normalized_name"])
    op.create_index("ix_crm_lead_normalized_phone", "crm_lead", ["normalized_phone"])
    op.create_index("ix_crm_lead_status_next_followup_at", "crm_lead", ["status", "next_followup_at"])
    op.create_index("ix_crm_lead_owner_assigned", "crm_lead", ["owner_user_id", "assigned_user_id"])

    op.create_table(
        "crm_lead_followup",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("crm_lead.id", ondelete="CASCADE"), nullable=False),
        sa.Column("followup_no", sa.String(length=120), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("method", sa.String(length=80)),
        sa.Column("outcome", sa.Text()),
        sa.Column("next_action", sa.Text()),
        sa.Column("next_followup_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        *_timestamp_columns(),
    )
    op.create_index("ix_crm_lead_followup_followup_no", "crm_lead_followup", ["followup_no"], unique=True)
    op.create_index("ix_crm_lead_followup_lead_created", "crm_lead_followup", ["lead_id", "created_at"])

    op.create_table(
        "crm_lead_assignment_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("crm_lead.id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_assignee_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("to_assignee_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("assigned_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("note", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_crm_lead_assignment_event_lead_created", "crm_lead_assignment_event", ["lead_id", "created_at"])

    op.create_table(
        "crm_lead_product_intent",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("crm_lead.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_code", sa.String(length=120), sa.ForeignKey("product_master.product_code", ondelete="SET NULL")),
        sa.Column("product_name", sa.String(length=255), nullable=False),
        sa.Column("quantity_note", sa.String(length=255)),
        sa.Column("interest_level", sa.String(length=40)),
        sa.Column("note", sa.Text()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        *_timestamp_columns(),
    )
    op.create_index("ix_crm_lead_product_intent_lead_sort", "crm_lead_product_intent", ["lead_id", "sort_order"])

    conn = op.get_bind()
    for code, name, action_type in LEAD_PERMISSIONS:
        conn.execute(
            sa.text(
                """
                INSERT INTO permissions (permission_code, permission_name, resource_type, action_type, created_at, updated_at)
                VALUES (:code, :name, 'crm_lead', :action_type, now(), now())
                ON CONFLICT (permission_code) DO NOTHING
                """
            ),
            {"code": code, "name": name, "action_type": action_type},
        )
    for role_code, permission_codes in ROLE_GRANTS.items():
        for permission_code in permission_codes:
            conn.execute(
                sa.text(
                    """
                    INSERT INTO role_permissions (role_id, permission_id, created_at)
                    SELECT roles.id, permissions.id, now()
                    FROM roles
                    JOIN permissions ON permissions.permission_code = :permission_code
                    WHERE roles.role_code = :role_code
                    ON CONFLICT ON CONSTRAINT uq_role_permissions_role_permission DO NOTHING
                    """
                ),
                {"role_code": role_code, "permission_code": permission_code},
            )
    for role_code, scope_mode in SCOPE_RULES:
        conn.execute(
            sa.text(
                """
                INSERT INTO data_scope_rules
                    (subject_type, subject_id, resource_type, scope_mode, scope_value, is_active, created_at, updated_at)
                SELECT 'role', CAST(:role_code AS VARCHAR(120)), 'crm_lead', CAST(:scope_mode AS VARCHAR(40)), NULL, true, now(), now()
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM data_scope_rules
                    WHERE subject_type = 'role'
                      AND subject_id = CAST(:role_code AS VARCHAR(120))
                      AND resource_type = 'crm_lead'
                )
                """
            ),
            {"role_code": role_code, "scope_mode": scope_mode},
        )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM data_scope_rules WHERE resource_type = 'crm_lead'"))
    conn.execute(
        sa.text(
            """
            DELETE FROM role_permissions
            USING permissions
            WHERE role_permissions.permission_id = permissions.id
              AND permissions.resource_type = 'crm_lead'
            """
        )
    )
    conn.execute(sa.text("DELETE FROM permissions WHERE resource_type = 'crm_lead'"))
    op.drop_table("crm_lead_product_intent")
    op.drop_table("crm_lead_assignment_event")
    op.drop_table("crm_lead_followup")
    op.drop_table("crm_lead")

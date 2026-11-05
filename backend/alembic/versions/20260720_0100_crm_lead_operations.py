"""crm lead operations domain, policy, and campaign

Revision ID: 20260720_0100
Revises: 20260713_0100
Create Date: 2026-07-20 01:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260720_0100"
down_revision = "20260713_0100"
branch_labels = None
depends_on = None


OPERATIONS_PERMISSIONS = [
    ("crm_lead.claim", "认领公海线索", "crm_lead", "claim"),
    ("crm_lead.recycle", "回收客户线索", "crm_lead", "recycle"),
    ("crm_lead.analytics", "查看线索运营分析", "crm_lead", "analytics"),
    ("crm_lead_campaign.view", "查看线索活动", "crm_lead_campaign", "view"),
    ("crm_lead_campaign.manage", "管理线索活动", "crm_lead_campaign", "manage"),
    ("crm_lead_policy.manage", "管理线索运营策略", "crm_lead_policy", "manage"),
]


ROLE_GRANTS = {
    "admin": [permission[0] for permission in OPERATIONS_PERMISSIONS],
    "boss": ["crm_lead.analytics", "crm_lead_campaign.view"],
    "business_middle_office": [
        "crm_lead.claim",
        "crm_lead.recycle",
        "crm_lead.analytics",
        "crm_lead_campaign.view",
    ],
    "salesperson": ["crm_lead.claim"],
}


def _timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "crm_lead_campaign",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("campaign_code", sa.String(length=120), nullable=False),
        sa.Column("campaign_name", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=120)),
        sa.Column("channel", sa.String(length=120)),
        sa.Column("description", sa.Text()),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="active"),
        sa.Column("start_date", sa.Date()),
        sa.Column("end_date", sa.Date()),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("updated_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        *_timestamp_columns(),
        sa.CheckConstraint(
            "status IN ('active', 'inactive', 'archived')",
            name="ck_crm_lead_campaign_status",
        ),
        sa.CheckConstraint(
            "end_date IS NULL OR start_date IS NULL OR end_date >= start_date",
            name="ck_crm_lead_campaign_dates",
        ),
    )
    op.create_index("ix_crm_lead_campaign_campaign_code", "crm_lead_campaign", ["campaign_code"], unique=True)
    op.create_index("ix_crm_lead_campaign_campaign_name", "crm_lead_campaign", ["campaign_name"])
    op.create_index("ix_crm_lead_campaign_source", "crm_lead_campaign", ["source"])
    op.create_index("ix_crm_lead_campaign_channel", "crm_lead_campaign", ["channel"])
    op.create_index("ix_crm_lead_campaign_start_date", "crm_lead_campaign", ["start_date"])
    op.create_index("ix_crm_lead_campaign_end_date", "crm_lead_campaign", ["end_date"])
    op.create_index("ix_crm_lead_campaign_owner_user_id", "crm_lead_campaign", ["owner_user_id"])
    op.create_index("ix_crm_lead_campaign_created_by_user_id", "crm_lead_campaign", ["created_by_user_id"])
    op.create_index("ix_crm_lead_campaign_updated_by_user_id", "crm_lead_campaign", ["updated_by_user_id"])
    op.create_index("ix_crm_lead_campaign_status_dates", "crm_lead_campaign", ["status", "start_date", "end_date"])

    op.create_table(
        "crm_lead_operation_policy",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("policy_key", sa.String(length=80), nullable=False, server_default="default"),
        sa.Column("first_response_hours", sa.Integer(), nullable=False, server_default="24"),
        sa.Column("next_followup_hours", sa.Integer(), nullable=False, server_default="72"),
        sa.Column("assignment_hold_hours", sa.Integer(), nullable=False, server_default="168"),
        sa.Column("due_soon_hours", sa.Integer(), nullable=False, server_default="4"),
        sa.Column("daily_claim_limit", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        *_timestamp_columns(),
        sa.CheckConstraint("first_response_hours > 0", name="ck_crm_lead_policy_first_response_hours"),
        sa.CheckConstraint("next_followup_hours > 0", name="ck_crm_lead_policy_next_followup_hours"),
        sa.CheckConstraint("assignment_hold_hours > 0", name="ck_crm_lead_policy_assignment_hold_hours"),
        sa.CheckConstraint("due_soon_hours >= 0", name="ck_crm_lead_policy_due_soon_hours"),
        sa.CheckConstraint("daily_claim_limit >= 0", name="ck_crm_lead_policy_daily_claim_limit"),
    )
    op.create_index("ix_crm_lead_operation_policy_policy_key", "crm_lead_operation_policy", ["policy_key"], unique=True)
    op.create_index("ix_crm_lead_operation_policy_is_active", "crm_lead_operation_policy", ["is_active"])
    op.create_index("ix_crm_lead_operation_policy_updated_by_user_id", "crm_lead_operation_policy", ["updated_by_user_id"])
    op.execute(
        """
        INSERT INTO crm_lead_operation_policy
            (policy_key, first_response_hours, next_followup_hours, assignment_hold_hours, due_soon_hours, daily_claim_limit, is_active, created_at, updated_at)
        VALUES ('default', 24, 72, 168, 4, 10, true, now(), now())
        ON CONFLICT (policy_key) DO NOTHING
        """
    )

    op.add_column("crm_lead", sa.Column("campaign_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_crm_lead_campaign_id", "crm_lead", "crm_lead_campaign", ["campaign_id"], ["id"], ondelete="SET NULL")
    op.add_column("crm_lead", sa.Column("priority", sa.String(length=40), nullable=False, server_default="normal"))
    op.add_column("crm_lead", sa.Column("pool_status", sa.String(length=40), nullable=False, server_default="private"))
    op.add_column("crm_lead", sa.Column("assignment_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("crm_lead", sa.Column("first_response_due_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("crm_lead", sa.Column("first_responded_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("crm_lead", sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("crm_lead", sa.Column("recycled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("crm_lead", sa.Column("recycle_count", sa.Integer(), nullable=False, server_default="0"))
    op.create_check_constraint("ck_crm_lead_priority", "crm_lead", "priority IN ('low', 'normal', 'high', 'urgent')")
    op.create_check_constraint("ck_crm_lead_pool_status", "crm_lead", "pool_status IN ('private', 'public')")
    op.create_index("ix_crm_lead_campaign_id", "crm_lead", ["campaign_id"])
    op.create_index("ix_crm_lead_priority", "crm_lead", ["priority"])
    op.create_index("ix_crm_lead_pool_status", "crm_lead", ["pool_status"])
    op.create_index("ix_crm_lead_assignment_expires_at", "crm_lead", ["assignment_expires_at"])
    op.create_index("ix_crm_lead_first_response_due_at", "crm_lead", ["first_response_due_at"])
    op.create_index("ix_crm_lead_first_responded_at", "crm_lead", ["first_responded_at"])
    op.create_index("ix_crm_lead_last_activity_at", "crm_lead", ["last_activity_at"])
    op.create_index("ix_crm_lead_recycled_at", "crm_lead", ["recycled_at"])
    op.create_index("ix_crm_lead_campaign_status", "crm_lead", ["campaign_id", "status"])
    op.create_index("ix_crm_lead_pool_status_assigned", "crm_lead", ["pool_status", "assigned_at"])
    op.create_index("ix_crm_lead_sla_first_response", "crm_lead", ["first_response_due_at", "last_activity_at"])
    op.execute(
        """
        UPDATE crm_lead
        SET pool_status = 'private',
            priority = COALESCE(priority, 'normal'),
            recycle_count = COALESCE(recycle_count, 0),
            last_activity_at = COALESCE(
                (
                    SELECT MAX(crm_lead_followup.created_at)
                    FROM crm_lead_followup
                    WHERE crm_lead_followup.lead_id = crm_lead.id
                ),
                updated_at,
                created_at
            )
        """
    )

    op.add_column(
        "crm_lead_assignment_event",
        sa.Column("event_type", sa.String(length=40), nullable=False, server_default="assigned"),
    )
    op.create_check_constraint(
        "ck_crm_lead_assignment_event_type",
        "crm_lead_assignment_event",
        "event_type IN ('assigned', 'claimed', 'recycled', 'returned')",
    )
    op.create_index("ix_crm_lead_assignment_event_event_type", "crm_lead_assignment_event", ["event_type"])

    conn = op.get_bind()
    for code, name, resource_type, action_type in OPERATIONS_PERMISSIONS:
        conn.execute(
            sa.text(
                """
                INSERT INTO permissions (permission_code, permission_name, resource_type, action_type, created_at, updated_at)
                VALUES (:code, :name, :resource_type, :action_type, now(), now())
                ON CONFLICT (permission_code) DO NOTHING
                """
            ),
            {"code": code, "name": name, "resource_type": resource_type, "action_type": action_type},
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


def downgrade() -> None:
    conn = op.get_bind()
    permission_codes = [permission[0] for permission in OPERATIONS_PERMISSIONS]
    conn.execute(
        sa.text(
            """
            DELETE FROM role_permissions
            USING permissions
            WHERE role_permissions.permission_id = permissions.id
              AND permissions.permission_code = ANY(:permission_codes)
            """
        ),
        {"permission_codes": permission_codes},
    )
    conn.execute(sa.text("DELETE FROM permissions WHERE permission_code = ANY(:permission_codes)"), {"permission_codes": permission_codes})

    op.drop_index("ix_crm_lead_assignment_event_event_type", table_name="crm_lead_assignment_event")
    op.drop_constraint("ck_crm_lead_assignment_event_type", "crm_lead_assignment_event", type_="check")
    op.drop_column("crm_lead_assignment_event", "event_type")

    op.drop_index("ix_crm_lead_sla_first_response", table_name="crm_lead")
    op.drop_index("ix_crm_lead_pool_status_assigned", table_name="crm_lead")
    op.drop_index("ix_crm_lead_campaign_status", table_name="crm_lead")
    op.drop_index("ix_crm_lead_recycled_at", table_name="crm_lead")
    op.drop_index("ix_crm_lead_last_activity_at", table_name="crm_lead")
    op.drop_index("ix_crm_lead_first_responded_at", table_name="crm_lead")
    op.drop_index("ix_crm_lead_first_response_due_at", table_name="crm_lead")
    op.drop_index("ix_crm_lead_assignment_expires_at", table_name="crm_lead")
    op.drop_index("ix_crm_lead_pool_status", table_name="crm_lead")
    op.drop_index("ix_crm_lead_priority", table_name="crm_lead")
    op.drop_index("ix_crm_lead_campaign_id", table_name="crm_lead")
    op.drop_constraint("ck_crm_lead_pool_status", "crm_lead", type_="check")
    op.drop_constraint("ck_crm_lead_priority", "crm_lead", type_="check")
    op.drop_constraint("fk_crm_lead_campaign_id", "crm_lead", type_="foreignkey")
    op.drop_column("crm_lead", "recycle_count")
    op.drop_column("crm_lead", "recycled_at")
    op.drop_column("crm_lead", "last_activity_at")
    op.drop_column("crm_lead", "first_responded_at")
    op.drop_column("crm_lead", "first_response_due_at")
    op.drop_column("crm_lead", "assignment_expires_at")
    op.drop_column("crm_lead", "pool_status")
    op.drop_column("crm_lead", "priority")
    op.drop_column("crm_lead", "campaign_id")

    op.drop_table("crm_lead_operation_policy")
    op.drop_table("crm_lead_campaign")

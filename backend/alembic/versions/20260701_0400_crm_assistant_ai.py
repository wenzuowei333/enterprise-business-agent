"""crm assistant conversations and ai insights

Revision ID: 20260701_0400
Revises: 20260701_0300
Create Date: 2026-07-01 04:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260701_0400"
down_revision = "20260701_0300"
branch_labels = None
depends_on = None


CRM_ASSISTANT_PERMISSIONS = [
    ("crm_insight.generate", "生成 CRM 智能判断", "crm_insight", "generate"),
    ("crm_insight.review", "复核 CRM 智能判断", "crm_insight", "review"),
]


def created_at_column() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def updated_at_column() -> sa.Column:
    return sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


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
        "assistant_conversation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_no", sa.String(length=120), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("username_snapshot", sa.String(length=80)),
        sa.Column("channel", sa.String(length=80), nullable=False, server_default="web"),
        sa.Column("session_id", sa.String(length=120)),
        sa.Column("context_type", sa.String(length=80)),
        sa.Column("context_id", sa.String(length=160)),
        sa.Column("operation", sa.String(length=120)),
        sa.Column("user_message", sa.Text(), nullable=False),
        sa.Column("assistant_message", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False, server_default="rule"),
        sa.Column("model_name", sa.String(length=120)),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="completed"),
        sa.Column("payload_json", postgresql.JSONB()),
        created_at_column(),
    )
    op.create_index("ix_assistant_conversation_no", "assistant_conversation", ["conversation_no"], unique=True)
    op.create_index("ix_assistant_conversation_user", "assistant_conversation", ["user_id", "created_at"])
    op.create_index("ix_assistant_conversation_username", "assistant_conversation", ["username_snapshot"])
    op.create_index("ix_assistant_conversation_channel", "assistant_conversation", ["channel", "created_at"])
    op.create_index("ix_assistant_conversation_session", "assistant_conversation", ["session_id", "created_at"])
    op.create_index("ix_assistant_conversation_context", "assistant_conversation", ["context_type", "context_id"])
    op.create_index("ix_assistant_conversation_operation", "assistant_conversation", ["operation", "created_at"])
    op.create_index("ix_assistant_conversation_source", "assistant_conversation", ["source"])
    op.create_index("ix_assistant_conversation_model", "assistant_conversation", ["model_name"])
    op.create_index("ix_assistant_conversation_status", "assistant_conversation", ["status"])
    op.create_index("ix_assistant_conversation_created", "assistant_conversation", ["created_at"])

    op.create_table(
        "crm_project_insight",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("insight_no", sa.String(length=120), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("crm_project.id", ondelete="CASCADE")),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("crm_project_customer_task.id", ondelete="CASCADE")),
        sa.Column("customer_code", sa.String(length=120), sa.ForeignKey("customer_master.customer_code", ondelete="RESTRICT")),
        sa.Column("insight_type", sa.String(length=120), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("suggested_action", sa.Text()),
        sa.Column("risk_level", sa.String(length=40), nullable=False, server_default="medium"),
        sa.Column("opportunity_level", sa.String(length=40)),
        sa.Column("confidence_score", sa.Integer(), nullable=False, server_default="70"),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="draft"),
        sa.Column("evidence_json", postgresql.JSONB()),
        sa.Column("source", sa.String(length=80), nullable=False, server_default="rule"),
        sa.Column("generated_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("reviewed_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("review_note", sa.Text()),
        sa.Column("payload_json", postgresql.JSONB()),
        created_at_column(),
        updated_at_column(),
    )
    op.create_index("ix_crm_project_insight_no", "crm_project_insight", ["insight_no"], unique=True)
    op.create_index("ix_crm_project_insight_project", "crm_project_insight", ["project_id", "created_at"])
    op.create_index("ix_crm_project_insight_task", "crm_project_insight", ["task_id", "created_at"])
    op.create_index("ix_crm_project_insight_customer", "crm_project_insight", ["customer_code", "created_at"])
    op.create_index("ix_crm_project_insight_type", "crm_project_insight", ["insight_type", "created_at"])
    op.create_index("ix_crm_project_insight_risk", "crm_project_insight", ["risk_level", "created_at"])
    op.create_index("ix_crm_project_insight_opportunity", "crm_project_insight", ["opportunity_level"])
    op.create_index("ix_crm_project_insight_status", "crm_project_insight", ["status", "created_at"])
    op.create_index("ix_crm_project_insight_source", "crm_project_insight", ["source"])
    op.create_index("ix_crm_project_insight_generated_by", "crm_project_insight", ["generated_by_user_id"])
    op.create_index("ix_crm_project_insight_reviewed_by", "crm_project_insight", ["reviewed_by_user_id"])
    op.create_index("ix_crm_project_insight_reviewed_at", "crm_project_insight", ["reviewed_at"])

    for code, name, resource_type, action_type in CRM_ASSISTANT_PERMISSIONS:
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
          AND p.resource_type = 'crm_insight'
        ON CONFLICT ON CONSTRAINT uq_role_permissions_role_permission DO NOTHING
        """
    )
    _grant("boss", ["crm_insight.generate", "crm_insight.review"])
    _grant("business_middle_office", ["crm_insight.generate", "crm_insight.review"])
    _grant("data_middle_office", ["crm_insight.generate", "crm_insight.review"])


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM role_permissions
        WHERE permission_id IN (
          SELECT id FROM permissions WHERE permission_code IN ('crm_insight.generate', 'crm_insight.review')
        )
        """
    )
    op.execute("DELETE FROM permissions WHERE permission_code IN ('crm_insight.generate', 'crm_insight.review')")
    op.drop_table("crm_project_insight")
    op.drop_table("assistant_conversation")

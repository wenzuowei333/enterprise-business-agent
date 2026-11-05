"""add AI case remediation workflow

Revision ID: 20260902_0100
Revises: 20260901_0100
Create Date: 2026-09-02 09:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260902_0100"
down_revision = "20260901_0100"
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "ai_case_remediation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workflow_no", sa.String(120), nullable=False, unique=True),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("exception_case.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("ai_conversation.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_message_id", sa.Integer(), sa.ForeignKey("ai_message.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("confirmed_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("work_item_id", sa.Integer(), sa.ForeignKey("work_item.id", ondelete="SET NULL")),
        sa.Column("exception_action_id", sa.Integer(), sa.ForeignKey("exception_action.id", ondelete="SET NULL")),
        sa.Column("client_request_id", sa.String(120), nullable=False),
        sa.Column("evidence_version", sa.String(128), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="schema_generating"),
        sa.Column("form_schema_json", JSON),
        sa.Column("answers_json", JSON),
        sa.Column("plan_json", JSON),
        sa.Column("action_dsl_json", JSON),
        sa.Column("sandbox_json", JSON),
        sa.Column("result_json", JSON),
        sa.Column("error_code", sa.String(120)),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("stale_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("actor_user_id", "client_request_id", name="uq_ai_case_remediation_actor_request"),
        sa.CheckConstraint("lock_version >= 1", name="ck_ai_case_remediation_lock_version"),
        sa.CheckConstraint("status IN ('schema_generating','form_ready','collecting','plan_generating','plan_ready','execution_queued','executing','completed','failed','stale','cancelled')", name="ck_ai_case_remediation_status"),
    )
    for column in ("workflow_no", "case_id", "conversation_id", "source_message_id", "actor_user_id", "evidence_version", "status", "error_code"):
        op.create_index(f"ix_ai_case_remediation_{column}", "ai_case_remediation", [column])
    op.create_index("ix_ai_case_remediation_actor_updated", "ai_case_remediation", ["actor_user_id", "updated_at"])
    op.create_index(
        "uq_ai_case_remediation_active_actor_message_evidence",
        "ai_case_remediation",
        ["actor_user_id", "source_message_id", "evidence_version"],
        unique=True,
        postgresql_where=sa.text("status IN ('schema_generating','form_ready','collecting','plan_generating','plan_ready','execution_queued','executing')"),
        sqlite_where=sa.text("status IN ('schema_generating','form_ready','collecting','plan_generating','plan_ready','execution_queued','executing')"),
    )
    for column in ("confirmed_by_user_id", "work_item_id", "exception_action_id"):
        op.create_index(f"ix_ai_case_remediation_{column}", "ai_case_remediation", [column])

    op.create_table(
        "ai_case_remediation_attachment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("attachment_no", sa.String(120), nullable=False, unique=True),
        sa.Column("workflow_id", sa.Integer(), sa.ForeignKey("ai_case_remediation.id", ondelete="CASCADE"), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("original_name", sa.String(255), nullable=False),
        sa.Column("object_key", sa.String(500), nullable=False, unique=True),
        sa.Column("content_type", sa.String(120), nullable=False),
        sa.Column("extension", sa.String(20), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("scan_status", sa.String(40), nullable=False, server_default="pending"),
        sa.Column("parse_status", sa.String(40), nullable=False, server_default="pending"),
        sa.Column("extracted_text", sa.Text()),
        sa.Column("error_code", sa.String(120)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("workflow_id", "sha256", name="uq_ai_remediation_attachment_workflow_sha256"),
        sa.CheckConstraint("size_bytes >= 0", name="ck_ai_remediation_attachment_size"),
    )
    for column in ("attachment_no", "workflow_id", "uploaded_by_user_id", "sha256", "scan_status", "parse_status", "error_code", "expires_at"):
        op.create_index(f"ix_ai_case_remediation_attachment_{column}", "ai_case_remediation_attachment", [column])

    op.create_table(
        "ai_case_remediation_run",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_no", sa.String(120), nullable=False, unique=True),
        sa.Column("workflow_id", sa.Integer(), sa.ForeignKey("ai_case_remediation.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("run_kind", sa.String(40), nullable=False),
        sa.Column("client_request_id", sa.String(120), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="queued"),
        sa.Column("request_id", sa.String(160), nullable=False, unique=True),
        sa.Column("usage_json", JSON),
        sa.Column("error_code", sa.String(120)),
        sa.Column("lease_owner", sa.String(120)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("actor_user_id", "client_request_id", name="uq_ai_remediation_run_actor_request"),
        sa.CheckConstraint("run_kind IN ('form','plan','sandbox','execution')", name="ck_ai_remediation_run_kind"),
        sa.CheckConstraint("status IN ('queued','processing','completed','failed','cancelled')", name="ck_ai_remediation_run_status"),
    )
    for column in ("run_no", "workflow_id", "actor_user_id", "run_kind", "status", "request_id", "error_code", "lease_owner", "lease_expires_at"):
        op.create_index(f"ix_ai_case_remediation_run_{column}", "ai_case_remediation_run", [column])


def downgrade() -> None:
    op.drop_table("ai_case_remediation_run")
    op.drop_table("ai_case_remediation_attachment")
    op.drop_table("ai_case_remediation")

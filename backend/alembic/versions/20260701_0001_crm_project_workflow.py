"""crm project workflow base tables

Revision ID: 20260701_0001
Revises: 20260630_1600
Create Date: 2026-07-01 00:01:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260701_0001"
down_revision = "20260630_1600"
branch_labels = None
depends_on = None


def created_at_column() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def updated_at_column() -> sa.Column:
    return sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "approval_instance",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("approval_no", sa.String(length=120), nullable=False),
        sa.Column("approval_type", sa.String(length=120), nullable=False),
        sa.Column("resource_type", sa.String(length=120), nullable=False),
        sa.Column("resource_id", sa.String(length=160), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("applicant_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("current_handler_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="draft"),
        sa.Column("priority", sa.String(length=40), nullable=False, server_default="normal"),
        sa.Column("payload_json", postgresql.JSONB()),
        sa.Column("result_json", postgresql.JSONB()),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        created_at_column(),
        updated_at_column(),
    )
    op.create_index("ix_approval_instance_approval_no", "approval_instance", ["approval_no"], unique=True)
    op.create_index("ix_approval_instance_approval_type", "approval_instance", ["approval_type"])
    op.create_index("ix_approval_instance_resource", "approval_instance", ["resource_type", "resource_id"])
    op.create_index("ix_approval_instance_applicant", "approval_instance", ["applicant_user_id"])
    op.create_index("ix_approval_instance_handler", "approval_instance", ["current_handler_user_id"])
    op.create_index("ix_approval_instance_status", "approval_instance", ["status"])
    op.create_index("ix_approval_instance_priority", "approval_instance", ["priority"])
    op.create_index("ix_approval_instance_submitted_at", "approval_instance", ["submitted_at"])
    op.create_index("ix_approval_instance_reviewed_at", "approval_instance", ["reviewed_at"])
    op.create_index("ix_approval_instance_closed_at", "approval_instance", ["closed_at"])

    op.create_table(
        "approval_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("approval_id", sa.Integer(), sa.ForeignKey("approval_instance.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("operator_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("from_status", sa.String(length=40)),
        sa.Column("to_status", sa.String(length=40)),
        sa.Column("comment", sa.Text()),
        sa.Column("snapshot_json", postgresql.JSONB()),
        created_at_column(),
    )
    op.create_index("ix_approval_event_approval_id", "approval_event", ["approval_id"])
    op.create_index("ix_approval_event_event_type", "approval_event", ["event_type"])
    op.create_index("ix_approval_event_operator", "approval_event", ["operator_user_id"])
    op.create_index("ix_approval_event_to_status", "approval_event", ["to_status"])
    op.create_index("ix_approval_event_created_at", "approval_event", ["created_at"])

    op.create_table(
        "approval_attachment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("approval_id", sa.Integer(), sa.ForeignKey("approval_instance.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=120)),
        sa.Column("size_bytes", sa.Integer()),
        sa.Column("storage_path", sa.String(length=500), nullable=False),
        sa.Column("file_digest", sa.String(length=160)),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        created_at_column(),
    )
    op.create_index("ix_approval_attachment_approval_id", "approval_attachment", ["approval_id"])
    op.create_index("ix_approval_attachment_file_digest", "approval_attachment", ["file_digest"])
    op.create_index("ix_approval_attachment_created_by", "approval_attachment", ["created_by_user_id"])
    op.create_index("ix_approval_attachment_created_at", "approval_attachment", ["created_at"])

    op.create_table(
        "crm_project",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_code", sa.String(length=120), nullable=False),
        sa.Column("project_name", sa.String(length=255), nullable=False),
        sa.Column("project_type", sa.String(length=120)),
        sa.Column("purpose", sa.Text()),
        sa.Column("customer_scope_note", sa.Text()),
        sa.Column("business_line", sa.String(length=120)),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("project_manager_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("participant_user_ids", postgresql.JSONB()),
        sa.Column("start_date", sa.Date()),
        sa.Column("due_date", sa.Date()),
        sa.Column("minimum_action", sa.Text()),
        sa.Column("closure_standard", sa.Text()),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="draft"),
        sa.Column("approval_status", sa.String(length=40), nullable=False, server_default="draft"),
        sa.Column("current_approval_id", sa.Integer(), sa.ForeignKey("approval_instance.id", ondelete="SET NULL")),
        sa.Column("next_step_status", sa.String(length=80)),
        sa.Column("next_step_action", sa.Text()),
        sa.Column("next_step_followup_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("updated_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        created_at_column(),
        updated_at_column(),
    )
    op.create_index("ix_crm_project_project_code", "crm_project", ["project_code"], unique=True)
    op.create_index("ix_crm_project_project_name", "crm_project", ["project_name"])
    op.create_index("ix_crm_project_project_type", "crm_project", ["project_type"])
    op.create_index("ix_crm_project_business_line", "crm_project", ["business_line"])
    op.create_index("ix_crm_project_owner", "crm_project", ["owner_user_id"])
    op.create_index("ix_crm_project_manager", "crm_project", ["project_manager_user_id"])
    op.create_index("ix_crm_project_start_date", "crm_project", ["start_date"])
    op.create_index("ix_crm_project_due_date", "crm_project", ["due_date"])
    op.create_index("ix_crm_project_status", "crm_project", ["status"])
    op.create_index("ix_crm_project_approval_status", "crm_project", ["approval_status"])
    op.create_index("ix_crm_project_current_approval", "crm_project", ["current_approval_id"])
    op.create_index("ix_crm_project_next_step_status", "crm_project", ["next_step_status"])
    op.create_index("ix_crm_project_next_followup", "crm_project", ["next_step_followup_at"])
    op.create_index("ix_crm_project_created_by", "crm_project", ["created_by_user_id"])
    op.create_index("ix_crm_project_updated_by", "crm_project", ["updated_by_user_id"])

    op.create_table(
        "crm_project_customer_task",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("crm_project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_code", sa.String(length=120), nullable=False),
        sa.Column("customer_code", sa.String(length=120), sa.ForeignKey("customer_master.customer_code", ondelete="RESTRICT"), nullable=False),
        sa.Column("customer_name_snapshot", sa.String(length=255), nullable=False),
        sa.Column("executor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("executor_employee_code", sa.String(length=80)),
        sa.Column("executor_name_snapshot", sa.String(length=120)),
        sa.Column("business_issue_point", sa.Text()),
        sa.Column("round_target", sa.Text()),
        sa.Column("feedback_due_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="not_started"),
        sa.Column("minimum_action_done", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("need_support", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("need_manager_support", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("need_boss_decision", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_blocked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_closed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("latest_followup_id", sa.Integer()),
        sa.Column("latest_blocker_reason", sa.String(length=160)),
        sa.Column("latest_blocker_note", sa.Text()),
        sa.Column("latest_owner_next_status", sa.String(length=80)),
        sa.Column("latest_owner_next_action", sa.Text()),
        sa.Column("latest_owner_next_followup_at", sa.DateTime(timezone=True)),
        sa.Column("last_followup_at", sa.DateTime(timezone=True)),
        created_at_column(),
        updated_at_column(),
        sa.UniqueConstraint("project_id", "customer_code", name="uq_crm_task_project_customer"),
    )
    op.create_index("ix_crm_task_task_code", "crm_project_customer_task", ["task_code"], unique=True)
    op.create_index("ix_crm_task_project", "crm_project_customer_task", ["project_id"])
    op.create_index("ix_crm_task_customer", "crm_project_customer_task", ["customer_code"])
    op.create_index("ix_crm_task_customer_name", "crm_project_customer_task", ["customer_name_snapshot"])
    op.create_index("ix_crm_task_executor_user", "crm_project_customer_task", ["executor_user_id"])
    op.create_index("ix_crm_task_executor_employee", "crm_project_customer_task", ["executor_employee_code"])
    op.create_index("ix_crm_task_executor_name", "crm_project_customer_task", ["executor_name_snapshot"])
    op.create_index("ix_crm_task_feedback_due", "crm_project_customer_task", ["feedback_due_at"])
    op.create_index("ix_crm_task_status", "crm_project_customer_task", ["status"])
    op.create_index("ix_crm_task_minimum_done", "crm_project_customer_task", ["minimum_action_done"])
    op.create_index("ix_crm_task_need_support", "crm_project_customer_task", ["need_support"])
    op.create_index("ix_crm_task_need_manager", "crm_project_customer_task", ["need_manager_support"])
    op.create_index("ix_crm_task_need_boss", "crm_project_customer_task", ["need_boss_decision"])
    op.create_index("ix_crm_task_is_blocked", "crm_project_customer_task", ["is_blocked"])
    op.create_index("ix_crm_task_is_closed", "crm_project_customer_task", ["is_closed"])
    op.create_index("ix_crm_task_latest_followup", "crm_project_customer_task", ["latest_followup_id"])
    op.create_index("ix_crm_task_blocker_reason", "crm_project_customer_task", ["latest_blocker_reason"])
    op.create_index("ix_crm_task_owner_next_status", "crm_project_customer_task", ["latest_owner_next_status"])
    op.create_index("ix_crm_task_owner_next_at", "crm_project_customer_task", ["latest_owner_next_followup_at"])
    op.create_index("ix_crm_task_last_followup", "crm_project_customer_task", ["last_followup_at"])

    op.create_table(
        "crm_followup",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("followup_no", sa.String(length=120), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("crm_project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("crm_project_customer_task.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_code", sa.String(length=120), sa.ForeignKey("customer_master.customer_code", ondelete="RESTRICT"), nullable=False),
        sa.Column("executor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("executor_name_snapshot", sa.String(length=120)),
        sa.Column("followup_date", sa.Date()),
        sa.Column("method", sa.String(length=80)),
        sa.Column("frontline_action", sa.Text()),
        sa.Column("customer_feedback", sa.Text()),
        sa.Column("current_need", sa.Text()),
        sa.Column("need_type", sa.String(length=120)),
        sa.Column("blocker_reason", sa.String(length=160)),
        sa.Column("blocker_note", sa.Text()),
        sa.Column("next_action_type", sa.String(length=120)),
        sa.Column("next_action", sa.Text()),
        sa.Column("next_followup_at", sa.DateTime(timezone=True)),
        sa.Column("minimum_action_done", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("need_support", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("need_manager_support", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("need_boss_decision", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_closed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("valid_feedback", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("review_status", sa.String(length=40), nullable=False, server_default="pending"),
        sa.Column("review_result", sa.String(length=120)),
        sa.Column("review_note", sa.Text()),
        sa.Column("owner_next_status", sa.String(length=80)),
        sa.Column("owner_next_action", sa.Text()),
        sa.Column("owner_next_followup_at", sa.DateTime(timezone=True)),
        sa.Column("reviewed_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("approval_id", sa.Integer(), sa.ForeignKey("approval_instance.id", ondelete="SET NULL")),
        created_at_column(),
        updated_at_column(),
    )
    op.create_index("ix_crm_followup_followup_no", "crm_followup", ["followup_no"], unique=True)
    op.create_index("ix_crm_followup_project", "crm_followup", ["project_id"])
    op.create_index("ix_crm_followup_task", "crm_followup", ["task_id"])
    op.create_index("ix_crm_followup_customer", "crm_followup", ["customer_code"])
    op.create_index("ix_crm_followup_executor", "crm_followup", ["executor_user_id"])
    op.create_index("ix_crm_followup_executor_name", "crm_followup", ["executor_name_snapshot"])
    op.create_index("ix_crm_followup_date", "crm_followup", ["followup_date"])
    op.create_index("ix_crm_followup_method", "crm_followup", ["method"])
    op.create_index("ix_crm_followup_need_type", "crm_followup", ["need_type"])
    op.create_index("ix_crm_followup_blocker_reason", "crm_followup", ["blocker_reason"])
    op.create_index("ix_crm_followup_next_action_type", "crm_followup", ["next_action_type"])
    op.create_index("ix_crm_followup_next_at", "crm_followup", ["next_followup_at"])
    op.create_index("ix_crm_followup_minimum_done", "crm_followup", ["minimum_action_done"])
    op.create_index("ix_crm_followup_need_support", "crm_followup", ["need_support"])
    op.create_index("ix_crm_followup_need_manager", "crm_followup", ["need_manager_support"])
    op.create_index("ix_crm_followup_need_boss", "crm_followup", ["need_boss_decision"])
    op.create_index("ix_crm_followup_is_closed", "crm_followup", ["is_closed"])
    op.create_index("ix_crm_followup_valid_feedback", "crm_followup", ["valid_feedback"])
    op.create_index("ix_crm_followup_review_status", "crm_followup", ["review_status"])
    op.create_index("ix_crm_followup_review_result", "crm_followup", ["review_result"])
    op.create_index("ix_crm_followup_owner_next_status", "crm_followup", ["owner_next_status"])
    op.create_index("ix_crm_followup_owner_next_at", "crm_followup", ["owner_next_followup_at"])
    op.create_index("ix_crm_followup_reviewed_by", "crm_followup", ["reviewed_by_user_id"])
    op.create_index("ix_crm_followup_reviewed_at", "crm_followup", ["reviewed_at"])
    op.create_index("ix_crm_followup_approval", "crm_followup", ["approval_id"])

    op.create_foreign_key(
        "fk_crm_task_latest_followup",
        "crm_project_customer_task",
        "crm_followup",
        ["latest_followup_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "crm_project_review",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("review_no", sa.String(length=120), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("crm_project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("review_date", sa.Date()),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="draft"),
        sa.Column("customer_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("feedback_customer_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("valid_feedback_customer_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("no_feedback_customer_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("support_item_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("closed_customer_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unclosed_customer_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("data_summary", sa.Text()),
        sa.Column("business_judgement", sa.Text()),
        sa.Column("main_problem", sa.Text()),
        sa.Column("next_suggestion", sa.Text()),
        sa.Column("conclusion", sa.String(length=80)),
        sa.Column("decision_maker_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        created_at_column(),
        updated_at_column(),
    )
    op.create_index("ix_crm_project_review_review_no", "crm_project_review", ["review_no"], unique=True)
    op.create_index("ix_crm_project_review_project", "crm_project_review", ["project_id"])
    op.create_index("ix_crm_project_review_date", "crm_project_review", ["review_date"])
    op.create_index("ix_crm_project_review_status", "crm_project_review", ["status"])
    op.create_index("ix_crm_project_review_conclusion", "crm_project_review", ["conclusion"])
    op.create_index("ix_crm_project_review_decision_maker", "crm_project_review", ["decision_maker_user_id"])

    op.create_table(
        "work_item",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("item_no", sa.String(length=120), nullable=False),
        sa.Column("source_type", sa.String(length=120), nullable=False),
        sa.Column("source_id", sa.String(length=160), nullable=False),
        sa.Column("resource_type", sa.String(length=120)),
        sa.Column("resource_id", sa.String(length=160)),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("crm_project.id", ondelete="CASCADE")),
        sa.Column("customer_code", sa.String(length=120), sa.ForeignKey("customer_master.customer_code", ondelete="RESTRICT")),
        sa.Column("item_type", sa.String(length=120), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("detail", sa.Text()),
        sa.Column("priority", sa.String(length=40), nullable=False, server_default="normal"),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="open"),
        sa.Column("assignee_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolution_note", sa.Text()),
        created_at_column(),
        updated_at_column(),
    )
    op.create_index("ix_work_item_item_no", "work_item", ["item_no"], unique=True)
    op.create_index("ix_work_item_source", "work_item", ["source_type", "source_id"])
    op.create_index("ix_work_item_resource", "work_item", ["resource_type", "resource_id"])
    op.create_index("ix_work_item_project", "work_item", ["project_id"])
    op.create_index("ix_work_item_customer", "work_item", ["customer_code"])
    op.create_index("ix_work_item_item_type", "work_item", ["item_type"])
    op.create_index("ix_work_item_title", "work_item", ["title"])
    op.create_index("ix_work_item_priority", "work_item", ["priority"])
    op.create_index("ix_work_item_status", "work_item", ["status"])
    op.create_index("ix_work_item_assignee", "work_item", ["assignee_user_id"])
    op.create_index("ix_work_item_due_at", "work_item", ["due_at"])
    op.create_index("ix_work_item_resolved_by", "work_item", ["resolved_by_user_id"])
    op.create_index("ix_work_item_resolved_at", "work_item", ["resolved_at"])
    op.create_index("ix_work_item_created_at", "work_item", ["created_at"])


def downgrade() -> None:
    op.drop_table("work_item")
    op.drop_table("crm_project_review")
    op.drop_constraint("fk_crm_task_latest_followup", "crm_project_customer_task", type_="foreignkey")
    op.drop_table("crm_followup")
    op.drop_table("crm_project_customer_task")
    op.drop_table("crm_project")
    op.drop_table("approval_attachment")
    op.drop_table("approval_event")
    op.drop_table("approval_instance")

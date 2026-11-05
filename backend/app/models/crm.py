from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.core.database import Base
from app.models.identity import TimestampMixin


CRM_PROJECT_STATUSES = ("draft", "submitted", "active", "paused", "closed", "cancelled")
CRM_TASK_STATUSES = ("not_started", "in_progress", "need_supplement", "need_support", "paused", "closed", "cancelled")
CRM_FOLLOWUP_REVIEW_STATUSES = ("pending", "approved", "rejected", "need_supplement")
CRM_PROJECT_REVIEW_STATUSES = ("draft", "submitted", "confirmed")
class CrmLeadStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    QUALIFIED = "qualified"
    CONVERSION_PENDING = "conversion_pending"
    CONVERTED = "converted"
    CLOSED = "closed"
    REJECTED = "rejected"


CRM_LEAD_STATUSES = tuple(status.value for status in CrmLeadStatus)
CRM_LEAD_PRIORITIES = ("low", "normal", "high", "urgent")
CRM_LEAD_POOL_STATUSES = ("private", "public")
CRM_LEAD_ASSIGNMENT_EVENT_TYPES = ("assigned", "claimed", "recycled", "returned")
CRM_LEAD_CAMPAIGN_STATUSES = ("active", "inactive", "archived")
CRM_APPROVAL_TYPES = (
    "crm_project_create",
    "crm_project_update",
    "crm_followup_submit",
    "customer_business_profile_update",
    "customer_profile_update",
    "crm_project_extension",
    "crm_task_extension",
    "crm_project_close",
    "crm_lead_convert",
    "customer_tag_change",
)
CRM_APPROVAL_STATUSES = (
    "draft",
    "submitted",
    "under_review",
    "need_supplement",
    "approved",
    "rejected",
    "cancelled",
    "completed",
)
WORK_ITEM_STATUSES = ("open", "processing", "resolved", "closed")
WORK_ITEM_PRIORITIES = ("normal", "high", "urgent")


class ApprovalInstance(Base, TimestampMixin):
    __tablename__ = "approval_instance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    approval_no: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    approval_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    resource_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    applicant_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    current_handler_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    status: Mapped[str] = mapped_column(String(40), default="draft", nullable=False, index=True)
    priority: Mapped[str] = mapped_column(String(40), default="normal", nullable=False, index=True)
    payload_json: Mapped[dict | list | None] = mapped_column(JSONB)
    result_json: Mapped[dict | list | None] = mapped_column(JSONB)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class ApprovalEvent(Base):
    __tablename__ = "approval_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    approval_id: Mapped[int] = mapped_column(ForeignKey("approval_instance.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    operator_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(40))
    to_status: Mapped[str | None] = mapped_column(String(40), index=True)
    comment: Mapped[str | None] = mapped_column(Text)
    snapshot_json: Mapped[dict | list | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


class ApprovalAttachment(Base):
    __tablename__ = "approval_attachment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    approval_id: Mapped[int] = mapped_column(ForeignKey("approval_instance.id", ondelete="CASCADE"), nullable=False, index=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(120))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_digest: Mapped[str | None] = mapped_column(String(160), index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


class ImageProcessingJob(Base, TimestampMixin):
    __tablename__ = "image_processing_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_no: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    created_by_username: Mapped[str | None] = mapped_column(String(80), index=True)
    template_type: Mapped[str] = mapped_column(String(40), default="main", nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), default="queued", nullable=False, index=True)
    input_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    options_json: Mapped[dict | list | None] = mapped_column(JSONB)
    result_json: Mapped[dict | list | None] = mapped_column(JSONB)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class ImageProcessingFile(Base):
    __tablename__ = "image_processing_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("image_processing_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    input_path: Mapped[str | None] = mapped_column(String(800))
    output_path: Mapped[str | None] = mapped_column(String(800))
    output_filename: Mapped[str | None] = mapped_column(String(255))
    content_type: Mapped[str | None] = mapped_column(String(120))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="queued", nullable=False, index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ExternalApiKey(Base, TimestampMixin):
    __tablename__ = "external_api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key_id: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    owner_name: Mapped[str | None] = mapped_column(String(120))
    key_prefix: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    key_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    scope_region: Mapped[str | None] = mapped_column(String(120), index=True)
    scope_project_ids: Mapped[list[int] | None] = mapped_column(JSONB)
    allowed_customer_fields: Mapped[list[str] | None] = mapped_column(JSONB)
    can_read_projects: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    can_read_customers: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    can_read_followups: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    can_read_judgements: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    can_read_tasks: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    can_read_approvals: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    can_read_audit_summary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    can_read_products: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    can_read_suppliers: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    can_read_sales_summary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    can_read_purchase_summary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    can_read_inventory_summary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    can_read_receivables: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    can_read_data_quality: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    can_read_changes: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    permission_scopes: Mapped[list[str] | None] = mapped_column(JSONB)
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    daily_request_limit: Mapped[int] = mapped_column(Integer, default=10000, nullable=False)
    previous_key_prefix: Mapped[str | None] = mapped_column(String(32))
    previous_key_hash: Mapped[str | None] = mapped_column(String(128), unique=True, index=True)
    previous_key_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    rotation_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    allowed_ips: Mapped[list[str] | None] = mapped_column(JSONB)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    revoked_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    revoked_reason: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_used_ip: Mapped[str | None] = mapped_column(String(80))


class ExternalApiUsageLog(Base):
    __tablename__ = "external_api_usage_log"
    __table_args__ = (Index("ix_external_api_usage_key_created", "key_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key_id: Mapped[str] = mapped_column(
        ForeignKey("external_api_keys.key_id", ondelete="CASCADE"), nullable=False, index=True
    )
    request_id: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    endpoint: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    method: Mapped[str] = mapped_column(String(12), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, default=0, nullable=False, index=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    response_count: Mapped[int | None] = mapped_column(Integer)
    client_ip: Mapped[str | None] = mapped_column(String(80))
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class AssistantConversation(Base):
    __tablename__ = "assistant_conversation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_no: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    username_snapshot: Mapped[str | None] = mapped_column(String(80), index=True)
    channel: Mapped[str] = mapped_column(String(80), default="web", nullable=False, index=True)
    session_id: Mapped[str | None] = mapped_column(String(120), index=True)
    context_type: Mapped[str | None] = mapped_column(String(80), index=True)
    context_id: Mapped[str | None] = mapped_column(String(160), index=True)
    operation: Mapped[str | None] = mapped_column(String(120), index=True)
    user_message: Mapped[str] = mapped_column(Text, nullable=False)
    assistant_message: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(80), default="rule", nullable=False, index=True)
    model_name: Mapped[str | None] = mapped_column(String(120), index=True)
    status: Mapped[str] = mapped_column(String(40), default="completed", nullable=False, index=True)
    payload_json: Mapped[dict | list | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


class CrmProjectInsight(Base, TimestampMixin):
    __tablename__ = "crm_project_insight"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    insight_no: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("crm_project.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("crm_project_customer_task.id", ondelete="CASCADE"), index=True)
    customer_code: Mapped[str | None] = mapped_column(
        String(120),
        ForeignKey("customer_master.customer_code", ondelete="RESTRICT"),
        index=True,
    )
    insight_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_action: Mapped[str | None] = mapped_column(Text)
    risk_level: Mapped[str] = mapped_column(String(40), default="medium", nullable=False, index=True)
    opportunity_level: Mapped[str | None] = mapped_column(String(40), index=True)
    confidence_score: Mapped[int] = mapped_column(Integer, default=70, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="draft", nullable=False, index=True)
    evidence_json: Mapped[dict | list | None] = mapped_column(JSONB)
    source: Mapped[str] = mapped_column(String(80), default="rule", nullable=False, index=True)
    generated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    review_note: Mapped[str | None] = mapped_column(Text)
    payload_json: Mapped[dict | list | None] = mapped_column(JSONB)


class CrmLeadCampaign(Base, TimestampMixin):
    __tablename__ = "crm_lead_campaign"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'inactive', 'archived')",
            name="ck_crm_lead_campaign_status",
        ),
        CheckConstraint(
            "end_date IS NULL OR start_date IS NULL OR end_date >= start_date",
            name="ck_crm_lead_campaign_dates",
        ),
        Index("ix_crm_lead_campaign_status_dates", "status", "start_date", "end_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_code: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    campaign_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source: Mapped[str | None] = mapped_column(String(120), index=True)
    channel: Mapped[str | None] = mapped_column(String(120), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="active", nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date, index=True)
    end_date: Mapped[date | None] = mapped_column(Date, index=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)

    @validates("status")
    def _validate_status(self, _key: str, status: str) -> str:
        if status not in CRM_LEAD_CAMPAIGN_STATUSES:
            raise ValueError(f"Invalid CRM lead campaign status: {status}")
        return status


class CrmLeadOperationPolicy(Base, TimestampMixin):
    __tablename__ = "crm_lead_operation_policy"
    __table_args__ = (
        CheckConstraint("first_response_hours > 0", name="ck_crm_lead_policy_first_response_hours"),
        CheckConstraint("next_followup_hours > 0", name="ck_crm_lead_policy_next_followup_hours"),
        CheckConstraint("assignment_hold_hours > 0", name="ck_crm_lead_policy_assignment_hold_hours"),
        CheckConstraint("due_soon_hours >= 0", name="ck_crm_lead_policy_due_soon_hours"),
        CheckConstraint("daily_claim_limit >= 0", name="ck_crm_lead_policy_daily_claim_limit"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    policy_key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, default="default")
    first_response_hours: Mapped[int] = mapped_column(Integer, default=24, nullable=False)
    next_followup_hours: Mapped[int] = mapped_column(Integer, default=72, nullable=False)
    assignment_hold_hours: Mapped[int] = mapped_column(Integer, default=168, nullable=False)
    due_soon_hours: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
    daily_claim_limit: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)


class CrmLead(Base, TimestampMixin):
    __tablename__ = "crm_lead"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'active', 'qualified', 'conversion_pending', 'converted', 'closed', 'rejected')",
            name="ck_crm_lead_status",
        ),
        CheckConstraint(
            "priority IN ('low', 'normal', 'high', 'urgent')",
            name="ck_crm_lead_priority",
        ),
        CheckConstraint(
            "pool_status IN ('private', 'public')",
            name="ck_crm_lead_pool_status",
        ),
        Index("ix_crm_lead_status_next_followup_at", "status", "next_followup_at"),
        Index("ix_crm_lead_owner_assigned", "owner_user_id", "assigned_user_id"),
        Index("ix_crm_lead_campaign_status", "campaign_id", "status"),
        Index("ix_crm_lead_pool_status_assigned", "pool_status", "assigned_at"),
        Index("ix_crm_lead_sla_first_response", "first_response_due_at", "last_activity_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_no: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    lead_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    # These remain non-unique because shared contacts and duplicate candidates need review;
    # Task 2 blocks exact duplicates and Task 3 rechecks them within conversion transactions.
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    company_name: Mapped[str | None] = mapped_column(String(255), index=True)
    contact_name: Mapped[str | None] = mapped_column(String(120), index=True)
    contact_phone: Mapped[str | None] = mapped_column(String(80), index=True)
    normalized_phone: Mapped[str | None] = mapped_column(String(80), index=True)
    source: Mapped[str | None] = mapped_column(String(120), index=True)
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("crm_lead_campaign.id", ondelete="SET NULL"), index=True)
    region: Mapped[str | None] = mapped_column(String(120), index=True)
    address: Mapped[str | None] = mapped_column(Text)
    customer_group_name: Mapped[str | None] = mapped_column(String(255))
    business_line: Mapped[str | None] = mapped_column(String(120), index=True)
    intent_summary: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="draft", nullable=False, index=True)
    priority: Mapped[str] = mapped_column(String(40), default="normal", nullable=False, index=True)
    pool_status: Mapped[str] = mapped_column(String(40), default="private", nullable=False, index=True)
    qualification_note: Mapped[str | None] = mapped_column(Text)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    assigned_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    assignment_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    first_response_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    first_responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_followup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    next_followup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    recycled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    recycle_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    current_approval_id: Mapped[int | None] = mapped_column(ForeignKey("approval_instance.id", ondelete="SET NULL"), index=True)
    converted_customer_code: Mapped[str | None] = mapped_column(
        ForeignKey("customer_master.customer_code", ondelete="SET NULL"), index=True
    )
    converted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    converted_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)

    @validates("status")
    def _validate_status(self, _key: str, status: CrmLeadStatus | str) -> str:
        try:
            return CrmLeadStatus(status).value
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid CRM lead status: {status}") from exc

    @validates("priority")
    def _validate_priority(self, _key: str, priority: str) -> str:
        if priority not in CRM_LEAD_PRIORITIES:
            raise ValueError(f"Invalid CRM lead priority: {priority}")
        return priority

    @validates("pool_status")
    def _validate_pool_status(self, _key: str, pool_status: str) -> str:
        if pool_status not in CRM_LEAD_POOL_STATUSES:
            raise ValueError(f"Invalid CRM lead pool status: {pool_status}")
        return pool_status


class CrmLeadFollowup(Base, TimestampMixin):
    __tablename__ = "crm_lead_followup"
    __table_args__ = (Index("ix_crm_lead_followup_lead_created", "lead_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("crm_lead.id", ondelete="CASCADE"), nullable=False, index=True)
    followup_no: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str | None] = mapped_column(String(80), index=True)
    outcome: Mapped[str | None] = mapped_column(Text)
    next_action: Mapped[str | None] = mapped_column(Text)
    next_followup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)


class CrmLeadAssignmentEvent(Base):
    __tablename__ = "crm_lead_assignment_event"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('assigned', 'claimed', 'recycled', 'returned')",
            name="ck_crm_lead_assignment_event_type",
        ),
        Index("ix_crm_lead_assignment_event_lead_created", "lead_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("crm_lead.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(40), default="assigned", nullable=False, index=True)
    from_assignee_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    to_assignee_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    assigned_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    @validates("event_type")
    def _validate_event_type(self, _key: str, event_type: str) -> str:
        if event_type not in CRM_LEAD_ASSIGNMENT_EVENT_TYPES:
            raise ValueError(f"Invalid CRM lead assignment event type: {event_type}")
        return event_type


class CrmLeadProductIntent(Base, TimestampMixin):
    __tablename__ = "crm_lead_product_intent"
    __table_args__ = (Index("ix_crm_lead_product_intent_lead_sort", "lead_id", "sort_order"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("crm_lead.id", ondelete="CASCADE"), nullable=False, index=True)
    product_code: Mapped[str | None] = mapped_column(ForeignKey("product_master.product_code", ondelete="SET NULL"), index=True)
    product_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    quantity_note: Mapped[str | None] = mapped_column(String(255))
    interest_level: Mapped[str | None] = mapped_column(String(40), index=True)
    note: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class CrmProject(Base, TimestampMixin):
    __tablename__ = "crm_project"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_code: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    project_type: Mapped[str | None] = mapped_column(String(120), index=True)
    purpose: Mapped[str | None] = mapped_column(Text)
    customer_scope_note: Mapped[str | None] = mapped_column(Text)
    business_line: Mapped[str | None] = mapped_column(String(120), index=True)
    applicant_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    landing_approver_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    project_manager_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    participant_user_ids: Mapped[list[int] | None] = mapped_column(JSONB)
    progress_cc_user_ids: Mapped[list[int] | None] = mapped_column(JSONB)
    start_date: Mapped[date | None] = mapped_column(Date, index=True)
    due_date: Mapped[date | None] = mapped_column(Date, index=True)
    minimum_action: Mapped[str | None] = mapped_column(Text)
    closure_standard: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="draft", nullable=False, index=True)
    approval_status: Mapped[str] = mapped_column(String(40), default="draft", nullable=False, index=True)
    current_approval_id: Mapped[int | None] = mapped_column(ForeignKey("approval_instance.id", ondelete="SET NULL"), index=True)
    approval_withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    approval_withdrawn_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    approval_withdrawn_reason: Mapped[str | None] = mapped_column(Text)
    pre_withdraw_status: Mapped[str | None] = mapped_column(String(40))
    next_step_status: Mapped[str | None] = mapped_column(String(80), index=True)
    next_step_action: Mapped[str | None] = mapped_column(Text)
    next_step_followup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)


class CrmProjectCustomerTask(Base, TimestampMixin):
    __tablename__ = "crm_project_customer_task"
    __table_args__ = (
        UniqueConstraint("project_id", "customer_code", name="uq_crm_task_project_customer"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("crm_project.id", ondelete="CASCADE"), nullable=False, index=True)
    task_code: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    customer_code: Mapped[str] = mapped_column(
        String(120),
        ForeignKey("customer_master.customer_code", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    customer_name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    executor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    executor_employee_code: Mapped[str | None] = mapped_column(String(80), index=True)
    executor_name_snapshot: Mapped[str | None] = mapped_column(String(120), index=True)
    business_issue_point: Mapped[str | None] = mapped_column(Text)
    round_target: Mapped[str | None] = mapped_column(Text)
    feedback_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(40), default="not_started", nullable=False, index=True)
    minimum_action_done: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    need_support: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    need_manager_support: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    need_boss_decision: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    latest_followup_id: Mapped[int | None] = mapped_column(
        ForeignKey("crm_followup.id", ondelete="SET NULL", name="fk_crm_task_latest_followup", use_alter=True),
        index=True,
    )
    latest_blocker_reason: Mapped[str | None] = mapped_column(String(160), index=True)
    latest_blocker_note: Mapped[str | None] = mapped_column(Text)
    latest_owner_next_status: Mapped[str | None] = mapped_column(String(80), index=True)
    latest_owner_next_action: Mapped[str | None] = mapped_column(Text)
    latest_owner_next_followup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_followup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class CrmFollowup(Base, TimestampMixin):
    __tablename__ = "crm_followup"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    followup_no: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("crm_project.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("crm_project_customer_task.id", ondelete="CASCADE"), nullable=False, index=True)
    customer_code: Mapped[str] = mapped_column(
        String(120),
        ForeignKey("customer_master.customer_code", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    executor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    executor_name_snapshot: Mapped[str | None] = mapped_column(String(120), index=True)
    followup_date: Mapped[date | None] = mapped_column(Date, index=True)
    method: Mapped[str | None] = mapped_column(String(80), index=True)
    frontline_action: Mapped[str | None] = mapped_column(Text)
    customer_feedback: Mapped[str | None] = mapped_column(Text)
    current_need: Mapped[str | None] = mapped_column(Text)
    need_type: Mapped[str | None] = mapped_column(String(120), index=True)
    blocker_reason: Mapped[str | None] = mapped_column(String(160), index=True)
    blocker_note: Mapped[str | None] = mapped_column(Text)
    next_action_type: Mapped[str | None] = mapped_column(String(120), index=True)
    next_action: Mapped[str | None] = mapped_column(Text)
    next_followup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    minimum_action_done: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    business_profile_updated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    business_profile_approval_id: Mapped[int | None] = mapped_column(ForeignKey("approval_instance.id", ondelete="SET NULL"), index=True)
    customer_profile_updated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    customer_profile_approval_id: Mapped[int | None] = mapped_column(ForeignKey("approval_instance.id", ondelete="SET NULL"), index=True)
    need_support: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    need_manager_support: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    need_boss_decision: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    valid_feedback: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    review_status: Mapped[str] = mapped_column(String(40), default="pending", nullable=False, index=True)
    review_result: Mapped[str | None] = mapped_column(String(120), index=True)
    review_note: Mapped[str | None] = mapped_column(Text)
    owner_next_status: Mapped[str | None] = mapped_column(String(80), index=True)
    owner_next_action: Mapped[str | None] = mapped_column(Text)
    owner_next_followup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    approval_id: Mapped[int | None] = mapped_column(ForeignKey("approval_instance.id", ondelete="SET NULL"), index=True)


class CrmProjectReview(Base, TimestampMixin):
    __tablename__ = "crm_project_review"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    review_no: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("crm_project.id", ondelete="CASCADE"), nullable=False, index=True)
    review_date: Mapped[date | None] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(40), default="draft", nullable=False, index=True)
    customer_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    feedback_customer_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    valid_feedback_customer_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    no_feedback_customer_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    support_item_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    closed_customer_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unclosed_customer_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    data_summary: Mapped[str | None] = mapped_column(Text)
    business_judgement: Mapped[str | None] = mapped_column(Text)
    main_problem: Mapped[str | None] = mapped_column(Text)
    next_suggestion: Mapped[str | None] = mapped_column(Text)
    conclusion: Mapped[str | None] = mapped_column(String(80), index=True)
    decision_maker_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)


class WorkItem(Base, TimestampMixin):
    __tablename__ = "work_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_no: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    resource_type: Mapped[str | None] = mapped_column(String(120), index=True)
    resource_id: Mapped[str | None] = mapped_column(String(160), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("crm_project.id", ondelete="CASCADE"), index=True)
    customer_code: Mapped[str | None] = mapped_column(
        String(120),
        ForeignKey("customer_master.customer_code", ondelete="RESTRICT"),
        index=True,
    )
    item_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    detail: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(40), default="normal", nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), default="open", nullable=False, index=True)
    assignee_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    resolved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    resolution_note: Mapped[str | None] = mapped_column(Text)

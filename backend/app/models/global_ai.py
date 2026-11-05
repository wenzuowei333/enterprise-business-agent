from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.identity import TimestampMixin


class AiConversation(Base, TimestampMixin):
    __tablename__ = "ai_conversation"
    __table_args__ = (
        UniqueConstraint(
            "source_system", "legacy_type", "legacy_id", name="uq_ai_conversation_legacy_ref"
        ),
        Index("ix_ai_conversation_actor_created", "actor_user_id", "created_at"),
        Index("ix_ai_conversation_context", "context_type", "context_id"),
        Index(
            "uq_ai_conversation_case_context",
            "actor_user_id",
            "channel",
            "source_system",
            "context_type",
            "context_id",
            unique=True,
            postgresql_where=text("context_type = 'exception_case' AND actor_user_id IS NOT NULL"),
            sqlite_where=text("context_type = 'exception_case' AND actor_user_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_no: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    domain: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(80), nullable=False, default="web", index=True)
    session_id: Mapped[str | None] = mapped_column(String(120), index=True)
    context_type: Mapped[str | None] = mapped_column(String(80), index=True)
    context_id: Mapped[str | None] = mapped_column(String(160), index=True)
    operation: Mapped[str | None] = mapped_column(String(120), index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="completed", index=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    model_name: Mapped[str | None] = mapped_column(String(160), index=True)
    source_system: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    legacy_type: Mapped[str | None] = mapped_column(String(80), index=True)
    legacy_id: Mapped[str | None] = mapped_column(String(160), index=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)


class AiMessage(Base, TimestampMixin):
    __tablename__ = "ai_message"
    __table_args__ = (
        UniqueConstraint("conversation_id", "sequence_no", name="uq_ai_message_conversation_sequence"),
        UniqueConstraint("source_system", "legacy_type", "legacy_id", name="uq_ai_message_legacy_ref"),
        CheckConstraint("role IN ('user','assistant','system','tool')", name="ck_ai_message_role"),
        Index("ix_ai_message_conversation_created", "conversation_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_no: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("ai_conversation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="completed", index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    request_id: Mapped[str | None] = mapped_column(String(160), index=True)
    model_name: Mapped[str | None] = mapped_column(String(160), index=True)
    contract_version: Mapped[str | None] = mapped_column(String(120), index=True)
    source_refs_json: Mapped[list | None] = mapped_column(JSONB)
    source_system: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    legacy_type: Mapped[str | None] = mapped_column(String(80), index=True)
    legacy_id: Mapped[str | None] = mapped_column(String(160), index=True)
    payload_json: Mapped[dict | list | None] = mapped_column(JSONB)


class AiChatRun(Base, TimestampMixin):
    __tablename__ = "ai_chat_run"
    __table_args__ = (
        UniqueConstraint("actor_user_id", "client_request_id", name="uq_ai_chat_run_actor_client_request"),
        CheckConstraint(
            "status IN ('created','streaming','completed','cancel_requested','cancelled','failed')",
            name="ck_ai_chat_run_status",
        ),
        Index("ix_ai_chat_run_actor_created", "actor_user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_no: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("ai_conversation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_message_id: Mapped[int] = mapped_column(
        ForeignKey("ai_message.id", ondelete="CASCADE"), nullable=False, index=True
    )
    assistant_message_id: Mapped[int] = mapped_column(
        ForeignKey("ai_message.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    client_request_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    request_id: Mapped[str] = mapped_column(String(160), unique=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="created", index=True)
    model_name: Mapped[str | None] = mapped_column(String(160), index=True)
    provider_request_id: Mapped[str | None] = mapped_column(String(160), index=True)
    usage_json: Mapped[dict | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(120), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class AiCaseRemediation(Base, TimestampMixin):
    __tablename__ = "ai_case_remediation"
    __table_args__ = (
        UniqueConstraint("actor_user_id", "client_request_id", name="uq_ai_case_remediation_actor_request"),
        Index(
            "uq_ai_case_remediation_active_actor_message_evidence",
            "actor_user_id",
            "source_message_id",
            "evidence_version",
            unique=True,
            postgresql_where=text("status IN ('schema_generating','form_ready','collecting','plan_generating','plan_ready','execution_queued','executing')"),
            sqlite_where=text("status IN ('schema_generating','form_ready','collecting','plan_generating','plan_ready','execution_queued','executing')"),
        ),
        CheckConstraint(
            "status IN ('schema_generating','form_ready','collecting','plan_generating','plan_ready',"
            "'execution_queued','executing','completed','failed','stale','cancelled')",
            name="ck_ai_case_remediation_status",
        ),
        CheckConstraint("lock_version >= 1", name="ck_ai_case_remediation_lock_version"),
        Index("ix_ai_case_remediation_actor_updated", "actor_user_id", "updated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workflow_no: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("exception_case.id", ondelete="CASCADE"), nullable=False, index=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("ai_conversation.id", ondelete="CASCADE"), nullable=False, index=True)
    source_message_id: Mapped[int] = mapped_column(ForeignKey("ai_message.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    confirmed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    work_item_id: Mapped[int | None] = mapped_column(ForeignKey("work_item.id", ondelete="SET NULL"), index=True)
    exception_action_id: Mapped[int | None] = mapped_column(ForeignKey("exception_action.id", ondelete="SET NULL"), index=True)
    client_request_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    evidence_version: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="schema_generating", index=True)
    form_schema_json: Mapped[dict | None] = mapped_column(JSONB)
    answers_json: Mapped[dict | None] = mapped_column(JSONB)
    plan_json: Mapped[dict | None] = mapped_column(JSONB)
    action_dsl_json: Mapped[dict | None] = mapped_column(JSONB)
    sandbox_json: Mapped[dict | None] = mapped_column(JSONB)
    result_json: Mapped[dict | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(120), index=True)
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    stale_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class AiCaseRemediationAttachment(Base, TimestampMixin):
    __tablename__ = "ai_case_remediation_attachment"
    __table_args__ = (
        UniqueConstraint("workflow_id", "sha256", name="uq_ai_remediation_attachment_workflow_sha256"),
        CheckConstraint("size_bytes >= 0", name="ck_ai_remediation_attachment_size"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    attachment_no: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("ai_case_remediation.id", ondelete="CASCADE"), nullable=False, index=True)
    uploaded_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    object_key: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    extension: Mapped[str] = mapped_column(String(20), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    scan_status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending", index=True)
    parse_status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending", index=True)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(120), index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class AiCaseRemediationRun(Base, TimestampMixin):
    __tablename__ = "ai_case_remediation_run"
    __table_args__ = (
        UniqueConstraint("actor_user_id", "client_request_id", name="uq_ai_remediation_run_actor_request"),
        CheckConstraint("run_kind IN ('form','plan','sandbox','execution')", name="ck_ai_remediation_run_kind"),
        CheckConstraint(
            "status IN ('queued','processing','completed','failed','cancelled')",
            name="ck_ai_remediation_run_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_no: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("ai_case_remediation.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    run_kind: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    client_request_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="queued", index=True)
    request_id: Mapped[str] = mapped_column(String(160), unique=True, nullable=False, index=True)
    usage_json: Mapped[dict | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(120), index=True)
    lease_owner: Mapped[str | None] = mapped_column(String(120), index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class AiInsight(Base, TimestampMixin):
    __tablename__ = "ai_insight"
    __table_args__ = (
        UniqueConstraint("source_system", "legacy_type", "legacy_id", name="uq_ai_insight_legacy_ref"),
        CheckConstraint(
            "confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 1)",
            name="ck_ai_insight_confidence",
        ),
        Index("ix_ai_insight_resource", "resource_type", "resource_id"),
        Index("ix_ai_insight_review", "review_status", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    insight_no: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_conversation.id", ondelete="SET NULL"), index=True
    )
    domain: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    insight_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    resource_type: Mapped[str | None] = mapped_column(String(120), index=True)
    resource_id: Mapped[str | None] = mapped_column(String(160), index=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_action: Mapped[str | None] = mapped_column(Text)
    risk_level: Mapped[str | None] = mapped_column(String(40), index=True)
    opportunity_level: Mapped[str | None] = mapped_column(String(40), index=True)
    confidence_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="active", index=True)
    review_status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending", index=True)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    review_note: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    source_refs_json: Mapped[list | None] = mapped_column(JSONB)
    evidence_json: Mapped[dict | list | None] = mapped_column(JSONB)
    model_name: Mapped[str | None] = mapped_column(String(160), index=True)
    source_system: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    legacy_type: Mapped[str | None] = mapped_column(String(80), index=True)
    legacy_id: Mapped[str | None] = mapped_column(String(160), index=True)
    payload_json: Mapped[dict | list | None] = mapped_column(JSONB)


class AiContextSnapshotRecord(Base, TimestampMixin):
    __tablename__ = "ai_context_snapshot"
    __table_args__ = (
        UniqueConstraint(
            "source_system", "legacy_type", "legacy_id", name="uq_ai_context_snapshot_legacy_ref"
        ),
        Index("ix_ai_context_snapshot_resource", "resource_type", "resource_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_no: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_conversation.id", ondelete="SET NULL"), index=True
    )
    domain: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    context_version: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    resource_type: Mapped[str | None] = mapped_column(String(120), index=True)
    resource_id: Mapped[str | None] = mapped_column(String(160), index=True)
    structured_fields_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    source_refs_json: Mapped[list] = mapped_column(JSONB, nullable=False)
    redacted_fields_json: Mapped[list] = mapped_column(JSONB, nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    source_system: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    legacy_type: Mapped[str | None] = mapped_column(String(80), index=True)
    legacy_id: Mapped[str | None] = mapped_column(String(160), index=True)


class AiActionProposal(Base, TimestampMixin):
    __tablename__ = "ai_action_proposal"
    __table_args__ = (
        UniqueConstraint(
            "source_system", "legacy_type", "legacy_id", name="uq_ai_action_proposal_legacy_ref"
        ),
        Index("ix_ai_action_proposal_resource", "resource_type", "resource_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    proposal_no: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_conversation.id", ondelete="SET NULL"), index=True
    )
    insight_id: Mapped[int | None] = mapped_column(ForeignKey("ai_insight.id", ondelete="SET NULL"), index=True)
    domain: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    action_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    resource_type: Mapped[str | None] = mapped_column(String(120), index=True)
    resource_id: Mapped[str | None] = mapped_column(String(160), index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="proposed", index=True)
    review_status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending", index=True)
    risk_level: Mapped[str | None] = mapped_column(String(40), index=True)
    requires_confirmation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    parameters_json: Mapped[dict | None] = mapped_column(JSONB)
    impact_json: Mapped[dict | None] = mapped_column(JSONB)
    source_refs_json: Mapped[list | None] = mapped_column(JSONB)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    reviewed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    review_note: Mapped[str | None] = mapped_column(Text)
    source_system: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    legacy_type: Mapped[str | None] = mapped_column(String(80), index=True)
    legacy_id: Mapped[str | None] = mapped_column(String(160), index=True)


class AiActionExecution(Base, TimestampMixin):
    __tablename__ = "ai_action_execution"
    __table_args__ = (
        UniqueConstraint(
            "source_system", "legacy_type", "legacy_id", name="uq_ai_action_execution_legacy_ref"
        ),
        CheckConstraint("attempts >= 0", name="ck_ai_action_execution_attempts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    execution_no: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    proposal_id: Mapped[int] = mapped_column(
        ForeignKey("ai_action_proposal.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    requested_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    approved_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    executor_identity: Mapped[str | None] = mapped_column(String(120), index=True)
    request_json: Mapped[dict | None] = mapped_column(JSONB)
    result_json: Mapped[dict | None] = mapped_column(JSONB)
    verification_json: Mapped[dict | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(120), index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    source_system: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    legacy_type: Mapped[str | None] = mapped_column(String(80), index=True)
    legacy_id: Mapped[str | None] = mapped_column(String(160), index=True)


class AiUsageEvent(Base):
    __tablename__ = "ai_usage_event"
    __table_args__ = (
        UniqueConstraint("source_system", "legacy_type", "legacy_id", name="uq_ai_usage_event_legacy_ref"),
        CheckConstraint("latency_ms IS NULL OR latency_ms >= 0", name="ck_ai_usage_event_latency"),
        CheckConstraint("prompt_tokens IS NULL OR prompt_tokens >= 0", name="ck_ai_usage_event_prompt_tokens"),
        CheckConstraint(
            "completion_tokens IS NULL OR completion_tokens >= 0", name="ck_ai_usage_event_completion_tokens"
        ),
        CheckConstraint("total_tokens IS NULL OR total_tokens >= 0", name="ck_ai_usage_event_total_tokens"),
        CheckConstraint("attempts >= 0", name="ck_ai_usage_event_attempts"),
        Index("ix_ai_usage_event_domain_occurred", "domain", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_no: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_conversation.id", ondelete="SET NULL"), index=True
    )
    message_id: Mapped[int | None] = mapped_column(ForeignKey("ai_message.id", ondelete="SET NULL"), index=True)
    insight_id: Mapped[int | None] = mapped_column(ForeignKey("ai_insight.id", ondelete="SET NULL"), index=True)
    request_id: Mapped[str | None] = mapped_column(String(160), index=True)
    provider_request_id: Mapped[str | None] = mapped_column(String(160), index=True)
    service_identity: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    domain: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    operation: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    model_name: Mapped[str | None] = mapped_column(String(160), index=True)
    prompt_version: Mapped[str | None] = mapped_column(String(120), index=True)
    contract_version: Mapped[str | None] = mapped_column(String(120), index=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source_system: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    legacy_type: Mapped[str | None] = mapped_column(String(80), index=True)
    legacy_id: Mapped[str | None] = mapped_column(String(160), index=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AiSecurityEvent(Base):
    __tablename__ = "ai_security_event"
    __table_args__ = (
        UniqueConstraint(
            "source_system", "legacy_type", "legacy_id", name="uq_ai_security_event_legacy_ref"
        ),
        Index("ix_ai_security_event_type_occurred", "event_type", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_no: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(40), nullable=False, default="info", index=True)
    outcome: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    service_identity: Mapped[str | None] = mapped_column(String(120), index=True)
    domain: Mapped[str | None] = mapped_column(String(60), index=True)
    resource_type: Mapped[str | None] = mapped_column(String(120), index=True)
    resource_id: Mapped[str | None] = mapped_column(String(160), index=True)
    request_id: Mapped[str | None] = mapped_column(String(160), index=True)
    detail_json: Mapped[dict | None] = mapped_column(JSONB)
    source_system: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    legacy_type: Mapped[str | None] = mapped_column(String(80), index=True)
    legacy_id: Mapped[str | None] = mapped_column(String(160), index=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

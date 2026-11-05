from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.identity import TimestampMixin


class ExceptionCase(Base, TimestampMixin):
    __tablename__ = "exception_case"
    __table_args__ = (
        UniqueConstraint("fingerprint", name="uq_exception_case_fingerprint"),
        CheckConstraint("occurrence_type IN ('baseline','new','reopened')", name="ck_exception_case_occurrence_type"),
        CheckConstraint(
            "(source_batch_kind IS NULL AND source_batch_id IS NULL) OR "
            "(source_batch_kind IS NOT NULL AND "
            "source_batch_kind IN ('import','inventory_check','legacy') AND source_batch_id IS NOT NULL)",
            name="ck_exception_case_source_batch_ref_pair",
        ),
        Index("ix_exception_case_source_batch_ref", "source_batch_kind", "source_batch_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_no: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    fingerprint: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    domain: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    rule_code: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    severity: Mapped[str] = mapped_column(String(40), nullable=False, default="warning", index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="open", index=True)
    occurrence_type: Mapped[str] = mapped_column(String(40), nullable=False, default="new", server_default="baseline", index=True)
    occurrence_cycle: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="0", index=True)
    rule_version: Mapped[str] = mapped_column(String(80), nullable=False, default="legacy-v1", server_default="legacy-v1", index=True)
    resource_type: Mapped[str | None] = mapped_column(String(120), index=True)
    resource_id: Mapped[str | None] = mapped_column(String(160), index=True)
    resource_code: Mapped[str | None] = mapped_column(String(160), index=True)
    resource_name: Mapped[str | None] = mapped_column(String(255), index=True)
    source_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    source_id: Mapped[str | None] = mapped_column(String(160), index=True)
    # Batch IDs come from independent tables, so kind and ID form the reference.
    source_batch_kind: Mapped[str | None] = mapped_column(String(40), index=True)
    source_batch_id: Mapped[int | None] = mapped_column(Integer, index=True)
    inventory_anomaly_case_id: Mapped[int | None] = mapped_column(
        ForeignKey("inventory_anomaly_case.id", ondelete="SET NULL"), index=True
    )
    data_date: Mapped[date | None] = mapped_column(Date, index=True)
    evidence_version: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    initial_guidance: Mapped[str | None] = mapped_column(Text)
    action_path: Mapped[str | None] = mapped_column(String(500))
    affected_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    affected_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    affected_quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    assignee_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    ignored_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    resolution_note: Mapped[str | None] = mapped_column(Text)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)


class ExceptionEvidence(Base, TimestampMixin):
    __tablename__ = "exception_evidence"
    __table_args__ = (UniqueConstraint("case_id", "evidence_version", name="uq_exception_evidence_case_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("exception_case.id", ondelete="CASCADE"), nullable=False, index=True)
    evidence_version: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    data_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)


class ExceptionDiagnosisJob(Base, TimestampMixin):
    __tablename__ = "exception_diagnosis_job"
    __table_args__ = (
        Index(
            "uq_exception_diagnosis_job_active_case_evidence",
            "case_id",
            "evidence_version",
            unique=True,
            postgresql_where=text("status IN ('queued','processing')"),
            sqlite_where=text("status IN ('queued','processing')"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_no: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("exception_case.id", ondelete="CASCADE"), nullable=False, index=True)
    evidence_version: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    trigger_type: Mapped[str] = mapped_column(String(40), nullable=False, default="manual", index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="queued", index=True)
    requested_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    lease_owner: Mapped[str | None] = mapped_column(String(160), index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    cancel_requested_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    error_message: Mapped[str | None] = mapped_column(Text)


class ExceptionBackgroundJob(Base, TimestampMixin):
    __tablename__ = "exception_background_job"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_no: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    job_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    payload_json: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    lease_owner: Mapped[str | None] = mapped_column(String(160), index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    dedupe_key: Mapped[str | None] = mapped_column(String(160), unique=True, index=True)


class ExceptionDiagnosis(Base, TimestampMixin):
    __tablename__ = "exception_diagnosis"
    __table_args__ = (
        CheckConstraint(
            "feedback_rating IS NULL OR feedback_rating IN ('helpful','partial','incorrect')",
            name="ck_exception_diagnosis_feedback_rating",
        ),
        CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0",
            name="ck_exception_diagnosis_latency_nonnegative",
        ),
        CheckConstraint(
            "prompt_tokens IS NULL OR prompt_tokens >= 0",
            name="ck_exception_diagnosis_prompt_tokens_nonnegative",
        ),
        CheckConstraint(
            "completion_tokens IS NULL OR completion_tokens >= 0",
            name="ck_exception_diagnosis_completion_tokens_nonnegative",
        ),
        CheckConstraint(
            "total_tokens IS NULL OR total_tokens >= 0",
            name="ck_exception_diagnosis_total_tokens_nonnegative",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("exception_case.id", ondelete="CASCADE"), nullable=False, index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("exception_diagnosis_job.id", ondelete="SET NULL"), index=True)
    evidence_version: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    root_cause_code: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    disposition: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    evidence_refs_json: Mapped[list] = mapped_column(JSONB, nullable=False)
    impact_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    recommended_steps_json: Mapped[list] = mapped_column(JSONB, nullable=False)
    missing_evidence_json: Mapped[list] = mapped_column(JSONB, nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(160))
    request_id: Mapped[str | None] = mapped_column(String(160), index=True)
    prompt_version: Mapped[str | None] = mapped_column(String(80), index=True)
    contract_version: Mapped[str | None] = mapped_column(String(80), index=True)
    provider_request_id: Mapped[str | None] = mapped_column(String(160), index=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    diagnosed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    feedback_rating: Mapped[str | None] = mapped_column(String(40), index=True)
    feedback_note: Mapped[str | None] = mapped_column(Text)
    feedback_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    feedback_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class ExceptionAction(Base, TimestampMixin):
    __tablename__ = "exception_action"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    action_no: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("exception_case.id", ondelete="CASCADE"), nullable=False, index=True)
    action_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="validated", index=True)
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    blockers_json: Mapped[list | None] = mapped_column(JSONB)
    parameters_json: Mapped[dict | None] = mapped_column(JSONB)
    impact_json: Mapped[dict | None] = mapped_column(JSONB)
    evidence_version: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    validation_token_hash: Mapped[str | None] = mapped_column(String(128), unique=True, index=True)
    validation_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(160), unique=True, index=True)
    requested_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    result_json: Mapped[dict | None] = mapped_column(JSONB)
    verification_json: Mapped[dict | None] = mapped_column(JSONB)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class ExceptionEvent(Base):
    __tablename__ = "exception_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("exception_case.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(40))
    to_status: Mapped[str | None] = mapped_column(String(40))
    detail_json: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)


class ExceptionNotification(Base, TimestampMixin):
    __tablename__ = "exception_notification"
    __table_args__ = (
        UniqueConstraint(
            "case_id",
            "user_id",
            "notification_type",
            "evidence_version",
            "occurrence_cycle",
            name="uq_exception_notification_case_user_version_cycle",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("exception_case.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    notification_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    evidence_version: Mapped[str] = mapped_column(String(128), nullable=False)
    occurrence_cycle: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    archive_reason: Mapped[str | None] = mapped_column(String(160), index=True)


class ExceptionPolicy(Base, TimestampMixin):
    __tablename__ = "exception_policy"
    __table_args__ = (
        CheckConstraint("manual_ai_daily_limit >= 0", name="ck_exception_policy_manual_daily_limit"),
        CheckConstraint("scheduled_ai_daily_limit >= 0", name="ck_exception_policy_scheduled_daily_limit"),
        CheckConstraint("scheduled_ai_batch_limit > 0", name="ck_exception_policy_scheduled_batch_limit"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    policy_key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    # Legacy master fields remain during the phase-three rollout. New code uses
    # the per-workflow switches and budgets below.
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    manual_ai_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false(), index=True)
    scheduled_ai_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false(), index=True)
    full_scan_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false(), index=True)
    digest_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false(), index=True)
    full_scan_cron: Mapped[str] = mapped_column(String(80), nullable=False, default="30 2 * * *")
    digest_cron: Mapped[str] = mapped_column(String(80), nullable=False, default="30 8 * * *")
    ai_daily_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    ai_batch_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    manual_ai_daily_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=20, server_default="20")
    scheduled_ai_daily_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    scheduled_ai_batch_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=20, server_default="20")
    ai_concurrency: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    stale_diagnosis_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=24)
    settings_json: Mapped[dict | None] = mapped_column(JSONB)
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)


class ExceptionServiceHeartbeat(Base, TimestampMixin):
    __tablename__ = "exception_service_heartbeat"
    __table_args__ = (
        UniqueConstraint("service_type", "instance_id", name="uq_exception_service_heartbeat_instance"),
        CheckConstraint(
            "service_type IN ('worker','ai_worker','scheduler')",
            name="ck_exception_service_heartbeat_type",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    instance_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    last_heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)

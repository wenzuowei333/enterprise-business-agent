from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator


ExceptionStatus = Literal["open", "action_required", "processing", "blocked", "resolved", "ignored"]
ExceptionOccurrenceType = Literal["baseline", "new", "reopened"]
ExceptionOwnershipFilter = Literal["all", "mine", "unassigned"]
ExceptionSlaFilter = Literal["all", "overdue", "due_soon", "on_track", "no_due_date"]
ExceptionJobStatus = Literal["queued", "processing", "completed", "failed", "cancelled"]
ExceptionServiceType = Literal["worker", "ai_worker", "scheduler"]
ExceptionGroupBy = Literal["rule", "batch"]
ExceptionSourceBatchKind = Literal["import", "inventory_check", "legacy"]
ExceptionDomainMode = Literal["off", "shadow", "visible"]


class ExceptionDomainModes(BaseModel):
    model_config = ConfigDict(extra="forbid")

    crm: ExceptionDomainMode = "off"
    approval: ExceptionDomainMode = "off"


class ExceptionCaseGroup(BaseModel):
    key: str
    label: str
    group_by: ExceptionGroupBy
    total: int = 0
    open: int = 0
    action_required: int = 0
    processing: int = 0
    blocked: int = 0
    critical: int = 0
    high: int = 0
    affected_rows: int = 0
    affected_quantity: Decimal | None = None
    latest_seen_at: datetime | None = None
    sample_case_no: str | None = None


class ExceptionCaseItem(BaseModel):
    id: int
    case_no: str
    domain: str
    diagnosis_supported: bool
    rule_code: str
    title: str
    severity: str
    status: ExceptionStatus
    occurrence_type: ExceptionOccurrenceType
    occurrence_cycle: int
    rule_version: str
    resource_type: str | None = None
    resource_id: str | None = None
    resource_code: str | None = None
    resource_name: str | None = None
    source_type: str
    source_id: str | None = None
    source_batch_kind: ExceptionSourceBatchKind | None = None
    source_batch_id: int | None = None
    data_date: date | None = None
    evidence_version: str
    reason: str
    initial_guidance: str | None = None
    action_path: str | None = None
    affected_rows: int = 0
    affected_amount: Decimal | None = None
    affected_quantity: Decimal | None = None
    assignee_user_id: int | None = None
    assignee_name: str | None = None
    due_at: datetime | None = None
    detected_at: datetime
    last_seen_at: datetime
    resolved_at: datetime | None = None
    ignored_until: datetime | None = None
    resolution_note: str | None = None
    verified_at: datetime | None = None
    sla_status: Literal["overdue", "due_soon", "on_track", "no_due_date"] | None = None
    is_mine: bool = False
    processing_kind: Literal["manual_diagnosis", "scheduled_diagnosis", "background_scan"] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    diagnosis: dict[str, Any] | None = None


class ExceptionCasePage(BaseModel):
    items: list[ExceptionCaseItem]
    groups: list[ExceptionCaseGroup] = Field(default_factory=list)
    total: int
    limit: int
    offset: int


class ExceptionSummary(BaseModel):
    total: int
    open: int
    action_required: int
    processing: int
    blocked: int
    resolved: int
    ignored: int
    unread_notifications: int = 0
    ai_enabled: bool = False
    ai_chat_enabled: bool = False
    ai_case_analysis_enabled: bool = False
    manual_ai_enabled: bool = False
    scheduled_ai_enabled: bool = False
    full_scan_enabled: bool = False
    digest_enabled: bool = False
    actions_enabled: bool = False
    by_domain: dict[str, int] = Field(default_factory=dict)
    by_severity: dict[str, int] = Field(default_factory=dict)
    by_occurrence: dict[str, int] = Field(default_factory=dict)
    mine: int = 0
    assigned_to_me: int = 0
    unassigned: int = 0
    overdue: int = 0
    due_soon: int = 0


class DiagnosisRequest(BaseModel):
    force: bool = False


class DiagnosisJobResponse(BaseModel):
    id: int
    job_no: str
    case_no: str
    evidence_version: str
    trigger_type: str
    status: str
    reused: bool = False
    requested_by_user_id: int | None = None
    requested_by_name: str | None = None
    attempts: int = 0
    attempt_count: int = 0
    max_attempts: int = 0
    available_at: datetime | None = None
    next_retry_at: datetime | None = None
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    heartbeat_at: datetime | None = None
    cancel_requested_at: datetime | None = None
    cancel_requested_by_user_id: int | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    case_title: str | None = None
    domain: str | None = None
    rule_code: str | None = None
    cancellable: bool = False
    retryable: bool = False


class ExceptionCaseDetail(ExceptionCaseItem):
    evidence: dict[str, Any] | None = None
    diagnoses: list[dict[str, Any]] = Field(default_factory=list)
    actions: list[dict[str, Any]] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
    active_diagnosis_job: DiagnosisJobResponse | None = None


class DiagnosisJobPage(BaseModel):
    items: list[DiagnosisJobResponse]
    total: int
    limit: int
    offset: int


class ExceptionJobItem(BaseModel):
    id: int
    job_no: str
    job_kind: Literal["diagnosis", "background"]
    job_type: str
    case_no: str | None = None
    evidence_version: str | None = None
    trigger_type: str | None = None
    status: ExceptionJobStatus
    attempts: int = 0
    requested_by_user_id: int | None = None
    requested_by_name: str | None = None
    available_at: datetime | None = None
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    cancel_requested_at: datetime | None = None
    cancel_requested_by_user_id: int | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ExceptionJobPage(BaseModel):
    items: list[ExceptionJobItem]
    total: int
    limit: int
    offset: int


class ExceptionAggregationGroup(BaseModel):
    key: str
    label: str
    source_batch_kind: ExceptionSourceBatchKind | None = None
    source_batch_id: int | None = None
    count: int = Field(default=0, ge=0)
    critical: int = Field(default=0, ge=0)
    high: int = Field(default=0, ge=0)
    warning: int = Field(default=0, ge=0)
    overdue: int = Field(default=0, ge=0)


class ExceptionAggregationResponse(BaseModel):
    group_by: ExceptionGroupBy
    groups: list[ExceptionAggregationGroup] = Field(default_factory=list)
    total: int = Field(default=0, ge=0)
    truncated: bool = False


class ExceptionBaselineScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: Literal["crm", "approval"]
    expected_policy_updated_at: datetime


class ExceptionScanResult(BaseModel):
    domains: list[str] = Field(default_factory=list)
    requested_domains: list[str] = Field(default_factory=list)
    domain_modes: dict[str, ExceptionDomainMode] = Field(default_factory=dict)
    scan_trigger: Literal["baseline"] = "baseline"
    scanned: int = Field(default=0, ge=0)
    created: int = Field(default=0, ge=0)
    new: int = Field(default=0, ge=0)
    reopened: int = Field(default=0, ge=0)
    evidence_updated: int = Field(default=0, ge=0)
    resolved: int = Field(default=0, ge=0)


class ExceptionBaselineScanResponse(BaseModel):
    scan_reference: str
    audit_id: int
    domain: Literal["crm", "approval"]
    domain_mode: Literal["shadow"] = "shadow"
    shadow_cycle: int = Field(ge=1)
    policy_updated_at: datetime
    reused: bool = False
    result: ExceptionScanResult


class ExceptionRuleQualityMetrics(BaseModel):
    total: int = Field(default=0, ge=0)
    active: int = Field(default=0, ge=0)
    baseline: int = Field(default=0, ge=0)
    new: int = Field(default=0, ge=0)
    reopened: int = Field(default=0, ge=0)
    ignored: int = Field(default=0, ge=0)
    resolved: int = Field(default=0, ge=0)
    evidence_changed_events: int = Field(default=0, ge=0)
    latest_seen_at: datetime | None = None
    false_positive_rate: float | None = Field(default=None, ge=0, le=1)


class ExceptionDomainRuleQuality(ExceptionRuleQualityMetrics):
    domain: str
    domain_mode: ExceptionDomainMode
    scan_job_metrics_available: bool = False
    queued_scan_jobs: int | None = Field(default=None, ge=0)
    failed_scan_jobs: int | None = Field(default=None, ge=0)
    scan_latency_p95_ms: int | None = Field(default=None, ge=0)


class ExceptionRuleQuality(ExceptionRuleQualityMetrics):
    domain: str
    domain_mode: ExceptionDomainMode
    rule_code: str
    rule_version: str


class ExceptionRuleQualityResponse(BaseModel):
    generated_at: datetime
    scan_job_window_days: int = Field(ge=1, le=90)
    scan_job_window_start: datetime
    scan_job_window_end: datetime
    scan_job_sample_limit: int = Field(ge=1)
    scan_job_sample_size: int = Field(default=0, ge=0)
    scan_job_metrics_truncated: bool = False
    domains: list[ExceptionDomainRuleQuality] = Field(default_factory=list)
    rules: list[ExceptionRuleQuality] = Field(default_factory=list)


class ExceptionJobRetryRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)
    reset_attempts: bool = False

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class ExceptionJobCancelRequest(BaseModel):
    reason: str = Field(min_length=2, max_length=1000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 2:
            raise ValueError("reason must contain at least two non-whitespace characters")
        return normalized


class ActionValidationRequest(BaseModel):
    action_type: Literal[
        "rebuild_inventory_flow",
        "rerun_inventory_check",
        "rebuild_receivable_checks",
        "rebuild_master_link_issues",
        "revalidate_import_batch",
    ]
    parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("parameters")
    @classmethod
    def validate_parameters(cls, value: dict[str, Any]) -> dict[str, Any]:
        if set(value) - {"batch_id"}:
            raise ValueError("Only batch_id is supported")
        batch_id = value.get("batch_id")
        if batch_id is not None and (isinstance(batch_id, bool) or not isinstance(batch_id, int) or batch_id <= 0):
            raise ValueError("batch_id must be a positive integer")
        return value


class ActionExecuteRequest(BaseModel):
    validation_token: str = Field(min_length=20, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    idempotency_key: str = Field(min_length=8, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


class ActionResponse(BaseModel):
    id: int
    action_no: str
    case_no: str
    action_type: str
    status: str
    allowed: bool
    blockers: list[str] = Field(default_factory=list)
    impact: dict[str, Any] = Field(default_factory=dict)
    evidence_version: str
    validation_token: str | None = None
    validation_expires_at: datetime | None = None
    result: dict[str, Any] | None = None
    verification: dict[str, Any] | None = None
    error_message: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


class AssignRequest(BaseModel):
    assignee_user_id: int | None = None
    due_at: datetime | None = None


def _normalize_case_nos(value: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in value:
        case_no = raw.strip()
        if not case_no:
            raise ValueError("case_nos must not contain blank values")
        if len(case_no) > 120:
            raise ValueError("case_no must not exceed 120 characters")
        if case_no not in seen:
            seen.add(case_no)
            normalized.append(case_no)
    if not normalized:
        raise ValueError("case_nos must contain at least one value")
    if len(normalized) > 100:
        raise ValueError("case_nos must contain at most 100 unique values")
    return normalized


class BatchAssignRequest(AssignRequest):
    case_nos: list[str]

    @field_validator("case_nos")
    @classmethod
    def validate_case_nos(cls, value: list[str]) -> list[str]:
        return _normalize_case_nos(value)


class IgnoreRequest(BaseModel):
    reason: str = Field(min_length=2, max_length=2000)
    ignored_until: datetime

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 2:
            raise ValueError("reason must contain at least two non-whitespace characters")
        return normalized


class BatchIgnoreRequest(IgnoreRequest):
    case_nos: list[str]

    @field_validator("case_nos")
    @classmethod
    def validate_case_nos(cls, value: list[str]) -> list[str]:
        return _normalize_case_nos(value)


class BatchExceptionMutationResponse(BaseModel):
    updated_count: int
    items: list[ExceptionCaseItem]


class DiagnosisFeedbackRequest(BaseModel):
    rating: Literal["helpful", "partial", "incorrect"]
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ExceptionDiagnosisResponse(BaseModel):
    id: int
    evidence_version: str
    root_cause_code: str
    summary: str
    confidence: Decimal
    disposition: str
    evidence_refs: list[Any] = Field(default_factory=list)
    impact: dict[str, Any] = Field(default_factory=dict)
    recommended_steps: list[Any] = Field(default_factory=list)
    missing_evidence: list[Any] = Field(default_factory=list)
    model_name: str | None = None
    request_id: str | None = None
    prompt_version: str | None = None
    contract_version: str | None = None
    provider_request_id: str | None = None
    latency_ms: int | None = Field(default=None, ge=0)
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    evidence_bytes: int | None = Field(default=None, ge=0)
    evidence_approx_tokens: int | None = Field(default=None, ge=0)
    evidence_truncated: bool | None = None
    diagnosed_at: datetime
    feedback_rating: Literal["helpful", "partial", "incorrect"] | None = None
    feedback_note: str | None = None
    feedback_by_user_id: int | None = None
    feedback_at: datetime | None = None


class VerifyRequest(BaseModel):
    note: str | None = Field(default=None, max_length=2000)
    expected_evidence_version: str = Field(min_length=1, max_length=128)
    expected_outcome: Literal["resolved", "still_present"] | None = None
    observed_result: str | None = Field(default=None, max_length=2000)

    @field_validator("note", "observed_result")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("expected_evidence_version")
    @classmethod
    def normalize_expected_evidence_version(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("expected_evidence_version must not be blank")
        return normalized


class ExceptionVerificationSnapshot(BaseModel):
    status: ExceptionStatus | str | None = None
    evidence_version: str | None = None
    affected_rows: int | None = None
    affected_amount: Decimal | None = None
    affected_quantity: Decimal | None = None
    summary: str | None = None


class VerifyResponse(BaseModel):
    case: ExceptionCaseItem
    resolved: bool
    before: ExceptionVerificationSnapshot | None = None
    after: ExceptionVerificationSnapshot | None = None
    note: str | None = None
    evidence_changed: bool = False
    scan_result: dict[str, Any] = Field(default_factory=dict)


ExceptionVerificationResponse = VerifyResponse


class NotificationItem(BaseModel):
    id: int
    case_no: str
    notification_type: str
    title: str
    message: str
    is_read: bool
    read_at: datetime | None = None
    acknowledged_at: datetime | None = None
    created_at: datetime


class PolicyResponse(BaseModel):
    policy_key: str
    is_enabled: bool
    manual_ai_enabled: bool = False
    scheduled_ai_enabled: bool = False
    full_scan_enabled: bool = False
    digest_enabled: bool = False
    full_scan_cron: str
    digest_cron: str
    ai_daily_limit: int
    ai_batch_limit: int
    manual_ai_daily_limit: int = 20
    scheduled_ai_daily_limit: int = 0
    scheduled_ai_batch_limit: int = 20
    ai_concurrency: int = 1
    stale_diagnosis_hours: int
    domain_modes: ExceptionDomainModes = Field(default_factory=ExceptionDomainModes)
    settings: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime


class PolicyUpdate(BaseModel):
    is_enabled: bool = False
    manual_ai_enabled: bool = False
    scheduled_ai_enabled: bool = False
    full_scan_enabled: bool = False
    digest_enabled: bool = False
    full_scan_cron: str = Field(min_length=5, max_length=80)
    digest_cron: str = Field(min_length=5, max_length=80)
    ai_daily_limit: int = Field(default=20, ge=0, le=10000)
    ai_batch_limit: int = Field(default=20, ge=1, le=1000)
    manual_ai_daily_limit: int = Field(default=20, ge=0, le=10000)
    scheduled_ai_daily_limit: int = Field(default=0, ge=0, le=10000)
    scheduled_ai_batch_limit: int = Field(default=20, ge=1, le=1000)
    ai_concurrency: int = Field(default=1, ge=1, le=20)
    stale_diagnosis_hours: int = Field(ge=1, le=720)
    domain_modes: ExceptionDomainModes = Field(default_factory=ExceptionDomainModes)
    settings: dict[str, Any] = Field(default_factory=dict)

    @field_validator("full_scan_cron", "digest_cron")
    @classmethod
    def validate_cron(cls, value: str) -> str:
        try:
            from apscheduler.triggers.cron import CronTrigger

            from app.core.config import settings

            CronTrigger.from_crontab(value, timezone=settings.exception_schedule_timezone)
            return value
        except ImportError:
            pass
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid five-field cron expression") from exc
        fields = value.split()
        if len(fields) != 5:
            raise ValueError("Invalid five-field cron expression")
        for field, minimum, maximum in zip(fields, (0, 0, 1, 1, 0), (59, 23, 31, 12, 6), strict=True):
            _validate_cron_field(field, minimum, maximum)
        return value


class PolicyPatch(BaseModel):
    expected_updated_at: datetime
    is_enabled: bool | None = None
    manual_ai_enabled: bool | None = None
    scheduled_ai_enabled: bool | None = None
    full_scan_enabled: bool | None = None
    digest_enabled: bool | None = None
    full_scan_cron: str | None = Field(default=None, min_length=5, max_length=80)
    digest_cron: str | None = Field(default=None, min_length=5, max_length=80)
    ai_daily_limit: int | None = Field(default=None, ge=0, le=10000)
    ai_batch_limit: int | None = Field(default=None, ge=1, le=1000)
    manual_ai_daily_limit: int | None = Field(default=None, ge=0, le=10000)
    scheduled_ai_daily_limit: int | None = Field(default=None, ge=0, le=10000)
    scheduled_ai_batch_limit: int | None = Field(default=None, ge=1, le=1000)
    ai_concurrency: int | None = Field(default=None, ge=1, le=20)
    stale_diagnosis_hours: int | None = Field(default=None, ge=1, le=720)
    domain_modes: ExceptionDomainModes | None = None
    settings: dict[str, Any] | None = None

    @field_validator("full_scan_cron", "digest_cron")
    @classmethod
    def validate_cron(cls, value: str | None) -> str | None:
        return None if value is None else PolicyUpdate.validate_cron(value)

    @model_validator(mode="after")
    def validate_partial_update(self) -> "PolicyPatch":
        policy_fields = self.model_fields_set - {"expected_updated_at"}
        if not policy_fields:
            raise ValueError("At least one policy field must be provided")
        null_fields = sorted(field for field in policy_fields if getattr(self, field) is None)
        if null_fields:
            raise ValueError(f"Policy fields cannot be null: {', '.join(null_fields)}")
        return self


def _validate_cron_field(value: str, minimum: int, maximum: int) -> None:
    for item in value.split(","):
        base, separator, step = item.partition("/")
        if separator and (not step.isdigit() or int(step) <= 0):
            raise ValueError("Invalid cron step")
        if base == "*":
            continue
        bounds = base.split("-")
        if len(bounds) not in {1, 2} or any(not bound.isdigit() for bound in bounds):
            raise ValueError("Invalid cron field")
        numbers = [int(bound) for bound in bounds]
        if any(number < minimum or number > maximum for number in numbers):
            raise ValueError("Cron field out of range")
        if len(numbers) == 2 and numbers[0] > numbers[1]:
            raise ValueError("Invalid cron range")


class ExceptionServiceHeartbeatItem(BaseModel):
    service_type: ExceptionServiceType
    instance_id: str
    started_at: datetime
    last_heartbeat_at: datetime
    is_stale: bool = False
    is_healthy: bool | None = None
    heartbeat_age_seconds: int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExceptionQueueMetrics(BaseModel):
    queued: int = 0
    processing: int = 0
    failed: int = 0
    cancelled: int = 0
    completed_today: int = 0
    oldest_queued_at: datetime | None = None
    oldest_processing_at: datetime | None = None


class ExceptionAiBudgetUsage(BaseModel):
    date: date
    manual_limit: int = Field(ge=0)
    manual_used: int = Field(ge=0)
    manual_remaining: int = Field(ge=0)
    scheduled_limit: int = Field(ge=0)
    scheduled_used: int = Field(ge=0)
    scheduled_remaining: int = Field(ge=0)


class ExceptionOpsBudget(BaseModel):
    limit: int = Field(ge=0)
    used: int = Field(ge=0)
    remaining: int | None = Field(default=None, ge=0)
    unlimited: bool = False


class ExceptionOpsPolicy(BaseModel):
    is_enabled: bool = False
    manual_ai_enabled: bool = False
    scheduled_ai_enabled: bool = False
    full_scan_enabled: bool = False
    digest_enabled: bool = False
    ai_concurrency: int = Field(default=1, ge=1)
    scheduled_ai_batch_limit: int = Field(default=20, ge=1)


class ExceptionCircuitStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    open: bool
    consecutive_failures: int = Field(ge=0)
    retry_after_seconds: int = Field(ge=0)
    stale: bool
    source: Literal["ai_worker"]


class ExceptionOpsSummary(BaseModel):
    generated_at: datetime
    global_ai_enabled: bool = False
    provider_configured: bool = False
    provider_host: str | None = None
    model: str | None = None
    circuit: ExceptionCircuitStatus | None = None
    diagnosis_jobs_by_status: dict[str, int] = Field(default_factory=dict)
    diagnosis_jobs_by_trigger: dict[str, dict[str, int]] = Field(default_factory=dict)
    background_jobs_by_status: dict[str, int] = Field(default_factory=dict)
    manual_queue_depth: int = Field(default=0, ge=0)
    scheduled_queue_depth: int = Field(default=0, ge=0)
    background_queue_depth: int = Field(default=0, ge=0)
    oldest_manual_queued_at: datetime | None = None
    oldest_scheduled_queued_at: datetime | None = None
    oldest_background_queued_at: datetime | None = None
    heartbeats: list[ExceptionServiceHeartbeatItem] = Field(default_factory=list)
    policy: ExceptionOpsPolicy = Field(default_factory=ExceptionOpsPolicy)
    manual_budget: ExceptionOpsBudget = Field(
        default_factory=lambda: ExceptionOpsBudget(limit=0, used=0, remaining=None, unlimited=True)
    )
    scheduled_budget: ExceptionOpsBudget = Field(
        default_factory=lambda: ExceptionOpsBudget(limit=0, used=0, remaining=None, unlimited=True)
    )
    last_full_scan_at: datetime | None = None
    last_digest_at: datetime | None = None
    last_scan_duration_ms: int | None = Field(default=None, ge=0)
    last_scan_created: int = Field(default=0, ge=0)
    last_scan_new: int = Field(default=0, ge=0)
    last_scan_reopened: int = Field(default=0, ge=0)
    last_scan_evidence_updated: int = Field(default=0, ge=0)
    last_scan_resolved: int = Field(default=0, ge=0)
    last_scan_scanned: int = Field(default=0, ge=0)
    diagnosis_completed_24h: int = Field(default=0, ge=0)
    diagnosis_failed_24h: int = Field(default=0, ge=0)


class ExceptionQualityBucket(BaseModel):
    key: str
    label: str | None = None
    diagnoses: int = 0
    rated: int = 0
    helpful: int = 0
    partial: int = 0
    incorrect: int = 0
    positive_rate: float | None = Field(default=None, ge=0, le=1)
    average_confidence: float | None = Field(default=None, ge=0, le=1)
    average_latency_ms: float | None = Field(default=None, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    usage_reported_count: int = Field(default=0, ge=0)
    usage_missing_count: int = Field(default=0, ge=0)
    usage_completeness_rate: float | None = Field(default=None, ge=0, le=1)


class ExceptionDiagnosisQualityRule(BaseModel):
    domain: str | None = None
    rule_code: str
    diagnoses: int = 0
    feedback_count: int = 0
    helpful: int = 0
    partial: int = 0
    incorrect: int = 0
    helpful_rate: float | None = Field(default=None, ge=0, le=1)
    average_confidence: float | None = Field(default=None, ge=0, le=1)
    average_resolution_hours: float | None = Field(default=None, ge=0)


class ExceptionDiagnosisQualitySummary(BaseModel):
    generated_at: datetime | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None
    total_diagnoses: int = Field(default=0, validation_alias=AliasChoices("total_diagnoses", "total"))
    feedback_count: int = 0
    feedback_rate: float | None = Field(default=None, ge=0, le=1)
    helpful_rate: float | None = Field(default=None, ge=0, le=1)
    feedback_coverage_rate: float | None = Field(default=None, ge=0, le=1)
    rated_diagnoses: int = 0
    helpful: int = 0
    partial: int = 0
    incorrect: int = 0
    unrated: int = 0
    positive_rate: float | None = Field(default=None, ge=0, le=1)
    evidence_citation_rate: float | None = Field(default=None, ge=0, le=1)
    evidence_reference_valid_rate: float | None = Field(default=None, ge=0, le=1)
    average_confidence: float | None = Field(default=None, ge=0, le=1)
    average_latency_ms: float | None = Field(default=None, ge=0)
    average_resolution_hours: float | None = Field(default=None, ge=0)
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    usage_reported_count: int = Field(default=0, ge=0)
    usage_missing_count: int = Field(default=0, ge=0)
    usage_completeness_rate: float | None = Field(default=None, ge=0, le=1)
    by_feedback: dict[str, int] = Field(default_factory=dict)
    by_disposition: dict[str, int] = Field(default_factory=dict)
    by_root_cause_code: list[ExceptionQualityBucket] | dict[str, int] = Field(default_factory=dict)
    by_contract_version: list[ExceptionQualityBucket] | dict[str, int] = Field(default_factory=dict)
    by_domain: list[ExceptionQualityBucket] | dict[str, int] = Field(default_factory=dict)
    by_rule: list[ExceptionQualityBucket] | dict[str, int] = Field(default_factory=dict)
    by_model: list[ExceptionQualityBucket] | dict[str, int] = Field(default_factory=dict)
    by_prompt_version: list[ExceptionQualityBucket] | dict[str, int] = Field(default_factory=dict)
    rules: list[ExceptionDiagnosisQualityRule] = Field(default_factory=list)


class ExceptionRuleAggregation(BaseModel):
    rule_code: str
    domain: str
    title: str | None = None
    total: int = 0
    open: int = 0
    critical: int = 0
    overdue: int = 0


class ExceptionBatchAggregation(BaseModel):
    source_type: str
    source_batch_kind: ExceptionSourceBatchKind
    source_batch_id: int
    data_date: date | None = None
    total: int = 0
    open: int = 0
    critical: int = 0
    affected_rows: int = 0


class ExceptionCaseAggregations(BaseModel):
    rules: list[ExceptionRuleAggregation] = Field(default_factory=list)
    batches: list[ExceptionBatchAggregation] = Field(default_factory=list)

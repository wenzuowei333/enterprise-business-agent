from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.crm import CRM_LEAD_CAMPAIGN_STATUSES, CRM_LEAD_PRIORITIES, CrmLeadStatus
from app.schemas.master_data import (
    CustomerBusinessProfileResponse,
    CustomerBusinessProfileUpsert,
    CustomerMasterUpdate,
    CustomerRecommendedProductUpsert,
)


JsonValue = dict[str, Any] | list[Any]
CrmFollowupSubmissionState = Literal["unsubmitted", "submitted", "needs_action"]


class ApprovalReturnFeedback(BaseModel):
    event_type: Literal["supplement_request", "reject"]
    comment: str | None
    operator_user_id: int | None
    operator_user_label: str | None = None
    created_at: datetime


class ApprovalInstancePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    approval_no: str
    approval_type: str
    resource_type: str
    resource_id: str
    title: str
    description: str | None
    applicant_user_id: int | None
    applicant_user_label: str | None = None
    current_handler_user_id: int | None
    current_handler_user_label: str | None = None
    status: str
    priority: str
    payload_json: JsonValue | None
    result_json: JsonValue | None
    business_summary: dict[str, Any] | None = None
    latest_return_feedback: ApprovalReturnFeedback | None = None
    submitted_at: datetime | None
    reviewed_at: datetime | None
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ApprovalEventPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    approval_id: int
    event_type: str
    operator_user_id: int | None
    operator_user_label: str | None = None
    from_status: str | None
    to_status: str | None
    comment: str | None
    snapshot_json: JsonValue | None
    created_at: datetime


class ApprovalAttachmentPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    approval_id: int
    file_name: str
    content_type: str | None
    size_bytes: int | None
    storage_path: str
    file_digest: str | None
    created_by_user_id: int | None
    created_by_user_label: str | None = None
    created_at: datetime


class ApprovalCreate(BaseModel):
    approval_type: str = Field(min_length=1, max_length=120)
    resource_type: str = Field(default="approval_pending", max_length=120)
    resource_id: str = Field(default="pending", max_length=160)
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    current_handler_user_id: int | None = None
    status: str = "draft"
    priority: str = "normal"
    payload_json: JsonValue | None = None
    submit: bool = False


class ApprovalActionRequest(BaseModel):
    comment: str | None = None
    payload_json: JsonValue | None = None
    result_json: dict[str, Any] | None = None


class ApprovalWithdrawalRequest(BaseModel):
    reason: str = Field(min_length=5, max_length=1000)


class ApprovalWithdrawalPreview(BaseModel):
    approval_id: int
    project_id: int | None = None
    state: str
    can_withdraw: bool
    deadline: datetime | None = None
    is_override: bool = False
    blockers: list[str] = Field(default_factory=list)
    impact_counts: dict[str, int] = Field(default_factory=dict)
    project_status: str | None = None


class ApprovalDraftUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    description: str | None = None
    current_handler_user_id: int | None = None
    priority: str | None = None
    payload_json: JsonValue | None = None
    comment: str | None = None


class ApprovalDetail(BaseModel):
    approval: ApprovalInstancePublic
    events: list[ApprovalEventPublic]
    attachments: list[ApprovalAttachmentPublic] = Field(default_factory=list)


class ApprovalPage(BaseModel):
    items: list[ApprovalInstancePublic]
    total: int
    limit: int
    offset: int


class CrmProjectPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_code: str
    project_name: str
    project_type: str | None
    purpose: str | None
    customer_scope_note: str | None
    business_line: str | None
    applicant_user_id: int | None
    landing_approver_user_id: int | None
    owner_user_id: int | None
    project_manager_user_id: int | None
    participant_user_ids: list[int] | None
    progress_cc_user_ids: list[int] | None
    applicant_user_label: str | None = None
    landing_approver_user_label: str | None = None
    owner_user_label: str | None = None
    project_manager_user_label: str | None = None
    participant_user_labels: list[str] = Field(default_factory=list)
    progress_cc_user_labels: list[str] = Field(default_factory=list)
    start_date: date | None
    due_date: date | None
    minimum_action: str | None
    closure_standard: str | None
    status: str
    approval_status: str
    current_approval_id: int | None
    approval_withdrawn_at: datetime | None = None
    approval_withdrawn_by_user_id: int | None = None
    approval_withdrawn_by_user_label: str | None = None
    approval_withdrawn_reason: str | None = None
    next_step_status: str | None
    next_step_action: str | None
    next_step_followup_at: datetime | None
    task_total: int = 0
    task_closed: int = 0
    task_open: int = 0
    task_need_support: int = 0
    task_blocked: int = 0
    support_item_open: int = 0
    pending_approval_count: int = 0
    latest_followup_at: datetime | None = None
    created_by_user_id: int | None
    updated_by_user_id: int | None
    created_at: datetime
    updated_at: datetime


class CrmProjectCreate(BaseModel):
    project_code: str | None = Field(default=None, max_length=120)
    project_name: str = Field(min_length=1, max_length=255)
    project_type: str | None = Field(default=None, max_length=120)
    purpose: str | None = None
    customer_scope_note: str | None = None
    business_line: str | None = Field(default=None, max_length=120)
    applicant_user_id: int | None = None
    landing_approver_user_id: int | None = None
    owner_user_id: int | None = None
    project_manager_user_id: int | None = None
    participant_user_ids: list[int] = Field(default_factory=list)
    progress_cc_user_ids: list[int] = Field(default_factory=list)
    assignment_mode: str | None = Field(default=None, max_length=40)
    allow_unassigned_tasks: bool = False
    start_date: date | None = None
    due_date: date | None = None
    minimum_action: str | None = None
    closure_standard: str | None = None
    status: str = "draft"
    approval_status: str = "draft"


class CrmProjectUpdate(BaseModel):
    project_name: str | None = Field(default=None, min_length=1, max_length=255)
    project_type: str | None = Field(default=None, max_length=120)
    purpose: str | None = None
    customer_scope_note: str | None = None
    business_line: str | None = Field(default=None, max_length=120)
    applicant_user_id: int | None = None
    landing_approver_user_id: int | None = None
    owner_user_id: int | None = None
    project_manager_user_id: int | None = None
    participant_user_ids: list[int] | None = None
    progress_cc_user_ids: list[int] | None = None
    start_date: date | None = None
    due_date: date | None = None
    minimum_action: str | None = None
    closure_standard: str | None = None
    status: str | None = None
    approval_status: str | None = None


class CrmProjectClosureSummary(BaseModel):
    task_total: int = 0
    task_closed: int = 0
    task_open: int = 0
    task_need_support: int = 0
    task_blocked: int = 0
    task_overdue: int = 0
    feedback_task_count: int = 0
    valid_feedback_task_count: int = 0
    no_feedback_task_count: int = 0
    support_open_count: int = 0
    support_closed_count: int = 0
    pending_approval_count: int = 0
    review_total: int = 0
    review_confirmed: int = 0
    latest_review_status: str | None = None
    latest_review_conclusion: str | None = None
    closure_ready: bool = False
    closure_state: str = "not_ready"


class CrmProjectDetail(BaseModel):
    project: CrmProjectPublic
    task_summary: dict[str, int]
    latest_followup: "CrmFollowupPublic | None" = None
    support_item_count: int = 0
    approval_summary: dict[str, int] = Field(default_factory=dict)
    review_summary: dict[str, int] = Field(default_factory=dict)
    closure_summary: CrmProjectClosureSummary = Field(default_factory=CrmProjectClosureSummary)


class CrmProjectPage(BaseModel):
    items: list[CrmProjectPublic]
    total: int
    limit: int
    offset: int


class CrmTestProjectCounts(BaseModel):
    task_total: int = 0
    followup_total: int = 0
    review_total: int = 0
    approval_total: int = 0
    work_item_total: int = 0
    open_work_item_total: int = 0
    pending_approval_total: int = 0
    latest_activity_at: datetime | None = None


class CrmTestProjectCandidate(BaseModel):
    project: CrmProjectPublic
    test_reasons: list[str] = Field(default_factory=list)
    counts: CrmTestProjectCounts = Field(default_factory=CrmTestProjectCounts)
    can_void: bool = False


class CrmTestProjectPage(BaseModel):
    items: list[CrmTestProjectCandidate]
    total: int
    limit: int
    offset: int
    marker: str | None = None


class CrmVoidTestProjectRequest(BaseModel):
    reason: str = Field(min_length=2, max_length=500)
    confirmation: str = Field(min_length=1, max_length=80)


class CrmVoidTestProjectResult(BaseModel):
    project: CrmProjectPublic
    test_reasons: list[str] = Field(default_factory=list)
    counts: CrmTestProjectCounts = Field(default_factory=CrmTestProjectCounts)
    message: str


class CrmProjectCustomerTaskPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    task_code: str
    customer_code: str
    customer_name_snapshot: str
    executor_user_id: int | None
    executor_employee_code: str | None
    executor_name_snapshot: str | None
    business_issue_point: str | None
    round_target: str | None
    feedback_due_at: datetime | None
    status: str
    minimum_action_done: bool
    need_support: bool
    need_manager_support: bool
    need_boss_decision: bool
    is_blocked: bool
    is_closed: bool
    latest_followup_id: int | None
    latest_blocker_reason: str | None
    latest_blocker_note: str | None
    latest_owner_next_status: str | None
    latest_owner_next_action: str | None
    latest_owner_next_followup_at: datetime | None
    last_followup_at: datetime | None
    followup_submission_state: CrmFollowupSubmissionState | None = None
    latest_followup_approval_status: str | None = None
    latest_followup_submitted_at: datetime | None = None
    project_purpose: str | None = None
    data_update_total: int = 0
    data_update_pending: int = 0
    latest_data_update_at: datetime | None = None
    customer_profile_approval_id: int | None = None
    customer_profile_approval_status: str | None = None
    business_profile_approval_id: int | None = None
    business_profile_approval_status: str | None = None
    created_at: datetime
    updated_at: datetime


class CrmTaskCreate(BaseModel):
    task_code: str | None = Field(default=None, max_length=120)
    customer_code: str = Field(min_length=1, max_length=120)
    executor_user_id: int | None = None
    executor_employee_code: str | None = Field(default=None, max_length=80)
    business_issue_point: str | None = None
    round_target: str | None = None
    feedback_due_at: datetime | None = None
    status: str = "not_started"


class CrmProjectApprovalTaskDraft(CrmTaskCreate):
    pass


class CrmProjectApprovalDraftCreate(BaseModel):
    title: str | None = None
    description: str | None = None
    current_handler_user_id: int | None = None
    priority: str = "normal"
    submit: bool = True
    project: CrmProjectCreate
    tasks: list[CrmProjectApprovalTaskDraft] = Field(default_factory=list)


class CrmBusinessProfileApprovalDraftCreate(BaseModel):
    title: str | None = None
    description: str | None = None
    priority: str = "normal"
    submit: bool = True
    profile: CustomerBusinessProfileUpsert
    recommended_products: list[CustomerRecommendedProductUpsert] = Field(default_factory=list)


class CrmBusinessProfileUpdateResponse(CustomerBusinessProfileResponse):
    recommended_products: list[CustomerRecommendedProductUpsert] = Field(default_factory=list)
    changed_fields: list[str] = Field(default_factory=list)
    task_id: int
    project_id: int
    synced_to_master: bool


class CrmCustomerProfileApprovalDraftCreate(BaseModel):
    title: str | None = None
    description: str | None = None
    priority: str = "normal"
    submit: bool = True
    profile: CustomerMasterUpdate


class CrmTaskUpdate(BaseModel):
    executor_user_id: int | None = None
    executor_employee_code: str | None = Field(default=None, max_length=80)
    business_issue_point: str | None = None
    round_target: str | None = None
    feedback_due_at: datetime | None = None
    status: str | None = None
    minimum_action_done: bool | None = None
    need_support: bool | None = None
    need_manager_support: bool | None = None
    need_boss_decision: bool | None = None
    is_blocked: bool | None = None
    is_closed: bool | None = None
    latest_blocker_reason: str | None = Field(default=None, max_length=160)
    latest_blocker_note: str | None = None


class CrmTaskSubmissionSummary(BaseModel):
    total: int = 0
    submitted: int = 0
    unsubmitted: int = 0
    needs_action: int = 0


class CrmTaskPage(BaseModel):
    items: list[CrmProjectCustomerTaskPublic]
    total: int
    limit: int
    offset: int
    submission_summary: CrmTaskSubmissionSummary = Field(default_factory=CrmTaskSubmissionSummary)


class CrmProjectCustomerDetailSummary(BaseModel):
    total: int = 0
    open: int = 0
    closed: int = 0
    overdue: int = 0
    need_support: int = 0
    need_manager_support: int = 0
    need_boss_decision: int = 0
    blocked: int = 0
    customer_groups: list[str] = Field(default_factory=list)
    salespersons: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    customer_types: list[str] = Field(default_factory=list)
    customer_statuses: list[str] = Field(default_factory=list)
    task_statuses: list[str] = Field(default_factory=list)
    blocker_reasons: list[str] = Field(default_factory=list)


class CrmProjectCustomerDetailRow(BaseModel):
    id: int
    project_id: int
    task_code: str
    customer_code: str
    customer_name_snapshot: str
    customer_name: str | None = None
    customer_short_name: str | None = None
    customer_type: str | None = None
    customer_status: str | None = None
    customer_group_name: str | None = None
    region: str | None = None
    salesperson_employee_code: str | None = None
    salesperson_name: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    executor_user_id: int | None
    executor_employee_code: str | None
    executor_name_snapshot: str | None
    business_issue_point: str | None
    round_target: str | None
    feedback_due_at: datetime | None
    status: str
    task_status: str
    minimum_action_done: bool
    need_support: bool
    need_manager_support: bool
    need_boss_decision: bool
    is_blocked: bool
    is_closed: bool
    overdue: bool
    latest_followup_id: int | None
    latest_blocker_reason: str | None
    latest_blocker_note: str | None
    latest_owner_next_status: str | None
    latest_owner_next_action: str | None
    latest_owner_next_followup_at: datetime | None
    last_followup_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CrmProjectCustomerDetailPage(BaseModel):
    items: list[CrmProjectCustomerDetailRow]
    total: int
    limit: int
    offset: int
    summary: CrmProjectCustomerDetailSummary = Field(default_factory=CrmProjectCustomerDetailSummary)


class CrmLinkedCustomerSummary(BaseModel):
    total_customers: int = 0
    project_total: int = 0
    task_total: int = 0
    task_open: int = 0
    task_closed: int = 0
    task_overdue: int = 0
    task_need_support: int = 0
    task_blocked: int = 0
    task_status_counts: dict[str, int] = Field(default_factory=dict)
    followup_total: int = 0
    work_item_open: int = 0
    profile_incomplete: int = 0
    pending_action_customers: int = 0
    risk_customers: int = 0
    generated_at: datetime | None = None


class CrmLinkedCustomerRow(BaseModel):
    customer_code: str
    customer_name: str
    customer_name_snapshot: str | None = None
    customer_short_name: str | None = None
    customer_type: str | None = None
    customer_status: str | None = None
    region: str | None = None
    salesperson_employee_code: str | None = None
    salesperson_name: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    contact_channel: str | None = None
    customer_group_name: str | None = None
    customer_tags: list[str] = Field(default_factory=list)
    address: str | None = None
    base_info_completeness: str | None = None
    profile_updated_at: datetime | None = None
    customer_updated_at: datetime | None = None
    base_remark: str | None = None
    project_total: int = 0
    latest_project_id: int | None = None
    latest_project_name: str | None = None
    latest_project_status: str | None = None
    task_total: int = 0
    task_open: int = 0
    task_closed: int = 0
    task_overdue: int = 0
    task_need_support: int = 0
    task_blocked: int = 0
    followup_total: int = 0
    latest_followup_at: datetime | None = None
    work_item_open: int = 0
    executor_names: list[str] = Field(default_factory=list)
    latest_task_id: int | None = None
    latest_task_code: str | None = None
    latest_task_status: str | None = None
    latest_owner_next_status: str | None = None
    latest_owner_next_action: str | None = None
    latest_owner_next_followup_at: datetime | None = None
    latest_blocker_reason: str | None = None
    current_flow_node: str | None = None
    current_handler_label: str | None = None
    blocked_reason_summary: str | None = None
    flow_status: str | None = None
    last_activity_at: datetime | None = None
    risk_level: str = "normal"


class CrmLinkedCustomerPage(BaseModel):
    items: list[CrmLinkedCustomerRow]
    total: int
    limit: int
    offset: int
    summary: CrmLinkedCustomerSummary = Field(default_factory=CrmLinkedCustomerSummary)


class CrmDataCenterBucket(BaseModel):
    value: str
    label: str
    count: int
    risk_count: int = 0
    meta: JsonValue | None = None


class CrmDataCenterSummary(BaseModel):
    project_total: int = 0
    task_total: int = 0
    open_tasks: int = 0
    closed_tasks: int = 0
    overdue_tasks: int = 0
    need_support_tasks: int = 0
    blocked_tasks: int = 0
    no_followup_tasks: int = 0
    valid_feedback_tasks: int = 0
    open_work_items: int = 0
    pending_approvals: int = 0
    generated_at: datetime | None = None


class CrmDataCenterDimensions(BaseModel):
    projects: list[CrmDataCenterBucket] = Field(default_factory=list)
    owners: list[CrmDataCenterBucket] = Field(default_factory=list)
    regions: list[CrmDataCenterBucket] = Field(default_factory=list)
    customer_types: list[CrmDataCenterBucket] = Field(default_factory=list)
    blocker_reasons: list[CrmDataCenterBucket] = Field(default_factory=list)
    followup_statuses: list[CrmDataCenterBucket] = Field(default_factory=list)


class CrmDataCenterTaskRow(CrmProjectCustomerDetailRow):
    project_name: str | None = None
    project_code: str | None = None
    project_status: str | None = None
    project_owner_user_id: int | None = None
    project_manager_user_id: int | None = None
    followup_status: str
    risk_level: str


class CrmDataCenterPage(BaseModel):
    items: list[CrmDataCenterTaskRow]
    total: int
    limit: int
    offset: int
    scope: str | None = None
    summary: CrmDataCenterSummary = Field(default_factory=CrmDataCenterSummary)
    dimensions: CrmDataCenterDimensions = Field(default_factory=CrmDataCenterDimensions)


class CrmTaskDetail(BaseModel):
    task: CrmProjectCustomerTaskPublic
    project: CrmProjectPublic
    followups: list["CrmFollowupPublic"] = Field(default_factory=list)
    approvals: list[ApprovalInstancePublic] = Field(default_factory=list)
    work_items: list[WorkItemPublic] = Field(default_factory=list)


class CrmFollowupPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    followup_no: str
    project_id: int
    task_id: int
    customer_code: str
    customer_name: str | None = None
    project_name: str | None = None
    executor_user_id: int | None
    executor_name_snapshot: str | None
    followup_date: date | None
    method: str | None
    frontline_action: str | None
    customer_feedback: str | None
    current_need: str | None
    need_type: str | None
    blocker_reason: str | None
    blocker_note: str | None
    next_action_type: str | None
    next_action: str | None
    next_followup_at: datetime | None
    minimum_action_done: bool
    business_profile_updated: bool
    business_profile_approval_id: int | None
    customer_profile_updated: bool
    customer_profile_approval_id: int | None
    need_support: bool
    need_manager_support: bool
    need_boss_decision: bool
    is_closed: bool
    valid_feedback: bool
    review_status: str
    review_result: str | None
    review_note: str | None
    owner_next_status: str | None
    owner_next_action: str | None
    owner_next_followup_at: datetime | None
    reviewed_by_user_id: int | None
    reviewed_at: datetime | None
    approval_id: int | None
    created_at: datetime
    updated_at: datetime


class CrmFollowupCreate(BaseModel):
    followup_no: str | None = Field(default=None, max_length=120)
    project_id: int
    task_id: int
    followup_date: date | None = None
    method: str | None = Field(default=None, max_length=80)
    frontline_action: str | None = None
    customer_feedback: str | None = None
    current_need: str | None = None
    need_type: str | None = Field(default=None, max_length=120)
    blocker_reason: str | None = Field(default=None, max_length=160)
    blocker_note: str | None = None
    next_action_type: str | None = Field(default=None, max_length=120)
    next_action: str | None = None
    next_followup_at: datetime | None = None
    minimum_action_done: bool = False
    business_profile_updated: bool = False
    business_profile_approval_id: int | None = None
    customer_profile_updated: bool = False
    customer_profile_approval_id: int | None = None
    need_support: bool = False
    need_manager_support: bool = False
    need_boss_decision: bool = False
    is_closed: bool = False
    valid_feedback: bool = True
    review_status: str = "pending"


class CrmFollowupApprovalDraftCreate(BaseModel):
    title: str | None = None
    description: str | None = None
    current_handler_user_id: int | None = None
    priority: str = "normal"
    submit: bool = True
    followup: CrmFollowupCreate


class CrmFollowupUpdate(BaseModel):
    followup_date: date | None = None
    method: str | None = Field(default=None, max_length=80)
    frontline_action: str | None = None
    customer_feedback: str | None = None
    current_need: str | None = None
    need_type: str | None = Field(default=None, max_length=120)
    blocker_reason: str | None = Field(default=None, max_length=160)
    blocker_note: str | None = None
    next_action_type: str | None = Field(default=None, max_length=120)
    next_action: str | None = None
    next_followup_at: datetime | None = None
    minimum_action_done: bool | None = None
    business_profile_updated: bool | None = None
    customer_profile_updated: bool | None = None
    customer_profile_approval_id: int | None = None
    need_support: bool | None = None
    need_manager_support: bool | None = None
    need_boss_decision: bool | None = None
    is_closed: bool | None = None
    valid_feedback: bool | None = None
    review_status: str | None = None
    review_result: str | None = Field(default=None, max_length=120)
    review_note: str | None = None
    owner_next_status: str | None = Field(default=None, max_length=80)
    owner_next_action: str | None = None
    owner_next_followup_at: datetime | None = None


class CrmFollowupPage(BaseModel):
    items: list[CrmFollowupPublic]
    total: int
    limit: int
    offset: int


class CrmProjectReviewPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    review_no: str
    project_id: int
    review_date: date | None
    status: str
    customer_total: int
    feedback_customer_count: int
    valid_feedback_customer_count: int
    no_feedback_customer_count: int
    support_item_count: int
    closed_customer_count: int
    unclosed_customer_count: int
    data_summary: str | None
    business_judgement: str | None
    main_problem: str | None
    next_suggestion: str | None
    conclusion: str | None
    decision_maker_user_id: int | None
    created_at: datetime
    updated_at: datetime


class CrmProjectReviewCreate(BaseModel):
    review_no: str | None = Field(default=None, max_length=120)
    review_date: date | None = None
    status: str = "draft"
    data_summary: str | None = None
    business_judgement: str | None = None
    main_problem: str | None = None
    next_suggestion: str | None = None
    conclusion: str | None = Field(default=None, max_length=80)
    decision_maker_user_id: int | None = None


class CrmProjectReviewUpdate(BaseModel):
    review_date: date | None = None
    status: str | None = None
    data_summary: str | None = None
    business_judgement: str | None = None
    main_problem: str | None = None
    next_suggestion: str | None = None
    conclusion: str | None = Field(default=None, max_length=80)
    decision_maker_user_id: int | None = None


class WorkItemPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    item_no: str
    source_type: str
    source_id: str
    resource_type: str | None
    resource_id: str | None
    project_id: int | None
    customer_code: str | None
    item_type: str
    title: str
    detail: str | None
    priority: str
    status: str
    assignee_user_id: int | None
    due_at: datetime | None
    resolved_by_user_id: int | None
    resolved_at: datetime | None
    resolution_note: str | None
    created_at: datetime
    updated_at: datetime
    customer_name: str | None = None
    project_name: str | None = None
    project_approval_frozen: bool = False
    project_approval_withdrawn_reason: str | None = None
    project_approval_withdrawn_at: datetime | None = None
    task_no: str | None = None
    task_title: str | None = None
    assignee_name: str | None = None
    resolved_by_name: str | None = None
    support_type: str | None = None
    support_detail: str | None = None
    source_followup_summary: str | None = None
    needs_next_action: bool = False


class WorkItemPage(BaseModel):
    items: list[WorkItemPublic]
    total: int
    limit: int
    offset: int


class WorkItemUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    detail: str | None = None
    priority: str | None = Field(default=None, max_length=40)
    status: str | None = Field(default=None, max_length=40)
    assignee_user_id: int | None = None
    due_at: datetime | None = None


class WorkItemActionRequest(BaseModel):
    resolution_note: str | None = None


class CrmSummary(BaseModel):
    active_projects: int = 0
    pending_project_approvals: int = 0
    task_total: int = 0
    due_today_tasks: int = 0
    overdue_no_feedback_tasks: int = 0
    open_work_items: int = 0
    closed_tasks: int = 0
    valid_feedback_tasks: int = 0
    valid_feedback_rate: float = 0
    latest_followup_at: datetime | None = None
    generated_at: datetime


class CrmDailySummaryTask(BaseModel):
    id: int
    project_id: int
    task_code: str
    customer_code: str
    customer_name_snapshot: str
    executor_user_id: int | None = None
    executor_employee_code: str | None = None
    executor_name_snapshot: str | None = None
    feedback_due_at: datetime | None = None
    status: str
    is_closed: bool
    last_followup_at: datetime | None = None
    latest_followup_id: int | None = None
    has_valid_followup: bool = False
    overdue: bool = False


class CrmDailySummary(BaseModel):
    date: date
    due_tasks: list[CrmDailySummaryTask] = Field(default_factory=list)
    overdue_tasks: list[CrmDailySummaryTask] = Field(default_factory=list)
    task_total: int = 0
    due_count: int = 0
    overdue_count: int = 0
    responsible_user_ids: list[int] = Field(default_factory=list)
    missing_responsible_user_ids: list[int] = Field(default_factory=list)
    generated_at: datetime


class CrmAssistantSkill(BaseModel):
    operation: str
    label: str
    description: str
    write_effect: str = "readonly"


class CrmAssistantRuntime(BaseModel):
    configured: bool
    model: str | None = None
    provider_host: str | None = None
    source: str = "project_base"
    direct_db_enabled: bool = False
    skills: list[CrmAssistantSkill] = Field(default_factory=list)


class CrmAssistantConversationPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_no: str
    user_id: int | None
    username_snapshot: str | None
    channel: str
    session_id: str | None
    context_type: str | None
    context_id: str | None
    operation: str | None
    user_message: str
    assistant_message: str
    source: str
    model_name: str | None
    status: str
    payload_json: JsonValue | None
    created_at: datetime


class CrmAssistantMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    operation: str | None = Field(default=None, max_length=120)
    channel: str = Field(default="web", max_length=80)
    session_id: str | None = Field(default=None, max_length=120)
    context_type: str | None = Field(default=None, max_length=80)
    context_id: str | None = Field(default=None, max_length=160)


class CrmAssistantMessageResponse(BaseModel):
    message: CrmAssistantConversationPublic
    runtime: CrmAssistantRuntime
    insights_created: int = 0


class CrmAssistantMessageCancelRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class CrmAssistantProjectDraftRequest(BaseModel):
    project_name: str | None = Field(default=None, max_length=255)
    customer_name: str | None = Field(default=None, max_length=255)
    project_type: str | None = Field(default="客户项目", max_length=120)
    business_line: str | None = Field(default=None, max_length=120)
    purpose: str | None = Field(default=None, max_length=1000)
    customer_scope_note: str | None = Field(default=None, max_length=1000)
    target: str | None = Field(default=None, max_length=1000)
    risk_note: str | None = Field(default=None, max_length=1000)
    due_days: int = Field(default=7, ge=1, le=180)
    channel: str = Field(default="web", max_length=80)


class CrmAssistantProjectDraftResponse(BaseModel):
    draft: JsonValue
    message: CrmAssistantConversationPublic
    runtime: CrmAssistantRuntime


class CrmAssistantAgentStatus(BaseModel):
    runtime: CrmAssistantRuntime
    status_counts: dict[str, int] = Field(default_factory=dict)
    source_counts: dict[str, int] = Field(default_factory=dict)
    operation_counts: dict[str, int] = Field(default_factory=dict)
    pending_actions: int = 0
    recent_calls: list[CrmAssistantConversationPublic] = Field(default_factory=list)
    last_call_at: datetime | None = None
    migration_status: dict[str, Any] = Field(default_factory=dict)


class CrmProjectInsightPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    insight_no: str
    project_id: int | None
    task_id: int | None
    customer_code: str | None
    insight_type: str
    summary: str
    suggested_action: str | None
    risk_level: str
    opportunity_level: str | None
    confidence_score: int
    status: str
    evidence_json: JsonValue | None
    source: str
    generated_by_user_id: int | None
    reviewed_by_user_id: int | None
    reviewed_at: datetime | None
    review_note: str | None
    payload_json: JsonValue | None
    created_at: datetime
    updated_at: datetime


class CrmProjectInsightPage(BaseModel):
    items: list[CrmProjectInsightPublic]
    total: int
    limit: int
    offset: int


class CrmAssistantJudgementResult(BaseModel):
    created: int = 0
    skipped: int = 0
    insights: list[CrmProjectInsightPublic] = Field(default_factory=list)


class CrmProjectInsightReviewRequest(BaseModel):
    action: str = Field(pattern="^(accept|reject|task)$")
    note: str | None = None


class CrmProjectContext(BaseModel):
    project_detail: CrmProjectDetail
    tasks: list[CrmProjectCustomerTaskPublic] = Field(default_factory=list)
    followups: list[CrmFollowupPublic] = Field(default_factory=list)
    approvals: list[ApprovalInstancePublic] = Field(default_factory=list)
    work_items: list[WorkItemPublic] = Field(default_factory=list)
    reviews: list[CrmProjectReviewPublic] = Field(default_factory=list)


class CrmReportNotificationPublic(BaseModel):
    notification_id: str
    notification_type: str
    title: str
    detail: str | None = None
    status: str
    priority: str = "normal"
    source_type: str
    source_id: str
    project_id: int | None = None
    task_id: int | None = None
    customer_code: str | None = None
    action_path: str | None = None
    created_at: datetime | None = None
    due_at: datetime | None = None
    is_mine: bool = False


class CrmReportNotificationSummary(BaseModel):
    total: int = 0
    pending: int = 0
    processed: int = 0
    today: int = 0
    overdue: int = 0
    supplement: int = 0
    support: int = 0


class CrmReportNotificationCenter(BaseModel):
    summary: CrmReportNotificationSummary = Field(default_factory=CrmReportNotificationSummary)
    items: list[CrmReportNotificationPublic] = Field(default_factory=list)
    generated_at: datetime


class CrmReportNotificationProcessRequest(BaseModel):
    action: str = Field(default="handled", max_length=80)
    note: str | None = Field(default=None, max_length=1000)


class CrmReportNotificationProcessResult(BaseModel):
    status: str
    notification_id: str
    action: str
    audit_logged: bool = True


class CrmLeadProductIntentInput(BaseModel):
    product_code: str | None = Field(default=None, max_length=120)
    product_name: str = Field(min_length=1, max_length=255)
    quantity_note: str | None = Field(default=None, max_length=255)
    interest_level: str | None = Field(default=None, max_length=40)
    note: str | None = None
    sort_order: int = 0


class CrmLeadCampaignCreate(BaseModel):
    campaign_code: str = Field(min_length=1, max_length=120)
    campaign_name: str = Field(min_length=1, max_length=255)
    source: str | None = Field(default=None, max_length=120)
    channel: str | None = Field(default=None, max_length=120)
    description: str | None = None
    status: str = Field(default="active", max_length=40)
    start_date: date | None = None
    end_date: date | None = None
    owner_user_id: int | None = None

    @field_validator("status")
    @classmethod
    def _validate_status(cls, status: str) -> str:
        if status not in CRM_LEAD_CAMPAIGN_STATUSES:
            raise ValueError("invalid CRM lead campaign status")
        return status

    @model_validator(mode="after")
    def _validate_dates(self) -> "CrmLeadCampaignCreate":
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("campaign end_date cannot be earlier than start_date")
        return self


class CrmLeadCampaignUpdate(BaseModel):
    campaign_name: str | None = Field(default=None, min_length=1, max_length=255)
    source: str | None = Field(default=None, max_length=120)
    channel: str | None = Field(default=None, max_length=120)
    description: str | None = None
    status: str | None = Field(default=None, max_length=40)
    start_date: date | None = None
    end_date: date | None = None
    owner_user_id: int | None = None

    @field_validator("status")
    @classmethod
    def _validate_status(cls, status: str | None) -> str | None:
        if status is not None and status not in CRM_LEAD_CAMPAIGN_STATUSES:
            raise ValueError("invalid CRM lead campaign status")
        return status

    @model_validator(mode="after")
    def _validate_dates(self) -> "CrmLeadCampaignUpdate":
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("campaign end_date cannot be earlier than start_date")
        return self


class CrmLeadOperationPolicyUpdate(BaseModel):
    first_response_hours: int | None = Field(default=None, gt=0, le=24 * 30)
    next_followup_hours: int | None = Field(default=None, gt=0, le=24 * 90)
    assignment_hold_hours: int | None = Field(default=None, gt=0, le=24 * 90)
    due_soon_hours: int | None = Field(default=None, ge=0, le=24 * 30)
    daily_claim_limit: int | None = Field(default=None, ge=0, le=500)


class CrmLeadRecycleRequest(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class CrmLeadCampaignPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    campaign_code: str
    campaign_name: str
    source: str | None
    channel: str | None
    description: str | None
    status: str
    start_date: date | None
    end_date: date | None
    owner_user_id: int | None
    created_by_user_id: int | None
    updated_by_user_id: int | None
    created_at: datetime
    updated_at: datetime


class CrmLeadOperationPolicyPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    policy_key: str
    first_response_hours: int
    next_followup_hours: int
    assignment_hold_hours: int
    due_soon_hours: int
    daily_claim_limit: int
    is_active: bool
    updated_by_user_id: int | None
    created_at: datetime
    updated_at: datetime


class CrmLeadPoolPublic(BaseModel):
    id: int
    lead_no: str
    lead_name: str
    company_name: str | None
    source: str | None
    region: str | None
    business_line: str | None
    priority: str
    pool_status: str
    status: str
    first_response_due_at: datetime | None
    recycled_at: datetime | None
    recycle_count: int
    created_at: datetime
    sla: dict[str, Any]


class CrmLeadPoolPage(BaseModel):
    items: list[CrmLeadPoolPublic]
    total: int
    limit: int
    offset: int


class CrmLeadCreate(BaseModel):
    lead_no: str | None = Field(default=None, max_length=120)
    lead_name: str = Field(min_length=1, max_length=255)
    company_name: str | None = Field(default=None, max_length=255)
    contact_name: str | None = Field(default=None, max_length=120)
    contact_phone: str | None = Field(default=None, max_length=80)
    source: str | None = Field(default=None, max_length=120)
    campaign_id: int | None = None
    region: str | None = Field(default=None, max_length=120)
    address: str | None = Field(default=None, max_length=2000)
    customer_group_name: str | None = Field(default=None, max_length=255)
    business_line: str | None = Field(default=None, max_length=120)
    intent_summary: str | None = None
    status: CrmLeadStatus = CrmLeadStatus.DRAFT
    priority: str = Field(default="normal", max_length=40)
    qualification_note: str | None = None
    owner_user_id: int | None = None
    assigned_user_id: int | None = None
    next_followup_at: datetime | None = None
    duplicate_acknowledged: bool = False
    product_intents: list[CrmLeadProductIntentInput] = Field(default_factory=list)

    @field_validator("status")
    @classmethod
    def _reject_conversion_statuses(cls, status: CrmLeadStatus) -> CrmLeadStatus:
        if status in {CrmLeadStatus.CONVERSION_PENDING, CrmLeadStatus.CONVERTED}:
            raise ValueError("conversion lifecycle statuses cannot be set when creating a lead")
        return status

    @field_validator("priority")
    @classmethod
    def _validate_priority(cls, priority: str) -> str:
        if priority not in CRM_LEAD_PRIORITIES:
            raise ValueError("invalid CRM lead priority")
        return priority


class CrmLeadUpdate(BaseModel):
    lead_name: str = Field(default=None, min_length=1, max_length=255)
    company_name: str | None = Field(default=None, max_length=255)
    contact_name: str | None = Field(default=None, max_length=120)
    contact_phone: str | None = Field(default=None, max_length=80)
    source: str | None = Field(default=None, max_length=120)
    campaign_id: int | None = None
    region: str | None = Field(default=None, max_length=120)
    address: str | None = Field(default=None, max_length=2000)
    customer_group_name: str | None = Field(default=None, max_length=255)
    business_line: str | None = Field(default=None, max_length=120)
    intent_summary: str | None = None
    status: CrmLeadStatus | None = None
    priority: str | None = Field(default=None, max_length=40)
    qualification_note: str | None = None
    owner_user_id: int | None = None
    assigned_user_id: int | None = None
    next_followup_at: datetime | None = None
    duplicate_acknowledged: bool = False
    product_intents: list[CrmLeadProductIntentInput] | None = None

    @field_validator("status", mode="before")
    @classmethod
    def _reject_explicit_null_status(cls, status: object) -> object:
        if status is None:
            raise ValueError("status cannot be null when supplied")
        return status

    @field_validator("priority")
    @classmethod
    def _validate_priority(cls, priority: str | None) -> str | None:
        if priority is not None and priority not in CRM_LEAD_PRIORITIES:
            raise ValueError("invalid CRM lead priority")
        return priority


class CrmLeadFollowupCreate(BaseModel):
    followup_no: str | None = Field(default=None, max_length=120)
    content: str = Field(min_length=1)
    method: str | None = Field(default=None, max_length=80)
    outcome: str | None = None
    next_action: str | None = None
    next_followup_at: datetime | None = None


class CrmLeadAssignmentCreate(BaseModel):
    assigned_user_id: int | None = None
    note: str | None = None


class CrmLeadConversionApprovalDraftCreate(BaseModel):
    submit: bool = False
    priority: str = Field(default="normal", max_length=40)
    note: str | None = Field(default=None, max_length=2000)


class CrmLeadProductIntentPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    lead_id: int
    product_code: str | None
    product_name: str
    quantity_note: str | None
    interest_level: str | None
    note: str | None
    sort_order: int
    created_at: datetime
    updated_at: datetime


class CrmLeadFollowupPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    lead_id: int
    followup_no: str
    content: str
    method: str | None
    outcome: str | None
    next_action: str | None
    next_followup_at: datetime | None
    created_by_user_id: int | None
    created_at: datetime
    updated_at: datetime


class CrmLeadAssignmentEventPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    lead_id: int
    event_type: str
    from_assignee_user_id: int | None
    to_assignee_user_id: int | None
    assigned_by_user_id: int | None
    note: str | None
    created_at: datetime


class CrmLeadPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    lead_no: str
    lead_name: str
    company_name: str | None
    contact_name: str | None
    contact_phone: str | None
    source: str | None
    campaign_id: int | None
    region: str | None
    address: str | None
    customer_group_name: str | None
    business_line: str | None
    intent_summary: str | None
    status: str
    priority: str
    pool_status: str
    qualification_note: str | None
    owner_user_id: int | None
    assigned_user_id: int | None
    assigned_at: datetime | None
    assignment_expires_at: datetime | None
    first_response_due_at: datetime | None
    first_responded_at: datetime | None
    last_activity_at: datetime | None
    last_followup_at: datetime | None
    next_followup_at: datetime | None
    recycled_at: datetime | None
    recycle_count: int
    current_approval_id: int | None
    converted_customer_code: str | None
    converted_at: datetime | None
    converted_by_user_id: int | None
    created_by_user_id: int | None
    updated_by_user_id: int | None
    created_at: datetime
    updated_at: datetime
    product_intents: list[CrmLeadProductIntentPublic] = Field(default_factory=list)
    followups: list[CrmLeadFollowupPublic] = Field(default_factory=list)
    assignments: list[CrmLeadAssignmentEventPublic] = Field(default_factory=list)


class CrmLeadPageSummary(BaseModel):
    total: int
    by_status: dict[str, int]


class CrmLeadPage(BaseModel):
    items: list[CrmLeadPublic]
    total: int
    limit: int
    offset: int
    summary: CrmLeadPageSummary


class CrmLeadSlaExceptionPublic(BaseModel):
    lead: CrmLeadPublic
    sla: dict[str, Any]


class CrmLeadSlaExceptionPage(BaseModel):
    items: list[CrmLeadSlaExceptionPublic]
    total: int
    limit: int
    offset: int

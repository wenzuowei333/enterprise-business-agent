from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field


ExternalDataT = TypeVar("ExternalDataT")


class ExternalResponseMeta(BaseModel):
    request_id: str
    generated_at: datetime
    schema_version: str = "2.0"
    next_cursor: str | None = None
    has_more: bool | None = None


class ExternalEnvelope(BaseModel, Generic[ExternalDataT]):
    data: ExternalDataT
    meta: ExternalResponseMeta


class ExternalDataScope(BaseModel):
    region: str | None = None
    project_ids: list[int] = Field(default_factory=list)
    customer_fields: list[str] = Field(default_factory=list)


class ExternalKeyIdentity(BaseModel):
    key_id: str
    name: str
    owner_name: str | None = None
    readonly: bool = True
    expires_at: datetime | None = None
    permissions: dict[str, bool] = Field(default_factory=dict)
    permission_scopes: list[str] = Field(default_factory=list)
    rate_limit_per_minute: int
    daily_request_limit: int
    rotated_at: datetime | None = None
    previous_key_expires_at: datetime | None = None
    data_scope: ExternalDataScope


class ExternalMeData(BaseModel):
    key: ExternalKeyIdentity


class ExternalCapability(BaseModel):
    code: str
    resource: str
    description: str
    enabled: bool


class ExternalCapabilitiesData(BaseModel):
    capabilities: list[ExternalCapability]


class ExternalDictionaryItem(BaseModel):
    code: str
    label: str


class ExternalDictionariesData(BaseModel):
    project_statuses: list[ExternalDictionaryItem]
    task_statuses: list[ExternalDictionaryItem]
    followup_review_statuses: list[ExternalDictionaryItem]
    approval_statuses: list[ExternalDictionaryItem]


class ExternalProjectItem(BaseModel):
    id: int
    project_code: str
    project_name: str
    project_type: str | None = None
    purpose: str | None = None
    business_line: str | None = None
    owner: str | None = None
    project_manager: str | None = None
    start_date: date | None = None
    due_date: date | None = None
    status: str
    approval_status: str
    next_step_status: str | None = None
    next_step_action: str | None = None
    next_step_followup_at: datetime | None = None
    task_total: int = 0
    task_closed: int = 0
    task_open: int = 0
    task_overdue: int = 0
    task_need_support: int = 0
    task_blocked: int = 0
    latest_approved_followup_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ExternalProjectListData(BaseModel):
    items: list[ExternalProjectItem]
    count: int


class ExternalTaskItem(BaseModel):
    id: int
    project_id: int
    task_code: str
    customer_code: str
    customer_name: str
    executor: str | None = None
    project_purpose: str | None = None
    business_issue_point: str | None = None
    round_target: str | None = None
    feedback_due_at: datetime | None = None
    status: str
    minimum_action_done: bool
    need_support: bool
    need_manager_support: bool
    need_boss_decision: bool
    is_blocked: bool
    is_closed: bool
    overdue: bool
    blocker_reason: str | None = None
    blocker_note: str | None = None
    next_status: str | None = None
    next_action: str | None = None
    next_followup_at: datetime | None = None
    last_followup_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ExternalTaskListData(BaseModel):
    items: list[ExternalTaskItem]
    count: int


class ExternalFollowupItem(BaseModel):
    id: int
    followup_no: str
    project_id: int
    task_id: int
    customer_code: str
    customer_name: str
    executor: str | None = None
    followup_date: date | None = None
    method: str | None = None
    frontline_action: str | None = None
    customer_feedback: str | None = None
    current_need: str | None = None
    blocker_reason: str | None = None
    blocker_note: str | None = None
    next_action_type: str | None = None
    next_action: str | None = None
    next_followup_at: datetime | None = None
    minimum_action_done: bool
    need_support: bool
    need_manager_support: bool
    need_boss_decision: bool
    is_closed: bool
    valid_feedback: bool
    review_status: str
    reviewed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ExternalFollowupListData(BaseModel):
    items: list[ExternalFollowupItem]
    count: int


class ExternalWorkItem(BaseModel):
    id: int
    item_no: str
    project_id: int | None = None
    customer_code: str | None = None
    item_type: str
    title: str
    detail: str | None = None
    priority: str
    status: str
    assignee: str | None = None
    due_at: datetime | None = None
    resolved_at: datetime | None = None
    resolution_note: str | None = None
    created_at: datetime
    updated_at: datetime


class ExternalWorkItemListData(BaseModel):
    items: list[ExternalWorkItem]
    count: int


class ExternalApprovalItem(BaseModel):
    id: int
    approval_no: str
    approval_type: str
    resource_type: str
    resource_id: str
    title: str
    status: str
    priority: str
    submitted_at: datetime | None = None
    reviewed_at: datetime | None = None
    closed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ExternalApprovalListData(BaseModel):
    items: list[ExternalApprovalItem]
    count: int


class ExternalProgressMetrics(BaseModel):
    task_total: int = 0
    task_closed: int = 0
    task_open: int = 0
    task_overdue: int = 0
    task_need_support: int = 0
    task_need_manager_support: int = 0
    task_need_boss_decision: int = 0
    task_blocked: int = 0
    feedback_task_count: int = 0
    valid_feedback_task_count: int = 0
    no_feedback_task_count: int = 0
    support_open_count: int = 0
    support_closed_count: int = 0
    pending_approval_count: int = 0
    review_total: int = 0
    review_confirmed: int = 0
    task_closure_rate: float = 0
    valid_feedback_rate: float = 0


class ExternalProjectProgressData(BaseModel):
    project: ExternalProjectItem
    metrics: ExternalProgressMetrics
    closure_ready: bool
    closure_state: str
    closure_blockers: list[str] = Field(default_factory=list)
    latest_review_status: str | None = None
    latest_review_conclusion: str | None = None
    calculated_at: datetime
    source_updated_at: datetime


class ExternalProjectDetailData(BaseModel):
    project: ExternalProjectItem
    progress: ExternalProjectProgressData


class ExternalTimelineEvent(BaseModel):
    event_id: str
    event_type: str
    title: str
    summary: str | None = None
    status: str | None = None
    occurred_at: datetime
    project_id: int
    task_id: int | None = None
    customer_code: str | None = None


class ExternalTimelineData(BaseModel):
    items: list[ExternalTimelineEvent]
    count: int


class ExternalOverviewStats(BaseModel):
    projects: int | None = None
    tasks: int | None = None
    open_tasks: int | None = None
    overdue_tasks: int | None = None
    blocked_tasks: int | None = None
    approved_followups: int | None = None
    open_work_items: int | None = None
    pending_approvals: int | None = None


class ExternalOverviewData(BaseModel):
    stats: ExternalOverviewStats


class ExternalCustomerItem(BaseModel):
    customer_code: str
    customer_name: str
    fields: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class ExternalCustomerListData(BaseModel):
    items: list[ExternalCustomerItem]
    count: int


class ExternalProductItem(BaseModel):
    product_code: str
    product_name: str
    spec: str | None = None
    unit: str | None = None
    category: str | None = None
    brand: str | None = None
    barcode: str | None = None
    reference_sale_price: Decimal | None = None
    status: str
    created_at: datetime
    updated_at: datetime


class ExternalProductListData(BaseModel):
    items: list[ExternalProductItem]
    count: int


class ExternalSupplierItem(BaseModel):
    supplier_code: str
    supplier_name: str
    supplier_short_name: str | None = None
    supplier_type: str | None = None
    region: str | None = None
    status: str
    created_at: datetime
    updated_at: datetime


class ExternalSupplierListData(BaseModel):
    items: list[ExternalSupplierItem]
    count: int


class ExternalSalesBreakdownItem(BaseModel):
    key: str
    label: str
    row_count: int
    document_count: int
    quantity: Decimal
    net_sales: Decimal
    gross_profit: Decimal


class ExternalSalesSummaryData(BaseModel):
    date_from: date | None = None
    date_to: date | None = None
    data_cutoff_date: date | None = None
    group_by: str
    row_count: int
    document_count: int
    quantity: Decimal
    net_sales: Decimal
    gross_profit: Decimal
    gross_margin_rate: Decimal | None = None
    breakdown: list[ExternalSalesBreakdownItem]


class ExternalPurchaseBreakdownItem(BaseModel):
    key: str
    label: str
    row_count: int
    document_count: int
    quantity: Decimal
    purchase_amount: Decimal


class ExternalPurchaseSummaryData(BaseModel):
    date_from: date | None = None
    date_to: date | None = None
    data_cutoff_date: date | None = None
    group_by: str
    row_count: int
    document_count: int
    quantity: Decimal
    purchase_amount: Decimal
    breakdown: list[ExternalPurchaseBreakdownItem]


class ExternalInventoryBreakdownItem(BaseModel):
    key: str
    label: str
    row_count: int
    sku_count: int
    stock_quantity: Decimal
    locked_quantity: Decimal
    cost_amount: Decimal


class ExternalInventorySummaryData(BaseModel):
    data_date: date | None = None
    row_count: int
    sku_count: int
    warehouse_count: int
    stock_quantity: Decimal
    locked_quantity: Decimal
    cost_amount: Decimal
    breakdown: list[ExternalInventoryBreakdownItem]


class ExternalReceivableBreakdownItem(BaseModel):
    key: str
    label: str
    customer_count: int
    receivable_amount: Decimal
    overdue_customer_count: int


class ExternalReceivableSummaryData(BaseModel):
    data_date: date | None = None
    customer_count: int
    receivable_amount: Decimal
    received_amount: Decimal
    unreceived_amount: Decimal
    overdue_customer_count: int
    overdue_amount: Decimal
    breakdown: list[ExternalReceivableBreakdownItem]


class ExternalDataQualityIssueGroup(BaseModel):
    expected_master_kind: str
    issue_type: str
    issue_count: int
    affected_rows: int
    affected_documents: int


class ExternalDataQualityImportStatus(BaseModel):
    file_type: str
    data_date: date | None = None
    status: str
    total_rows: int
    success_rows: int
    error_rows: int
    uploaded_at: datetime


class ExternalDataQualitySummaryData(BaseModel):
    open_issue_count: int
    affected_rows: int
    affected_documents: int
    issue_groups: list[ExternalDataQualityIssueGroup]
    latest_imports: list[ExternalDataQualityImportStatus]
    calculated_at: datetime


class ExternalChangeEvent(BaseModel):
    change_id: int
    action: str
    resource_type: str
    resource_id: str | None = None
    project_id: int | None = None
    customer_code: str | None = None
    changed_fields: list[str] = Field(default_factory=list)
    deleted: bool = False
    occurred_at: datetime


class ExternalChangeFeedData(BaseModel):
    items: list[ExternalChangeEvent]
    count: int


class ExternalUsageItem(BaseModel):
    request_id: str
    endpoint: str
    method: str
    status_code: int
    duration_ms: int | None = None
    response_count: int | None = None
    created_at: datetime


class ExternalUsageSummaryData(BaseModel):
    minute_count: int
    minute_limit: int
    day_count: int
    day_limit: int
    success_count: int
    error_count: int
    recent: list[ExternalUsageItem]
    calculated_at: datetime


ExternalInventoryRootCause = Literal[
    "true_negative_stock",
    "missing_purchase",
    "duplicate_sale",
    "warehouse_mismatch",
    "warehouse_missing",
    "unit_conversion_error",
    "stale_snapshot",
    "import_error",
    "snapshot_mismatch",
    "missing_product_master",
    "insufficient_evidence",
]

ExternalInventoryActionType = Literal[
    "rebuild_inventory_flow",
    "rerun_inventory_check",
    "reimport_latest_snapshot",
    "create_upstream_adjustment",
    "reverse_or_repost_document",
]


class ExternalInventoryAnomalyItem(BaseModel):
    id: int
    case_no: str
    snapshot_id: int | None = None
    batch_id: int | None = None
    data_date: date | None = None
    product_code: str | None = None
    product_name: str | None = None
    warehouse_name: str | None = None
    warehouse_scope: str | None = None
    reason_code: str
    severity: str
    status: str
    stock_qty: Decimal | None = None
    locked_qty: Decimal | None = None
    evidence_version: str
    root_cause: str | None = None
    confidence: Decimal | None = None
    recommended_action: str | None = None
    expected_result: str | None = None
    resolution_note: str | None = None
    detected_at: datetime
    diagnosed_at: datetime | None = None
    resolved_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ExternalInventoryAnomalyListData(BaseModel):
    items: list[ExternalInventoryAnomalyItem]
    count: int
    latest_batch_id: int | None = None
    data_cutoff_date: date | None = None


class ExternalInventoryEvidenceData(BaseModel):
    case: ExternalInventoryAnomalyItem
    snapshot: dict[str, Any]
    product: dict[str, Any] | None = None
    supplier: dict[str, Any] | None = None
    historical_snapshots: list[dict[str, Any]] = Field(default_factory=list)
    inventory_flows: list[dict[str, Any]] = Field(default_factory=list)
    sales_details: list[dict[str, Any]] = Field(default_factory=list)
    purchase_details: list[dict[str, Any]] = Field(default_factory=list)
    inventory_checks: list[dict[str, Any]] = Field(default_factory=list)
    import_batches: list[dict[str, Any]] = Field(default_factory=list)
    import_errors: list[dict[str, Any]] = Field(default_factory=list)
    data_cutoff_date: date | None = None
    evidence_version: str


class ExternalInventoryDiagnosisCreate(BaseModel):
    root_cause: ExternalInventoryRootCause
    confidence: Decimal = Field(ge=0, le=1, max_digits=5, decimal_places=4)
    evidence_refs: list[str] = Field(min_length=1, max_length=100)
    impact: dict[str, Any] = Field(default_factory=dict)
    recommended_action: ExternalInventoryActionType
    expected_result: str = Field(min_length=1, max_length=2000)
    reasoning: str = Field(min_length=1, max_length=5000)


class ExternalInventoryActionValidateRequest(BaseModel):
    case_id: int
    action_type: ExternalInventoryActionType
    parameters: dict[str, Any] = Field(default_factory=dict)


class ExternalInventoryActionValidationData(BaseModel):
    action_id: int
    action_no: str
    allowed: bool
    blockers: list[str] = Field(default_factory=list)
    impact: dict[str, Any] = Field(default_factory=dict)
    validation_token: str | None = None
    validation_expires_at: datetime | None = None
    evidence_version: str


class ExternalInventoryActionExecuteRequest(BaseModel):
    action_id: int
    validation_token: str = Field(min_length=20, max_length=500)


class ExternalInventoryActionItem(BaseModel):
    id: int
    action_no: str
    case_id: int
    requested_by_key_id: str | None = None
    action_type: str
    status: str
    allowed: bool
    blockers: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    impact: dict[str, Any] = Field(default_factory=dict)
    evidence_version: str
    idempotency_key: str | None = None
    result: dict[str, Any] | None = None
    verification: dict[str, Any] | None = None
    compensation: dict[str, Any] | None = None
    upstream_reference: str | None = None
    error_message: str | None = None
    validation_expires_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

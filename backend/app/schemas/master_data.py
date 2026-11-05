from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ImportBatchPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    batch_no: str
    file_name: str
    file_type: str
    data_date: date | None
    uploaded_by: int | None
    uploaded_at: datetime
    status: str
    total_rows: int
    success_rows: int
    error_rows: int
    raw_file_path: str
    content_sha256: str | None
    header_json: list | None
    preview_json: list | None
    mapping_json: dict | None
    created_at: datetime
    updated_at: datetime


class ImportErrorPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    batch_id: int
    row_number: int
    error_type: str
    error_message: str
    raw_row_json: dict | None
    created_at: datetime


class MasterLinkIssuePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    batch_id: int | None
    source_file_type: str
    issue_type: str
    expected_master_kind: str
    reference_code: str | None
    reference_name: str | None
    counterpart_master_kind: str | None
    counterpart_code: str | None
    counterpart_name: str | None
    first_seen_date: date | None
    last_seen_date: date | None
    affected_rows: int
    affected_documents: int
    amount_total: Decimal | None
    quantity_total: Decimal | None
    status: str
    resolution_type: str | None
    resolved_by_user_id: int | None
    resolved_at: datetime | None
    resolution_note: str | None
    source_json: dict | None
    created_at: datetime
    updated_at: datetime


class MasterLinkIssueResolveRequest(BaseModel):
    resolution_type: str = "ignore"
    note: str | None = None


class MasterLinkIssuePage(BaseModel):
    items: list[MasterLinkIssuePublic]
    total: int
    limit: int
    offset: int
    summary: dict[str, int] = Field(default_factory=dict)


class MasterLinkIssueRebuildResponse(BaseModel):
    batches: int
    issues: int


class DataQualityRiskAlertPublic(BaseModel):
    rule_code: str
    rule_name: str
    rule_description: str
    status: str = "open"
    status_label: str = "待处理"
    closure_hint: str | None = None
    is_actionable: bool = True
    level: str
    category: str
    resource_type: str | None = None
    code: str | None = None
    name: str | None = None
    reason: str
    action: str | None = None
    affected_rows: int = 0
    affected_documents: int = 0
    affected_amount: str | None = None
    affected_quantity: str | None = None
    first_seen_date: date | None = None
    last_seen_date: date | None = None
    source: str | None = None
    metadata: dict | None = None


class DataQualityRiskSummaryPublic(BaseModel):
    warning_count: int = 0
    risk_count: int = 0
    total: int = 0
    categories: dict[str, int] = Field(default_factory=dict)
    rules: dict[str, int] = Field(default_factory=dict)


class DataQualityRiskAlertPage(BaseModel):
    items: list[DataQualityRiskAlertPublic]
    total: int
    limit: int
    offset: int
    summary: DataQualityRiskSummaryPublic


class DataQualityRiskRulePublic(BaseModel):
    rule_code: str
    rule_name: str
    level: str
    category: str
    resource_type: str | None = None
    scope: str
    description: str
    action: str
    is_enabled: bool = True


class DataQualityRiskRulePage(BaseModel):
    items: list[DataQualityRiskRulePublic]
    total: int


class DataCalendarRulePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rule_code: str
    file_type: str
    label: str
    action_layer: str
    frequency: str
    deadline_hour: int | None
    owner_role: str
    owner_user_ids: list | None
    is_required: bool
    is_enabled: bool
    sort_order: int
    remark: str | None
    created_at: datetime
    updated_at: datetime


class DataCalendarRuleUpdate(BaseModel):
    id: int | None = None
    rule_code: str
    file_type: str
    label: str
    action_layer: str
    frequency: str
    deadline_hour: int | None = None
    owner_role: str = "数据中台"
    owner_user_ids: list | None = None
    is_required: bool = True
    is_enabled: bool = True
    sort_order: int = 0
    remark: str | None = None


class DataCalendarReminderItem(BaseModel):
    rule_code: str
    file_type: str
    label: str
    status: str
    detail: str
    responsible_user_ids: list[int] = []
    missing_responsible_user_ids: list[int] = []
    latest_batch_no: str | None = None


class DataCalendarReminderRequest(BaseModel):
    data_date: date
    reminder_type: str = "missing_and_abnormal"
    items: list[DataCalendarReminderItem]
    message: str | None = None


class DataCalendarReminderResponse(BaseModel):
    status: str
    audit_id: int
    resource_id: str
    reminder_count: int


class DataCalendarCoveragePublic(BaseModel):
    data_date: date
    file_type: str
    status: str = "complete"
    row_count: int
    batch_ids: list[int] = []
    batch_nos: list[str] = []
    latest_batch_id: int | None = None
    latest_batch_no: str | None = None
    latest_uploaded_by: int | None = None
    source: str = "document_date"


class MasterCategoryNodePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    node_code: str
    kind: str
    label: str
    parent_id: int | None
    sort_order: int
    is_enabled: bool
    remark: str | None
    created_by_user_id: int | None
    updated_by_user_id: int | None
    created_at: datetime
    updated_at: datetime


class MasterCategoryNodeUpsert(BaseModel):
    label: str = Field(min_length=1, max_length=160)
    parent_id: int | None = None
    sort_order: int = 0
    is_enabled: bool = True
    remark: str | None = None


class MasterCategoryBindingPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    category_id: int
    resource_type: str
    resource_code: str
    is_primary: bool
    sort_order: int
    source: str | None
    created_by_user_id: int | None
    created_at: datetime
    updated_at: datetime


class MasterCategoryBindingCreate(BaseModel):
    resource_code: str = Field(min_length=1, max_length=120)
    is_primary: bool = True
    source: str = Field(default="manual", max_length=120)


class CustomerAttentionReasonPublic(BaseModel):
    code: Literal["inactive", "missing_contact", "missing_phone", "missing_address"]
    label: str


class CustomerTagPublic(BaseModel):
    id: int
    name: str
    color_key: Literal["blue", "green", "cyan", "yellow", "red", "purple", "pink", "gray"]
    is_active: bool
    usage_count: int = 0
    created_by_user_id: int | None = None
    created_by_name: str | None = None
    created_at: datetime
    updated_at: datetime
    stable_code: str | None = None
    category_key: str | None = None
    category_name: str | None = None
    group_code: str | None = None
    group_name: str | None = None
    catalog_version_id: int | None = None
    sort_order: int = 0
    selection_rule: str = "multi"
    mutual_exclusion_key: str | None = None
    applicability_json: dict | None = None
    is_formal: bool = False


class CustomerTagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=30)
    color_key: Literal["blue", "green", "cyan", "yellow", "red", "purple", "pink", "gray"] = "blue"


class CustomerTagUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=30)
    color_key: Literal["blue", "green", "cyan", "yellow", "red", "purple", "pink", "gray"] | None = None
    is_active: bool | None = None


class CustomerMasterPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_code: str
    customer_name: str
    customer_short_name: str | None
    customer_type: str | None
    region: str | None
    salesperson_employee_code: str | None
    salesperson_name: str | None
    historical_salespersons: str | None = None
    contact_name: str | None
    contact_phone: str | None
    contact_channel: str | None
    customer_group_name: str | None
    customer_tags: list[str] = []
    address: str | None
    base_info_completeness: str
    status: str
    source: str | None
    profile_updated_at: datetime | None
    base_remark: str | None
    attention_state: Literal["normal", "needs_attention"] | None = None
    attention_reasons: list[CustomerAttentionReasonPublic] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class CustomerMasterUpdate(BaseModel):
    customer_name: str | None = None
    customer_short_name: str | None = None
    customer_type: str | None = None
    region: str | None = None
    salesperson_employee_code: str | None = None
    salesperson_name: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    contact_channel: str | None = None
    customer_group_name: str | None = None
    customer_tags: list[str] | None = None
    address: str | None = None
    status: str | None = None
    profile_updated_at: datetime | None = None
    base_remark: str | None = None


class CustomerMasterCreate(CustomerMasterUpdate):
    customer_code: str
    customer_name: str


class CustomerBusinessProductPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_code: str
    product_category: str | None
    spec: str | None
    common_brand: str | None
    monthly_usage: str | None
    price_sensitivity: str | None
    cooperation_status: str | None
    change_type: str | None
    opportunity_note: str | None
    last_confirmed_at: date | None
    sort_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CustomerBusinessProductUpsert(BaseModel):
    id: int | None = None
    product_category: str | None = None
    spec: str | None = None
    common_brand: str | None = None
    monthly_usage: str | None = None
    price_sensitivity: str | None = None
    cooperation_status: str | None = None
    change_type: str | None = None
    opportunity_note: str | None = None
    last_confirmed_at: date | None = None
    sort_order: int = 0
    is_active: bool = True


class CustomerRecommendedProductUpsert(BaseModel):
    product_name: str | None = None
    spec: str | None = None
    recommended_quote: str | None = None
    recommend_reason: str | None = None
    customer_feedback: str | None = None
    next_action: str | None = None


class CustomerBusinessProfilePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_code: str
    customer_name_snapshot: str
    business_customer_type: str | None
    confirmed_at: date | None
    filled_by: str | None
    update_source: str | None
    update_type: str | None
    current_salesperson: str | None
    sales_channels: list | None
    business_status_tags: list | None
    business_status_label: str | None
    business_status_note: str | None
    other_status_label: str | None
    other_status_note: str | None
    latest_update_note: str | None
    version_no: int
    confirmed_by: str | None
    created_by_user_id: int | None
    updated_by_user_id: int | None
    created_at: datetime
    updated_at: datetime


class CustomerBusinessProfileHistoryPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_code: str
    version_no: int
    update_source: str | None
    update_type: str | None
    filled_by: str | None
    update_note: str | None
    confirmed_by: str | None
    snapshot_json: dict | None
    created_by_user_id: int | None
    created_at: datetime


class CustomerCurrentSalesProductPublic(BaseModel):
    product_code: str | None
    product_name: str | None
    monthly_sales_qty: Decimal
    quarter_sales_qty: Decimal


class CustomerBusinessProfileResponse(BaseModel):
    customer: CustomerMasterPublic
    profile: CustomerBusinessProfilePublic | None
    products: list[CustomerBusinessProductPublic] = []
    history_summary: list[CustomerBusinessProfileHistoryPublic] = []
    current_sales_products: list[CustomerCurrentSalesProductPublic] = []


class CustomerBusinessProfileUpsert(BaseModel):
    business_customer_type: str | None = None
    confirmed_at: date | None = None
    filled_by: str | None = None
    update_source: str | None = None
    update_type: str | None = None
    current_salesperson: str | None = None
    sales_channels: list[str] = []
    business_status_tags: list[str] = []
    business_status_label: str | None = None
    business_status_note: str | None = None
    other_status_label: str | None = None
    other_status_note: str | None = None
    latest_update_note: str | None = None
    confirmed_by: str | None = None
    products: list[CustomerBusinessProductUpsert] = []
    recommended_products: list[CustomerRecommendedProductUpsert] = []


class ProductMasterPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_code: str
    product_name: str
    spec: str | None
    unit: str | None
    category: str | None
    brand: str | None
    barcode: str | None
    reference_sale_price: Decimal | None
    reference_cost: Decimal | None
    status: str
    source: str | None
    created_at: datetime
    updated_at: datetime


class ProductMasterUpdate(BaseModel):
    product_name: str | None = None
    spec: str | None = None
    unit: str | None = None
    category: str | None = None
    brand: str | None = None
    barcode: str | None = None
    reference_sale_price: Decimal | None = None
    reference_cost: Decimal | None = None
    status: str | None = None


class ProductMasterCreate(ProductMasterUpdate):
    product_code: str
    product_name: str


class SupplierMasterPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    supplier_code: str
    supplier_name: str
    supplier_short_name: str | None
    supplier_type: str | None
    region: str | None
    contact_name: str | None
    contact_phone: str | None
    address: str | None
    status: str
    source: str | None
    created_at: datetime
    updated_at: datetime


class SupplierMasterUpdate(BaseModel):
    supplier_name: str | None = None
    supplier_short_name: str | None = None
    supplier_type: str | None = None
    region: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    address: str | None = None
    status: str | None = None


class SupplierMasterCreate(SupplierMasterUpdate):
    supplier_code: str
    supplier_name: str

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.crm import ApprovalInstancePublic
from app.schemas.identity import UserPublic


class MobileLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=128)
    device_id: str = Field(min_length=1, max_length=160)
    device_name: str | None = Field(default=None, max_length=200)
    app_version: str | None = Field(default=None, max_length=40)
    android_version: str | None = Field(default=None, max_length=40)
    device_model: str | None = Field(default=None, max_length=160)


class MobileRefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=32, max_length=512)
    device_id: str = Field(min_length=1, max_length=160)


class MobileTokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserPublic


class MobileLogoutResponse(BaseModel):
    status: str = "ok"


class MobileUserOption(BaseModel):
    id: int
    username: str
    real_name: str
    employee_code: str | None = None
    role: str
    label: str


class MobileUserOptionPage(BaseModel):
    items: list[MobileUserOption]
    total: int
    limit: int
    offset: int


class MobileCustomerOption(BaseModel):
    customer_code: str
    customer_name: str
    customer_short_name: str | None = None
    salesperson_employee_code: str | None = None
    salesperson_name: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    region: str | None = None
    customer_type: str | None = None


class MobileCustomerOptionPage(BaseModel):
    items: list[MobileCustomerOption]
    total: int
    limit: int
    offset: int


class MobileProjectSubmissionPage(BaseModel):
    items: list[ApprovalInstancePublic]
    total: int
    limit: int
    offset: int


class MobilePage(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)
    total: int = 0
    limit: int = 20
    offset: int = 0
    summary: dict[str, Any] = Field(default_factory=dict)


class MobileTelemetryEvent(BaseModel):
    event_type: Literal["crash", "api_error", "api_timing", "screen", "upload_error", "feature_usage", "form_timing"]
    occurred_at: str
    request_id: str | None = Field(default=None, max_length=120)
    route: str | None = Field(default=None, max_length=240)
    code: str | None = Field(default=None, max_length=120)
    duration_ms: int | None = Field(default=None, ge=0, le=600_000)
    app_version: str | None = Field(default=None, max_length=40)
    device_model: str | None = Field(default=None, max_length=160)
    android_version: str | None = Field(default=None, max_length=40)


class MobileTelemetryBatch(BaseModel):
    installation_id: str | None = Field(default=None, min_length=8, max_length=160)
    events: list[MobileTelemetryEvent] = Field(min_length=1, max_length=50)


class MobileNotificationProcessRequest(BaseModel):
    action: str = Field(default="handled", max_length=40)
    note: str | None = Field(default=None, max_length=500)


class MobileSyncOperation(BaseModel):
    client_operation_id: str = Field(min_length=8, max_length=160)
    device_id: str = Field(min_length=1, max_length=160)
    action_type: Literal["followup.create", "customer_profile.patch", "support.create", "crm_lead_followup_create"]
    resource_type: str | None = Field(default=None, max_length=80)
    resource_id: str | None = Field(default=None, max_length=160)
    base_updated_at: datetime | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    attachments: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    created_at: datetime | None = None


class MobileSyncOperationBatch(BaseModel):
    operations: list[MobileSyncOperation] = Field(min_length=1, max_length=50)


class MobileSyncOperationResult(BaseModel):
    client_operation_id: str
    status: Literal["applied", "conflict", "rejected", "retryable_error", "processing"]
    resource_type: str | None = None
    resource_id: str | None = None
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


class MobileDevicePublic(BaseModel):
    id: int
    device_id: str
    device_name: str | None = None
    app_version: str | None = None
    android_version: str | None = None
    device_model: str | None = None
    last_used_at: datetime | None = None
    last_sync_at: datetime | None = None
    expires_at: datetime
    revoked_at: datetime | None = None
    is_current: bool = False
    notification_preferences: dict[str, bool] = Field(default_factory=dict)


class MobileNotificationPreferencesUpdate(BaseModel):
    approval: bool = True
    task: bool = True
    risk: bool = True


class MobileFeedbackCreate(BaseModel):
    category: Literal["bug", "experience", "request", "other"]
    description: str = Field(min_length=2, max_length=2000)
    current_route: str | None = Field(default=None, max_length=240)
    request_id: str | None = Field(default=None, max_length=120)
    app_version: str | None = Field(default=None, max_length=40)
    android_version: str | None = Field(default=None, max_length=40)
    device_model: str | None = Field(default=None, max_length=160)
    screenshot_path: str | None = Field(default=None, max_length=500)


class MobileFeedbackUpdate(BaseModel):
    status: Literal["open", "processing", "resolved", "closed"]
    resolution: str | None = Field(default=None, max_length=2000)


class MobileFeedbackPublic(BaseModel):
    id: int
    user_id: int
    user_label: str | None = None
    category: str
    description: str
    current_route: str | None = None
    request_id: str | None = None
    app_version: str | None = None
    android_version: str | None = None
    device_model: str | None = None
    screenshot_path: str | None = None
    status: str
    handler_user_id: int | None = None
    handler_label: str | None = None
    resolution: str | None = None
    resolved_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class MobileFeedbackPage(BaseModel):
    items: list[MobileFeedbackPublic]
    total: int
    limit: int
    offset: int


class MobileAssistantDraftRequest(BaseModel):
    text: str | None = Field(default=None, max_length=8000)
    task_id: int | None = None
    approval_id: int | None = None
    project_id: int | None = None
    context_revision: str | None = Field(default=None, max_length=160)


class MobileAssistantDraftResponse(BaseModel):
    draft_id: str
    draft_type: Literal["followup", "approval_opinion", "project_summary"]
    fields: dict[str, Any]
    warnings: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    model: str | None = None
    generated_at: datetime


class MobileDeliveryEventRequest(BaseModel):
    expected_updated_at: datetime
    idempotency_key: str = Field(min_length=16, max_length=160)
    event_type: Literal["plan", "dispatch", "deliver", "sign", "exception", "cancel"]
    to_status: Literal["pending", "planned", "delivering", "delivered", "exception", "cancelled"]
    note: str | None = Field(default=None, max_length=2000)
    assignee_user_id: int | None = None
    signed_by: str | None = Field(default=None, max_length=120)
    signed_at: datetime | None = None

    @model_validator(mode="after")
    def validate_delivery_event(self) -> "MobileDeliveryEventRequest":
        if self.to_status == "delivered" and not self.signed_by:
            raise ValueError("signed_by is required when delivery is completed")
        if self.to_status in {"exception", "cancelled"} and not self.note:
            raise ValueError("note is required for a delivery exception or cancellation")
        return self

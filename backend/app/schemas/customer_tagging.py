from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


TagCategoryKey = Literal["classification", "product_opportunity", "purchase_characteristic", "delivery_requirement"]
TagAttributeType = Literal["long_term", "temporary"]
TagColorKey = Literal["blue", "green", "cyan", "yellow", "red", "purple", "pink", "gray"]


class CustomerTagCatalogVersionPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    version_code: str
    name: str
    status: str
    description: str | None
    activated_at: datetime | None
    retired_at: datetime | None
    created_by_user_id: int | None
    created_at: datetime
    updated_at: datetime


class CustomerTagCatalogVersionCreate(BaseModel):
    version_code: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9._-]+$")
    name: str = Field(min_length=1, max_length=160)
    description: str | None = None


class CustomerTagCatalogDefinitionCreate(BaseModel):
    stable_code: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9._-]+$")
    name: str = Field(min_length=1, max_length=30)
    color_key: TagColorKey = "blue"
    category_key: TagCategoryKey
    category_name: str = Field(min_length=1, max_length=120)
    group_code: str | None = Field(default=None, max_length=120)
    group_name: str | None = Field(default=None, max_length=160)
    sort_order: int = Field(default=0, ge=0, le=100000)
    selection_rule: Literal["single", "multi"] = "multi"
    mutual_exclusion_key: str | None = Field(default=None, max_length=120)
    attribute_types: list[TagAttributeType] = Field(default_factory=lambda: ["long_term"], min_length=1)


class CustomerTagCatalogReplacementCreate(BaseModel):
    replacement_tag_id: int


class CustomerTagCatalogPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    stable_code: str | None
    name: str
    color_key: str
    category_key: str | None
    category_name: str | None
    group_code: str | None
    group_name: str | None
    catalog_version_id: int | None
    sort_order: int
    selection_rule: str
    mutual_exclusion_key: str | None
    applicability_json: dict | None
    is_formal: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CustomerTagAssignmentPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_code: str
    tag_id: int
    tag_code: str | None = None
    tag_name: str | None = None
    category_key: str | None = None
    category_name: str | None = None
    group_code: str | None = None
    group_name: str | None = None
    color_key: str | None = None
    attribute_type: str
    source: str
    evidence: str
    effective_date: date
    review_date: date | None
    ended_at: datetime | None
    status: str
    owner_user_id: int | None
    owner_user_label: str | None = None
    is_primary: bool
    details_json: dict | None
    approved_by_user_id: int | None
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CustomerTagLegacyMappingPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_code: str
    legacy_tag_name: str
    target_tag_id: int | None
    target_tag_name: str | None = None
    confidence: Decimal | None
    rationale: str | None
    status: str
    reviewed_by_user_id: int | None
    reviewed_at: datetime | None


class CustomerTagProfilePublic(BaseModel):
    customer_code: str
    customer_name: str
    assignments: list[CustomerTagAssignmentPublic] = Field(default_factory=list)
    by_category: dict[str, list[CustomerTagAssignmentPublic]] = Field(default_factory=dict)
    legacy_tags: list[CustomerTagLegacyMappingPublic] = Field(default_factory=list)
    review_due_count: int = 0
    compatibility_tags: list[str] = Field(default_factory=list)


class CustomerTagChangeItemCreate(BaseModel):
    action: Literal["add", "update", "cancel"]
    assignment_id: int | None = None
    tag_id: int
    attribute_type: TagAttributeType = "long_term"
    source: Literal["business_input", "customer_confirmed", "management_input", "system_recommendation"] = "business_input"
    evidence: str = Field(min_length=1)
    effective_date: date = Field(default_factory=date.today)
    review_date: date | None = None
    owner_user_id: int | None = None
    is_primary: bool = False
    details_json: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_action_target(self) -> "CustomerTagChangeItemCreate":
        if self.action in {"update", "cancel"} and not self.assignment_id:
            raise ValueError("assignment_id is required for update or cancel")
        return self


class CustomerTagChangeRequestCreate(BaseModel):
    customer_code: str = Field(min_length=1, max_length=120)
    reason: str | None = None
    reviewer_user_id: int | None = None
    items: list[CustomerTagChangeItemCreate] = Field(min_length=1, max_length=50)


class CustomerTagChangeItemPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    request_id: int
    action: str
    assignment_id: int | None
    tag_id: int
    tag_code: str | None = None
    tag_name: str | None = None
    category_key: str | None = None
    group_code: str | None = None
    attribute_type: str
    source: str
    evidence: str
    effective_date: date
    review_date: date | None
    owner_user_id: int | None
    is_primary: bool
    details_json: dict | None
    before_json: dict | None
    status: str
    review_comment: str | None
    reviewed_by_user_id: int | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CustomerTagChangeRequestPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    request_no: str
    customer_code: str
    customer_name: str | None = None
    applicant_user_id: int | None
    applicant_user_label: str | None = None
    reviewer_user_id: int | None
    reviewer_user_label: str | None = None
    backup_reviewer_user_id: int | None
    approval_instance_id: int | None
    status: str
    reason: str | None
    submitted_at: datetime | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    items: list[CustomerTagChangeItemPublic] = Field(default_factory=list)


class CustomerTagReviewDecision(BaseModel):
    item_id: int
    decision: Literal["approved", "need_supplement", "rejected"]
    comment: str | None = None


class CustomerTagReviewRequest(BaseModel):
    decisions: list[CustomerTagReviewDecision] = Field(min_length=1)
    comment: str | None = None


class CustomerTagSupplementItem(BaseModel):
    item_id: int
    evidence: str = Field(min_length=1)
    review_date: date | None = None
    owner_user_id: int | None = None
    details_json: dict[str, Any] = Field(default_factory=dict)


class CustomerTagSupplementRequest(BaseModel):
    items: list[CustomerTagSupplementItem] = Field(min_length=1)
    comment: str | None = None


class CustomerTagSettingsPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    settings_key: str
    default_reviewer_user_id: int | None
    backup_reviewer_user_id: int | None
    tag_workflow_enabled: bool
    recommendation_enabled: bool
    fulfillment_enabled: bool
    review_reminder_days: int
    updated_by_user_id: int | None
    created_at: datetime
    updated_at: datetime


class CustomerTagSettingsUpdate(BaseModel):
    default_reviewer_user_id: int | None = None
    backup_reviewer_user_id: int | None = None
    tag_workflow_enabled: bool | None = None
    recommendation_enabled: bool | None = None
    fulfillment_enabled: bool | None = None
    review_reminder_days: int | None = Field(default=None, ge=0, le=90)


class CustomerTagRuleVersionCreate(BaseModel):
    rule_code: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=160)
    parameters_json: dict[str, Any]


class CustomerTagRuleVersionPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rule_code: str
    version_no: int
    name: str
    status: str
    parameters_json: dict
    activated_at: datetime | None
    created_by_user_id: int | None
    created_at: datetime
    updated_at: datetime


class CustomerTagRecommendationPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_code: str
    tag_id: int
    tag_name: str | None = None
    rule_version_id: int | None
    statistics_start: date | None
    statistics_end: date | None
    metrics_json: dict
    confidence: Decimal
    status: str
    manual_result: str | None
    manual_note: str | None
    reviewed_by_user_id: int | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CustomerTagRecommendationDecision(BaseModel):
    decision: Literal["accept", "reject"]
    manual_result: str | None = None
    manual_note: str = Field(min_length=1)
    reviewer_user_id: int | None = None


class CustomerTagLegacyReview(BaseModel):
    target_tag_id: int | None = None
    decision: Literal["submit", "reject", "unmatched"]
    evidence: str = Field(min_length=1)
    reviewer_user_id: int | None = None
    attribute_type: TagAttributeType = "long_term"
    review_date: date | None = None
    owner_user_id: int | None = None
    is_primary: bool = False
    details_json: dict[str, Any] = Field(default_factory=dict)

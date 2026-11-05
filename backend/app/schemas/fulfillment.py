from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SalesOrderLineCreate(BaseModel):
    product_code: str | None = Field(default=None, max_length=120)
    product_name: str = Field(min_length=1, max_length=255)
    quantity: Decimal = Field(gt=0)
    unit: str | None = Field(default=None, max_length=80)
    remark: str | None = None


class TemporaryOrderRequirement(BaseModel):
    tag_id: int | None = None
    tag_name: str = Field(min_length=1, max_length=120)
    group_code: str | None = Field(default=None, max_length=120)
    details: dict[str, Any] = Field(default_factory=dict)


class SalesOrderCreate(BaseModel):
    external_order_no: str | None = Field(default=None, max_length=160)
    customer_code: str = Field(min_length=1, max_length=120)
    planned_delivery_at: datetime | None = None
    delivery_address: str | None = None
    temporary_requirements: list[TemporaryOrderRequirement] = Field(default_factory=list, max_length=30)
    lines: list[SalesOrderLineCreate] = Field(min_length=1, max_length=500)


class SalesOrderUpdate(BaseModel):
    planned_delivery_at: datetime | None = None
    delivery_address: str | None = None
    temporary_requirements: list[TemporaryOrderRequirement] | None = Field(default=None, max_length=30)
    lines: list[SalesOrderLineCreate] | None = Field(default=None, min_length=1, max_length=500)


class SalesOrderCancel(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class SalesOrderLinePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: int
    line_no: int
    product_code: str | None
    product_name: str
    quantity: Decimal
    unit: str | None
    remark: str | None


class OrderRequirementSnapshotPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: int
    snapshot_version: int
    tag_id: int | None
    tag_code: str | None
    tag_name: str
    group_code: str | None
    source_type: str
    requirement_json: dict | None
    source_assignment_id: int | None
    created_at: datetime


class SalesOrderPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_no: str
    external_order_no: str | None
    customer_code: str
    customer_name_snapshot: str
    source: str
    status: str
    planned_delivery_at: datetime | None
    delivery_address: str | None
    temporary_requirements_json: list | None
    requirement_snapshot_version: int
    confirmed_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    created_by_user_id: int | None
    updated_by_user_id: int | None
    created_at: datetime
    updated_at: datetime
    lines: list[SalesOrderLinePublic] = Field(default_factory=list)
    requirements: list[OrderRequirementSnapshotPublic] = Field(default_factory=list)
    delivery_id: int | None = None
    requirement_diff: dict[str, list[dict[str, Any]]] | None = None


class DeliveryEventCreate(BaseModel):
    event_type: Literal["plan", "dispatch", "deliver", "sign", "exception", "cancel"]
    to_status: Literal["pending", "planned", "delivering", "delivered", "exception", "cancelled"]
    note: str | None = None
    payload_json: dict[str, Any] = Field(default_factory=dict)
    assignee_user_id: int | None = None
    signed_by: str | None = Field(default=None, max_length=120)
    signed_at: datetime | None = None

    @model_validator(mode="after")
    def validate_signing(self) -> "DeliveryEventCreate":
        if self.to_status == "delivered" and not self.signed_by:
            raise ValueError("signed_by is required when delivery is completed")
        if self.to_status == "exception" and not self.note:
            raise ValueError("note is required for a delivery exception")
        return self


class DeliveryEventPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    delivery_id: int
    event_type: str
    from_status: str | None
    to_status: str | None
    note: str | None
    payload_json: dict | None
    operator_user_id: int | None
    created_at: datetime


class DeliveryAttachmentPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    delivery_id: int
    file_name: str
    content_type: str | None
    size_bytes: int | None
    created_by_user_id: int | None
    created_at: datetime


class DeliveryTaskPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    delivery_no: str
    order_id: int
    order_no: str | None = None
    customer_code: str | None = None
    customer_name: str | None = None
    status: str
    planned_at: datetime | None
    delivery_address: str | None
    requirements_json: list | None
    assignee_user_id: int | None
    signed_by: str | None
    signed_at: datetime | None
    exception_note: str | None
    created_by_user_id: int | None
    created_at: datetime
    updated_at: datetime
    events: list[DeliveryEventPublic] = Field(default_factory=list)
    attachments: list[DeliveryAttachmentPublic] = Field(default_factory=list)


class SalesOrderImportResult(BaseModel):
    imported_orders: int
    imported_lines: int
    errors: list[dict[str, Any]] = Field(default_factory=list)

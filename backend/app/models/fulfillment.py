from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.identity import TimestampMixin


class SalesOrder(Base, TimestampMixin):
    __tablename__ = "sales_order"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_no: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    external_order_no: Mapped[str | None] = mapped_column(String(160), unique=True, index=True)
    customer_code: Mapped[str] = mapped_column(ForeignKey("customer_master.customer_code", ondelete="RESTRICT"), nullable=False, index=True)
    customer_name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str] = mapped_column(String(40), default="web", nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), default="draft", nullable=False, index=True)
    planned_delivery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    delivery_address: Mapped[str | None] = mapped_column(Text)
    temporary_requirements_json: Mapped[list | None] = mapped_column(JSONB)
    requirement_snapshot_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)


class SalesOrderLine(Base, TimestampMixin):
    __tablename__ = "sales_order_line"
    __table_args__ = (UniqueConstraint("order_id", "line_no", name="uq_sales_order_line_no"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("sales_order.id", ondelete="CASCADE"), nullable=False, index=True)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    product_code: Mapped[str | None] = mapped_column(ForeignKey("product_master.product_code", ondelete="SET NULL"), index=True)
    product_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(80))
    remark: Mapped[str | None] = mapped_column(Text)


class SalesOrderRequirementSnapshot(Base):
    __tablename__ = "sales_order_requirement_snapshot"
    __table_args__ = (UniqueConstraint("order_id", "snapshot_version", "tag_id", "source_type", name="uq_order_requirement_snapshot"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("sales_order.id", ondelete="CASCADE"), nullable=False, index=True)
    snapshot_version: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    tag_id: Mapped[int | None] = mapped_column(ForeignKey("customer_tag.id", ondelete="SET NULL"), index=True)
    tag_code: Mapped[str | None] = mapped_column(String(160), index=True)
    tag_name: Mapped[str] = mapped_column(String(120), nullable=False)
    group_code: Mapped[str | None] = mapped_column(String(120), index=True)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    requirement_json: Mapped[dict | None] = mapped_column(JSONB)
    source_assignment_id: Mapped[int | None] = mapped_column(ForeignKey("customer_tag_assignment.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


class DeliveryTask(Base, TimestampMixin):
    __tablename__ = "delivery_task"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    delivery_no: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("sales_order.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), default="pending", nullable=False, index=True)
    planned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    delivery_address: Mapped[str | None] = mapped_column(Text)
    requirements_json: Mapped[list | None] = mapped_column(JSONB)
    assignee_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    signed_by: Mapped[str | None] = mapped_column(String(120))
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    exception_note: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)


class DeliveryEvent(Base):
    __tablename__ = "delivery_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    delivery_id: Mapped[int] = mapped_column(ForeignKey("delivery_task.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    from_status: Mapped[str | None] = mapped_column(String(40))
    to_status: Mapped[str | None] = mapped_column(String(40), index=True)
    note: Mapped[str | None] = mapped_column(Text)
    payload_json: Mapped[dict | None] = mapped_column(JSONB)
    operator_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


class DeliveryAttachment(Base):
    __tablename__ = "delivery_attachment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    delivery_id: Mapped[int] = mapped_column(ForeignKey("delivery_task.id", ondelete="CASCADE"), nullable=False, index=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(120))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.identity import TimestampMixin


class CustomerTagCatalogVersion(Base, TimestampMixin):
    __tablename__ = "customer_tag_catalog_version"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="draft", nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)


class CustomerTagGovernanceSettings(Base, TimestampMixin):
    __tablename__ = "customer_tag_governance_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    settings_key: Mapped[str] = mapped_column(String(40), unique=True, default="default", nullable=False)
    default_reviewer_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    backup_reviewer_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    tag_workflow_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    recommendation_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    fulfillment_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    review_reminder_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)


class CustomerTagAssignment(Base, TimestampMixin):
    __tablename__ = "customer_tag_assignment"
    __table_args__ = (
        UniqueConstraint("customer_code", "tag_id", "effective_date", "status", name="uq_customer_tag_assignment_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_code: Mapped[str] = mapped_column(ForeignKey("customer_master.customer_code", ondelete="CASCADE"), nullable=False, index=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("customer_tag.id", ondelete="RESTRICT"), nullable=False, index=True)
    attribute_type: Mapped[str] = mapped_column(String(40), default="long_term", nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(80), default="business_input", nullable=False, index=True)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    review_date: Mapped[date | None] = mapped_column(Date, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(40), default="effective", nullable=False, index=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    details_json: Mapped[dict | None] = mapped_column(JSONB)
    source_request_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("customer_tag_change_item.id", ondelete="SET NULL"), index=True
    )
    approved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class CustomerTagChangeRequest(Base, TimestampMixin):
    __tablename__ = "customer_tag_change_request"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_no: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    customer_code: Mapped[str] = mapped_column(ForeignKey("customer_master.customer_code", ondelete="CASCADE"), nullable=False, index=True)
    applicant_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    reviewer_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    backup_reviewer_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    approval_instance_id: Mapped[int | None] = mapped_column(ForeignKey("approval_instance.id", ondelete="SET NULL"), index=True)
    status: Mapped[str] = mapped_column(String(40), default="submitted", nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class CustomerTagChangeItem(Base, TimestampMixin):
    __tablename__ = "customer_tag_change_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("customer_tag_change_request.id", ondelete="CASCADE"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    assignment_id: Mapped[int | None] = mapped_column(ForeignKey("customer_tag_assignment.id", ondelete="SET NULL"), index=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("customer_tag.id", ondelete="RESTRICT"), nullable=False, index=True)
    attribute_type: Mapped[str] = mapped_column(String(40), default="long_term", nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(80), default="business_input", nullable=False, index=True)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    review_date: Mapped[date | None] = mapped_column(Date)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    details_json: Mapped[dict | None] = mapped_column(JSONB)
    before_json: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(40), default="pending", nullable=False, index=True)
    review_comment: Mapped[str | None] = mapped_column(Text)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class CustomerTagRuleVersion(Base, TimestampMixin):
    __tablename__ = "customer_tag_rule_version"
    __table_args__ = (UniqueConstraint("rule_code", "version_no", name="uq_customer_tag_rule_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_code: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="draft", nullable=False, index=True)
    parameters_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)


class CustomerTagRecommendation(Base, TimestampMixin):
    __tablename__ = "customer_tag_recommendation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_code: Mapped[str] = mapped_column(ForeignKey("customer_master.customer_code", ondelete="CASCADE"), nullable=False, index=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("customer_tag.id", ondelete="CASCADE"), nullable=False, index=True)
    rule_version_id: Mapped[int | None] = mapped_column(ForeignKey("customer_tag_rule_version.id", ondelete="SET NULL"), index=True)
    statistics_start: Mapped[date | None] = mapped_column(Date, index=True)
    statistics_end: Mapped[date | None] = mapped_column(Date, index=True)
    metrics_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="pending", nullable=False, index=True)
    manual_result: Mapped[str | None] = mapped_column(String(120))
    manual_note: Mapped[str | None] = mapped_column(Text)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class CustomerTagLegacyMapping(Base, TimestampMixin):
    __tablename__ = "customer_tag_legacy_mapping"
    __table_args__ = (UniqueConstraint("customer_code", "legacy_tag_name", name="uq_customer_tag_legacy_mapping"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_code: Mapped[str] = mapped_column(ForeignKey("customer_master.customer_code", ondelete="CASCADE"), nullable=False, index=True)
    legacy_tag_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    target_tag_id: Mapped[int | None] = mapped_column(ForeignKey("customer_tag.id", ondelete="SET NULL"), index=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    rationale: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="pending", nullable=False, index=True)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

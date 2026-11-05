from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.identity import TimestampMixin


class InventoryAnomalyCase(Base, TimestampMixin):
    __tablename__ = "inventory_anomaly_case"
    __table_args__ = (UniqueConstraint("fingerprint", name="uq_inventory_anomaly_case_fingerprint"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_no: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    fingerprint: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("inventory_snapshot.id", ondelete="SET NULL"), index=True
    )
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batch.id", ondelete="SET NULL"), index=True)
    data_date: Mapped[date | None] = mapped_column(Date, index=True)
    product_code: Mapped[str | None] = mapped_column(String(120), index=True)
    product_name: Mapped[str | None] = mapped_column(String(255), index=True)
    warehouse_name: Mapped[str | None] = mapped_column(String(160), index=True)
    warehouse_scope: Mapped[str | None] = mapped_column(String(40), index=True)
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(40), default="high", nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), default="open", nullable=False, index=True)
    stock_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    locked_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    evidence_version: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    root_cause: Mapped[str | None] = mapped_column(String(80), index=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    diagnosis_json: Mapped[dict | None] = mapped_column(JSONB)
    recommended_action: Mapped[str | None] = mapped_column(String(80), index=True)
    expected_result: Mapped[str | None] = mapped_column(Text)
    resolution_note: Mapped[str | None] = mapped_column(Text)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    diagnosed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class InventoryRemediationAction(Base, TimestampMixin):
    __tablename__ = "inventory_remediation_action"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    action_no: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    case_id: Mapped[int] = mapped_column(
        ForeignKey("inventory_anomaly_case.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requested_by_key_id: Mapped[str | None] = mapped_column(
        ForeignKey("external_api_keys.key_id", ondelete="SET NULL"), index=True
    )
    action_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), default="validated", nullable=False, index=True)
    allowed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    blockers_json: Mapped[list | None] = mapped_column(JSONB)
    parameters_json: Mapped[dict | None] = mapped_column(JSONB)
    impact_json: Mapped[dict | None] = mapped_column(JSONB)
    evidence_version: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    validation_token_hash: Mapped[str | None] = mapped_column(String(128), unique=True, index=True)
    validation_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(160), unique=True, index=True)
    before_data: Mapped[dict | None] = mapped_column(JSONB)
    result_json: Mapped[dict | None] = mapped_column(JSONB)
    verification_json: Mapped[dict | None] = mapped_column(JSONB)
    compensation_json: Mapped[dict | None] = mapped_column(JSONB)
    upstream_reference: Mapped[str | None] = mapped_column(String(255), index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB as PostgreSQLJSONB

JSONB = JSON().with_variant(PostgreSQLJSONB(), 'postgresql')
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

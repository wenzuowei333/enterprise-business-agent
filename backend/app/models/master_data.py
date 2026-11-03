from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB as PostgreSQLJSONB

JSONB = JSON().with_variant(PostgreSQLJSONB(), 'postgresql')
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base
from app.models.identity import TimestampMixin


class ImportBatch(Base, TimestampMixin):
    __tablename__ = "import_batch"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_no: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    data_date: Mapped[date | None] = mapped_column(Date)
    export_date: Mapped[date | None] = mapped_column(Date)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="uploaded", nullable=False, index=True)
    total_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    success_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    amount_total: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    raw_file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    content_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    header_json: Mapped[list | None] = mapped_column(JSONB)
    preview_json: Mapped[list | None] = mapped_column(JSONB)
    mapping_json: Mapped[dict | None] = mapped_column(JSONB)


class InventorySnapshot(Base):
    __tablename__ = "inventory_snapshot"
    __table_args__ = (UniqueConstraint("batch_id", "row_number", name="uq_inventory_snapshot_batch_row"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("import_batch.id", ondelete="CASCADE"), nullable=False, index=True)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    data_date: Mapped[date | None] = mapped_column(Date, index=True)
    product_code: Mapped[str | None] = mapped_column(String(120), index=True)
    product_name: Mapped[str | None] = mapped_column(String(255), index=True)
    warehouse_name: Mapped[str | None] = mapped_column(String(160), index=True)
    warehouse_scope: Mapped[str] = mapped_column(String(40), default="unknown", nullable=False, index=True)
    barcode: Mapped[str | None] = mapped_column(String(160), index=True)
    default_supplier: Mapped[str | None] = mapped_column(String(255), index=True)
    unit_relation: Mapped[str | None] = mapped_column(String(255))
    stock_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    stock_base_unit: Mapped[str | None] = mapped_column(String(80))
    stock_inventory_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    stock_inventory_unit: Mapped[str | None] = mapped_column(String(80))
    locked_base_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    inventory_status: Mapped[str | None] = mapped_column(String(80), index=True)
    float_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    float_unit: Mapped[str | None] = mapped_column(String(80))
    average_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    cost_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    auxiliary_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    raw_row_json: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
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


class ImportError(Base):
    __tablename__ = "import_error"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("import_batch.id", ondelete="CASCADE"), nullable=False, index=True)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    error_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    raw_row_json: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class MasterLinkIssue(Base, TimestampMixin):
    __tablename__ = "master_link_issue"
    __table_args__ = (
        UniqueConstraint(
            "batch_id",
            "source_file_type",
            "issue_type",
            "reference_code",
            "reference_name",
            name="uq_master_link_issue_batch_reference",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batch.id", ondelete="CASCADE"), index=True)
    source_file_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    issue_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    expected_master_kind: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    reference_code: Mapped[str | None] = mapped_column(String(120), index=True)
    reference_name: Mapped[str | None] = mapped_column(String(255), index=True)
    counterpart_master_kind: Mapped[str | None] = mapped_column(String(40), index=True)
    counterpart_code: Mapped[str | None] = mapped_column(String(120), index=True)
    counterpart_name: Mapped[str | None] = mapped_column(String(255))
    first_seen_date: Mapped[date | None] = mapped_column(Date, index=True)
    last_seen_date: Mapped[date | None] = mapped_column(Date, index=True)
    affected_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    affected_documents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    amount_total: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    quantity_total: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    status: Mapped[str] = mapped_column(String(40), default="open", nullable=False, index=True)
    resolution_type: Mapped[str | None] = mapped_column(String(80), index=True)
    resolved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_note: Mapped[str | None] = mapped_column(Text)
    source_json: Mapped[dict | None] = mapped_column(JSONB)


class DataCalendarRule(Base, TimestampMixin):
    __tablename__ = "data_calendar_rule"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_code: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    file_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    action_layer: Mapped[str] = mapped_column(String(40), nullable=False, default="blue", index=True)
    frequency: Mapped[str] = mapped_column(String(40), nullable=False, default="daily", index=True)
    deadline_hour: Mapped[int | None] = mapped_column(Integer)
    owner_role: Mapped[str] = mapped_column(String(120), nullable=False, default="数据中台")
    owner_user_ids: Mapped[list | None] = mapped_column(JSONB)
    is_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    remark: Mapped[str | None] = mapped_column(Text)


class MasterCategoryNode(Base, TimestampMixin):
    __tablename__ = "master_category_node"
    __table_args__ = (
        UniqueConstraint("node_code", name="uq_master_category_node_code"),
        UniqueConstraint("kind", "parent_id", "label", name="uq_master_category_node_kind_parent_label"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    node_code: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("master_category_node.id", ondelete="CASCADE"), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False, index=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    remark: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)


class MasterCategoryBinding(Base, TimestampMixin):
    __tablename__ = "master_category_binding"
    __table_args__ = (
        UniqueConstraint("category_id", "resource_type", "resource_code", name="uq_master_category_binding_category_resource"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("master_category_node.id", ondelete="CASCADE"), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    resource_code: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False, index=True)
    source: Mapped[str | None] = mapped_column(String(120), index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)


class CustomerTag(Base, TimestampMixin):
    __tablename__ = "customer_tag"
    __table_args__ = (
        CheckConstraint(
            "color_key IN ('blue', 'green', 'cyan', 'yellow', 'red', 'purple', 'pink', 'gray')",
            name="ck_customer_tag_color_key",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    normalized_name: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    color_key: Mapped[str] = mapped_column(String(20), default="blue", nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    stable_code: Mapped[str | None] = mapped_column(String(160), unique=True, index=True)
    category_key: Mapped[str | None] = mapped_column(String(80), index=True)
    category_name: Mapped[str | None] = mapped_column(String(120))
    group_code: Mapped[str | None] = mapped_column(String(120), index=True)
    group_name: Mapped[str | None] = mapped_column(String(160))
    catalog_version_id: Mapped[int | None] = mapped_column(ForeignKey("customer_tag_catalog_version.id", ondelete="SET NULL"), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False, index=True)
    selection_rule: Mapped[str] = mapped_column(String(40), default="multi", nullable=False)
    mutual_exclusion_key: Mapped[str | None] = mapped_column(String(120), index=True)
    applicability_json: Mapped[dict | None] = mapped_column(JSONB)
    is_formal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    replaced_by_tag_id: Mapped[int | None] = mapped_column(ForeignKey("customer_tag.id", ondelete="SET NULL"), index=True)


class CustomerMaster(Base, TimestampMixin):
    __tablename__ = "customer_master"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_code: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    customer_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    customer_short_name: Mapped[str | None] = mapped_column(String(255))
    customer_type: Mapped[str | None] = mapped_column(String(120), index=True)
    region: Mapped[str | None] = mapped_column(String(120), index=True)
    salesperson_employee_code: Mapped[str | None] = mapped_column(String(80), index=True)
    salesperson_name: Mapped[str | None] = mapped_column(String(120), index=True)
    contact_name: Mapped[str | None] = mapped_column(String(120))
    contact_phone: Mapped[str | None] = mapped_column(String(120))
    contact_channel: Mapped[str | None] = mapped_column(String(255))
    customer_group_name: Mapped[str | None] = mapped_column(String(255), index=True)
    customer_tags: Mapped[list | None] = mapped_column(JSONB)
    address: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="active", nullable=False, index=True)
    source: Mapped[str | None] = mapped_column(String(120))
    profile_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    base_remark: Mapped[str | None] = mapped_column(Text)


class CustomerBusinessProfile(Base, TimestampMixin):
    __tablename__ = "customer_business_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_code: Mapped[str] = mapped_column(
        ForeignKey("customer_master.customer_code", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    customer_name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    business_customer_type: Mapped[str | None] = mapped_column(String(120), index=True)
    confirmed_at: Mapped[date | None] = mapped_column(Date, index=True)
    filled_by: Mapped[str | None] = mapped_column(String(120), index=True)
    update_source: Mapped[str | None] = mapped_column(String(80), index=True)
    update_type: Mapped[str | None] = mapped_column(String(80), index=True)
    current_salesperson: Mapped[str | None] = mapped_column(String(120), index=True)
    sales_channels: Mapped[list | None] = mapped_column(JSONB)
    business_status_tags: Mapped[list | None] = mapped_column(JSONB)
    business_status_label: Mapped[str | None] = mapped_column(String(160), index=True)
    business_status_note: Mapped[str | None] = mapped_column(Text)
    other_status_label: Mapped[str | None] = mapped_column(String(160), index=True)
    other_status_note: Mapped[str | None] = mapped_column(Text)
    latest_update_note: Mapped[str | None] = mapped_column(Text)
    version_no: Mapped[int] = mapped_column(Integer, default=1, nullable=False, index=True)
    confirmed_by: Mapped[str | None] = mapped_column(String(120), index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)


class CustomerBusinessProduct(Base, TimestampMixin):
    __tablename__ = "customer_business_product"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_code: Mapped[str] = mapped_column(
        ForeignKey("customer_master.customer_code", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_category: Mapped[str | None] = mapped_column(String(160), index=True)
    spec: Mapped[str | None] = mapped_column(String(255))
    common_brand: Mapped[str | None] = mapped_column(String(160), index=True)
    monthly_usage: Mapped[str | None] = mapped_column(String(120))
    price_sensitivity: Mapped[str | None] = mapped_column(String(40), index=True)
    cooperation_status: Mapped[str | None] = mapped_column(String(40), index=True)
    change_type: Mapped[str | None] = mapped_column(String(40), index=True)
    opportunity_note: Mapped[str | None] = mapped_column(Text)
    last_confirmed_at: Mapped[date | None] = mapped_column(Date, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)


class CustomerBusinessProfileHistory(Base):
    __tablename__ = "customer_business_profile_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_code: Mapped[str] = mapped_column(
        ForeignKey("customer_master.customer_code", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    update_source: Mapped[str | None] = mapped_column(String(80), index=True)
    update_type: Mapped[str | None] = mapped_column(String(80), index=True)
    filled_by: Mapped[str | None] = mapped_column(String(120), index=True)
    update_note: Mapped[str | None] = mapped_column(Text)
    confirmed_by: Mapped[str | None] = mapped_column(String(120), index=True)
    snapshot_json: Mapped[dict | None] = mapped_column(JSONB)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


class CustomerAlias(Base):
    __tablename__ = "customer_alias"
    __table_args__ = (UniqueConstraint("customer_id", "alias_name", name="uq_customer_alias_customer_alias"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customer_master.id", ondelete="CASCADE"), nullable=False, index=True)
    alias_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CustomerPortraitRuleVersion(Base):
    __tablename__ = "customer_portrait_rule_version"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_code: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    version_name: Mapped[str] = mapped_column(String(160), nullable=False)
    rule_json: Mapped[dict | None] = mapped_column(JSONB)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CustomerPortraitTask(Base):
    __tablename__ = "customer_portrait_task"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_no: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    task_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), default="pending", nullable=False, index=True)
    customer_code: Mapped[str | None] = mapped_column(String(120), index=True)
    total_customers: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_json: Mapped[dict | list | None] = mapped_column(JSONB)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CustomerPortraitSnapshot(Base, TimestampMixin):
    __tablename__ = "customer_portrait_snapshot"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_code: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    customer_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    data_cutoff_date: Mapped[date | None] = mapped_column(Date, index=True)
    rule_version: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), default="generated", nullable=False, index=True)
    task_no: Mapped[str | None] = mapped_column(String(120), index=True)
    summary_json: Mapped[dict | None] = mapped_column(JSONB)
    tag_json: Mapped[list | None] = mapped_column(JSONB)
    payment_json: Mapped[dict | None] = mapped_column(JSONB)
    profile_json: Mapped[dict | None] = mapped_column(JSONB)
    quality_json: Mapped[dict | None] = mapped_column(JSONB)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


class ProductMaster(Base, TimestampMixin):
    __tablename__ = "product_master"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_code: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    product_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    spec: Mapped[str | None] = mapped_column(String(255))
    unit: Mapped[str | None] = mapped_column(String(80))
    category: Mapped[str | None] = mapped_column(String(160), index=True)
    brand: Mapped[str | None] = mapped_column(String(160), index=True)
    barcode: Mapped[str | None] = mapped_column(String(160), index=True)
    reference_sale_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    reference_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    status: Mapped[str] = mapped_column(String(40), default="active", nullable=False, index=True)
    source: Mapped[str | None] = mapped_column(String(120))


class ProductAlias(Base):
    __tablename__ = "product_alias"
    __table_args__ = (UniqueConstraint("product_id", "alias_name", name="uq_product_alias_product_alias"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("product_master.id", ondelete="CASCADE"), nullable=False, index=True)
    alias_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SupplierMaster(Base, TimestampMixin):
    __tablename__ = "supplier_master"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    supplier_code: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    supplier_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    supplier_short_name: Mapped[str | None] = mapped_column(String(255))
    supplier_type: Mapped[str | None] = mapped_column(String(120), index=True)
    region: Mapped[str | None] = mapped_column(String(120), index=True)
    contact_name: Mapped[str | None] = mapped_column(String(120))
    contact_phone: Mapped[str | None] = mapped_column(String(120))
    address: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="active", nullable=False, index=True)
    source: Mapped[str | None] = mapped_column(String(120))


class SupplierAlias(Base):
    __tablename__ = "supplier_alias"
    __table_args__ = (UniqueConstraint("supplier_id", "alias_name", name="uq_supplier_alias_supplier_alias"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("supplier_master.id", ondelete="CASCADE"), nullable=False, index=True)
    alias_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SalesDetail(Base):
    __tablename__ = "sales_detail"
    __table_args__ = (UniqueConstraint("batch_id", "row_number", name="uq_sales_detail_batch_row"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("import_batch.id", ondelete="CASCADE"), nullable=False, index=True)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    data_date: Mapped[date | None] = mapped_column(Date, index=True)
    document_no: Mapped[str | None] = mapped_column(String(160), index=True)
    document_date: Mapped[date | None] = mapped_column(Date, index=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    document_type: Mapped[str | None] = mapped_column(String(120), index=True)
    branch_name: Mapped[str | None] = mapped_column(String(160))
    department_name: Mapped[str | None] = mapped_column(String(160))
    settlement_unit_code: Mapped[str | None] = mapped_column(String(120), index=True)
    settlement_unit_name: Mapped[str | None] = mapped_column(String(255), index=True)
    customer_code: Mapped[str | None] = mapped_column(String(120), index=True)
    customer_name: Mapped[str | None] = mapped_column(String(255), index=True)
    employee_name: Mapped[str | None] = mapped_column(String(120), index=True)
    warehouse_name: Mapped[str | None] = mapped_column(String(160), index=True)
    product_code: Mapped[str | None] = mapped_column(String(120), index=True)
    product_name: Mapped[str | None] = mapped_column(String(255), index=True)
    sale_qty_base: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    sale_qty_unit: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    sale_qty_float: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    amount_before_discount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    unit_price_after_discount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    amount_after_discount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    amount_tax_total: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    tax_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    cost_unit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    cost_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    expense_allocated_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    gross_profit: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    gross_margin_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    prepared_by: Mapped[str | None] = mapped_column(String(120))
    note: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    reconciliation_mark: Mapped[str | None] = mapped_column(String(80))
    raw_row_json: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PurchaseDetail(Base):
    __tablename__ = "purchase_detail"
    __table_args__ = (UniqueConstraint("batch_id", "row_number", name="uq_purchase_detail_batch_row"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("import_batch.id", ondelete="CASCADE"), nullable=False, index=True)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    data_date: Mapped[date | None] = mapped_column(Date, index=True)
    document_no: Mapped[str | None] = mapped_column(String(160), index=True)
    document_date: Mapped[date | None] = mapped_column(Date, index=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    document_type: Mapped[str | None] = mapped_column(String(120), index=True)
    branch_name: Mapped[str | None] = mapped_column(String(160))
    department_name: Mapped[str | None] = mapped_column(String(160))
    settlement_unit_code: Mapped[str | None] = mapped_column(String(120), index=True)
    settlement_unit_name: Mapped[str | None] = mapped_column(String(255), index=True)
    supplier_code: Mapped[str | None] = mapped_column(String(120), index=True)
    supplier_name: Mapped[str | None] = mapped_column(String(255), index=True)
    employee_name: Mapped[str | None] = mapped_column(String(120), index=True)
    warehouse_name: Mapped[str | None] = mapped_column(String(160), index=True)
    product_code: Mapped[str | None] = mapped_column(String(120), index=True)
    product_name: Mapped[str | None] = mapped_column(String(255), index=True)
    purchase_qty_base: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    purchase_qty_unit: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    purchase_qty_float: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    amount_after_discount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    amount_tax_total: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    tax_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    tax_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    purchase_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    discount_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    prepared_note: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    remark: Mapped[str | None] = mapped_column(Text)
    reconciliation_mark: Mapped[str | None] = mapped_column(String(80))
    raw_row_json: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


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


class InventoryFlowLedger(Base):
    __tablename__ = "inventory_flow_ledger"
    __table_args__ = (
        UniqueConstraint("data_date", "warehouse_name", "warehouse_scope", "product_code", name="uq_inventory_flow_day_wh_product"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    data_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    warehouse_name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    warehouse_scope: Mapped[str] = mapped_column(String(40), default="specific", nullable=False, index=True)
    product_code: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    product_name: Mapped[str | None] = mapped_column(String(255), index=True)
    opening_stock_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    purchase_qty: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    sales_qty: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    calculated_closing_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    snapshot_stock_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    diff_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    anomaly_type: Mapped[str] = mapped_column(String(80), default="normal", nullable=False, index=True)
    anomaly_flags: Mapped[list | None] = mapped_column(JSONB)
    source_batch_ids: Mapped[list | None] = mapped_column(JSONB)
    source_counts: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class InventoryCheckBatch(Base, TimestampMixin):
    __tablename__ = "inventory_check_batch"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_no: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    data_date: Mapped[date | None] = mapped_column(Date, index=True)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    status: Mapped[str] = mapped_column(String(40), default="completed", nullable=False, index=True)
    total_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    matched_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    difference_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    missing_in_system_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    missing_in_upload_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    invalid_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicate_upload_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    raw_file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    header_json: Mapped[list | None] = mapped_column(JSONB)
    mapping_json: Mapped[dict | None] = mapped_column(JSONB)


class InventoryCheckRow(Base):
    __tablename__ = "inventory_check_row"
    __table_args__ = (UniqueConstraint("batch_id", "row_number", name="uq_inventory_check_row_batch_row"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("inventory_check_batch.id", ondelete="CASCADE"), nullable=False, index=True)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    product_code: Mapped[str | None] = mapped_column(String(120), index=True)
    product_name: Mapped[str | None] = mapped_column(String(255), index=True)
    warehouse_name: Mapped[str | None] = mapped_column(String(160), index=True)
    platform_stock_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    row_status: Mapped[str] = mapped_column(String(40), default="valid", nullable=False, index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    raw_row_json: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class InventoryCheckResult(Base):
    __tablename__ = "inventory_check_result"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("inventory_check_batch.id", ondelete="CASCADE"), nullable=False, index=True)
    result_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    product_code: Mapped[str | None] = mapped_column(String(120), index=True)
    product_name: Mapped[str | None] = mapped_column(String(255), index=True)
    warehouse_name: Mapped[str | None] = mapped_column(String(160), index=True)
    warehouse_scope: Mapped[str | None] = mapped_column(String(40), index=True)
    platform_stock_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    system_stock_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    diff_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    system_data_date: Mapped[date | None] = mapped_column(Date, index=True)
    duplicate_in_upload: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    source_row_numbers: Mapped[list | None] = mapped_column(JSONB)
    platform_row_json: Mapped[dict | None] = mapped_column(JSONB)
    system_snapshot_json: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AccountBalanceSnapshot(Base):
    __tablename__ = "account_balance_snapshot"
    __table_args__ = (UniqueConstraint("batch_id", "row_number", name="uq_account_balance_snapshot_batch_row"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("import_batch.id", ondelete="CASCADE"), nullable=False, index=True)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    data_date: Mapped[date | None] = mapped_column(Date, index=True)
    period_start: Mapped[date | None] = mapped_column(Date, index=True)
    period_end: Mapped[date | None] = mapped_column(Date, index=True)
    balance_date: Mapped[date | None] = mapped_column(Date, index=True)
    settlement_unit_code: Mapped[str | None] = mapped_column(String(120), index=True)
    settlement_unit_name: Mapped[str | None] = mapped_column(String(255), index=True)
    current_opening_balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    current_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    current_closing_balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    ar_opening_balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    ar_current_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    ar_balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    ap_opening_balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    ap_current_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    ap_balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    advance_receipt_opening_balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    advance_receipt_current_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    advance_receipt_balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    advance_payment_opening_balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    advance_payment_current_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    advance_payment_balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    raw_row_json: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AccountLedgerEntry(Base):
    __tablename__ = "account_ledger_entry"
    __table_args__ = (UniqueConstraint("batch_id", "row_number", name="uq_account_ledger_entry_batch_row"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("import_batch.id", ondelete="CASCADE"), nullable=False, index=True)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    data_date: Mapped[date | None] = mapped_column(Date, index=True)
    settlement_unit_code: Mapped[str | None] = mapped_column(String(120), index=True)
    settlement_unit_name: Mapped[str | None] = mapped_column(String(255), index=True)
    document_type: Mapped[str | None] = mapped_column(String(120), index=True)
    document_date: Mapped[date | None] = mapped_column(Date, index=True)
    document_no: Mapped[str | None] = mapped_column(String(160), index=True)
    handler_name: Mapped[str | None] = mapped_column(String(120), index=True)
    counterparty_name: Mapped[str | None] = mapped_column(String(255), index=True)
    amount_before_discount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    document_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    discount_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    received_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    ar_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    paid_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    ap_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    advance_receipt_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    advance_payment_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    current_balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    uninvoiced_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    uninvoiced_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    invoice_participation: Mapped[str | None] = mapped_column(String(80))
    summary: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    reconciliation_date: Mapped[date | None] = mapped_column(Date, index=True)
    reconciliation_mark: Mapped[str | None] = mapped_column(String(120), index=True)
    row_role: Mapped[str] = mapped_column(String(40), default="transaction", nullable=False, index=True)
    period_start: Mapped[date | None] = mapped_column(Date, index=True)
    period_end: Mapped[date | None] = mapped_column(Date, index=True)
    balance_date: Mapped[date | None] = mapped_column(Date, index=True)
    raw_row_json: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ReceivableSnapshot(Base):
    __tablename__ = "receivable_snapshot"
    __table_args__ = (UniqueConstraint("batch_id", "row_number", name="uq_receivable_snapshot_batch_row"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("import_batch.id", ondelete="CASCADE"), nullable=False, index=True)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    data_date: Mapped[date | None] = mapped_column(Date, index=True)
    customer_code: Mapped[str | None] = mapped_column(String(120), index=True)
    customer_name: Mapped[str | None] = mapped_column(String(255), index=True)
    matched_customer_code: Mapped[str | None] = mapped_column(String(120), index=True)
    matched_customer_name: Mapped[str | None] = mapped_column(String(255), index=True)
    match_status: Mapped[str] = mapped_column(String(60), default="pending", nullable=False, index=True)
    ar_opening_balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    ar_current_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    received_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    unreceived_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    ar_balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), index=True)
    aging_label: Mapped[str | None] = mapped_column(String(120), index=True)
    overdue_days: Mapped[int | None] = mapped_column(Integer, index=True)
    salesperson_name: Mapped[str | None] = mapped_column(String(120), index=True)
    department_name: Mapped[str | None] = mapped_column(String(160), index=True)
    remark: Mapped[str | None] = mapped_column(Text)
    raw_row_json: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ReceivableCheckResult(Base):
    __tablename__ = "receivable_check_result"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("import_batch.id", ondelete="CASCADE"), nullable=False, index=True)
    receivable_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("receivable_snapshot.id", ondelete="CASCADE"), index=True)
    result_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(40), default="warning", nullable=False, index=True)
    data_date: Mapped[date | None] = mapped_column(Date, index=True)
    customer_code: Mapped[str | None] = mapped_column(String(120), index=True)
    customer_name: Mapped[str | None] = mapped_column(String(255), index=True)
    matched_customer_code: Mapped[str | None] = mapped_column(String(120), index=True)
    matched_customer_name: Mapped[str | None] = mapped_column(String(255), index=True)
    receivable_ar_balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    account_ar_balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    previous_ar_balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    diff_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    overdue_days: Mapped[int | None] = mapped_column(Integer, index=True)
    recent_sales_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    message: Mapped[str | None] = mapped_column(Text)
    source_json: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

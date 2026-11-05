from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import String, case, cast, func, or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import (
    CustomerMaster,
    ExternalApiKey,
    ImportBatch,
    InventorySnapshot,
    MasterLinkIssue,
    ProductMaster,
    PurchaseDetail,
    ReceivableSnapshot,
    SalesDetail,
    SupplierMaster,
)
from app.schemas.external_api import (
    ExternalCustomerItem,
    ExternalCustomerListData,
    ExternalDataQualityImportStatus,
    ExternalDataQualityIssueGroup,
    ExternalDataQualitySummaryData,
    ExternalEnvelope,
    ExternalInventoryBreakdownItem,
    ExternalInventorySummaryData,
    ExternalProductItem,
    ExternalProductListData,
    ExternalPurchaseBreakdownItem,
    ExternalPurchaseSummaryData,
    ExternalReceivableBreakdownItem,
    ExternalReceivableSummaryData,
    ExternalSalesBreakdownItem,
    ExternalSalesSummaryData,
    ExternalSupplierItem,
    ExternalSupplierListData,
)
from app.services.external_api_service import (
    allowed_customer_fields,
    apply_external_cursor,
    apply_external_customer_scope,
    audit_external_request,
    external_limit,
    external_meta,
    external_page,
    external_scope_is_restricted,
    require_external_permission,
)


router = APIRouter(prefix="/api/external/v2", tags=["external-agent-api-v2-operations"])


def _customer_item(db: Session, row: CustomerMaster, fields: list[str]) -> ExternalCustomerItem:
    from app.services.customer_tagging_service import external_customer_tag_profile

    attributes = {
        field: getattr(row, field)
        for field in fields
        if field not in {"customer_code", "customer_name", "customer_tag_profile"}
    }
    if "customer_tag_profile" in fields:
        attributes["customer_tag_profile"] = external_customer_tag_profile(db, row)
    return ExternalCustomerItem(
        customer_code=row.customer_code,
        customer_name=row.customer_name,
        fields=attributes,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _product_item(row: ProductMaster) -> ExternalProductItem:
    return ExternalProductItem(
        product_code=row.product_code,
        product_name=row.product_name,
        spec=row.spec,
        unit=row.unit,
        category=row.category,
        brand=row.brand,
        barcode=row.barcode,
        reference_sale_price=row.reference_sale_price,
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _supplier_item(row: SupplierMaster) -> ExternalSupplierItem:
    return ExternalSupplierItem(
        supplier_code=row.supplier_code,
        supplier_name=row.supplier_name,
        supplier_short_name=row.supplier_short_name,
        supplier_type=row.supplier_type,
        region=row.region,
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _visible_customer_codes_stmt(api_key: ExternalApiKey) -> Any:
    return apply_external_customer_scope(select(CustomerMaster.customer_code), api_key)


def _apply_customer_fact_scope(stmt: Any, code_column: Any, api_key: ExternalApiKey, *, fallback_column: Any | None = None) -> Any:
    if not external_scope_is_restricted(api_key):
        return stmt
    visible = _visible_customer_codes_stmt(api_key)
    if fallback_column is None:
        return stmt.where(code_column.in_(visible))
    return stmt.where(or_(code_column.in_(visible), (code_column.is_(None) & fallback_column.in_(visible))))


def _date_expression(model: Any) -> Any:
    return func.coalesce(model.document_date, model.data_date)


def _apply_date_filters(stmt: Any, expression: Any, date_from: date | None, date_to: date | None) -> Any:
    if date_from is not None:
        stmt = stmt.where(expression >= date_from)
    if date_to is not None:
        stmt = stmt.where(expression <= date_to)
    return stmt


@router.get("/customers", response_model=ExternalEnvelope[ExternalCustomerListData])
def external_v2_customers(
    request: Request,
    q: str | None = None,
    region: str | None = None,
    customer_type: str | None = None,
    salesperson: str | None = None,
    customer_status: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
    api_key: ExternalApiKey = Depends(require_external_permission("can_read_customers")),
    db: Session = Depends(get_db),
) -> ExternalEnvelope[ExternalCustomerListData]:
    limit_value = external_limit(limit)
    stmt = apply_external_customer_scope(select(CustomerMaster), api_key)
    if q:
        keyword = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                CustomerMaster.customer_code.ilike(keyword),
                CustomerMaster.customer_name.ilike(keyword),
                CustomerMaster.customer_short_name.ilike(keyword),
            )
        )
    if region:
        stmt = stmt.where(CustomerMaster.region == region)
    if customer_type:
        stmt = stmt.where(CustomerMaster.customer_type == customer_type)
    if salesperson:
        stmt = stmt.where(
            or_(CustomerMaster.salesperson_name == salesperson, CustomerMaster.salesperson_employee_code == salesperson)
        )
    if customer_status:
        stmt = stmt.where(CustomerMaster.status == customer_status)
    stmt = apply_external_cursor(stmt, CustomerMaster, cursor, dialect_name=db.get_bind().dialect.name)
    rows = list(
        db.scalars(stmt.order_by(CustomerMaster.updated_at.desc(), CustomerMaster.id.desc()).limit(limit_value + 1)).all()
    )
    customers, next_cursor, has_more = external_page(rows, limit_value)
    fields = allowed_customer_fields(api_key)
    items = [_customer_item(db, row, fields) for row in customers]
    audit_external_request(db, request, api_key, "/customers", {"count": len(items)})
    return ExternalEnvelope(
        data=ExternalCustomerListData(items=items, count=len(items)),
        meta=external_meta(request, next_cursor=next_cursor, has_more=has_more),
    )


@router.get("/customers/{customer_code}", response_model=ExternalEnvelope[ExternalCustomerItem])
def external_v2_customer_detail(
    customer_code: str,
    request: Request,
    api_key: ExternalApiKey = Depends(require_external_permission("can_read_customers")),
    db: Session = Depends(get_db),
) -> ExternalEnvelope[ExternalCustomerItem]:
    row = db.scalar(
        apply_external_customer_scope(
            select(CustomerMaster).where(CustomerMaster.customer_code == customer_code), api_key
        )
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    item = _customer_item(db, row, allowed_customer_fields(api_key))
    audit_external_request(db, request, api_key, f"/customers/{customer_code}")
    return ExternalEnvelope(data=item, meta=external_meta(request))


@router.get("/products", response_model=ExternalEnvelope[ExternalProductListData])
def external_v2_products(
    request: Request,
    q: str | None = None,
    category: str | None = None,
    brand: str | None = None,
    product_status: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
    api_key: ExternalApiKey = Depends(require_external_permission("can_read_products")),
    db: Session = Depends(get_db),
) -> ExternalEnvelope[ExternalProductListData]:
    limit_value = external_limit(limit)
    stmt = select(ProductMaster)
    if q:
        keyword = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                ProductMaster.product_code.ilike(keyword),
                ProductMaster.product_name.ilike(keyword),
                ProductMaster.barcode.ilike(keyword),
            )
        )
    if category:
        stmt = stmt.where(ProductMaster.category == category)
    if brand:
        stmt = stmt.where(ProductMaster.brand == brand)
    if product_status:
        stmt = stmt.where(ProductMaster.status == product_status)
    stmt = apply_external_cursor(stmt, ProductMaster, cursor, dialect_name=db.get_bind().dialect.name)
    rows = list(db.scalars(stmt.order_by(ProductMaster.updated_at.desc(), ProductMaster.id.desc()).limit(limit_value + 1)).all())
    products, next_cursor, has_more = external_page(rows, limit_value)
    items = [_product_item(row) for row in products]
    audit_external_request(db, request, api_key, "/products", {"count": len(items)})
    return ExternalEnvelope(
        data=ExternalProductListData(items=items, count=len(items)),
        meta=external_meta(request, next_cursor=next_cursor, has_more=has_more),
    )


@router.get("/products/{product_code}", response_model=ExternalEnvelope[ExternalProductItem])
def external_v2_product_detail(
    product_code: str,
    request: Request,
    api_key: ExternalApiKey = Depends(require_external_permission("can_read_products")),
    db: Session = Depends(get_db),
) -> ExternalEnvelope[ExternalProductItem]:
    row = db.scalar(select(ProductMaster).where(ProductMaster.product_code == product_code))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    item = _product_item(row)
    audit_external_request(db, request, api_key, f"/products/{product_code}")
    return ExternalEnvelope(data=item, meta=external_meta(request))


@router.get("/suppliers", response_model=ExternalEnvelope[ExternalSupplierListData])
def external_v2_suppliers(
    request: Request,
    q: str | None = None,
    region: str | None = None,
    supplier_type: str | None = None,
    supplier_status: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
    api_key: ExternalApiKey = Depends(require_external_permission("can_read_suppliers")),
    db: Session = Depends(get_db),
) -> ExternalEnvelope[ExternalSupplierListData]:
    limit_value = external_limit(limit)
    stmt = select(SupplierMaster)
    if q:
        keyword = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                SupplierMaster.supplier_code.ilike(keyword),
                SupplierMaster.supplier_name.ilike(keyword),
                SupplierMaster.supplier_short_name.ilike(keyword),
            )
        )
    if region:
        stmt = stmt.where(SupplierMaster.region == region)
    if supplier_type:
        stmt = stmt.where(SupplierMaster.supplier_type == supplier_type)
    if supplier_status:
        stmt = stmt.where(SupplierMaster.status == supplier_status)
    stmt = apply_external_cursor(stmt, SupplierMaster, cursor, dialect_name=db.get_bind().dialect.name)
    rows = list(db.scalars(stmt.order_by(SupplierMaster.updated_at.desc(), SupplierMaster.id.desc()).limit(limit_value + 1)).all())
    suppliers, next_cursor, has_more = external_page(rows, limit_value)
    items = [_supplier_item(row) for row in suppliers]
    audit_external_request(db, request, api_key, "/suppliers", {"count": len(items)})
    return ExternalEnvelope(
        data=ExternalSupplierListData(items=items, count=len(items)),
        meta=external_meta(request, next_cursor=next_cursor, has_more=has_more),
    )


@router.get("/suppliers/{supplier_code}", response_model=ExternalEnvelope[ExternalSupplierItem])
def external_v2_supplier_detail(
    supplier_code: str,
    request: Request,
    api_key: ExternalApiKey = Depends(require_external_permission("can_read_suppliers")),
    db: Session = Depends(get_db),
) -> ExternalEnvelope[ExternalSupplierItem]:
    row = db.scalar(select(SupplierMaster).where(SupplierMaster.supplier_code == supplier_code))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supplier not found")
    item = _supplier_item(row)
    audit_external_request(db, request, api_key, f"/suppliers/{supplier_code}")
    return ExternalEnvelope(data=item, meta=external_meta(request))


@router.get("/operations/sales-summary", response_model=ExternalEnvelope[ExternalSalesSummaryData])
def external_v2_sales_summary(
    request: Request,
    date_from: date | None = None,
    date_to: date | None = None,
    customer_code: str | None = None,
    product_code: str | None = None,
    group_by: str = Query(default="customer", pattern="^(customer|product|day)$"),
    limit: int = 20,
    api_key: ExternalApiKey = Depends(require_external_permission("can_read_sales_summary")),
    db: Session = Depends(get_db),
) -> ExternalEnvelope[ExternalSalesSummaryData]:
    limit_value = external_limit(limit, maximum=100)
    business_date = _date_expression(SalesDetail)

    def scoped(stmt: Any) -> Any:
        stmt = _apply_customer_fact_scope(stmt, SalesDetail.customer_code, api_key)
        stmt = _apply_date_filters(stmt, business_date, date_from, date_to)
        if customer_code:
            stmt = stmt.where(SalesDetail.customer_code == customer_code)
        if product_code:
            stmt = stmt.where(SalesDetail.product_code == product_code)
        return stmt

    total = db.execute(
        scoped(
            select(
                func.count(SalesDetail.id),
                func.count(func.distinct(SalesDetail.document_no)),
                func.coalesce(func.sum(SalesDetail.sale_qty_base), 0),
                func.coalesce(func.sum(SalesDetail.amount_after_discount), 0),
                func.coalesce(func.sum(SalesDetail.gross_profit), 0),
                func.max(business_date),
            ).select_from(SalesDetail)
        )
    ).one()
    if group_by == "product":
        key_expression = func.coalesce(SalesDetail.product_code, "unknown")
        label_expression = func.max(func.coalesce(SalesDetail.product_name, SalesDetail.product_code, "Unknown product"))
    elif group_by == "day":
        key_expression = cast(business_date, String)
        label_expression = func.max(cast(business_date, String))
    else:
        key_expression = func.coalesce(SalesDetail.customer_code, "unknown")
        label_expression = func.max(func.coalesce(SalesDetail.customer_name, SalesDetail.customer_code, "Unknown customer"))
    rows = db.execute(
        scoped(
            select(
                key_expression.label("key"),
                label_expression.label("label"),
                func.count(SalesDetail.id).label("row_count"),
                func.count(func.distinct(SalesDetail.document_no)).label("document_count"),
                func.coalesce(func.sum(SalesDetail.sale_qty_base), 0).label("quantity"),
                func.coalesce(func.sum(SalesDetail.amount_after_discount), 0).label("net_sales"),
                func.coalesce(func.sum(SalesDetail.gross_profit), 0).label("gross_profit"),
            )
            .select_from(SalesDetail)
            .group_by(key_expression)
            .order_by(func.coalesce(func.sum(SalesDetail.amount_after_discount), 0).desc())
            .limit(limit_value)
        )
    ).all()
    net_sales = _decimal(total[3])
    gross_profit = _decimal(total[4])
    gross_margin_rate = (gross_profit / net_sales * Decimal("100")) if net_sales else None
    data = ExternalSalesSummaryData(
        date_from=date_from,
        date_to=date_to,
        data_cutoff_date=total[5],
        group_by=group_by,
        row_count=int(total[0] or 0),
        document_count=int(total[1] or 0),
        quantity=_decimal(total[2]),
        net_sales=net_sales,
        gross_profit=gross_profit,
        gross_margin_rate=gross_margin_rate,
        breakdown=[
            ExternalSalesBreakdownItem(
                key=str(row.key or "unknown"),
                label=str(row.label or row.key or "Unknown"),
                row_count=int(row.row_count or 0),
                document_count=int(row.document_count or 0),
                quantity=_decimal(row.quantity),
                net_sales=_decimal(row.net_sales),
                gross_profit=_decimal(row.gross_profit),
            )
            for row in rows
        ],
    )
    audit_external_request(db, request, api_key, "/operations/sales-summary", {"row_count": data.row_count})
    return ExternalEnvelope(data=data, meta=external_meta(request))


@router.get("/operations/purchase-summary", response_model=ExternalEnvelope[ExternalPurchaseSummaryData])
def external_v2_purchase_summary(
    request: Request,
    date_from: date | None = None,
    date_to: date | None = None,
    supplier_code: str | None = None,
    product_code: str | None = None,
    group_by: str = Query(default="supplier", pattern="^(supplier|product|day)$"),
    limit: int = 20,
    api_key: ExternalApiKey = Depends(require_external_permission("can_read_purchase_summary")),
    db: Session = Depends(get_db),
) -> ExternalEnvelope[ExternalPurchaseSummaryData]:
    limit_value = external_limit(limit, maximum=100)
    business_date = _date_expression(PurchaseDetail)

    def filtered(stmt: Any) -> Any:
        stmt = _apply_date_filters(stmt, business_date, date_from, date_to)
        if supplier_code:
            stmt = stmt.where(PurchaseDetail.supplier_code == supplier_code)
        if product_code:
            stmt = stmt.where(PurchaseDetail.product_code == product_code)
        return stmt

    total = db.execute(
        filtered(
            select(
                func.count(PurchaseDetail.id),
                func.count(func.distinct(PurchaseDetail.document_no)),
                func.coalesce(func.sum(PurchaseDetail.purchase_qty_base), 0),
                func.coalesce(func.sum(PurchaseDetail.purchase_amount), 0),
                func.max(business_date),
            ).select_from(PurchaseDetail)
        )
    ).one()
    if group_by == "product":
        key_expression = func.coalesce(PurchaseDetail.product_code, "unknown")
        label_expression = func.max(func.coalesce(PurchaseDetail.product_name, PurchaseDetail.product_code, "Unknown product"))
    elif group_by == "day":
        key_expression = cast(business_date, String)
        label_expression = func.max(cast(business_date, String))
    else:
        key_expression = func.coalesce(PurchaseDetail.supplier_code, "unknown")
        label_expression = func.max(func.coalesce(PurchaseDetail.supplier_name, PurchaseDetail.supplier_code, "Unknown supplier"))
    rows = db.execute(
        filtered(
            select(
                key_expression.label("key"),
                label_expression.label("label"),
                func.count(PurchaseDetail.id).label("row_count"),
                func.count(func.distinct(PurchaseDetail.document_no)).label("document_count"),
                func.coalesce(func.sum(PurchaseDetail.purchase_qty_base), 0).label("quantity"),
                func.coalesce(func.sum(PurchaseDetail.purchase_amount), 0).label("purchase_amount"),
            )
            .select_from(PurchaseDetail)
            .group_by(key_expression)
            .order_by(func.coalesce(func.sum(PurchaseDetail.purchase_amount), 0).desc())
            .limit(limit_value)
        )
    ).all()
    data = ExternalPurchaseSummaryData(
        date_from=date_from,
        date_to=date_to,
        data_cutoff_date=total[4],
        group_by=group_by,
        row_count=int(total[0] or 0),
        document_count=int(total[1] or 0),
        quantity=_decimal(total[2]),
        purchase_amount=_decimal(total[3]),
        breakdown=[
            ExternalPurchaseBreakdownItem(
                key=str(row.key or "unknown"),
                label=str(row.label or row.key or "Unknown"),
                row_count=int(row.row_count or 0),
                document_count=int(row.document_count or 0),
                quantity=_decimal(row.quantity),
                purchase_amount=_decimal(row.purchase_amount),
            )
            for row in rows
        ],
    )
    audit_external_request(db, request, api_key, "/operations/purchase-summary", {"row_count": data.row_count})
    return ExternalEnvelope(data=data, meta=external_meta(request))


@router.get("/operations/inventory-summary", response_model=ExternalEnvelope[ExternalInventorySummaryData])
def external_v2_inventory_summary(
    request: Request,
    data_date: date | None = None,
    warehouse_name: str | None = None,
    product_code: str | None = None,
    group_by: str = Query(default="warehouse", pattern="^(warehouse|product)$"),
    limit: int = 20,
    api_key: ExternalApiKey = Depends(require_external_permission("can_read_inventory_summary")),
    db: Session = Depends(get_db),
) -> ExternalEnvelope[ExternalInventorySummaryData]:
    limit_value = external_limit(limit, maximum=100)

    def filtered(stmt: Any, *, include_date: bool = True) -> Any:
        if include_date and selected_date is not None:
            stmt = stmt.where(InventorySnapshot.data_date == selected_date)
        if warehouse_name:
            stmt = stmt.where(InventorySnapshot.warehouse_name == warehouse_name)
        if product_code:
            stmt = stmt.where(InventorySnapshot.product_code == product_code)
        return stmt

    selected_date = data_date
    if selected_date is None:
        selected_date = db.scalar(filtered(select(func.max(InventorySnapshot.data_date)), include_date=False))
    total = db.execute(
        filtered(
            select(
                func.count(InventorySnapshot.id),
                func.count(func.distinct(InventorySnapshot.product_code)),
                func.count(func.distinct(InventorySnapshot.warehouse_name)),
                func.coalesce(func.sum(InventorySnapshot.stock_qty), 0),
                func.coalesce(func.sum(InventorySnapshot.locked_base_qty), 0),
                func.coalesce(func.sum(InventorySnapshot.cost_amount), 0),
            ).select_from(InventorySnapshot)
        )
    ).one()
    if group_by == "product":
        key_expression = func.coalesce(InventorySnapshot.product_code, "unknown")
        label_expression = func.max(func.coalesce(InventorySnapshot.product_name, InventorySnapshot.product_code, "Unknown product"))
    else:
        key_expression = func.coalesce(InventorySnapshot.warehouse_name, "unknown")
        label_expression = func.max(func.coalesce(InventorySnapshot.warehouse_name, "Unknown warehouse"))
    rows = db.execute(
        filtered(
            select(
                key_expression.label("key"),
                label_expression.label("label"),
                func.count(InventorySnapshot.id).label("row_count"),
                func.count(func.distinct(InventorySnapshot.product_code)).label("sku_count"),
                func.coalesce(func.sum(InventorySnapshot.stock_qty), 0).label("stock_quantity"),
                func.coalesce(func.sum(InventorySnapshot.locked_base_qty), 0).label("locked_quantity"),
                func.coalesce(func.sum(InventorySnapshot.cost_amount), 0).label("cost_amount"),
            )
            .select_from(InventorySnapshot)
            .group_by(key_expression)
            .order_by(func.coalesce(func.sum(InventorySnapshot.cost_amount), 0).desc())
            .limit(limit_value)
        )
    ).all()
    data = ExternalInventorySummaryData(
        data_date=selected_date,
        row_count=int(total[0] or 0),
        sku_count=int(total[1] or 0),
        warehouse_count=int(total[2] or 0),
        stock_quantity=_decimal(total[3]),
        locked_quantity=_decimal(total[4]),
        cost_amount=_decimal(total[5]),
        breakdown=[
            ExternalInventoryBreakdownItem(
                key=str(row.key or "unknown"),
                label=str(row.label or row.key or "Unknown"),
                row_count=int(row.row_count or 0),
                sku_count=int(row.sku_count or 0),
                stock_quantity=_decimal(row.stock_quantity),
                locked_quantity=_decimal(row.locked_quantity),
                cost_amount=_decimal(row.cost_amount),
            )
            for row in rows
        ],
    )
    audit_external_request(db, request, api_key, "/operations/inventory-summary", {"row_count": data.row_count})
    return ExternalEnvelope(data=data, meta=external_meta(request))


@router.get("/operations/receivable-summary", response_model=ExternalEnvelope[ExternalReceivableSummaryData])
def external_v2_receivable_summary(
    request: Request,
    data_date: date | None = None,
    customer_code: str | None = None,
    salesperson: str | None = None,
    group_by: str = Query(default="aging", pattern="^(aging|salesperson|customer)$"),
    limit: int = 20,
    api_key: ExternalApiKey = Depends(require_external_permission("can_read_receivables")),
    db: Session = Depends(get_db),
) -> ExternalEnvelope[ExternalReceivableSummaryData]:
    limit_value = external_limit(limit, maximum=100)

    def filtered(stmt: Any, *, include_date: bool = True) -> Any:
        stmt = _apply_customer_fact_scope(
            stmt,
            ReceivableSnapshot.matched_customer_code,
            api_key,
            fallback_column=ReceivableSnapshot.customer_code,
        )
        if include_date and selected_date is not None:
            stmt = stmt.where(ReceivableSnapshot.data_date == selected_date)
        if customer_code:
            stmt = stmt.where(
                or_(
                    ReceivableSnapshot.matched_customer_code == customer_code,
                    ReceivableSnapshot.customer_code == customer_code,
                )
            )
        if salesperson:
            stmt = stmt.where(ReceivableSnapshot.salesperson_name == salesperson)
        return stmt

    selected_date = data_date
    if selected_date is None:
        selected_date = db.scalar(filtered(select(func.max(ReceivableSnapshot.data_date)), include_date=False))
    overdue_condition = func.coalesce(ReceivableSnapshot.overdue_days, 0) > 0
    canonical_customer = func.coalesce(ReceivableSnapshot.matched_customer_code, ReceivableSnapshot.customer_code)
    total = db.execute(
        filtered(
            select(
                func.count(func.distinct(canonical_customer)),
                func.coalesce(func.sum(ReceivableSnapshot.ar_balance), 0),
                func.coalesce(func.sum(ReceivableSnapshot.received_amount), 0),
                func.coalesce(func.sum(ReceivableSnapshot.unreceived_amount), 0),
                func.count(func.distinct(case((overdue_condition, canonical_customer), else_=None))),
                func.coalesce(func.sum(case((overdue_condition, ReceivableSnapshot.ar_balance), else_=0)), 0),
            ).select_from(ReceivableSnapshot)
        )
    ).one()
    if group_by == "salesperson":
        key_expression = func.coalesce(ReceivableSnapshot.salesperson_name, "unknown")
        label_expression = func.max(func.coalesce(ReceivableSnapshot.salesperson_name, "Unknown salesperson"))
    elif group_by == "customer":
        key_expression = func.coalesce(canonical_customer, "unknown")
        label_expression = func.max(
            func.coalesce(
                ReceivableSnapshot.matched_customer_name,
                ReceivableSnapshot.customer_name,
                canonical_customer,
                "Unknown customer",
            )
        )
    else:
        key_expression = func.coalesce(ReceivableSnapshot.aging_label, "unclassified")
        label_expression = func.max(func.coalesce(ReceivableSnapshot.aging_label, "Unclassified"))
    rows = db.execute(
        filtered(
            select(
                key_expression.label("key"),
                label_expression.label("label"),
                func.count(func.distinct(canonical_customer)).label("customer_count"),
                func.coalesce(func.sum(ReceivableSnapshot.ar_balance), 0).label("receivable_amount"),
                func.count(func.distinct(case((overdue_condition, canonical_customer), else_=None))).label(
                    "overdue_customer_count"
                ),
            )
            .select_from(ReceivableSnapshot)
            .group_by(key_expression)
            .order_by(func.coalesce(func.sum(ReceivableSnapshot.ar_balance), 0).desc())
            .limit(limit_value)
        )
    ).all()
    data = ExternalReceivableSummaryData(
        data_date=selected_date,
        customer_count=int(total[0] or 0),
        receivable_amount=_decimal(total[1]),
        received_amount=_decimal(total[2]),
        unreceived_amount=_decimal(total[3]),
        overdue_customer_count=int(total[4] or 0),
        overdue_amount=_decimal(total[5]),
        breakdown=[
            ExternalReceivableBreakdownItem(
                key=str(row.key or "unknown"),
                label=str(row.label or row.key or "Unknown"),
                customer_count=int(row.customer_count or 0),
                receivable_amount=_decimal(row.receivable_amount),
                overdue_customer_count=int(row.overdue_customer_count or 0),
            )
            for row in rows
        ],
    )
    audit_external_request(db, request, api_key, "/operations/receivable-summary", {"customer_count": data.customer_count})
    return ExternalEnvelope(data=data, meta=external_meta(request))


@router.get("/data-quality/summary", response_model=ExternalEnvelope[ExternalDataQualitySummaryData])
def external_v2_data_quality_summary(
    request: Request,
    api_key: ExternalApiKey = Depends(require_external_permission("can_read_data_quality")),
    db: Session = Depends(get_db),
) -> ExternalEnvelope[ExternalDataQualitySummaryData]:
    totals = db.execute(
        select(
            func.count(MasterLinkIssue.id),
            func.coalesce(func.sum(MasterLinkIssue.affected_rows), 0),
            func.coalesce(func.sum(MasterLinkIssue.affected_documents), 0),
        ).where(MasterLinkIssue.status == "open")
    ).one()
    issue_rows = db.execute(
        select(
            MasterLinkIssue.expected_master_kind,
            MasterLinkIssue.issue_type,
            func.count(MasterLinkIssue.id).label("issue_count"),
            func.coalesce(func.sum(MasterLinkIssue.affected_rows), 0).label("affected_rows"),
            func.coalesce(func.sum(MasterLinkIssue.affected_documents), 0).label("affected_documents"),
        )
        .where(MasterLinkIssue.status == "open")
        .group_by(MasterLinkIssue.expected_master_kind, MasterLinkIssue.issue_type)
        .order_by(func.count(MasterLinkIssue.id).desc())
    ).all()
    latest_subquery = (
        select(ImportBatch.file_type, func.max(ImportBatch.uploaded_at).label("latest_uploaded_at"))
        .group_by(ImportBatch.file_type)
        .subquery()
    )
    import_rows = list(
        db.scalars(
            select(ImportBatch)
            .join(
                latest_subquery,
                (ImportBatch.file_type == latest_subquery.c.file_type)
                & (ImportBatch.uploaded_at == latest_subquery.c.latest_uploaded_at),
            )
            .order_by(ImportBatch.file_type, ImportBatch.id.desc())
        ).all()
    )
    latest_by_type: dict[str, ImportBatch] = {}
    for row in import_rows:
        latest_by_type.setdefault(row.file_type, row)
    data = ExternalDataQualitySummaryData(
        open_issue_count=int(totals[0] or 0),
        affected_rows=int(totals[1] or 0),
        affected_documents=int(totals[2] or 0),
        issue_groups=[
            ExternalDataQualityIssueGroup(
                expected_master_kind=row.expected_master_kind,
                issue_type=row.issue_type,
                issue_count=int(row.issue_count or 0),
                affected_rows=int(row.affected_rows or 0),
                affected_documents=int(row.affected_documents or 0),
            )
            for row in issue_rows
        ],
        latest_imports=[
            ExternalDataQualityImportStatus(
                file_type=row.file_type,
                data_date=row.data_date,
                status=row.status,
                total_rows=row.total_rows,
                success_rows=row.success_rows,
                error_rows=row.error_rows,
                uploaded_at=row.uploaded_at,
            )
            for row in latest_by_type.values()
        ],
        calculated_at=datetime.now(timezone.utc),
    )
    audit_external_request(db, request, api_key, "/data-quality/summary", {"open_issue_count": data.open_issue_count})
    return ExternalEnvelope(data=data, meta=external_meta(request))

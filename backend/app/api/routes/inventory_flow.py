from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.dependencies import require_permission
from app.core.database import get_db
from app.models import InventoryFlowLedger, SalesDetail, User
from app.services.access_control_service import apply_data_scope
from app.services.inventory_flow_service import (
    inventory_flow_status_label,
    rebuild_inventory_flow,
    serialize_inventory_flow,
)

router = APIRouter(prefix="/inventory-flow", tags=["inventory-flow"])


def _safe_limit(limit: int) -> int:
    return max(1, min(limit, 200))


def _safe_offset(offset: int) -> int:
    return max(0, offset)


def _base_stmt(
    *,
    date_from: date | None,
    date_to: date | None,
    warehouse_name: str | None,
    product_code: str | None,
    anomaly_type: str | None,
    q: str | None,
):
    stmt = select(InventoryFlowLedger)
    if date_from:
        stmt = stmt.where(InventoryFlowLedger.data_date >= date_from)
    if date_to:
        stmt = stmt.where(InventoryFlowLedger.data_date <= date_to)
    if warehouse_name:
        stmt = stmt.where(InventoryFlowLedger.warehouse_name == warehouse_name)
    if product_code:
        stmt = stmt.where(InventoryFlowLedger.product_code == product_code)
    if anomaly_type:
        stmt = stmt.where(InventoryFlowLedger.anomaly_type == anomaly_type)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(InventoryFlowLedger.product_code.ilike(like), InventoryFlowLedger.product_name.ilike(like), InventoryFlowLedger.warehouse_name.ilike(like)))
    return stmt


@router.get("/page")
def inventory_flow_page(
    date_from: date | None = None,
    date_to: date | None = None,
    warehouse_name: str | None = None,
    product_code: str | None = None,
    anomaly_type: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("inventory_check.view")),
) -> dict[str, Any]:
    safe_limit = _safe_limit(limit)
    safe_offset = _safe_offset(offset)
    stmt = _base_stmt(date_from=date_from, date_to=date_to, warehouse_name=warehouse_name, product_code=product_code, anomaly_type=anomaly_type, q=q)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = list(db.scalars(stmt.order_by(InventoryFlowLedger.data_date.desc(), InventoryFlowLedger.anomaly_type, InventoryFlowLedger.product_code).offset(safe_offset).limit(safe_limit)).all())
    return {
        "items": [serialize_inventory_flow(row) for row in rows],
        "total": total,
        "limit": safe_limit,
        "offset": safe_offset,
        "summary": _summary(db, stmt),
    }


@router.get("/summary")
def inventory_flow_summary(
    date_from: date | None = None,
    date_to: date | None = None,
    warehouse_name: str | None = None,
    product_code: str | None = None,
    anomaly_type: str | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("inventory_check.view")),
) -> dict[str, Any]:
    stmt = _base_stmt(date_from=date_from, date_to=date_to, warehouse_name=warehouse_name, product_code=product_code, anomaly_type=anomaly_type, q=q)
    return _summary(db, stmt)


@router.get("/sales-status")
def sales_inventory_status(
    ids: str = Query(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("sales_detail.view")),
) -> dict[str, Any]:
    parsed_ids = [int(item) for item in ids.split(",") if item.strip().isdigit()]
    if not parsed_ids:
        return {"items": {}}
    sales_stmt = select(SalesDetail).where(SalesDetail.id.in_(parsed_ids))
    sales_stmt = apply_data_scope(sales_stmt, SalesDetail, db, current_user, "sales_detail")
    sales_rows = list(db.scalars(sales_stmt).all())
    flow_keys = [
        (row.data_date, row.warehouse_name or "未识别仓库", row.product_code)
        for row in sales_rows
        if row.data_date and row.product_code
    ]
    flow_rows: dict[tuple[date, str, str], InventoryFlowLedger] = {}
    if flow_keys:
        conditions = [
            (InventoryFlowLedger.data_date == data_date)
            & (InventoryFlowLedger.warehouse_name == warehouse)
            & (InventoryFlowLedger.product_code == product_code)
            for data_date, warehouse, product_code in flow_keys
        ]
        for flow in db.scalars(select(InventoryFlowLedger).where(or_(*conditions))).all():
            flow_rows[(flow.data_date, flow.warehouse_name, flow.product_code)] = flow
    payload: dict[str, Any] = {}
    for row in sales_rows:
        flow = flow_rows.get((row.data_date, row.warehouse_name or "未识别仓库", row.product_code)) if row.data_date and row.product_code else None
        anomaly_type = flow.anomaly_type if flow else "normal"
        payload[str(row.id)] = {
            "sales_detail_id": row.id,
            "flow_id": flow.id if flow else None,
            "anomaly_type": anomaly_type,
            "label": inventory_flow_status_label(anomaly_type),
            "anomaly_flags": flow.anomaly_flags if flow else [],
        }
    return {"items": payload}


@router.post("/rebuild")
def rebuild_inventory_flow_endpoint(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("inventory_check.upload")),
) -> dict[str, Any]:
    result = rebuild_inventory_flow(db)
    from app.services.exception_center_service import enqueue_incremental_exception_scan_safely

    enqueue_incremental_exception_scan_safely(db, domains=["inventory"])
    db.commit()
    return result


def _summary(db: Session, stmt) -> dict[str, Any]:
    filtered = stmt.order_by(None).subquery()
    rows = db.execute(select(filtered.c.anomaly_type, func.count()).select_from(filtered).group_by(filtered.c.anomaly_type)).all()
    by_type = {row[0]: int(row[1] or 0) for row in rows}
    total = db.scalar(select(func.count()).select_from(filtered)) or 0
    abnormal = sum(count for key, count in by_type.items() if key != "normal")
    warehouses = db.scalar(select(func.count(func.distinct(filtered.c.warehouse_name))).select_from(filtered)) or 0
    products = db.scalar(select(func.count(func.distinct(filtered.c.product_code))).select_from(filtered)) or 0
    return {
        "total": total,
        "abnormal": abnormal,
        "normal": by_type.get("normal", 0),
        "warehouses": warehouses,
        "products": products,
        "by_type": by_type,
    }

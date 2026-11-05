from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.api.routes.master_data import list_customers_page, list_products_page, list_suppliers_page
from app.api.routes.process_data import (
    list_account_ledger_page,
    list_inventory_snapshots_page,
    list_purchase_details_page,
    list_sales_details_page,
)
from app.core.database import get_db
from app.models import User
from app.services.permission_service import has_permission

router = APIRouter(prefix="/mobile/data", tags=["mobile-data"])

DATA_MODULES = (
    ("customers", "客户", "customer.view"),
    ("products", "商品", "product.view"),
    ("suppliers", "供应商", "supplier.view"),
    ("sales", "销售明细", "sales_detail.view"),
    ("purchases", "采购明细", "purchase_detail.view"),
    ("account_ledger", "往来明细", "account_balance.view"),
    ("inventory", "库存快照", "inventory_snapshot.view"),
    ("inventory_check", "库存核验", "inventory_check.view"),
    ("receivable_check", "应收校验", "receivable.view"),
)


def _require(db: Session, user: User, code: str) -> None:
    if not has_permission(db, user, code):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权查看该数据")


def _normalized_page(payload: dict[str, Any], *, limit: int, offset: int) -> dict[str, Any]:
    return {
        "items": payload.get("items") or [],
        "total": int(payload.get("total") or 0),
        "limit": int(payload.get("limit") or limit),
        "offset": int(payload.get("offset") or offset),
        "summary": payload.get("summary") or {},
    }


@router.get("/overview")
def mobile_data_overview(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    modules = [
        {"key": key, "label": label, "permission": permission}
        for key, label, permission in DATA_MODULES
        if has_permission(db, current_user, permission)
    ]
    if not modules:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无移动数据查询权限")
    return {"modules": modules, "page_size": 20}


@router.get("/master/{kind}")
def mobile_master_data(
    kind: str,
    q: str | None = None,
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    if kind == "customers":
        _require(db, current_user, "customer.view")
        payload = list_customers_page(q=q, limit=limit, offset=offset, db=db, current_user=current_user)
    elif kind == "products":
        _require(db, current_user, "product.view")
        payload = list_products_page(q=q, limit=limit, offset=offset, db=db, current_user=current_user)
    elif kind == "suppliers":
        _require(db, current_user, "supplier.view")
        payload = list_suppliers_page(q=q, limit=limit, offset=offset, db=db, current_user=current_user)
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不支持的主数据类型")
    return _normalized_page(payload, limit=limit, offset=offset)


@router.get("/sales")
def mobile_sales_data(
    q: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    customer_code: str | None = None,
    product_code: str | None = None,
    warehouse_name: str | None = None,
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require(db, current_user, "sales_detail.view")
    payload = list_sales_details_page(q=q, date_from=date_from, date_to=date_to, customer_code=customer_code, product_code=product_code, warehouse_name=warehouse_name, limit=limit, offset=offset, db=db, current_user=current_user)
    return _normalized_page(payload, limit=limit, offset=offset)


@router.get("/purchases")
def mobile_purchase_data(
    q: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    supplier_code: str | None = None,
    product_code: str | None = None,
    warehouse_name: str | None = None,
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require(db, current_user, "purchase_detail.view")
    payload = list_purchase_details_page(q=q, date_from=date_from, date_to=date_to, supplier_code=supplier_code, product_code=product_code, warehouse_name=warehouse_name, limit=limit, offset=offset, db=db, current_user=current_user)
    return _normalized_page(payload, limit=limit, offset=offset)


@router.get("/account-ledger")
def mobile_account_ledger_data(
    q: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    settlement_unit_code: str | None = None,
    document_type: str | None = None,
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require(db, current_user, "account_balance.view")
    payload = list_account_ledger_page(q=q, date_from=date_from, date_to=date_to, settlement_unit_code=settlement_unit_code, document_type=document_type, limit=limit, offset=offset, db=db, current_user=current_user)
    return _normalized_page(payload, limit=limit, offset=offset)


@router.get("/inventory-snapshots")
def mobile_inventory_data(
    q: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    product_code: str | None = None,
    warehouse_name: str | None = None,
    inventory_status: str | None = None,
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require(db, current_user, "inventory_snapshot.view")
    payload = list_inventory_snapshots_page(q=q, date_from=date_from, date_to=date_to, product_code=product_code, warehouse_name=warehouse_name, inventory_status=inventory_status, limit=limit, offset=offset, db=db, current_user=current_user)
    return _normalized_page(payload, limit=limit, offset=offset)

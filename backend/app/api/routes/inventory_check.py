from __future__ import annotations

from datetime import date
from io import BytesIO
from urllib.parse import quote

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.dependencies import require_permission
from app.core.database import get_db
from app.models import InventoryCheckBatch, InventoryCheckResult, InventoryCheckRow, User
from app.services.inventory_check_service import (
    RESULT_TYPES,
    create_inventory_check_batch,
    rebuild_inventory_check_batch,
    serialize_inventory_check_batch,
    serialize_inventory_check_result,
    serialize_inventory_check_row,
)

router = APIRouter(prefix="/inventory-check", tags=["inventory-check"])


def _safe_limit(limit: int) -> int:
    return max(1, min(limit, 200))


def _safe_offset(offset: int) -> int:
    return max(0, offset)


def _count(db: Session, stmt) -> int:
    return db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0


def _get_batch(db: Session, batch_id: int) -> InventoryCheckBatch:
    batch = db.get(InventoryCheckBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inventory check batch not found")
    return batch


@router.post("/batches", status_code=status.HTTP_201_CREATED)
def upload_inventory_check_batch(
    data_date: date | None = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("inventory_check.upload")),
) -> dict:
    try:
        batch = create_inventory_check_batch(db, file=file, data_date=data_date, user=current_user)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.commit()
    db.refresh(batch)
    return serialize_inventory_check_batch(batch)


@router.get("/batches")
def list_inventory_check_batches(
    limit: int = 30,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("inventory_check.view")),
) -> dict:
    safe_limit = _safe_limit(limit)
    safe_offset = _safe_offset(offset)
    stmt = select(InventoryCheckBatch).order_by(InventoryCheckBatch.created_at.desc(), InventoryCheckBatch.id.desc())
    total = _count(db, stmt)
    rows = list(db.scalars(stmt.offset(safe_offset).limit(safe_limit)).all())
    return {
        "items": [serialize_inventory_check_batch(row) for row in rows],
        "total": total,
        "limit": safe_limit,
        "offset": safe_offset,
    }


@router.get("/batches/{batch_id}")
def get_inventory_check_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("inventory_check.view")),
) -> dict:
    return serialize_inventory_check_batch(_get_batch(db, batch_id))


@router.post("/batches/{batch_id}/rebuild")
def rebuild_inventory_check_batch_endpoint(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("inventory_check.upload")),
) -> dict:
    batch = _get_batch(db, batch_id)
    try:
        rebuild_inventory_check_batch(db, batch=batch, user=current_user)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    from app.services.exception_center_service import enqueue_incremental_exception_scan_safely

    enqueue_incremental_exception_scan_safely(
        db,
        domains=["inventory"],
        source_batch_kind="inventory_check",
        source_batch_id=batch.id,
    )
    db.commit()
    db.refresh(batch)
    return serialize_inventory_check_batch(batch)


@router.get("/batches/{batch_id}/results")
def list_inventory_check_results(
    batch_id: int,
    type: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("inventory_check.view")),
) -> dict:
    _get_batch(db, batch_id)
    safe_limit = _safe_limit(limit)
    safe_offset = _safe_offset(offset)
    stmt = select(InventoryCheckResult).where(InventoryCheckResult.batch_id == batch_id)
    if type:
        if type not in RESULT_TYPES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid result type")
        stmt = stmt.where(InventoryCheckResult.result_type == type)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(InventoryCheckResult.product_code.ilike(like), InventoryCheckResult.product_name.ilike(like)))
    stmt = stmt.order_by(InventoryCheckResult.result_type, InventoryCheckResult.product_code, InventoryCheckResult.id)
    total = _count(db, stmt)
    rows = list(db.scalars(stmt.offset(safe_offset).limit(safe_limit)).all())
    return {
        "items": [serialize_inventory_check_result(row) for row in rows],
        "total": total,
        "limit": safe_limit,
        "offset": safe_offset,
        "summary": _result_summary(db, batch_id),
    }


@router.get("/batches/{batch_id}/rows")
def list_inventory_check_rows(
    batch_id: int,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("inventory_check.upload")),
) -> dict:
    _get_batch(db, batch_id)
    safe_limit = _safe_limit(limit)
    safe_offset = _safe_offset(offset)
    stmt = select(InventoryCheckRow).where(InventoryCheckRow.batch_id == batch_id).order_by(InventoryCheckRow.row_number)
    total = _count(db, stmt)
    rows = list(db.scalars(stmt.offset(safe_offset).limit(safe_limit)).all())
    return {
        "items": [serialize_inventory_check_row(row) for row in rows],
        "total": total,
        "limit": safe_limit,
        "offset": safe_offset,
    }


@router.get("/batches/{batch_id}/export")
def export_inventory_check_results(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("inventory_check.export")),
) -> StreamingResponse:
    batch = _get_batch(db, batch_id)
    rows = list(
        db.scalars(
            select(InventoryCheckResult)
            .where(InventoryCheckResult.batch_id == batch_id)
            .order_by(InventoryCheckResult.result_type, InventoryCheckResult.product_code, InventoryCheckResult.id)
        ).all()
    )
    payload = [
        {
            "差异类型": result_type_label(row.result_type),
            "商品编号": row.product_code,
            "商品名称": row.product_name,
            "平台库存": row.platform_stock_qty,
            "系统库存": row.system_stock_qty,
            "差异数量": row.diff_qty,
            "系统基准": (row.system_snapshot_json or {}).get("basis_label"),
            "系统库存日期": row.system_data_date,
            "上传重复": "是" if row.duplicate_in_upload else "否",
            "来源行号": "、".join(str(item) for item in (row.source_row_numbers or [])),
        }
        for row in rows
    ]
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame(payload).to_excel(writer, index=False, sheet_name="库存校验差异")
    output.seek(0)
    filename = f"{batch.batch_no}-库存校验差异.xlsx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


def _result_summary(db: Session, batch_id: int) -> dict:
    rows = db.execute(
        select(InventoryCheckResult.result_type, func.count())
        .where(InventoryCheckResult.batch_id == batch_id)
        .group_by(InventoryCheckResult.result_type)
    ).all()
    summary = {key: 0 for key in RESULT_TYPES}
    for result_type, count in rows:
        summary[result_type] = int(count or 0)
    return summary


def result_type_label(value: str) -> str:
    return {
        "quantity_mismatch": "数量不一致",
        "missing_in_system": "系统缺基准",
        "missing_in_upload": "系统有平台无",
        "missing_product_master": "待补商品档案",
        "invalid_row": "无效行",
    }.get(value, value)

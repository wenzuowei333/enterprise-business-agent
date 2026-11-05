from __future__ import annotations

import io
import json
from collections import defaultdict
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.dependencies import require_any_permission, require_permission
from app.core.config import settings
from app.core.database import get_db
from app.models import DeliveryAttachment, DeliveryTask, SalesOrder, User
from app.schemas.fulfillment import (
    DeliveryAttachmentPublic,
    DeliveryEventCreate,
    DeliveryTaskPublic,
    SalesOrderCreate,
    SalesOrderCancel,
    SalesOrderImportResult,
    SalesOrderPublic,
    SalesOrderUpdate,
    TemporaryOrderRequirement,
)
from app.services.fulfillment_service import (
    apply_delivery_event,
    cancel_order,
    confirm_order,
    create_order,
    refresh_order_requirements,
    serialize_delivery,
    serialize_order,
    update_order,
)


router = APIRouter(prefix="/fulfillment", tags=["fulfillment"])
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024


def _order_or_404(db: Session, order_id: int) -> SalesOrder:
    row = db.get(SalesOrder, order_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sales order not found")
    return row


def _delivery_or_404(db: Session, delivery_id: int) -> DeliveryTask:
    row = db.get(DeliveryTask, delivery_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delivery task not found")
    return row


@router.get("/orders")
def list_orders(
    q: str | None = None,
    status_value: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("sales_order.view")),
) -> dict[str, Any]:
    safe_limit = max(1, min(limit, 200))
    safe_offset = max(0, offset)
    stmt = select(SalesOrder).order_by(SalesOrder.id.desc())
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(SalesOrder.order_no.ilike(like), SalesOrder.external_order_no.ilike(like), SalesOrder.customer_code.ilike(like), SalesOrder.customer_name_snapshot.ilike(like)))
    if status_value:
        stmt = stmt.where(SalesOrder.status == status_value)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = list(db.scalars(stmt.offset(safe_offset).limit(safe_limit)).all())
    return {"items": [serialize_order(db, row) for row in rows], "total": total, "limit": safe_limit, "offset": safe_offset}


@router.post("/orders", response_model=SalesOrderPublic, status_code=status.HTTP_201_CREATED)
def add_order(
    payload: SalesOrderCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("sales_order.create")),
) -> dict[str, Any]:
    row = create_order(db, payload=payload, operator=current_user, source="web", request=request)
    db.commit()
    db.refresh(row)
    return serialize_order(db, row)


def _cell(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None and not pd.isna(value) and str(value).strip():
            return value
    return None


@router.post("/orders/import", response_model=SalesOrderImportResult)
def import_orders(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("sales_order.import")),
) -> SalesOrderImportResult:
    content = file.file.read()
    try:
        frame = pd.read_excel(io.BytesIO(content), dtype=object)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unable to read order workbook: {exc}") from exc
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    records = frame.fillna("").to_dict(orient="records")
    for index, raw in enumerate(records, start=2):
        row = dict(raw)
        external_no = str(_cell(row, "外部订单号", "订单号", "external_order_no") or f"ROW-{index}").strip()
        grouped[external_no].append(row)
    imported_orders = 0
    imported_lines = 0
    errors: list[dict[str, Any]] = []
    for external_no, rows in grouped.items():
        first = rows[0]
        try:
            temporary_raw = _cell(first, "临时配送要求", "temporary_requirements")
            temporary_values = json.loads(str(temporary_raw)) if temporary_raw else []
            planned_raw = _cell(first, "计划配送时间", "planned_delivery_at")
            planned = pd.to_datetime(planned_raw).to_pydatetime() if planned_raw else None
            payload = SalesOrderCreate(
                external_order_no=external_no,
                customer_code=str(_cell(first, "客户编号", "customer_code") or "").strip(),
                planned_delivery_at=planned,
                delivery_address=_cell(first, "配送地址", "delivery_address"),
                temporary_requirements=[TemporaryOrderRequirement.model_validate(item) for item in temporary_values],
                lines=[
                    {
                        "product_code": _cell(row, "商品编号", "product_code"),
                        "product_name": str(_cell(row, "商品名称", "product_name") or "").strip(),
                        "quantity": _cell(row, "数量", "quantity"),
                        "unit": _cell(row, "单位", "unit"),
                        "remark": _cell(row, "备注", "remark"),
                    }
                    for row in rows
                ],
            )
            with db.begin_nested():
                create_order(db, payload=payload, operator=current_user, source="excel", request=request)
            imported_orders += 1
            imported_lines += len(payload.lines)
        except Exception as exc:
            errors.append({"external_order_no": external_no, "message": str(exc)})
    db.commit()
    return SalesOrderImportResult(imported_orders=imported_orders, imported_lines=imported_lines, errors=errors)


@router.get("/orders/{order_id}", response_model=SalesOrderPublic)
def get_order(
    order_id: int,
    include_requirement_diff: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("sales_order.view")),
) -> dict[str, Any]:
    return serialize_order(db, _order_or_404(db, order_id), include_diff=include_requirement_diff)


@router.patch("/orders/{order_id}", response_model=SalesOrderPublic)
def edit_order(
    order_id: int,
    payload: SalesOrderUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("sales_order.edit")),
) -> dict[str, Any]:
    row = update_order(db, order=_order_or_404(db, order_id), payload=payload, operator=current_user, request=request)
    db.commit()
    db.refresh(row)
    return serialize_order(db, row)


@router.post("/orders/{order_id}/confirm", response_model=SalesOrderPublic)
def confirm_sales_order(
    order_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("sales_order.confirm")),
) -> dict[str, Any]:
    order = _order_or_404(db, order_id)
    confirm_order(db, order=order, operator=current_user, request=request)
    db.commit()
    db.refresh(order)
    return serialize_order(db, order)


@router.post("/orders/{order_id}/cancel", response_model=SalesOrderPublic)
def cancel_sales_order(
    order_id: int,
    payload: SalesOrderCancel,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("sales_order.edit", "sales_order.confirm")),
) -> dict[str, Any]:
    order = _order_or_404(db, order_id)
    cancel_order(db, order=order, operator=current_user, reason=payload.reason, request=request)
    db.commit()
    db.refresh(order)
    return serialize_order(db, order)


@router.post("/orders/{order_id}/refresh-requirements", response_model=SalesOrderPublic)
def refresh_requirements(
    order_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("sales_order.confirm")),
) -> dict[str, Any]:
    order = _order_or_404(db, order_id)
    diff = refresh_order_requirements(db, order=order, operator=current_user, request=request)
    db.commit()
    db.refresh(order)
    result = serialize_order(db, order)
    result["requirement_diff"] = diff
    return result


@router.get("/deliveries")
def list_deliveries(
    status_value: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("delivery.view")),
) -> dict[str, Any]:
    safe_limit = max(1, min(limit, 200))
    safe_offset = max(0, offset)
    stmt = select(DeliveryTask).order_by(DeliveryTask.id.desc())
    if status_value:
        stmt = stmt.where(DeliveryTask.status == status_value)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = list(db.scalars(stmt.offset(safe_offset).limit(safe_limit)).all())
    return {"items": [serialize_delivery(db, row) for row in rows], "total": total, "limit": safe_limit, "offset": safe_offset}


@router.get("/deliveries/{delivery_id}", response_model=DeliveryTaskPublic)
def get_delivery(
    delivery_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("delivery.view")),
) -> dict[str, Any]:
    return serialize_delivery(db, _delivery_or_404(db, delivery_id))


@router.post("/deliveries/{delivery_id}/events", response_model=DeliveryTaskPublic)
def add_delivery_event(
    delivery_id: int,
    payload: DeliveryEventCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("delivery.manage")),
) -> dict[str, Any]:
    delivery = _delivery_or_404(db, delivery_id)
    apply_delivery_event(db, delivery=delivery, payload=payload, operator=current_user, request=request)
    db.commit()
    db.refresh(delivery)
    return serialize_delivery(db, delivery)


def _upload_root() -> Path:
    root = Path(settings.upload_root)
    if not root.is_absolute():
        root = (Path(__file__).resolve().parents[3] / root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


@router.post("/deliveries/{delivery_id}/attachments", response_model=DeliveryAttachmentPublic, status_code=status.HTTP_201_CREATED)
def upload_delivery_attachment(
    delivery_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("delivery.manage")),
) -> DeliveryAttachment:
    delivery = _delivery_or_404(db, delivery_id)
    content = file.file.read(MAX_ATTACHMENT_BYTES + 1)
    if len(content) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Attachment exceeds 20MB")
    name = Path(file.filename or "delivery-attachment").name
    relative = Path("delivery_attachments") / str(delivery.id) / f"{uuid4().hex}_{name}"
    target = _upload_root() / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    row = DeliveryAttachment(delivery_id=delivery.id, file_name=name, content_type=file.content_type, size_bytes=len(content), storage_path=str(relative), created_by_user_id=current_user.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _attachment_target(row: DeliveryAttachment) -> Path:
    root = _upload_root().resolve()
    target = (root / row.storage_path).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delivery attachment not found") from exc
    if not target.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delivery attachment file not found")
    return target


@router.get("/deliveries/{delivery_id}/attachments/{attachment_id}/download")
def download_delivery_attachment(
    delivery_id: int,
    attachment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("delivery.view")),
) -> FileResponse:
    row = db.get(DeliveryAttachment, attachment_id)
    if row is None or row.delivery_id != delivery_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delivery attachment not found")
    return FileResponse(_attachment_target(row), media_type=row.content_type, filename=row.file_name)

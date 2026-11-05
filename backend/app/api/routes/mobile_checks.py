from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.api.routes.imports import commit_import_batch, upload_import_file, validate_import_batch
from app.api.routes.inventory_check import list_inventory_check_batches, list_inventory_check_results, upload_inventory_check_batch
from app.api.routes.receivables import list_receivable_check_results, receivable_timeline
from app.core.database import get_db
from app.models import User
from app.services.permission_service import has_permission

router = APIRouter(prefix="/mobile/checks", tags=["mobile-checks"])
ALLOWED_SUFFIXES = {".xls", ".xlsx", ".csv"}
MAX_UPLOAD_BYTES = 30 * 1024 * 1024


def _require(db: Session, user: User, code: str) -> None:
    if not has_permission(db, user, code):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权使用该核验能力")


def _validate_file(file: UploadFile) -> None:
    if Path(file.filename or "").suffix.lower() not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅支持 xls、xlsx、csv 文件")
    if file.size is not None and file.size > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件不能超过 30MB")


@router.post("/inventory/batches", status_code=status.HTTP_201_CREATED)
def mobile_upload_inventory_check(
    file: UploadFile = File(...),
    data_date: date | None = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require(db, current_user, "inventory_check.upload")
    _validate_file(file)
    return upload_inventory_check_batch(data_date=data_date, file=file, db=db, current_user=current_user)


@router.get("/inventory/batches")
def mobile_inventory_check_batches(
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require(db, current_user, "inventory_check.view")
    return list_inventory_check_batches(limit=limit, offset=offset, db=db, current_user=current_user)


@router.get("/inventory/batches/{batch_id}/results")
def mobile_inventory_check_results(
    batch_id: int,
    result_type: str | None = Query(None, alias="type"),
    q: str | None = None,
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require(db, current_user, "inventory_check.view")
    return list_inventory_check_results(batch_id=batch_id, type=result_type, q=q, limit=limit, offset=offset, db=db, current_user=current_user)


@router.post("/receivable/uploads", status_code=status.HTTP_201_CREATED)
def mobile_upload_receivable_check(
    file: UploadFile = File(...),
    data_date: date | None = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    _require(db, current_user, "receivable.import")
    _validate_file(file)
    return upload_import_file(file_type="receivable_snapshot", data_date=data_date, file=file, db=db, current_user=current_user)


@router.post("/receivable/uploads/{batch_id}/validate")
def mobile_validate_receivable_check(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    _require(db, current_user, "receivable.import")
    return validate_import_batch(batch_id=batch_id, db=db, current_user=current_user)


@router.post("/receivable/uploads/{batch_id}/commit")
def mobile_commit_receivable_check(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    _require(db, current_user, "receivable.import")
    return commit_import_batch(batch_id=batch_id, db=db, current_user=current_user)


@router.get("/receivable/results")
def mobile_receivable_check_results(
    result_type: str | None = None,
    q: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require(db, current_user, "receivable.view")
    return list_receivable_check_results(result_type=result_type, q=q, date_from=date_from, date_to=date_to, limit=limit, offset=offset, db=db, current_user=current_user)


@router.get("/receivable/timeline")
def mobile_receivable_timeline(
    customer_code: str | None = None,
    customer_name: str | None = None,
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require(db, current_user, "receivable.view")
    return receivable_timeline(customer_code=customer_code, customer_name=customer_name, limit=limit, db=db, current_user=current_user)

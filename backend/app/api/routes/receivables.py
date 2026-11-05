from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO
from urllib.parse import quote

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.dependencies import require_permission
from app.core.database import get_db
from app.models import ReceivableCheckResult, ReceivableSnapshot, User
from app.services.audit_service import write_audit_log
from app.services.receivable_service import RECEIVABLE_RESULT_TYPES, rebuild_receivable_checks, receivable_summary

router = APIRouter(prefix="/receivables", tags=["receivables"])


def _safe_limit(limit: int) -> int:
    return max(1, min(limit, 200))


def _safe_offset(offset: int) -> int:
    return max(0, offset)


def _count(db: Session, stmt) -> int:
    return db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0


@router.get("/summary")
def get_receivable_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("receivable.view")),
) -> dict:
    return receivable_summary(db)


@router.get("/page")
def list_receivables_page(
    q: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    customer_code: str | None = None,
    customer_name: str | None = None,
    salesperson_name: str | None = None,
    match_status: str | None = None,
    risk_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("receivable.view")),
) -> dict:
    safe_limit = _safe_limit(limit)
    safe_offset = _safe_offset(offset)
    stmt = select(ReceivableSnapshot)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                ReceivableSnapshot.customer_code.ilike(like),
                ReceivableSnapshot.customer_name.ilike(like),
                ReceivableSnapshot.matched_customer_code.ilike(like),
                ReceivableSnapshot.matched_customer_name.ilike(like),
                ReceivableSnapshot.salesperson_name.ilike(like),
            )
        )
    if date_from:
        stmt = stmt.where(ReceivableSnapshot.data_date >= date_from)
    if date_to:
        stmt = stmt.where(ReceivableSnapshot.data_date <= date_to)
    if customer_code:
        stmt = stmt.where(or_(ReceivableSnapshot.customer_code == customer_code, ReceivableSnapshot.matched_customer_code == customer_code))
    if customer_name:
        like = f"%{customer_name.strip()}%"
        stmt = stmt.where(or_(ReceivableSnapshot.customer_name.ilike(like), ReceivableSnapshot.matched_customer_name.ilike(like)))
    if salesperson_name:
        stmt = stmt.where(ReceivableSnapshot.salesperson_name.ilike(f"%{salesperson_name.strip()}%"))
    if match_status:
        stmt = stmt.where(ReceivableSnapshot.match_status == match_status)
    if risk_type:
        if risk_type not in RECEIVABLE_RESULT_TYPES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid risk type")
        risky_ids = select(ReceivableCheckResult.receivable_snapshot_id).where(ReceivableCheckResult.result_type == risk_type)
        stmt = stmt.where(ReceivableSnapshot.id.in_(risky_ids))

    total = _count(db, stmt)
    rows = list(
        db.scalars(
            stmt.order_by(
                ReceivableSnapshot.data_date.desc().nullslast(),
                ReceivableSnapshot.ar_balance.desc().nullslast(),
                ReceivableSnapshot.id.desc(),
            )
            .offset(safe_offset)
            .limit(safe_limit)
        ).all()
    )
    return {
        "items": [_receivable_public(row) for row in rows],
        "total": total,
        "limit": safe_limit,
        "offset": safe_offset,
        "summary": receivable_summary(db),
    }


@router.get("/timeline")
def receivable_timeline(
    customer_code: str | None = None,
    customer_name: str | None = None,
    limit: int = 30,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("receivable.view")),
) -> dict:
    if not customer_code and not customer_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="customer_code or customer_name is required")
    safe_limit = _safe_limit(limit)
    stmt = select(ReceivableSnapshot)
    if customer_code:
        stmt = stmt.where(or_(ReceivableSnapshot.customer_code == customer_code, ReceivableSnapshot.matched_customer_code == customer_code))
    if customer_name:
        like = f"%{customer_name.strip()}%"
        stmt = stmt.where(or_(ReceivableSnapshot.customer_name.ilike(like), ReceivableSnapshot.matched_customer_name.ilike(like)))
    rows = list(db.scalars(stmt.order_by(ReceivableSnapshot.data_date.desc().nullslast(), ReceivableSnapshot.id.desc()).limit(safe_limit)).all())
    return {"items": [_receivable_public(row) for row in rows], "total": len(rows), "limit": safe_limit}


@router.get("/check-results")
def list_receivable_check_results(
    result_type: str | None = None,
    q: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("receivable.view")),
) -> dict:
    safe_limit = _safe_limit(limit)
    safe_offset = _safe_offset(offset)
    stmt = _check_results_stmt(result_type=result_type, q=q, date_from=date_from, date_to=date_to)
    total = _count(db, stmt)
    rows = list(
        db.scalars(
            stmt.order_by(
                ReceivableCheckResult.severity.desc(),
                ReceivableCheckResult.data_date.desc().nullslast(),
                ReceivableCheckResult.result_type,
                ReceivableCheckResult.id.desc(),
            )
            .offset(safe_offset)
            .limit(safe_limit)
        ).all()
    )
    return {
        "items": [_check_result_public(row) for row in rows],
        "total": total,
        "limit": safe_limit,
        "offset": safe_offset,
        "summary": _check_result_summary(db, result_type=result_type, q=q, date_from=date_from, date_to=date_to),
    }


@router.post("/rebuild-check")
def rebuild_receivable_check_results(
    request: Request,
    batch_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("receivable.check")),
) -> dict:
    summary = rebuild_receivable_checks(db, batch_id=batch_id)
    from app.services.exception_center_service import enqueue_incremental_exception_scan_safely

    enqueue_incremental_exception_scan_safely(db, domains=["receivable"])
    write_audit_log(
        db,
        action_type="rebuild_receivable_check",
        resource_type="receivable",
        resource_id=str(batch_id or "all"),
        user=current_user,
        request=request,
        after_data=summary,
    )
    db.commit()
    return summary


@router.get("/check-results/export")
def export_receivable_check_results(
    result_type: str | None = None,
    q: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("receivable.export")),
) -> StreamingResponse:
    rows = list(
        db.scalars(
            _check_results_stmt(result_type=result_type, q=q, date_from=date_from, date_to=date_to).order_by(
                ReceivableCheckResult.data_date.desc().nullslast(),
                ReceivableCheckResult.result_type,
                ReceivableCheckResult.id.desc(),
            )
        ).all()
    )
    payload = [
        {
            "差异类型": result_type_label(row.result_type),
            "严重程度": "高" if row.severity == "danger" else "关注",
            "数据日期": row.data_date,
            "结算单位编号": row.matched_customer_code or row.customer_code,
            "结算单位名称": row.matched_customer_name or row.customer_name,
            "应收查询金额": row.receivable_ar_balance,
            "往来明细应收": row.account_ar_balance,
            "差异金额": row.diff_amount,
            "说明": row.message,
        }
        for row in rows
    ]
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame(payload).to_excel(writer, index=False, sheet_name="应收校验差异")
    output.seek(0)
    filename = "应收校验差异.xlsx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


def _check_results_stmt(
    *,
    result_type: str | None = None,
    q: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
):
    stmt = select(ReceivableCheckResult)
    if result_type:
        if result_type not in RECEIVABLE_RESULT_TYPES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid result type")
        stmt = stmt.where(ReceivableCheckResult.result_type == result_type)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                ReceivableCheckResult.customer_code.ilike(like),
                ReceivableCheckResult.customer_name.ilike(like),
                ReceivableCheckResult.matched_customer_code.ilike(like),
                ReceivableCheckResult.matched_customer_name.ilike(like),
            )
        )
    if date_from:
        stmt = stmt.where(ReceivableCheckResult.data_date >= date_from)
    if date_to:
        stmt = stmt.where(ReceivableCheckResult.data_date <= date_to)
    return stmt


def _check_result_summary(db: Session, **filters) -> dict:
    filtered = _check_results_stmt(**filters).order_by(None).subquery()
    rows = db.execute(select(filtered.c.result_type, func.count()).group_by(filtered.c.result_type)).all()
    summary = {key: 0 for key in RECEIVABLE_RESULT_TYPES}
    for result_type, count in rows:
        summary[result_type] = int(count or 0)
    summary["total"] = sum(summary.values())
    return summary


def _receivable_public(row: ReceivableSnapshot) -> dict:
    return {
        "id": row.id,
        "batch_id": row.batch_id,
        "row_number": row.row_number,
        "data_date": row.data_date.isoformat() if row.data_date else None,
        "customer_code": row.customer_code,
        "customer_name": row.customer_name,
        "matched_customer_code": row.matched_customer_code,
        "matched_customer_name": row.matched_customer_name,
        "match_status": row.match_status,
        "ar_opening_balance": _jsonable(row.ar_opening_balance),
        "ar_current_amount": _jsonable(row.ar_current_amount),
        "received_amount": _jsonable(row.received_amount),
        "unreceived_amount": _jsonable(row.unreceived_amount),
        "ar_balance": _jsonable(row.ar_balance),
        "aging_label": row.aging_label,
        "overdue_days": row.overdue_days,
        "salesperson_name": row.salesperson_name,
        "department_name": row.department_name,
        "remark": row.remark,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _check_result_public(row: ReceivableCheckResult) -> dict:
    return {
        "id": row.id,
        "batch_id": row.batch_id,
        "receivable_snapshot_id": row.receivable_snapshot_id,
        "result_type": row.result_type,
        "result_label": result_type_label(row.result_type),
        "severity": row.severity,
        "data_date": row.data_date.isoformat() if row.data_date else None,
        "customer_code": row.customer_code,
        "customer_name": row.customer_name,
        "matched_customer_code": row.matched_customer_code,
        "matched_customer_name": row.matched_customer_name,
        "receivable_ar_balance": _jsonable(row.receivable_ar_balance),
        "account_ar_balance": _jsonable(row.account_ar_balance),
        "previous_ar_balance": _jsonable(row.previous_ar_balance),
        "diff_amount": _jsonable(row.diff_amount),
        "overdue_days": row.overdue_days,
        "recent_sales_amount": _jsonable(row.recent_sales_amount),
        "message": row.message,
        "source_json": row.source_json,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def result_type_label(value: str) -> str:
    return {
        "amount_mismatch": "金额不一致",
        "missing_in_ledger": "往来明细缺失",
        "missing_in_receivable_query": "应收查询缺失",
        "unit_name_mismatch": "名称不一致",
        "duplicate_unit": "重复结算单位",
    }.get(value, value)


def _jsonable(value):
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    return value

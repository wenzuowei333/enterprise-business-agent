from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.api.dependencies import require_permission
from app.core.database import get_db
from app.models import AccountLedgerEntry, DataCalendarRule, ImportBatch, ImportError, PurchaseDetail, SalesDetail, User
from app.schemas.master_data import (
    DataCalendarCoveragePublic,
    DataCalendarReminderRequest,
    DataCalendarReminderResponse,
    DataCalendarRulePublic,
    DataCalendarRuleUpdate,
    ImportBatchPublic,
    ImportErrorPublic,
    MasterLinkIssuePublic,
)
from app.services.audit_service import write_audit_log
from app.services.import_service import UploadStorageError, create_batch_from_upload, validate_batch, commit_batch, required_file_type_import_permission
from app.services.master_link_service import rebuild_batch_master_link_issues
from app.services.permission_service import has_permission

router = APIRouter(prefix="/import", tags=["import"])


DEFAULT_DATA_CALENDAR_RULES: list[dict] = [
    {"rule_code": "daily_sales_detail", "file_type": "sales_detail", "label": "销售统计明细", "action_layer": "blue", "frequency": "daily", "deadline_hour": 18, "owner_role": "数据中台", "is_required": True, "is_enabled": True, "sort_order": 10, "remark": "每日销售过程数据。"},
    {"rule_code": "daily_purchase_detail", "file_type": "purchase_detail", "label": "采购明细", "action_layer": "blue", "frequency": "daily", "deadline_hour": 18, "owner_role": "数据中台", "is_required": True, "is_enabled": True, "sort_order": 20, "remark": "每日采购过程数据。"},
    {"rule_code": "daily_account_ledger", "file_type": "account_ledger", "label": "往来明细", "action_layer": "blue", "frequency": "daily", "deadline_hour": 18, "owner_role": "数据中台", "is_required": True, "is_enabled": True, "sort_order": 30, "remark": "每日往来明细过程数据。"},
    {"rule_code": "ondemand_employee_profile", "file_type": "employee_profile", "label": "员工档案", "action_layer": "gray", "frequency": "ondemand", "deadline_hour": None, "owner_role": "数据中台", "is_required": False, "is_enabled": True, "sort_order": 110, "remark": "按需补录或批量更新。"},
    {"rule_code": "ondemand_customer_master", "file_type": "customer_master", "label": "客户档案", "action_layer": "gray", "frequency": "ondemand", "deadline_hour": None, "owner_role": "数据中台", "is_required": False, "is_enabled": True, "sort_order": 120, "remark": "按需补录或批量更新。"},
    {"rule_code": "ondemand_product_master", "file_type": "product_master", "label": "商品档案", "action_layer": "gray", "frequency": "ondemand", "deadline_hour": None, "owner_role": "数据中台", "is_required": False, "is_enabled": True, "sort_order": 130, "remark": "按需补录或批量更新。"},
    {"rule_code": "ondemand_supplier_master", "file_type": "supplier_master", "label": "供应商档案", "action_layer": "gray", "frequency": "ondemand", "deadline_hour": None, "owner_role": "数据中台", "is_required": False, "is_enabled": True, "sort_order": 140, "remark": "按需补录或批量更新。"},
]


VALID_CALENDAR_LAYERS = {"blue", "green", "orange", "red", "gray"}
VALID_CALENDAR_FREQUENCIES = {"daily", "ondemand"}


def ensure_file_type_import_permission(db: Session, user: User, file_type: str | None) -> None:
    permission_code = required_file_type_import_permission(file_type)
    if permission_code and not has_permission(db, user, permission_code):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing permission: {permission_code}",
        )


def ensure_default_calendar_rules(db: Session) -> None:
    existing_codes = set(db.scalars(select(DataCalendarRule.rule_code)).all())
    for rule in DEFAULT_DATA_CALENDAR_RULES:
        if rule["rule_code"] not in existing_codes:
            db.add(DataCalendarRule(**rule))
    db.flush()


def validate_calendar_rule(payload: DataCalendarRuleUpdate) -> None:
    if payload.action_layer not in VALID_CALENDAR_LAYERS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid action layer")
    if payload.frequency not in VALID_CALENDAR_FREQUENCIES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid frequency")
    if payload.frequency == "daily" and payload.deadline_hour is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Daily rule requires deadline_hour")
    if payload.deadline_hour is not None and not 0 <= payload.deadline_hour <= 23:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="deadline_hour must be between 0 and 23")


def list_calendar_rules_for_response(db: Session) -> list[DataCalendarRule]:
    ensure_default_calendar_rules(db)
    return list(db.scalars(select(DataCalendarRule).order_by(DataCalendarRule.sort_order, DataCalendarRule.id)).all())


@router.post("/upload", response_model=ImportBatchPublic, status_code=status.HTTP_201_CREATED)
def upload_import_file(
    file_type: str = Form(...),
    data_date: date | None = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("import.upload")),
) -> ImportBatch:
    ensure_file_type_import_permission(db, current_user, file_type)
    try:
        batch = create_batch_from_upload(db, file=file, file_type=file_type, data_date=data_date, user=current_user)
        ensure_file_type_import_permission(db, current_user, batch.file_type)
        from app.services.exception_center_service import enqueue_incremental_exception_scan_safely

        enqueue_incremental_exception_scan_safely(
            db,
            domains=["import"],
            source_batch_kind="import",
            source_batch_id=batch.id,
        )
    except UploadStorageError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.commit()
    db.refresh(batch)
    return batch


@router.get("/calendar-rules", response_model=list[DataCalendarRulePublic])
def list_data_calendar_rules(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("import.view")),
) -> list[DataCalendarRule]:
    return list_calendar_rules_for_response(db)


@router.put("/calendar-rules", response_model=list[DataCalendarRulePublic])
def save_data_calendar_rules(
    payload: list[DataCalendarRuleUpdate],
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("import.commit")),
) -> list[DataCalendarRule]:
    if not payload:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Rules cannot be empty")
    seen_codes: set[str] = set()
    existing = {rule.rule_code: rule for rule in db.scalars(select(DataCalendarRule)).all()}
    for item in payload:
        validate_calendar_rule(item)
        if item.rule_code in seen_codes:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Duplicate rule_code: {item.rule_code}")
        seen_codes.add(item.rule_code)
        rule = existing.get(item.rule_code)
        values = item.model_dump()
        values.pop("id", None)
        if rule is None:
            db.add(DataCalendarRule(**values))
            continue
        for key, value in values.items():
            setattr(rule, key, value)
    db.commit()
    return list_calendar_rules_for_response(db)


@router.post("/calendar-rules/reset", response_model=list[DataCalendarRulePublic])
def reset_data_calendar_rules(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("import.commit")),
) -> list[DataCalendarRule]:
    existing = {rule.rule_code: rule for rule in db.scalars(select(DataCalendarRule)).all()}
    for defaults in DEFAULT_DATA_CALENDAR_RULES:
        rule = existing.get(defaults["rule_code"])
        if rule is None:
            db.add(DataCalendarRule(**defaults))
            continue
        for key, value in defaults.items():
            setattr(rule, key, value)
    db.commit()
    return list_calendar_rules_for_response(db)


@router.post("/calendar-reminders", response_model=DataCalendarReminderResponse)
def create_data_calendar_reminder(
    payload: DataCalendarReminderRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("import.commit")),
) -> DataCalendarReminderResponse:
    if not payload.items:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Reminder items cannot be empty")
    resource_id = payload.data_date.isoformat()
    audit = write_audit_log(
        db,
        action_type="send_data_calendar_reminder",
        resource_type="data_calendar",
        resource_id=resource_id,
        user=current_user,
        request=request,
        after_data={
            "data_date": resource_id,
            "reminder_type": payload.reminder_type,
            "message": payload.message,
            "items": [item.model_dump() for item in payload.items],
            "reminder_count": len(payload.items),
        },
    )
    db.flush()
    audit_id = audit.id
    db.commit()
    return DataCalendarReminderResponse(
        status="recorded",
        audit_id=audit_id,
        resource_id=resource_id,
        reminder_count=len(payload.items),
    )


def collect_document_date_coverage(
    db: Session,
    *,
    model,
    file_type: str,
    from_date: date,
    to_date: date,
) -> list[DataCalendarCoveragePublic]:
    stmt = (
        select(
            model.document_date.label("data_date"),
            model.batch_id.label("batch_id"),
            ImportBatch.batch_no.label("batch_no"),
            ImportBatch.uploaded_by.label("uploaded_by"),
            ImportBatch.uploaded_at.label("uploaded_at"),
            func.count(model.id).label("row_count"),
        )
        .join(ImportBatch, ImportBatch.id == model.batch_id)
        .where(
            model.document_date.is_not(None),
            model.document_date >= from_date,
            model.document_date <= to_date,
            ImportBatch.file_type == file_type,
            ImportBatch.status == "committed",
        )
        .group_by(model.document_date, model.batch_id, ImportBatch.batch_no, ImportBatch.uploaded_by, ImportBatch.uploaded_at)
        .order_by(model.document_date, ImportBatch.uploaded_at)
    )
    grouped: dict[date, dict] = {}
    for row in db.execute(stmt).mappings():
        data_date_value = row["data_date"]
        if data_date_value is None:
            continue
        item = grouped.setdefault(
            data_date_value,
            {
                "data_date": data_date_value,
                "file_type": file_type,
                "status": "complete",
                "row_count": 0,
                "batch_ids": [],
                "batch_nos": [],
                "latest_batch_id": None,
                "latest_batch_no": None,
                "latest_uploaded_by": None,
                "latest_uploaded_at": None,
                "source": "document_date",
            },
        )
        item["row_count"] += int(row["row_count"] or 0)
        batch_id = int(row["batch_id"])
        if batch_id not in item["batch_ids"]:
            item["batch_ids"].append(batch_id)
        batch_no = str(row["batch_no"])
        if batch_no not in item["batch_nos"]:
            item["batch_nos"].append(batch_no)
        uploaded_at = row["uploaded_at"]
        if item["latest_uploaded_at"] is None or (uploaded_at is not None and uploaded_at > item["latest_uploaded_at"]):
            item["latest_uploaded_at"] = uploaded_at
            item["latest_batch_id"] = batch_id
            item["latest_batch_no"] = batch_no
            item["latest_uploaded_by"] = row["uploaded_by"]

    coverage: list[DataCalendarCoveragePublic] = []
    for item in grouped.values():
        item.pop("latest_uploaded_at", None)
        coverage.append(DataCalendarCoveragePublic(**item))
    return coverage


def collect_batch_date_coverage(
    db: Session,
    *,
    file_types: list[str],
    from_date: date,
    to_date: date,
) -> list[DataCalendarCoveragePublic]:
    if not file_types:
        return []
    stmt = (
        select(
            ImportBatch.data_date.label("data_date"),
            ImportBatch.file_type.label("file_type"),
            ImportBatch.id.label("batch_id"),
            ImportBatch.batch_no.label("batch_no"),
            ImportBatch.uploaded_by.label("uploaded_by"),
            ImportBatch.uploaded_at.label("uploaded_at"),
            ImportBatch.success_rows.label("row_count"),
        )
        .where(
            ImportBatch.data_date.is_not(None),
            ImportBatch.data_date >= from_date,
            ImportBatch.data_date <= to_date,
            ImportBatch.file_type.in_(file_types),
            ImportBatch.status == "committed",
        )
        .order_by(ImportBatch.data_date, ImportBatch.file_type, ImportBatch.uploaded_at)
    )
    grouped: dict[tuple[date, str], dict] = {}
    for row in db.execute(stmt).mappings():
        data_date_value = row["data_date"]
        file_type_value = str(row["file_type"])
        if data_date_value is None:
            continue
        item = grouped.setdefault(
            (data_date_value, file_type_value),
            {
                "data_date": data_date_value,
                "file_type": file_type_value,
                "status": "complete",
                "row_count": 0,
                "batch_ids": [],
                "batch_nos": [],
                "latest_batch_id": None,
                "latest_batch_no": None,
                "latest_uploaded_by": None,
                "latest_uploaded_at": None,
                "source": "batch_date",
            },
        )
        item["row_count"] += int(row["row_count"] or 0)
        batch_id = int(row["batch_id"])
        if batch_id not in item["batch_ids"]:
            item["batch_ids"].append(batch_id)
        batch_no = str(row["batch_no"])
        if batch_no not in item["batch_nos"]:
            item["batch_nos"].append(batch_no)
        uploaded_at = row["uploaded_at"]
        if item["latest_uploaded_at"] is None or (uploaded_at is not None and uploaded_at > item["latest_uploaded_at"]):
            item["latest_uploaded_at"] = uploaded_at
            item["latest_batch_id"] = batch_id
            item["latest_batch_no"] = batch_no
            item["latest_uploaded_by"] = row["uploaded_by"]

    coverage: list[DataCalendarCoveragePublic] = []
    for item in grouped.values():
        item.pop("latest_uploaded_at", None)
        coverage.append(DataCalendarCoveragePublic(**item))
    return coverage


def iter_dates(start_date: date, end_date: date):
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)


def merge_account_ledger_coverage_item(
    grouped: dict[date, dict],
    *,
    data_date_value: date,
    batch_id: int,
    batch_no: str,
    uploaded_by: int | None,
    uploaded_at: datetime | None,
    row_count: int,
    source: str,
) -> None:
    item = grouped.setdefault(
        data_date_value,
        {
            "data_date": data_date_value,
            "file_type": "account_ledger",
            "status": "complete",
            "row_count": 0,
            "batch_ids": [],
            "batch_nos": [],
            "latest_batch_id": None,
            "latest_batch_no": None,
            "latest_uploaded_by": None,
            "latest_uploaded_at": None,
            "source": source,
        },
    )
    item["row_count"] += row_count
    if batch_id not in item["batch_ids"]:
        item["batch_ids"].append(batch_id)
    if batch_no not in item["batch_nos"]:
        item["batch_nos"].append(batch_no)
    if item["latest_uploaded_at"] is None or (uploaded_at is not None and uploaded_at > item["latest_uploaded_at"]):
        item["latest_uploaded_at"] = uploaded_at
        item["latest_batch_id"] = batch_id
        item["latest_batch_no"] = batch_no
        item["latest_uploaded_by"] = uploaded_by


def collect_account_ledger_coverage(
    db: Session,
    *,
    from_date: date,
    to_date: date,
) -> list[DataCalendarCoveragePublic]:
    period_stmt = (
        select(
            AccountLedgerEntry.batch_id.label("batch_id"),
            ImportBatch.batch_no.label("batch_no"),
            ImportBatch.uploaded_by.label("uploaded_by"),
            ImportBatch.uploaded_at.label("uploaded_at"),
            func.min(AccountLedgerEntry.period_start).label("period_start"),
            func.max(AccountLedgerEntry.period_end).label("period_end"),
        )
        .join(ImportBatch, ImportBatch.id == AccountLedgerEntry.batch_id)
        .where(
            ImportBatch.file_type == "account_ledger",
            ImportBatch.status == "committed",
            AccountLedgerEntry.period_start.is_not(None),
            AccountLedgerEntry.period_end.is_not(None),
            AccountLedgerEntry.period_start <= to_date,
            AccountLedgerEntry.period_end >= from_date,
        )
        .group_by(AccountLedgerEntry.batch_id, ImportBatch.batch_no, ImportBatch.uploaded_by, ImportBatch.uploaded_at)
        .order_by(AccountLedgerEntry.batch_id)
    )
    grouped: dict[date, dict] = {}
    for row in db.execute(period_stmt).mappings():
        period_start = row["period_start"]
        period_end = row["period_end"]
        if period_start is None or period_end is None:
            continue
        start = max(period_start, from_date)
        end = min(period_end, to_date)
        for data_date_value in iter_dates(start, end):
            merge_account_ledger_coverage_item(
                grouped,
                data_date_value=data_date_value,
                batch_id=int(row["batch_id"]),
                batch_no=str(row["batch_no"]),
                uploaded_by=row["uploaded_by"],
                uploaded_at=row["uploaded_at"],
                row_count=0,
                source="ledger_period",
            )

    count_stmt = (
        select(
            AccountLedgerEntry.data_date.label("data_date"),
            AccountLedgerEntry.batch_id.label("batch_id"),
            ImportBatch.batch_no.label("batch_no"),
            ImportBatch.uploaded_by.label("uploaded_by"),
            ImportBatch.uploaded_at.label("uploaded_at"),
            func.count(AccountLedgerEntry.id).label("row_count"),
        )
        .join(ImportBatch, ImportBatch.id == AccountLedgerEntry.batch_id)
        .where(
            AccountLedgerEntry.data_date.is_not(None),
            AccountLedgerEntry.data_date >= from_date,
            AccountLedgerEntry.data_date <= to_date,
            ImportBatch.file_type == "account_ledger",
            ImportBatch.status == "committed",
        )
        .group_by(AccountLedgerEntry.data_date, AccountLedgerEntry.batch_id, ImportBatch.batch_no, ImportBatch.uploaded_by, ImportBatch.uploaded_at)
        .order_by(AccountLedgerEntry.data_date, ImportBatch.uploaded_at)
    )
    for row in db.execute(count_stmt).mappings():
        data_date_value = row["data_date"]
        if data_date_value is None:
            continue
        merge_account_ledger_coverage_item(
            grouped,
            data_date_value=data_date_value,
            batch_id=int(row["batch_id"]),
            batch_no=str(row["batch_no"]),
            uploaded_by=row["uploaded_by"],
            uploaded_at=row["uploaded_at"],
            row_count=int(row["row_count"] or 0),
            source="ledger_entry_date",
        )

    coverage: list[DataCalendarCoveragePublic] = []
    for item in grouped.values():
        item.pop("latest_uploaded_at", None)
        coverage.append(DataCalendarCoveragePublic(**item))
    return coverage


@router.get("/calendar-coverage", response_model=list[DataCalendarCoveragePublic])
def list_data_calendar_coverage(
    data_date_from: date,
    data_date_to: date,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("import.view")),
) -> list[DataCalendarCoveragePublic]:
    if data_date_to < data_date_from:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="data_date_to must be after data_date_from")
    if (data_date_to - data_date_from).days > 370:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Date range is too large")
    coverage: list[DataCalendarCoveragePublic] = []
    coverage.extend(collect_document_date_coverage(db, model=SalesDetail, file_type="sales_detail", from_date=data_date_from, to_date=data_date_to))
    coverage.extend(collect_document_date_coverage(db, model=PurchaseDetail, file_type="purchase_detail", from_date=data_date_from, to_date=data_date_to))
    coverage.extend(collect_account_ledger_coverage(db, from_date=data_date_from, to_date=data_date_to))
    coverage.extend(
        collect_batch_date_coverage(
            db,
            file_types=[
                "employee_profile",
                "customer_master",
                "product_master",
                "supplier_master",
            ],
            from_date=data_date_from,
            to_date=data_date_to,
        )
    )
    return sorted(coverage, key=lambda item: (item.data_date, item.file_type))


@router.get("/batches", response_model=list[ImportBatchPublic])
def list_batches(
    file_type: str | None = None,
    data_date_from: date | None = None,
    data_date_to: date | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("import.view")),
) -> list[ImportBatch]:
    stmt = select(ImportBatch).order_by(ImportBatch.id.desc())
    if file_type:
        stmt = stmt.where(ImportBatch.file_type == file_type)
    if data_date_from or data_date_to:
        from_date = data_date_from or date.min
        to_date = data_date_to or date.max
        uploaded_from = datetime.combine(from_date, time.min)
        uploaded_to = datetime.combine(to_date + timedelta(days=1), time.min) if to_date != date.max else datetime.max
        stmt = stmt.where(
            or_(
                and_(ImportBatch.data_date.is_not(None), ImportBatch.data_date >= from_date, ImportBatch.data_date <= to_date),
                and_(ImportBatch.data_date.is_(None), ImportBatch.uploaded_at >= uploaded_from, ImportBatch.uploaded_at < uploaded_to),
            )
        )
    safe_limit = max(1, min(limit, 1000))
    return list(db.scalars(stmt.limit(safe_limit)).all())


@router.get("/batches/{batch_id}", response_model=ImportBatchPublic)
def get_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("import.view")),
) -> ImportBatch:
    batch = db.get(ImportBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch not found")
    return batch


@router.post("/batches/{batch_id}/validate", response_model=ImportBatchPublic)
def validate_import_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("import.commit")),
) -> ImportBatch:
    batch = db.get(ImportBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch not found")
    ensure_file_type_import_permission(db, current_user, batch.file_type)
    validate_batch(db, batch)
    from app.services.exception_center_service import enqueue_incremental_exception_scan_safely

    enqueue_incremental_exception_scan_safely(
        db,
        domains=["import"],
        source_batch_kind="import",
        source_batch_id=batch.id,
    )
    db.commit()
    db.refresh(batch)
    return batch


@router.post("/batches/{batch_id}/commit", response_model=ImportBatchPublic)
def commit_import_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("import.commit")),
) -> ImportBatch:
    batch = db.get(ImportBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch not found")
    ensure_file_type_import_permission(db, current_user, batch.file_type)
    commit_batch(db, batch)
    db.commit()
    db.refresh(batch)
    return batch


@router.get("/batches/{batch_id}/errors", response_model=list[ImportErrorPublic])
def list_batch_errors(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("import.view")),
) -> list[ImportError]:
    stmt = select(ImportError).where(ImportError.batch_id == batch_id).order_by(ImportError.row_number, ImportError.id)
    return list(db.scalars(stmt).all())


@router.get("/batches/{batch_id}/master-link-issues", response_model=list[MasterLinkIssuePublic])
def list_batch_master_link_issues(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("import.view")),
) -> list:
    batch = db.get(ImportBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch not found")
    if batch.status == "committed":
        rebuild_batch_master_link_issues(db, batch)
        db.commit()
    from app.models import MasterLinkIssue

    stmt = (
        select(MasterLinkIssue)
        .where(MasterLinkIssue.batch_id == batch_id, MasterLinkIssue.status == "open")
        .order_by(MasterLinkIssue.issue_type, MasterLinkIssue.amount_total.desc().nullslast(), MasterLinkIssue.id)
    )
    return list(db.scalars(stmt).all())

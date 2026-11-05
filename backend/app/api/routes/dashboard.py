from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.api.routes.process_data import (
    ACCOUNT_ATTENTION_LABELS,
    INVENTORY_ATTENTION_LABELS,
    _account_attention_conditions,
    _account_ledger_summary,
    _apply_snapshot_scope,
    _attention_summary,
    _inventory_attention_conditions,
    _inventory_summary,
    _purchase_summary,
    _sales_summary,
)
from app.core.database import get_db
from app.models import (
    AccountLedgerEntry,
    AuditLog,
    CrmProject,
    CrmProjectCustomerTask,
    EmployeeProfile,
    ImportBatch,
    InventoryCheckBatch,
    InventoryFlowLedger,
    InventorySnapshot,
    ProductMaster,
    PurchaseDetail,
    SalesDetail,
    SupplierMaster,
    User,
    WorkItem,
    CustomerMaster,
)
from app.services.access_control_service import apply_data_scope
from app.services.crm_access_service import crm_project_scope_filter, crm_task_scope_filter, crm_work_item_scope_filter
from app.services.permission_service import has_permission

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

DASHBOARD_PERMISSION_CODES = (
    "dashboard.view",
    "employee.view",
    "customer.view",
    "product.view",
    "supplier.view",
    "import.view",
    "sales_detail.view",
    "inventory_snapshot.view",
    "inventory_check.view",
    "purchase_detail.view",
    "account_balance.view",
    "account_ledger.view",
    "crm_project.view",
    "crm_task.view",
    "crm_issue.view",
    "approval.view",
    "user.view",
    "audit.view",
)

RANGE_DAYS = {
    "today": 1,
    "7d": 7,
    "30d": 30,
}


@router.get("/overview")
def dashboard_overview(
    range_key: str = Query("7d", alias="range", pattern="^(today|7d|30d|month)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    if not any(has_permission(db, current_user, code) for code in DASHBOARD_PERMISSION_CODES):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing dashboard permissions")

    today = date.today()
    start_date = today.replace(day=1) if range_key == "month" else today - timedelta(days=RANGE_DAYS[range_key] - 1)
    day_labels = _day_labels(start_date, today)

    can_sales = _can(db, current_user, "sales_detail.view")
    can_inventory = _can(db, current_user, "inventory_snapshot.view")
    can_inventory_check = _can(db, current_user, "inventory_check.view")
    can_purchase = _can(db, current_user, "purchase_detail.view")
    can_account = _can(db, current_user, "account_ledger.view")
    can_import = _can(db, current_user, "import.view", "import.upload", "import.commit")
    can_crm_project = _can(db, current_user, "crm_project.view")
    can_crm_task = _can(db, current_user, "crm_task.view")
    can_crm_issue = _can(db, current_user, "crm_issue.view")
    can_master = _can(db, current_user, "employee.view", "customer.view", "product.view", "supplier.view")
    can_user = _can(db, current_user, "user.view")
    can_audit = _can(db, current_user, "audit.view")

    summaries: dict[str, dict[str, Any]] = {}
    trend_maps: dict[str, dict[str, float]] = {}

    if can_sales:
        sales_stmt = apply_data_scope(
            select(SalesDetail).where(SalesDetail.document_date >= start_date, SalesDetail.document_date <= today),
            SalesDetail,
            db,
            current_user,
            "sales_detail",
        )
        summaries["sales"] = _sales_summary(db, current_user, sales_stmt)
        trend_maps["sales"] = _daily_sum(db, sales_stmt, "document_date", "amount_tax_total")
        trend_maps["gross_profit"] = _daily_sum(db, sales_stmt, "document_date", "gross_profit")

    if can_purchase:
        purchase_stmt = apply_data_scope(
            select(PurchaseDetail).where(PurchaseDetail.document_date >= start_date, PurchaseDetail.document_date <= today),
            PurchaseDetail,
            db,
            current_user,
            "purchase_detail",
        )
        summaries["purchase"] = _purchase_summary(db, purchase_stmt)
        trend_maps["purchase"] = _daily_sum(db, purchase_stmt, "document_date", "purchase_amount")

    if can_inventory:
        inventory_current_stmt = apply_data_scope(
            select(InventorySnapshot),
            InventorySnapshot,
            db,
            current_user,
            "inventory_snapshot",
        )
        inventory_current_stmt, _inventory_batch_id = _apply_snapshot_scope(
            db,
            inventory_current_stmt,
            model=InventorySnapshot,
            file_type="inventory_snapshot",
            snapshot_scope="latest",
            batch_id=None,
        )
        summaries["inventory"] = _inventory_summary(db, inventory_current_stmt)
        summaries["inventory"]["attention_summary"] = _attention_summary(
            db,
            inventory_current_stmt,
            condition_factory=_inventory_attention_conditions,
            labels=INVENTORY_ATTENTION_LABELS,
        )
        inventory_trend_stmt = apply_data_scope(
            select(InventorySnapshot).where(InventorySnapshot.data_date >= start_date, InventorySnapshot.data_date <= today),
            InventorySnapshot,
            db,
            current_user,
            "inventory_snapshot",
        )
        inventory_trend_stmt, _inventory_trend_batch_id = _apply_snapshot_scope(
            db,
            inventory_trend_stmt,
            model=InventorySnapshot,
            file_type="inventory_snapshot",
            snapshot_scope="daily_latest",
            batch_id=None,
            date_from=start_date,
            date_to=today,
        )
        trend_maps["inventory"] = _daily_sum(db, inventory_trend_stmt, "data_date", "cost_amount")

    if can_account:
        account_current_stmt = apply_data_scope(
            select(AccountLedgerEntry),
            AccountLedgerEntry,
            db,
            current_user,
            "account_ledger",
        )
        account_current_stmt, _account_batch_id = _apply_snapshot_scope(
            db,
            account_current_stmt,
            model=AccountLedgerEntry,
            file_type="account_ledger",
            snapshot_scope="latest",
            batch_id=None,
        )
        summaries["account"] = _account_ledger_summary(db, account_current_stmt)
        summaries["account"]["attention_summary"] = _attention_summary(
            db,
            account_current_stmt,
            condition_factory=_account_attention_conditions,
            labels=ACCOUNT_ATTENTION_LABELS,
        )
        account_trend_stmt = apply_data_scope(
            select(AccountLedgerEntry).where(
                AccountLedgerEntry.data_date >= start_date,
                AccountLedgerEntry.data_date <= today,
                AccountLedgerEntry.row_role == "closing",
            ),
            AccountLedgerEntry,
            db,
            current_user,
            "account_ledger",
        )
        account_trend_stmt, _account_trend_batch_id = _apply_snapshot_scope(
            db,
            account_trend_stmt,
            model=AccountLedgerEntry,
            file_type="account_ledger",
            snapshot_scope="daily_latest",
            batch_id=None,
            date_from=start_date,
            date_to=today,
        )
        trend_maps["account"] = _daily_sum(db, account_trend_stmt, "data_date", "current_balance")

    import_summary = _import_summary(db, start_date, today) if can_import else {}
    inventory_check_summary = _latest_inventory_check_summary(db) if can_inventory_check else {}
    inventory_flow_summary = _inventory_flow_summary(db) if can_inventory_check else {}
    crm_summary = _crm_summary(db, current_user) if can_crm_project or can_crm_task or can_crm_issue else {}
    master_summary = _master_summary(db) if can_master else {}
    user_summary = _user_summary(db) if can_user else {}

    trend = [
        {
            "date": day.isoformat(),
            "label": day.strftime("%m/%d"),
            "sales_amount": trend_maps.get("sales", {}).get(day.isoformat(), 0),
            "gross_profit": trend_maps.get("gross_profit", {}).get(day.isoformat(), 0),
            "purchase_amount": trend_maps.get("purchase", {}).get(day.isoformat(), 0),
            "inventory_cost": trend_maps.get("inventory", {}).get(day.isoformat(), 0),
            "account_balance": trend_maps.get("account", {}).get(day.isoformat(), 0),
        }
        for day in day_labels
    ]

    metrics = _metrics(summaries, import_summary, crm_summary, can_sales, can_purchase, can_inventory, can_account)
    actions = _actions(summaries, import_summary, inventory_check_summary, inventory_flow_summary, crm_summary, user_summary, can_sales, can_inventory, can_inventory_check, can_account, can_import, can_crm_task, can_crm_issue, can_user)
    risk_matrix = _risk_matrix(summaries, import_summary, crm_summary, user_summary, can_sales, can_inventory, can_purchase, can_account, can_import, can_crm_task, can_user)
    flow = _business_flow(summaries, master_summary, import_summary, crm_summary, can_master, can_sales, can_purchase, can_inventory, can_account)
    conclusion = _conclusion(actions, summaries, import_summary, crm_summary)

    return {
        "range": range_key,
        "date_from": start_date.isoformat(),
        "date_to": today.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "conclusion": conclusion,
        "metrics": metrics,
        "trend": trend,
        "actions": actions,
        "risk_matrix": risk_matrix,
        "business_flow": flow,
        "run_records": {
            "imports": _recent_imports(db) if can_import else [],
            "audits": _recent_audits(db) if can_audit else [],
        },
    }


def _can(db: Session, user: User, *codes: str) -> bool:
    return any(has_permission(db, user, code) for code in codes)


def _day_labels(start_date: date, end_date: date) -> list[date]:
    days = max(1, (end_date - start_date).days + 1)
    return [start_date + timedelta(days=index) for index in range(days)]


def _count(db: Session, stmt: Select[tuple[Any, ...]]) -> int:
    return db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0


def _daily_sum(db: Session, stmt: Select[tuple[Any, ...]], day_column: str, value_column: str) -> dict[str, float]:
    filtered = stmt.order_by(None).subquery()
    day_col = getattr(filtered.c, day_column)
    value_col = getattr(filtered.c, value_column)
    rows = db.execute(
        select(day_col.label("day"), func.coalesce(func.sum(value_col), 0).label("value"))
        .where(day_col.is_not(None))
        .group_by(day_col)
        .order_by(day_col)
    ).all()
    return {_to_day_key(day): _to_float(value) for day, value in rows}


def _to_day_key(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _to_float(value: Any) -> float:
    if value is None:
        return 0
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0


def _to_int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _target(page: str, path: str | None = None) -> dict[str, str]:
    target = {"page": page}
    if path:
        target["path"] = path
    return target


def _attention_meta(summary: dict[str, Any]) -> tuple[int, str | None, int | None]:
    attention = summary.get("attention_summary") or {}
    return (
        _to_int(attention.get("needs_attention")),
        str(attention["effective_date"]) if attention.get("effective_date") else None,
        _to_int(attention.get("batch_id")) if attention.get("batch_id") is not None else None,
    )


def _attention_target(page: str, *, state: str, batch_id: int | None) -> dict[str, str]:
    path = f"/{page}?snapshot_scope=latest&attention_state={state}"
    if page == "account-balance":
        path += "&row_role=closing"
    if batch_id is not None:
        path += f"&batch_id={batch_id}"
    return _target(page, path)


def _effective_date_text(effective_date: str | None) -> str:
    return f"截至 {effective_date}" if effective_date else "当前有效批次"


def _import_summary(db: Session, start_date: date, end_date: date) -> dict[str, int]:
    stmt = select(ImportBatch).where(
        or_(ImportBatch.data_date.is_(None), ImportBatch.data_date >= start_date),
        or_(ImportBatch.data_date.is_(None), ImportBatch.data_date <= end_date),
    )
    filtered = stmt.order_by(None).subquery()
    failed = ["failed", "error", "partial_error"]
    return {
        "total": _count(db, stmt),
        "error_batches": db.scalar(select(func.count()).select_from(filtered).where(or_(filtered.c.error_rows > 0, filtered.c.status.in_(failed)))) or 0,
        "pending_batches": db.scalar(select(func.count()).select_from(filtered).where(~filtered.c.status.in_(["committed", "failed", "error"]))) or 0,
        "error_rows": db.scalar(select(func.coalesce(func.sum(filtered.c.error_rows), 0)).select_from(filtered)) or 0,
    }


def _latest_inventory_check_summary(db: Session) -> dict[str, Any]:
    batch = db.scalars(
        select(InventoryCheckBatch).order_by(InventoryCheckBatch.created_at.desc(), InventoryCheckBatch.id.desc()).limit(1)
    ).first()
    if not batch:
        return {}
    return {
        "id": batch.id,
        "file_name": batch.file_name,
        "data_date": batch.data_date.isoformat() if batch.data_date else None,
        "total_rows": batch.total_rows,
        "difference_rows": batch.difference_rows,
        "missing_in_system_rows": batch.missing_in_system_rows,
        "missing_in_upload_rows": batch.missing_in_upload_rows,
        "invalid_rows": batch.invalid_rows,
    }


def _inventory_flow_summary(db: Session) -> dict[str, Any]:
    total = db.scalar(select(func.count()).select_from(InventoryFlowLedger)) or 0
    abnormal = db.scalar(select(func.count()).select_from(InventoryFlowLedger).where(InventoryFlowLedger.anomaly_type != "normal")) or 0
    latest = db.scalar(select(func.max(InventoryFlowLedger.data_date)))
    return {"total": total, "abnormal": abnormal, "latest_date": latest.isoformat() if latest else None}


def _crm_summary(db: Session, current_user: User) -> dict[str, int]:
    result = {"active_projects": 0, "open_tasks": 0, "due_tasks": 0, "overdue_tasks": 0, "open_work_items": 0, "high_work_items": 0}
    now = datetime.now(timezone.utc)
    if has_permission(db, current_user, "crm_project.view"):
        result["active_projects"] = _count(
            db,
            crm_project_scope_filter(select(CrmProject).where(CrmProject.status == "active"), db, current_user),
        )
    if has_permission(db, current_user, "crm_task.view"):
        task_stmt = crm_task_scope_filter(select(CrmProjectCustomerTask).where(CrmProjectCustomerTask.is_closed.is_(False)), db, current_user)
        result["open_tasks"] = _count(db, task_stmt)
        result["due_tasks"] = _count(db, task_stmt.where(CrmProjectCustomerTask.feedback_due_at.is_not(None), CrmProjectCustomerTask.feedback_due_at <= now))
        result["overdue_tasks"] = _count(
            db,
            task_stmt.where(
                CrmProjectCustomerTask.feedback_due_at.is_not(None),
                CrmProjectCustomerTask.feedback_due_at < now,
                CrmProjectCustomerTask.last_followup_at.is_(None),
            ),
        )
    if has_permission(db, current_user, "crm_issue.view"):
        item_stmt = crm_work_item_scope_filter(select(WorkItem).where(WorkItem.status.in_(["open", "processing"])), db, current_user)
        result["open_work_items"] = _count(db, item_stmt)
        result["high_work_items"] = _count(db, item_stmt.where(WorkItem.priority.in_(["high", "urgent"])))
    return result


def _master_summary(db: Session) -> dict[str, int]:
    return {
        "customers": db.scalar(select(func.count()).select_from(CustomerMaster)) or 0,
        "products": db.scalar(select(func.count()).select_from(ProductMaster)) or 0,
        "suppliers": db.scalar(select(func.count()).select_from(SupplierMaster)) or 0,
        "employees": db.scalar(select(func.count()).select_from(EmployeeProfile)) or 0,
    }


def _user_summary(db: Session) -> dict[str, int]:
    active = db.scalar(select(func.count()).select_from(User).where(User.status == "active")) or 0
    disabled = db.scalar(select(func.count()).select_from(User).where(User.status == "disabled")) or 0
    cancelled = db.scalar(select(func.count()).select_from(User).where(User.status == "cancelled")) or 0
    admins = db.scalar(select(func.count()).select_from(User).where(User.role == "admin")) or 0
    return {"active": active, "disabled": disabled, "cancelled": cancelled, "admins": admins}


def _metrics(
    summaries: dict[str, dict[str, Any]],
    import_summary: dict[str, int],
    crm_summary: dict[str, int],
    can_sales: bool,
    can_purchase: bool,
    can_inventory: bool,
    can_account: bool,
) -> list[dict[str, Any]]:
    metrics: list[dict[str, Any]] = []
    if can_sales:
        sales = summaries.get("sales", {})
        gross_profit = _to_float(sales.get("gross_profit"))
        metrics.append({
            "key": "sales",
            "label": "销售额",
            "value": _to_float(sales.get("amount_tax_total")),
            "sub_value": f"毛利 {_money(gross_profit)}",
            "tone": "bad" if gross_profit < 0 else "ok",
            "target": _target("sales"),
        })
    if can_purchase:
        purchase = summaries.get("purchase", {})
        metrics.append({
            "key": "purchase",
            "label": "采购额",
            "value": _to_float(purchase.get("purchase_amount") or purchase.get("amount_tax_total")),
            "sub_value": f"{_to_int(purchase.get('documents'))} 张单据",
            "tone": "neutral",
            "target": _target("purchase"),
        })
    if can_inventory:
        inventory = summaries.get("inventory", {})
        abnormal, effective_date, batch_id = _attention_meta(inventory)
        metrics.append({
            "key": "inventory",
            "label": "库存成本",
            "value": _to_float(inventory.get("cost_amount")),
            "sub_value": f"库存风险 {abnormal} 行 · {_effective_date_text(effective_date)}",
            "tone": "warn" if abnormal else "ok",
            "target": _attention_target("inventory", state="needs_attention", batch_id=batch_id),
            "effective_date": effective_date,
        })
    if can_account:
        account = summaries.get("account", {})
        risk, effective_date, batch_id = _attention_meta(account)
        metrics.append({
            "key": "account",
            "label": "往来期末余额",
            "value": _to_float(account.get("current_balance")),
            "sub_value": f"余额待核对 {risk} 行 · {_effective_date_text(effective_date)}",
            "tone": "warn" if risk else "ok",
            "target": _attention_target("account-balance", state="needs_attention", batch_id=batch_id),
            "effective_date": effective_date,
        })
    if import_summary:
        metrics.append({
            "key": "import",
            "label": "导入错误行",
            "value": _to_int(import_summary.get("error_rows")),
            "sub_value": f"{_to_int(import_summary.get('error_batches'))} 个异常批次",
            "tone": "bad" if _to_int(import_summary.get("error_rows")) else "ok",
            "target": _target("master-data", "/master-data?drawer=import"),
        })
    if crm_summary:
        risk = _to_int(crm_summary.get("overdue_tasks")) + _to_int(crm_summary.get("high_work_items"))
        metrics.append({
            "key": "crm",
            "label": "CRM 风险",
            "value": risk,
            "sub_value": f"待跟进 {_to_int(crm_summary.get('due_tasks'))} · 待支持 {_to_int(crm_summary.get('open_work_items'))}",
            "tone": "bad" if risk else "ok",
            "target": _target("crm", "/crm/work"),
        })
    return metrics


def _actions(
    summaries: dict[str, dict[str, Any]],
    import_summary: dict[str, int],
    inventory_check_summary: dict[str, Any],
    inventory_flow_summary: dict[str, Any],
    crm_summary: dict[str, int],
    user_summary: dict[str, int],
    can_sales: bool,
    can_inventory: bool,
    can_inventory_check: bool,
    can_account: bool,
    can_import: bool,
    can_crm_task: bool,
    can_crm_issue: bool,
    can_user: bool,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    sales = summaries.get("sales", {})
    if can_sales and _to_float(sales.get("gross_profit")) < 0:
        actions.append(_action("sales-profit", "销售毛利异常", "当前周期毛利为负，建议按客户和商品下钻核查。", "bad", "销售", _target("sales")))
    inventory = summaries.get("inventory", {})
    abnormal, inventory_effective_date, inventory_batch_id = _attention_meta(inventory)
    if can_inventory and abnormal:
        actions.append(_action(
            "inventory-attention",
            "库存风险",
            f"{_effective_date_text(inventory_effective_date)}，负库存或锁定库存共 {abnormal} 行。",
            "bad",
            "库存",
            _attention_target("inventory", state="needs_attention", batch_id=inventory_batch_id),
            effective_date=inventory_effective_date,
        ))
    inventory_check_diff = _to_int(inventory_check_summary.get("difference_rows"))
    if can_inventory_check and inventory_check_diff:
        actions.append(_action(
            "inventory-check-diff",
            "实时库存校验存在差异",
            f"最近校验发现 {inventory_check_diff} 条差异，建议按商品逐行核对。",
            "bad",
            "校验",
            _target("inventory", f"/inventory?tab=check&batch_id={inventory_check_summary.get('id')}"),
        ))
    inventory_flow_abnormal = _to_int(inventory_flow_summary.get("abnormal"))
    if can_inventory_check and inventory_flow_abnormal:
        actions.append(_action(
            "inventory-flow-abnormal",
            "销售库存闭环异常",
            f"闭环校验发现 {inventory_flow_abnormal} 条异常，建议按日期、仓库、商品核查。",
            "bad",
            "闭环",
            _target("inventory", "/inventory?tab=check&check_tab=flow"),
        ))
    account = summaries.get("account", {})
    risk_rows, account_effective_date, account_batch_id = _attention_meta(account)
    if can_account and risk_rows:
        actions.append(_action(
            "account-attention",
            "余额待核对",
            f"{_effective_date_text(account_effective_date)}，期末应收、应付、预收或预付非零 {risk_rows} 行。",
            "warn",
            "往来",
            _attention_target("account-balance", state="needs_attention", batch_id=account_batch_id),
            effective_date=account_effective_date,
        ))
    if can_import and _to_int(import_summary.get("error_rows")):
        actions.append(_action("import-error", "导入错误待处理", f"错误行 {_to_int(import_summary.get('error_rows'))}，异常批次 {_to_int(import_summary.get('error_batches'))}。", "bad", "导入", _target("master-data", "/master-data?drawer=import")))
    if can_import and _to_int(import_summary.get("pending_batches")):
        actions.append(_action("import-pending", "导入批次未闭环", f"{_to_int(import_summary.get('pending_batches'))} 个批次仍在上传、预校验或提交流程中。", "warn", "导入", _target("master-data", "/master-data?drawer=import")))
    if can_crm_task and _to_int(crm_summary.get("overdue_tasks")):
        actions.append(_action("crm-overdue", "CRM 跟进超期", f"{_to_int(crm_summary.get('overdue_tasks'))} 个客户任务超期未反馈。", "bad", "CRM", _target("crm", "/crm/tasks")))
    if can_crm_issue and _to_int(crm_summary.get("open_work_items")):
        actions.append(_action("crm-support", "待支持事项未关闭", f"{_to_int(crm_summary.get('open_work_items'))} 个支持事项等待处理。", "warn", "CRM", _target("crm", "/crm/issues")))
    if can_user and _to_int(user_summary.get("admins")) > 1:
        actions.append(_action("user-admin-review", "高权限账号复核", f"{_to_int(user_summary.get('admins'))} 个管理员账号，建议定期复核权限。", "neutral", "权限", _target("users", "/users/roles")))
    if not actions:
        actions.append(_action("all-clear", "暂无高优先异常", "当前可见数据域没有明显异常，可继续查看经营趋势。", "ok", "正常", _target("dashboard")))
    severity_order = {"bad": 0, "warn": 1, "neutral": 2, "ok": 3}
    return sorted(actions, key=lambda item: severity_order.get(item["severity"], 9))[:8]


def _action(
    action_id: str,
    title: str,
    detail: str,
    severity: str,
    badge: str,
    target: dict[str, str],
    *,
    effective_date: str | None = None,
) -> dict[str, Any]:
    result = {"id": action_id, "title": title, "detail": detail, "severity": severity, "badge": badge, "target": target}
    if effective_date is not None:
        result["effective_date"] = effective_date
    return result


def _risk_matrix(
    summaries: dict[str, dict[str, Any]],
    import_summary: dict[str, int],
    crm_summary: dict[str, int],
    user_summary: dict[str, int],
    can_sales: bool,
    can_inventory: bool,
    can_purchase: bool,
    can_account: bool,
    can_import: bool,
    can_crm_task: bool,
    can_user: bool,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    if can_sales:
        sales = summaries.get("sales", {})
        gross_bad = 1 if _to_float(sales.get("gross_profit")) < 0 else 0
        rows.append(_risk_row("sales", "销售", _to_int(sales.get("rows")), 0, gross_bad, 0, _target("sales")))
    if can_inventory:
        inv = summaries.get("inventory", {})
        attention, effective_date, batch_id = _attention_meta(inv)
        rows.append(_risk_row(
            "inventory",
            "库存关注",
            _to_int(inv.get("rows")),
            0,
            attention,
            0,
            _attention_target("inventory", state="needs_attention", batch_id=batch_id),
            description=f"{_effective_date_text(effective_date)}；负库存或锁定库存需要关注。",
            effective_date=effective_date,
            cell_targets={
                "normal": _attention_target("inventory", state="normal", batch_id=batch_id),
                "abnormal": _attention_target("inventory", state="needs_attention", batch_id=batch_id),
            },
            cell_metadata={
                "normal": {"label": "正常库存", "description": f"{_effective_date_text(effective_date)}，未命中库存风险规则。", "effective_date": effective_date},
                "abnormal": {"label": "库存风险", "description": f"{_effective_date_text(effective_date)}，负库存或锁定库存需要核对。", "effective_date": effective_date},
            },
        ))
    if can_purchase:
        purchase = summaries.get("purchase", {})
        rows.append(_risk_row("purchase", "采购", _to_int(purchase.get("rows")), 0, 0, 0, _target("purchase")))
    if can_account:
        account = summaries.get("account", {})
        attention, effective_date, batch_id = _attention_meta(account)
        rows.append(_risk_row(
            "account",
            "往来期末",
            _to_int((account.get("attention_summary") or {}).get("total")),
            0,
            attention,
            0,
            _attention_target("account-balance", state="needs_attention", batch_id=batch_id),
            description=f"{_effective_date_text(effective_date)}；仅期末应收、应付、预收或预付非零需要关注。",
            effective_date=effective_date,
            cell_targets={
                "normal": _attention_target("account-balance", state="normal", batch_id=batch_id),
                "abnormal": _attention_target("account-balance", state="needs_attention", batch_id=batch_id),
            },
            cell_metadata={
                "normal": {"label": "无需核对", "description": f"{_effective_date_text(effective_date)}，期末余额未命中核对规则。", "effective_date": effective_date},
                "abnormal": {"label": "余额待核对", "description": f"{_effective_date_text(effective_date)}，期末应收、应付、预收或预付非零。", "effective_date": effective_date},
            },
        ))
    if can_import:
        rows.append(_risk_row("import", "主数据导入", _to_int(import_summary.get("total")), 0, _to_int(import_summary.get("error_batches")), _to_int(import_summary.get("pending_batches")), _target("master-data", "/master-data?drawer=import")))
    if can_crm_task:
        rows.append(_risk_row("crm", "客户 CRM", _to_int(crm_summary.get("open_tasks")), 0, _to_int(crm_summary.get("overdue_tasks")), _to_int(crm_summary.get("open_work_items")), _target("crm", "/crm/work")))
    if can_user:
        rows.append(_risk_row("user", "账号权限", _to_int(user_summary.get("active")), _to_int(user_summary.get("admins")), _to_int(user_summary.get("cancelled")), _to_int(user_summary.get("disabled")), _target("users")))
    return {
        "columns": [
            {"key": "normal", "label": "正常"},
            {"key": "watch", "label": "关注"},
            {"key": "abnormal", "label": "异常"},
            {"key": "pending", "label": "待处理"},
        ],
        "rows": rows,
    }


def _risk_row(
    key: str,
    label: str,
    total: int,
    watch: int,
    abnormal: int,
    pending: int,
    target: dict[str, str],
    *,
    description: str | None = None,
    effective_date: str | None = None,
    cell_targets: dict[str, dict[str, str]] | None = None,
    cell_metadata: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    normal = max(total - watch - abnormal - pending, 0)
    targets = cell_targets or {}
    metadata = cell_metadata or {}
    result = {
        "key": key,
        "label": label,
        "cells": [
            {"key": "normal", "value": normal, "tone": "ok", "target": targets.get("normal", target), **metadata.get("normal", {})},
            {"key": "watch", "value": watch, "tone": "neutral" if watch == 0 else "warn", "target": targets.get("watch", target), **metadata.get("watch", {})},
            {"key": "abnormal", "value": abnormal, "tone": "neutral" if abnormal == 0 else "bad", "target": targets.get("abnormal", target), **metadata.get("abnormal", {})},
            {"key": "pending", "value": pending, "tone": "neutral" if pending == 0 else "warn", "target": targets.get("pending", target), **metadata.get("pending", {})},
        ],
    }
    if description is not None:
        result["description"] = description
    if effective_date is not None:
        result["effective_date"] = effective_date
    return result


def _business_flow(
    summaries: dict[str, dict[str, Any]],
    master_summary: dict[str, int],
    import_summary: dict[str, int],
    crm_summary: dict[str, int],
    can_master: bool,
    can_sales: bool,
    can_purchase: bool,
    can_inventory: bool,
    can_account: bool,
) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    if can_master:
        nodes.append(_flow_node("customer", "客户", master_summary.get("customers", 0), crm_summary.get("overdue_tasks", 0), "客户档案与 CRM 跟进", _target("master-data", "/master-data?kind=customers")))
    if can_sales:
        sales = summaries.get("sales", {})
        nodes.append(_flow_node("sales", "销售", _to_int(sales.get("rows")), 1 if _to_float(sales.get("gross_profit")) < 0 else 0, "销售明细与毛利", _target("sales")))
    if can_master:
        nodes.append(_flow_node("product", "商品", master_summary.get("products", 0), 0, "商品档案", _target("master-data", "/master-data?kind=products")))
    if can_inventory:
        inv = summaries.get("inventory", {})
        attention, effective_date, batch_id = _attention_meta(inv)
        nodes.append(_flow_node(
            "inventory",
            "库存",
            _to_int(inv.get("rows")),
            attention,
            f"库存数量与成本 · {_effective_date_text(effective_date)}",
            _attention_target("inventory", state="needs_attention", batch_id=batch_id),
            effective_date=effective_date,
        ))
    if can_purchase:
        purchase = summaries.get("purchase", {})
        nodes.append(_flow_node("purchase", "采购", _to_int(purchase.get("rows")), 0, "采购明细", _target("purchase")))
    if can_master:
        nodes.append(_flow_node("supplier", "供应商", master_summary.get("suppliers", 0), 0, "供应商档案", _target("master-data", "/master-data?kind=suppliers")))
    if can_account:
        account = summaries.get("account", {})
        attention, effective_date, batch_id = _attention_meta(account)
        nodes.append(_flow_node(
            "account",
            "往来期末",
            _to_int((account.get("attention_summary") or {}).get("total")),
            attention,
            f"期末应收应付与预收预付 · {_effective_date_text(effective_date)}",
            _attention_target("account-balance", state="needs_attention", batch_id=batch_id),
            effective_date=effective_date,
        ))
    if import_summary:
        nodes.append(_flow_node("import", "导入", _to_int(import_summary.get("total")), _to_int(import_summary.get("error_batches")), "数据入口质量", _target("master-data", "/master-data?drawer=import")))
    return nodes


def _flow_node(
    key: str,
    label: str,
    value: int,
    risk: int,
    detail: str,
    target: dict[str, str],
    *,
    effective_date: str | None = None,
) -> dict[str, Any]:
    result = {"key": key, "label": label, "value": value, "risk": risk, "detail": detail, "target": target}
    if effective_date is not None:
        result["effective_date"] = effective_date
    return result


def _conclusion(
    actions: list[dict[str, Any]],
    summaries: dict[str, dict[str, Any]],
    import_summary: dict[str, int],
    crm_summary: dict[str, int],
) -> dict[str, Any]:
    top = actions[0] if actions else None
    if top and top["severity"] != "ok":
        return {
            "tone": top["severity"],
            "title": f"{top['title']}，今日优先处理",
            "detail": top["detail"],
            "target": top["target"],
        }
    sales_amount = _money(_to_float(summaries.get("sales", {}).get("amount_tax_total")))
    import_errors = _to_int(import_summary.get("error_rows"))
    crm_due = _to_int(crm_summary.get("due_tasks"))
    return {
        "tone": "ok",
        "title": "经营数据平稳，优先查看趋势变化",
        "detail": f"当前销售 {sales_amount}，导入错误行 {import_errors}，CRM 待跟进 {crm_due}。",
        "target": _target("dashboard"),
    }


def _recent_imports(db: Session) -> list[dict[str, Any]]:
    rows = list(db.scalars(select(ImportBatch).order_by(ImportBatch.uploaded_at.desc()).limit(6)).all())
    return [
        {
            "id": row.id,
            "batch_no": row.batch_no,
            "file_type": row.file_type,
            "status": row.status,
            "total_rows": row.total_rows,
            "error_rows": row.error_rows,
            "uploaded_at": row.uploaded_at.isoformat() if row.uploaded_at else None,
            "target": _target("master-data", f"/master-data?drawer=import&batch_id={row.id}"),
        }
        for row in rows
    ]


def _recent_audits(db: Session) -> list[dict[str, Any]]:
    rows = list(db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(6)).all())
    return [
        {
            "id": row.id,
            "role_code": row.role_code,
            "action_type": row.action_type,
            "resource_type": row.resource_type,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "target": _target("users", "/users/audit"),
        }
        for row in rows
    ]


def _money(value: float) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}¥{abs(value):,.0f}"

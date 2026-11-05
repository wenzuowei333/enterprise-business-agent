from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

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
from app.core.config import settings
from app.models import (
    AccountLedgerEntry,
    ApprovalInstance,
    CustomerMaster,
    EmployeeProfile,
    ImportBatch,
    InventorySnapshot,
    ProductMaster,
    PurchaseDetail,
    SalesDetail,
    SupplierMaster,
    User,
)
from app.schemas.global_ai import AiContextPayload, AiContextRequest, AiContextSnapshot
from app.services.access_control_service import apply_data_scope, get_field_permission_rules
from app.services.ai_context_service import AiContextProvider
from app.services.approval_access_service import visible_approvals_stmt
from app.services.exception_center_service import scoped_exception_stmt


GLOBAL_BUSINESS_CONTEXT_FIELDS = {
    "generated_at",
    "period",
    "crm",
    "master_data",
    "sales",
    "purchase",
    "inventory",
    "finance",
    "imports",
    "approvals",
    "exceptions",
    "availability",
}

_DOMAIN_PERMISSION = {
    "sales": "sales_detail.view",
    "purchase": "purchase_detail.view",
    "inventory": "inventory_snapshot.view",
    "finance": "account_ledger.view",
    "imports": "import.view",
}

_MASTER_MODELS = (
    ("customers", "customer.view", "customer", CustomerMaster),
    ("products", "product.view", "product", ProductMaster),
    ("suppliers", "supplier.view", "supplier", SupplierMaster),
    ("employees", "employee.view", "employee", EmployeeProfile),
)

_SUMMARY_FIELD_MAP = {
    "sales_detail": {
        "sale_qty_base": "sale_qty_base",
        "amount_tax_total": "amount_tax_total",
        "amount_after_discount": "amount_after_discount",
        "cost_amount": "cost_amount",
        "gross_profit": "gross_profit",
        "gross_margin_rate": "gross_profit",
    },
    "purchase_detail": {
        "purchase_qty_base": "purchase_qty_base",
        "amount_tax_total": "amount_tax_total",
        "amount_after_discount": "amount_after_discount",
        "purchase_amount": "purchase_amount",
        "discount_amount": "discount_amount",
        "tax_amount": "tax_amount",
    },
    "inventory_snapshot": {
        "stock_qty": "stock_qty",
        "stock_inventory_qty": "stock_inventory_qty",
        "locked_base_qty": "locked_base_qty",
        "cost_amount": "cost_amount",
        "positive_rows": "stock_qty",
        "zero_rows": "stock_qty",
        "negative_rows": "stock_qty",
        "locked_rows": "locked_base_qty",
    },
    "account_ledger": {
        "current_balance": "current_balance",
        "ar_amount": "ar_amount",
        "ap_amount": "ap_amount",
        "advance_receipt_amount": "advance_receipt_amount",
        "advance_payment_amount": "advance_payment_amount",
        "received_amount": "received_amount",
        "paid_amount": "paid_amount",
        "non_zero_ar_rows": "ar_amount",
        "non_zero_ap_rows": "ap_amount",
    },
}


def _count(db: Session, stmt: Select[tuple[Any, ...]]) -> int:
    return db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0


def _availability(*, enabled: bool, reason: str | None = None) -> dict[str, Any]:
    return {"available": enabled, "reason": reason}


def _permission_available(permission_codes: set[str], permission: str) -> dict[str, Any]:
    if permission in permission_codes:
        return _availability(enabled=True)
    return _availability(enabled=False, reason=f"missing_permission:{permission}")


def _scoped_summary(
    db: Session,
    user: User,
    *,
    resource_type: str,
    summary: dict[str, Any],
) -> dict[str, Any]:
    restricted = {
        rule.field_name
        for rule in get_field_permission_rules(db, user, resource_type)
        if rule.permission_type in {"hidden", "masked"}
    }
    redacted_metrics: list[str] = []
    for metric, source_field in _SUMMARY_FIELD_MAP.get(resource_type, {}).items():
        if source_field in restricted and metric in summary:
            summary[metric] = None
            redacted_metrics.append(metric)
    if resource_type == "sales_detail" and "amount_tax_total" in restricted:
        summary["gross_margin_rate"] = None
        redacted_metrics.append("gross_margin_rate")
    if resource_type == "inventory_snapshot" and restricted & {"stock_qty", "locked_base_qty"}:
        summary["abnormal_rows"] = None
        redacted_metrics.append("abnormal_rows")
    summary["redacted_metrics"] = sorted(set(redacted_metrics))
    return summary


def _scoped_attention(
    attention: dict[str, Any],
    *,
    redacted_metrics: list[str],
    reason_fields: dict[str, str],
) -> dict[str, Any]:
    restricted = set(redacted_metrics)
    redacted_reasons: list[str] = []
    for item in attention.get("by_reason", []):
        source_field = reason_fields.get(str(item.get("code")))
        if source_field in restricted:
            item["count"] = None
            redacted_reasons.append(str(item["code"]))
    if redacted_reasons:
        attention["needs_attention"] = None
        attention["normal"] = None
    attention["redacted_reasons"] = sorted(redacted_reasons)
    return attention


def _crm_source_refs(context: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for key, prefix in (
        ("projects", "crm_project"),
        ("risky_tasks", "crm_task"),
        ("open_work_items", "work_item"),
    ):
        rows = context.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict) and row.get("id") is not None:
                refs.append(f"{prefix}:{row['id']}")
    return refs


def _master_context(
    db: Session,
    user: User,
    permission_codes: set[str],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    counts: dict[str, int] = {}
    denied: list[str] = []
    for label, permission, resource_type, model in _MASTER_MODELS:
        if permission not in permission_codes:
            denied.append(permission)
            continue
        stmt = apply_data_scope(select(model), model, db, user, resource_type)
        counts[label] = _count(db, stmt)
    if not counts:
        reason = "missing_permission:" + ",".join(sorted(denied))
        return None, _availability(enabled=False, reason=reason)
    return {
        "counts": counts,
        "partial": bool(denied),
        "unavailable_permissions": sorted(denied),
    }, _availability(enabled=True)


def _sales_context(db: Session, user: User, start_date: date, end_date: date) -> dict[str, Any]:
    stmt = apply_data_scope(
        select(SalesDetail).where(
            SalesDetail.document_date >= start_date,
            SalesDetail.document_date <= end_date,
        ),
        SalesDetail,
        db,
        user,
        "sales_detail",
    )
    summary = _sales_summary(db, user, stmt, date_from=start_date, date_to=end_date)
    for key in (
        "inventory_abnormal_rows",
        "zero_stock_sales",
        "negative_stock_sales",
        "without_stock_sales",
    ):
        summary.pop(key, None)
    return _scoped_summary(db, user, resource_type="sales_detail", summary=summary)


def _purchase_context(db: Session, user: User, start_date: date, end_date: date) -> dict[str, Any]:
    stmt = apply_data_scope(
        select(PurchaseDetail).where(
            PurchaseDetail.document_date >= start_date,
            PurchaseDetail.document_date <= end_date,
        ),
        PurchaseDetail,
        db,
        user,
        "purchase_detail",
    )
    summary = _purchase_summary(db, stmt)
    return _scoped_summary(db, user, resource_type="purchase_detail", summary=summary)


def _inventory_context(db: Session, user: User) -> tuple[dict[str, Any], list[str]]:
    stmt = apply_data_scope(
        select(InventorySnapshot),
        InventorySnapshot,
        db,
        user,
        "inventory_snapshot",
    )
    stmt, batch_id = _apply_snapshot_scope(
        db,
        stmt,
        model=InventorySnapshot,
        file_type="inventory_snapshot",
        snapshot_scope="latest",
        batch_id=None,
    )
    summary = _scoped_summary(
        db,
        user,
        resource_type="inventory_snapshot",
        summary=_inventory_summary(db, stmt),
    )
    summary["attention"] = _scoped_attention(
        _attention_summary(
            db,
            stmt,
            condition_factory=_inventory_attention_conditions,
            labels=INVENTORY_ATTENTION_LABELS,
        ),
        redacted_metrics=summary["redacted_metrics"],
        reason_fields={"negative_stock": "stock_qty", "locked_stock": "locked_base_qty"},
    )
    return summary, [f"import_batch:{batch_id}"] if batch_id is not None else []


def _finance_context(db: Session, user: User) -> tuple[dict[str, Any], list[str]]:
    stmt = apply_data_scope(
        select(AccountLedgerEntry),
        AccountLedgerEntry,
        db,
        user,
        "account_ledger",
    )
    stmt, batch_id = _apply_snapshot_scope(
        db,
        stmt,
        model=AccountLedgerEntry,
        file_type="account_ledger",
        snapshot_scope="latest",
        batch_id=None,
    )
    summary = _scoped_summary(
        db,
        user,
        resource_type="account_ledger",
        summary=_account_ledger_summary(db, stmt),
    )
    summary["attention"] = _scoped_attention(
        _attention_summary(
            db,
            stmt,
            condition_factory=_account_attention_conditions,
            labels=ACCOUNT_ATTENTION_LABELS,
        ),
        redacted_metrics=summary["redacted_metrics"],
        reason_fields={
            "ar_non_zero": "ar_amount",
            "ap_non_zero": "ap_amount",
            "advance_receipt_non_zero": "advance_receipt_amount",
            "advance_payment_non_zero": "advance_payment_amount",
        },
    )
    return summary, [f"import_batch:{batch_id}"] if batch_id is not None else []


def _import_context(db: Session, user: User, start_at: datetime) -> tuple[dict[str, Any], list[str]]:
    stmt = apply_data_scope(
        select(ImportBatch).where(ImportBatch.uploaded_at >= start_at),
        ImportBatch,
        db,
        user,
        "import_batch",
    )
    filtered = stmt.order_by(None).subquery()
    rows = db.execute(
        select(filtered.c.status, func.count()).group_by(filtered.c.status).order_by(filtered.c.status)
    ).all()
    failures = list(
        db.scalars(
            stmt.where(
                or_(
                    ImportBatch.error_rows > 0,
                    ImportBatch.status.in_(["failed", "error", "partial_error"]),
                )
            )
            .order_by(ImportBatch.uploaded_at.desc(), ImportBatch.id.desc())
            .limit(10)
        ).all()
    )
    return {
        "total": _count(db, stmt),
        "status_counts": {str(status or "unknown"): int(count or 0) for status, count in rows},
        "error_batches": len(failures),
        "error_rows": sum(int(row.error_rows or 0) for row in failures),
        "recent_failures": [
            {
                "id": row.id,
                "batch_no": row.batch_no,
                "file_type": row.file_type,
                "status": row.status,
                "error_rows": row.error_rows,
                "data_date": row.data_date,
            }
            for row in failures
        ],
    }, [f"import_batch:{row.id}" for row in failures]


def _approval_context(db: Session, user: User) -> tuple[dict[str, Any], list[str]]:
    stmt = visible_approvals_stmt(db, user)
    filtered = stmt.order_by(None).subquery()
    rows = db.execute(
        select(filtered.c.status, func.count()).group_by(filtered.c.status).order_by(filtered.c.status)
    ).all()
    pending = list(
        db.scalars(
            stmt.where(ApprovalInstance.status.in_(["submitted", "under_review", "need_supplement"]))
            .order_by(ApprovalInstance.submitted_at.asc().nullsfirst(), ApprovalInstance.id)
            .limit(10)
        ).all()
    )
    return {
        "total": _count(db, stmt),
        "status_counts": {str(status or "unknown"): int(count or 0) for status, count in rows},
        "pending": [
            {
                "id": row.id,
                "approval_type": row.approval_type,
                "status": row.status,
                "priority": row.priority,
                "is_current_handler": row.current_handler_user_id == user.id,
            }
            for row in pending
        ],
    }, [f"approval:{row.id}" for row in pending]


def _exception_context(db: Session, user: User) -> tuple[dict[str, Any], list[str]]:
    stmt = scoped_exception_stmt(db, user)
    filtered = stmt.order_by(None).subquery()
    statuses = db.execute(
        select(filtered.c.status, func.count()).group_by(filtered.c.status).order_by(filtered.c.status)
    ).all()
    domains = db.execute(
        select(filtered.c.domain, func.count()).group_by(filtered.c.domain).order_by(filtered.c.domain)
    ).all()
    severities = db.execute(
        select(filtered.c.severity, func.count()).group_by(filtered.c.severity).order_by(filtered.c.severity)
    ).all()
    active = list(
        db.execute(
            select(
                filtered.c.id,
                filtered.c.domain,
                filtered.c.rule_code,
                filtered.c.severity,
                filtered.c.status,
                filtered.c.occurrence_type,
            )
            .where(filtered.c.status.in_(["open", "action_required", "processing", "blocked"]))
            .order_by(filtered.c.last_seen_at.desc(), filtered.c.id.desc())
            .limit(10)
        ).mappings()
    )
    return {
        "total": _count(db, stmt),
        "status_counts": {str(key or "unknown"): int(value or 0) for key, value in statuses},
        "domain_counts": {str(key or "unknown"): int(value or 0) for key, value in domains},
        "severity_counts": {str(key or "unknown"): int(value or 0) for key, value in severities},
        "active_cases": [dict(row) for row in active],
    }, [f"exception_case:{row['id']}" for row in active]


def build_global_business_context_snapshot(
    db: Session,
    user: User,
    *,
    crm_context: dict[str, Any],
    permission_codes: list[str],
    required_permission: str,
) -> AiContextSnapshot:
    permissions = set(permission_codes)
    if required_permission not in permissions:
        raise PermissionError(
            f"AI context permission denied for domain global_business: {required_permission}"
        )
    now = datetime.now(timezone.utc)
    end_date = now.astimezone(ZoneInfo(settings.exception_schedule_timezone)).date()
    start_date = end_date - timedelta(days=29)
    fields: dict[str, Any] = {
        "generated_at": now,
        "period": {"date_from": start_date, "date_to": end_date, "days": 30},
        "crm": crm_context,
        "availability": {"crm": _availability(enabled=True)},
    }
    refs = _crm_source_refs(crm_context)

    if settings.exception_ai_data_enabled:
        master_data, master_availability = _master_context(db, user, permissions)
        fields["availability"]["master_data"] = master_availability
        if master_data is not None:
            fields["master_data"] = master_data
        for domain, builder in (
            ("sales", lambda: (_sales_context(db, user, start_date, end_date), [])),
            ("purchase", lambda: (_purchase_context(db, user, start_date, end_date), [])),
            ("inventory", lambda: _inventory_context(db, user)),
            ("imports", lambda: _import_context(db, user, now - timedelta(days=30))),
        ):
            permission = _DOMAIN_PERMISSION[domain]
            availability = _permission_available(permissions, permission)
            fields["availability"][domain] = availability
            if not availability["available"]:
                continue
            value, domain_refs = builder()
            fields[domain] = value
            refs.extend(domain_refs)
    else:
        for domain in ("master_data", "sales", "purchase", "inventory", "imports"):
            fields["availability"][domain] = _availability(
                enabled=False,
                reason="feature_disabled:EXCEPTION_AI_DATA_ENABLED",
            )

    if settings.exception_ai_finance_enabled:
        finance_availability = _permission_available(permissions, _DOMAIN_PERMISSION["finance"])
        fields["availability"]["finance"] = finance_availability
        if finance_availability["available"]:
            finance, finance_refs = _finance_context(db, user)
            fields["finance"] = finance
            refs.extend(finance_refs)
    else:
        fields["availability"]["finance"] = _availability(
            enabled=False,
            reason="feature_disabled:EXCEPTION_AI_FINANCE_ENABLED",
        )

    approval_permissions = {
        "approval.view",
        "approval.approve",
        "crm_lead.approve",
        "customer_tag.review",
    }
    if permissions & approval_permissions:
        approvals, approval_refs = _approval_context(db, user)
        fields["approvals"] = approvals
        fields["availability"]["approvals"] = _availability(enabled=True)
        refs.extend(approval_refs)
    else:
        fields["availability"]["approvals"] = _availability(
            enabled=False,
            reason="missing_permission:approval",
        )

    if "exception_center.view" in permissions:
        exceptions, exception_refs = _exception_context(db, user)
        fields["exceptions"] = exceptions
        fields["availability"]["exceptions"] = _availability(enabled=True)
        refs.extend(exception_refs)
    else:
        fields["availability"]["exceptions"] = _availability(
            enabled=False,
            reason="missing_permission:exception_center.view",
        )

    provider = AiContextProvider()
    provider.register(
        "global_business",
        lambda _request: AiContextPayload(
            context_version="global-business-context.v1",
            fields=fields,
            source_refs=list(dict.fromkeys(refs))[:200],
        ),
        allowed_fields=GLOBAL_BUSINESS_CONTEXT_FIELDS,
        required_permissions={required_permission},
    )
    return provider.build(
        AiContextRequest(
            domain="global_business",
            actor_user_id=user.id,
            permission_codes=permission_codes,
        )
    )

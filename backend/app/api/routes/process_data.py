from datetime import date
from decimal import Decimal
from typing import Any, Literal

import json

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy import Select, and_, case, exists, func, or_, select
from sqlalchemy.orm import Session

from app.api.dependencies import require_permission
from app.core.database import get_db
from app.models import AccountBalanceSnapshot, AccountLedgerEntry, ImportBatch, InventoryFlowLedger, InventorySnapshot, PurchaseDetail, SalesDetail, User
from app.services.access_control_service import (
    apply_data_scope,
    get_field_permission_rules,
    serialize_many_with_field_rules,
    serialize_with_field_rules,
)

router = APIRouter(prefix="/process-data", tags=["process-data"])

SnapshotScope = Literal["all", "latest", "daily_latest"]
AttentionState = Literal["normal", "needs_attention"]

INVENTORY_ATTENTION_LABELS = {
    "negative_stock": "负库存",
    "locked_stock": "锁定库存",
}
ACCOUNT_ATTENTION_LABELS = {
    "ar_non_zero": "应收余额非零",
    "ap_non_zero": "应付余额非零",
    "advance_receipt_non_zero": "预收余额非零",
    "advance_payment_non_zero": "预付余额非零",
}

SALES_EDITABLE_FIELDS = {
    "customer_name",
    "product_name",
    "employee_name",
    "warehouse_name",
    "sale_qty_base",
    "amount_tax_total",
    "gross_profit",
    "note",
    "summary",
    "reconciliation_mark",
}
INVENTORY_EDITABLE_FIELDS = {
    "product_name",
    "warehouse_name",
    "default_supplier",
    "stock_inventory_qty",
    "locked_base_qty",
    "inventory_status",
    "average_cost",
    "cost_amount",
}
PURCHASE_EDITABLE_FIELDS = {
    "supplier_name",
    "product_name",
    "employee_name",
    "warehouse_name",
    "purchase_qty_base",
    "unit_price",
    "amount_tax_total",
    "purchase_amount",
    "remark",
    "summary",
    "reconciliation_mark",
}
ACCOUNT_BALANCE_EDITABLE_FIELDS = {
    "settlement_unit_name",
    "current_opening_balance",
    "current_amount",
    "current_closing_balance",
    "ar_balance",
    "ap_balance",
    "advance_receipt_balance",
    "advance_payment_balance",
}
ACCOUNT_LEDGER_EDITABLE_FIELDS = {
    "settlement_unit_name",
    "document_type",
    "document_date",
    "document_no",
    "handler_name",
    "counterparty_name",
    "document_amount",
    "received_amount",
    "ar_amount",
    "paid_amount",
    "ap_amount",
    "advance_receipt_amount",
    "advance_payment_amount",
    "current_balance",
    "summary",
    "description",
    "reconciliation_mark",
}

DECIMAL_FIELDS = {
    "sale_qty_base",
    "amount_tax_total",
    "gross_profit",
    "stock_qty",
    "stock_inventory_qty",
    "locked_base_qty",
    "average_cost",
    "cost_amount",
    "purchase_qty_base",
    "unit_price",
    "purchase_amount",
    "current_opening_balance",
    "current_amount",
    "current_closing_balance",
    "ar_balance",
    "ap_balance",
    "advance_receipt_balance",
    "advance_payment_balance",
    "document_amount",
    "received_amount",
    "ar_amount",
    "paid_amount",
    "ap_amount",
    "advance_receipt_amount",
    "advance_payment_amount",
    "current_balance",
}
DATE_PATCH_FIELDS = {"document_date", "reconciliation_date"}


def _safe_limit(limit: int) -> int:
    return max(1, min(limit, 50))


def _safe_offset(offset: int) -> int:
    return max(0, offset)


def _count_stmt(db: Session, stmt: Select[tuple[Any, ...]]) -> int:
    return db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0


def _apply_snapshot_scope(
    db: Session,
    stmt: Select[tuple[Any, ...]],
    *,
    model: type[InventorySnapshot] | type[AccountLedgerEntry],
    file_type: str,
    snapshot_scope: SnapshotScope,
    batch_id: int | None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> tuple[Select[tuple[Any, ...]], int | None]:
    if batch_id is not None:
        valid_batch = exists(
            select(1).where(
                ImportBatch.id == batch_id,
                ImportBatch.file_type == file_type,
                ImportBatch.status == "committed",
            )
        )
        return stmt.where(model.batch_id == batch_id, valid_batch), batch_id
    if snapshot_scope == "all":
        return stmt, None

    is_account_ledger = model is AccountLedgerEntry
    effective_date = (
        func.coalesce(AccountLedgerEntry.balance_date, ImportBatch.data_date, AccountLedgerEntry.data_date)
        if is_account_ledger
        else InventorySnapshot.data_date
    )
    committed = (
        select(ImportBatch.id)
        .join(model, model.batch_id == ImportBatch.id)
        .where(ImportBatch.file_type == file_type, ImportBatch.status == "committed")
        .group_by(ImportBatch.id, ImportBatch.data_date, ImportBatch.uploaded_at)
        .order_by(
            func.max(effective_date).desc().nullslast(),
            ImportBatch.data_date.desc().nullslast(),
            ImportBatch.uploaded_at.desc(),
            ImportBatch.id.desc(),
        )
        .limit(1)
    )
    if is_account_ledger:
        committed = committed.where(AccountLedgerEntry.row_role == "closing")
    if snapshot_scope == "latest":
        selected_batch_id = db.scalar(committed)
        if selected_batch_id is None:
            return stmt.where(model.batch_id == -1), None
        return stmt.where(model.batch_id == selected_batch_id), int(selected_batch_id)

    if is_account_ledger:
        account_effective_date = func.coalesce(
            AccountLedgerEntry.balance_date,
            ImportBatch.data_date,
            AccountLedgerEntry.data_date,
        )
        candidates = (
            select(
                account_effective_date.label("data_date"),
                AccountLedgerEntry.batch_id.label("batch_id"),
                ImportBatch.uploaded_at.label("uploaded_at"),
            )
            .join(ImportBatch, ImportBatch.id == AccountLedgerEntry.batch_id)
            .where(
                ImportBatch.file_type == file_type,
                ImportBatch.status == "committed",
                AccountLedgerEntry.row_role == "closing",
                account_effective_date.is_not(None),
            )
        )
        if date_from is not None:
            candidates = candidates.where(account_effective_date >= date_from)
        if date_to is not None:
            candidates = candidates.where(account_effective_date <= date_to)
        candidates = candidates.group_by(
            account_effective_date,
            AccountLedgerEntry.batch_id,
            ImportBatch.uploaded_at,
        ).subquery()
    else:
        candidates = (
            select(
                model.data_date.label("data_date"),
                model.batch_id.label("batch_id"),
                ImportBatch.uploaded_at.label("uploaded_at"),
            )
            .join(ImportBatch, ImportBatch.id == model.batch_id)
            .where(
                ImportBatch.file_type == file_type,
                ImportBatch.status == "committed",
                model.data_date.is_not(None),
            )
        )
        if date_from is not None:
            candidates = candidates.where(model.data_date >= date_from)
        if date_to is not None:
            candidates = candidates.where(model.data_date <= date_to)
        candidates = candidates.group_by(model.data_date, model.batch_id, ImportBatch.uploaded_at).subquery()
    ranked = select(
        candidates.c.data_date,
        candidates.c.batch_id,
        func.row_number()
        .over(
            partition_by=candidates.c.data_date,
            order_by=(candidates.c.uploaded_at.desc(), candidates.c.batch_id.desc()),
        )
        .label("rank"),
    ).subquery()
    latest_per_day = select(ranked.c.data_date, ranked.c.batch_id).where(ranked.c.rank == 1).subquery()
    if is_account_ledger:
        selected = model.batch_id.in_(select(latest_per_day.c.batch_id))
    else:
        selected = exists(
            select(1).where(
                latest_per_day.c.data_date == model.data_date,
                latest_per_day.c.batch_id == model.batch_id,
            )
        )
    return stmt.where(selected), None


def _inventory_attention_conditions(source: Any) -> dict[str, Any]:
    return {
        "negative_stock": func.coalesce(source.stock_qty < 0, False),
        "locked_stock": func.coalesce(source.locked_base_qty > 0, False),
    }


def _account_attention_conditions(source: Any) -> dict[str, Any]:
    closing = source.row_role == "closing"
    return {
        "ar_non_zero": and_(closing, func.coalesce(source.ar_amount != 0, False)),
        "ap_non_zero": and_(closing, func.coalesce(source.ap_amount != 0, False)),
        "advance_receipt_non_zero": and_(closing, func.coalesce(source.advance_receipt_amount != 0, False)),
        "advance_payment_non_zero": and_(closing, func.coalesce(source.advance_payment_amount != 0, False)),
    }


def _apply_attention_filter(
    stmt: Select[tuple[Any, ...]],
    *,
    conditions: dict[str, Any],
    labels: dict[str, str],
    attention_state: AttentionState | None,
    attention_reason: str | None,
) -> Select[tuple[Any, ...]]:
    if attention_reason and attention_reason not in labels:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown attention reason: {attention_reason}")
    needs_attention = or_(*conditions.values())
    if attention_state == "needs_attention":
        stmt = stmt.where(needs_attention)
    elif attention_state == "normal":
        stmt = stmt.where(~needs_attention)
    if attention_reason:
        stmt = stmt.where(conditions[attention_reason])
    return stmt


def _attention_summary(
    db: Session,
    stmt: Select[tuple[Any, ...]],
    *,
    condition_factory,
    labels: dict[str, str],
) -> dict[str, Any]:
    filtered = stmt.order_by(None).subquery()
    conditions = condition_factory(filtered.c)
    needs_attention = or_(*conditions.values())
    effective_date_column = (
        func.coalesce(filtered.c.balance_date, filtered.c.data_date)
        if condition_factory is _account_attention_conditions
        else filtered.c.data_date
    )
    columns = [
        func.count().label("total"),
        func.coalesce(func.sum(case((needs_attention, 1), else_=0)), 0).label("needs_attention"),
        func.max(effective_date_column).label("effective_date"),
        func.min(filtered.c.batch_id).label("min_batch_id"),
        func.max(filtered.c.batch_id).label("max_batch_id"),
    ]
    columns.extend(
        func.coalesce(func.sum(case((condition, 1), else_=0)), 0).label(f"reason_{code}")
        for code, condition in conditions.items()
    )
    row = db.execute(select(*columns).select_from(filtered)).mappings().one()
    total = int(row["total"] or 0)
    attention_count = int(row["needs_attention"] or 0)
    summary: dict[str, Any] = {
        "total": total,
        "normal": max(total - attention_count, 0),
        "needs_attention": attention_count,
        "by_reason": [
            {"code": code, "label": label, "count": int(row[f"reason_{code}"] or 0)}
            for code, label in labels.items()
        ],
    }
    effective_date = row["effective_date"]
    if effective_date is not None:
        summary["effective_date"] = effective_date.isoformat()
    if row["min_batch_id"] is not None and row["min_batch_id"] == row["max_batch_id"]:
        summary["batch_id"] = int(row["min_batch_id"])
    return summary


def _inventory_attention_reasons(row: InventorySnapshot) -> list[dict[str, str]]:
    codes: list[str] = []
    if row.stock_qty is not None and row.stock_qty < 0:
        codes.append("negative_stock")
    if row.locked_base_qty is not None and row.locked_base_qty > 0:
        codes.append("locked_stock")
    return [{"code": code, "label": INVENTORY_ATTENTION_LABELS[code]} for code in codes]


def _account_attention_reasons(row: AccountLedgerEntry) -> list[dict[str, str]]:
    if row.row_role != "closing":
        return []
    values = {
        "ar_non_zero": row.ar_amount,
        "ap_non_zero": row.ap_amount,
        "advance_receipt_non_zero": row.advance_receipt_amount,
        "advance_payment_non_zero": row.advance_payment_amount,
    }
    return [
        {"code": code, "label": ACCOUNT_ATTENTION_LABELS[code]}
        for code, value in values.items()
        if value is not None and value != 0
    ]


def _add_attention_fields(
    data: dict[str, Any],
    reasons: list[dict[str, str]],
    *,
    applicable: bool = True,
) -> dict[str, Any]:
    data["attention_state"] = ("needs_attention" if reasons else "normal") if applicable else None
    data["attention_reasons"] = reasons
    return data


def _parse_category_path(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        parsed = value.split("/")
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def _blank_label(value: Any, fallback: str) -> str:
    text = str(value).strip() if value is not None else ""
    return text or fallback


def _category_root(kind: str, label: str) -> dict:
    return {"id": f"{kind}:root", "label": label, "path": [], "count": 0, "abnormal_count": 0, "children": []}


def _category_node(kind: str, path: list[str], label: str) -> dict:
    return {"id": f"{kind}:{' / '.join(path)}", "label": label, "path": path, "count": 0, "abnormal_count": 0, "children": []}


def _add_process_category(root: dict, kind: str, path: list[str], abnormal: bool) -> None:
    current = root
    for index, segment in enumerate(path):
        next_path = path[: index + 1]
        child = next((item for item in current["children"] if item["label"] == segment), None)
        if child is None:
            child = _category_node(kind, next_path, segment)
            current["children"].append(child)
        child["count"] += 1
        if abnormal:
            child["abnormal_count"] += 1
        current = child


def _blank_filter(column: Any, fallback_label: str, value: str) -> Any:
    if value == fallback_label:
        return or_(column.is_(None), column == "")
    return column == value


def _sort_category_tree(node: dict) -> dict:
    node["children"].sort(key=lambda item: (-item["count"], item["label"]))
    for child in node["children"]:
        _sort_category_tree(child)
    return node


def _to_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid decimal value: {value}") from exc


def _clean_patch(payload: dict, allowed_fields: set[str]) -> dict:
    cleaned = {key: value for key, value in payload.items() if key in allowed_fields}
    if not cleaned:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No editable fields provided")
    return cleaned


def _apply_patch(row: Any, payload: dict) -> None:
    for key, value in payload.items():
        if key in DECIMAL_FIELDS:
            next_value = _to_decimal(value)
        elif key in DATE_PATCH_FIELDS:
            next_value = date.fromisoformat(value) if value else None
        else:
            next_value = None if value == "" else value
        setattr(row, key, next_value)


def _sales_base_stmt(
    *,
    q: str | None,
    date_from: date | None,
    date_to: date | None,
    customer_code: str | None,
    product_code: str | None,
    warehouse_name: str | None,
    employee_name: str | None,
) -> Select[tuple[SalesDetail]]:
    stmt = select(SalesDetail)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                SalesDetail.document_no.ilike(like),
                SalesDetail.customer_code.ilike(like),
                SalesDetail.customer_name.ilike(like),
                SalesDetail.product_code.ilike(like),
                SalesDetail.product_name.ilike(like),
                SalesDetail.employee_name.ilike(like),
                SalesDetail.warehouse_name.ilike(like),
            )
        )
    if date_from:
        stmt = stmt.where(SalesDetail.document_date >= date_from)
    if date_to:
        stmt = stmt.where(SalesDetail.document_date <= date_to)
    if customer_code:
        stmt = stmt.where(SalesDetail.customer_code == customer_code)
    if product_code:
        stmt = stmt.where(SalesDetail.product_code == product_code)
    if warehouse_name:
        stmt = stmt.where(SalesDetail.warehouse_name == warehouse_name)
    if employee_name:
        stmt = stmt.where(SalesDetail.employee_name == employee_name)
    return stmt


def _inventory_base_stmt(
    *,
    q: str | None,
    date_from: date | None,
    date_to: date | None,
    product_code: str | None,
    default_supplier: str | None,
    inventory_status: str | None,
    warehouse_name: str | None = None,
) -> Select[tuple[InventorySnapshot]]:
    stmt = select(InventorySnapshot)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                InventorySnapshot.product_code.ilike(like),
                InventorySnapshot.product_name.ilike(like),
                InventorySnapshot.warehouse_name.ilike(like),
                InventorySnapshot.barcode.ilike(like),
                InventorySnapshot.default_supplier.ilike(like),
                InventorySnapshot.inventory_status.ilike(like),
            )
        )
    if date_from:
        stmt = stmt.where(InventorySnapshot.data_date >= date_from)
    if date_to:
        stmt = stmt.where(InventorySnapshot.data_date <= date_to)
    if product_code:
        stmt = stmt.where(InventorySnapshot.product_code == product_code)
    if default_supplier:
        stmt = stmt.where(InventorySnapshot.default_supplier.ilike(f"%{default_supplier}%"))
    if inventory_status:
        stmt = stmt.where(InventorySnapshot.inventory_status == inventory_status)
    if warehouse_name:
        stmt = stmt.where(InventorySnapshot.warehouse_name == warehouse_name)
    return stmt


def _purchase_base_stmt(
    *,
    q: str | None,
    date_from: date | None,
    date_to: date | None,
    supplier_code: str | None,
    product_code: str | None,
    warehouse_name: str | None,
    employee_name: str | None,
) -> Select[tuple[PurchaseDetail]]:
    stmt = select(PurchaseDetail)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                PurchaseDetail.document_no.ilike(like),
                PurchaseDetail.supplier_code.ilike(like),
                PurchaseDetail.supplier_name.ilike(like),
                PurchaseDetail.product_code.ilike(like),
                PurchaseDetail.product_name.ilike(like),
                PurchaseDetail.employee_name.ilike(like),
                PurchaseDetail.warehouse_name.ilike(like),
            )
        )
    if date_from:
        stmt = stmt.where(PurchaseDetail.document_date >= date_from)
    if date_to:
        stmt = stmt.where(PurchaseDetail.document_date <= date_to)
    if supplier_code:
        stmt = stmt.where(PurchaseDetail.supplier_code == supplier_code)
    if product_code:
        stmt = stmt.where(PurchaseDetail.product_code == product_code)
    if warehouse_name:
        stmt = stmt.where(PurchaseDetail.warehouse_name == warehouse_name)
    if employee_name:
        stmt = stmt.where(PurchaseDetail.employee_name == employee_name)
    return stmt


def _account_balance_base_stmt(
    *,
    q: str | None,
    date_from: date | None,
    date_to: date | None,
    settlement_unit_code: str | None,
    settlement_unit_name: str | None,
    balance_type: str | None,
) -> Select[tuple[AccountBalanceSnapshot]]:
    stmt = select(AccountBalanceSnapshot)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                AccountBalanceSnapshot.settlement_unit_code.ilike(like),
                AccountBalanceSnapshot.settlement_unit_name.ilike(like),
            )
        )
    if date_from:
        stmt = stmt.where(AccountBalanceSnapshot.data_date >= date_from)
    if date_to:
        stmt = stmt.where(AccountBalanceSnapshot.data_date <= date_to)
    if settlement_unit_code:
        stmt = stmt.where(AccountBalanceSnapshot.settlement_unit_code == settlement_unit_code)
    if settlement_unit_name:
        stmt = stmt.where(AccountBalanceSnapshot.settlement_unit_name.ilike(f"%{settlement_unit_name}%"))
    if balance_type == "ar":
        stmt = stmt.where(AccountBalanceSnapshot.ar_balance != 0)
    elif balance_type == "ap":
        stmt = stmt.where(AccountBalanceSnapshot.ap_balance != 0)
    elif balance_type == "advance_receipt":
        stmt = stmt.where(AccountBalanceSnapshot.advance_receipt_balance != 0)
    elif balance_type == "advance_payment":
        stmt = stmt.where(AccountBalanceSnapshot.advance_payment_balance != 0)
    elif balance_type == "current":
        stmt = stmt.where(AccountBalanceSnapshot.current_closing_balance != 0)
    elif balance_type == "zero":
        stmt = stmt.where(AccountBalanceSnapshot.current_closing_balance == 0)
    return stmt


def _account_ledger_base_stmt(
    *,
    q: str | None,
    date_from: date | None,
    date_to: date | None,
    settlement_unit_code: str | None,
    settlement_unit_name: str | None,
    document_type: str | None,
    row_role: str | None,
) -> Select[tuple[AccountLedgerEntry]]:
    stmt = select(AccountLedgerEntry)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                AccountLedgerEntry.settlement_unit_code.ilike(like),
                AccountLedgerEntry.settlement_unit_name.ilike(like),
                AccountLedgerEntry.document_no.ilike(like),
                AccountLedgerEntry.document_type.ilike(like),
                AccountLedgerEntry.handler_name.ilike(like),
                AccountLedgerEntry.counterparty_name.ilike(like),
                AccountLedgerEntry.summary.ilike(like),
                AccountLedgerEntry.description.ilike(like),
            )
        )
    if date_from:
        stmt = stmt.where(AccountLedgerEntry.data_date >= date_from)
    if date_to:
        stmt = stmt.where(AccountLedgerEntry.data_date <= date_to)
    if settlement_unit_code:
        stmt = stmt.where(AccountLedgerEntry.settlement_unit_code == settlement_unit_code)
    if settlement_unit_name:
        stmt = stmt.where(AccountLedgerEntry.settlement_unit_name.ilike(f"%{settlement_unit_name}%"))
    if document_type:
        stmt = stmt.where(AccountLedgerEntry.document_type == document_type)
    if row_role:
        stmt = stmt.where(AccountLedgerEntry.row_role == row_role)
    return stmt


def _apply_sales_category(stmt: Select[tuple[SalesDetail]], path: list[str]) -> Select[tuple[SalesDetail]]:
    if len(path) < 2:
        return stmt
    group, value = path[0], path[1]
    if group == "客户":
        return stmt.where(_blank_filter(SalesDetail.customer_name, "未识别客户", value))
    if group == "商品":
        return stmt.where(_blank_filter(SalesDetail.product_name, "未识别商品", value))
    if group == "业务员":
        return stmt.where(_blank_filter(SalesDetail.employee_name, "未识别业务员", value))
    if group == "仓库":
        return stmt.where(_blank_filter(SalesDetail.warehouse_name, "未识别仓库", value))
    return stmt


def _apply_inventory_category(stmt: Select[tuple[InventorySnapshot]], path: list[str]) -> Select[tuple[InventorySnapshot]]:
    if len(path) < 2:
        return stmt
    group, value = path[0], path[1]
    if group == "供货商":
        return stmt.where(_blank_filter(InventorySnapshot.default_supplier, "未识别供货商", value))
    if group == "仓库":
        return stmt.where(_blank_filter(InventorySnapshot.warehouse_name, "未识别仓库", value))
    if group == "库存状态":
        return stmt.where(_blank_filter(InventorySnapshot.inventory_status, "未识别状态", value))
    if group == "商品":
        return stmt.where(_blank_filter(InventorySnapshot.product_name, "未识别商品", value))
    return stmt


def _apply_purchase_category(stmt: Select[tuple[PurchaseDetail]], path: list[str]) -> Select[tuple[PurchaseDetail]]:
    if len(path) < 2:
        return stmt
    group, value = path[0], path[1]
    if group == "供应商":
        return stmt.where(_blank_filter(PurchaseDetail.supplier_name, "未识别供应商", value))
    if group == "商品":
        return stmt.where(_blank_filter(PurchaseDetail.product_name, "未识别商品", value))
    if group == "采购员":
        return stmt.where(_blank_filter(PurchaseDetail.employee_name, "未识别采购员", value))
    if group == "仓库":
        return stmt.where(_blank_filter(PurchaseDetail.warehouse_name, "未识别仓库", value))
    return stmt


def _apply_account_balance_category(stmt: Select[tuple[AccountBalanceSnapshot]], path: list[str]) -> Select[tuple[AccountBalanceSnapshot]]:
    if not path:
        return stmt
    if path[0] == "余额类型" and len(path) >= 2:
        value = path[1]
        if value == "应收非零":
            return stmt.where(AccountBalanceSnapshot.ar_balance != 0)
        if value == "应付非零":
            return stmt.where(AccountBalanceSnapshot.ap_balance != 0)
        if value == "预收非零":
            return stmt.where(AccountBalanceSnapshot.advance_receipt_balance != 0)
        if value == "预付非零":
            return stmt.where(AccountBalanceSnapshot.advance_payment_balance != 0)
        if value == "往来余额为零":
            return stmt.where(AccountBalanceSnapshot.current_closing_balance == 0)
        if value == "往来余额非零":
            return stmt.where(AccountBalanceSnapshot.current_closing_balance != 0)
    if path[0] == "结算单位" and len(path) >= 2:
        return stmt.where(_blank_filter(AccountBalanceSnapshot.settlement_unit_name, "未识别结算单位", path[1]))
    return stmt


def _apply_account_ledger_category(stmt: Select[tuple[AccountLedgerEntry]], path: list[str]) -> Select[tuple[AccountLedgerEntry]]:
    if len(path) < 2:
        return stmt
    group, value = path[0], path[1]
    if group == "结算单位":
        return stmt.where(_blank_filter(AccountLedgerEntry.settlement_unit_name, "未识别结算单位", value))
    if group == "单据类型":
        return stmt.where(_blank_filter(AccountLedgerEntry.document_type, "未识别类型", value))
    if group == "经手人":
        return stmt.where(_blank_filter(AccountLedgerEntry.handler_name, "未识别经手人", value))
    if group == "行角色":
        role_map = {"期初": "opening", "期末": "closing", "明细": "transaction"}
        return stmt.where(AccountLedgerEntry.row_role == role_map.get(value, value))
    return stmt


def _sales_hierarchy(rows: list[SalesDetail]) -> dict:
    root = _category_root("sales_detail", "全部销售")
    root["count"] = len(rows)
    for row in rows:
        abnormal = bool(row.gross_profit is not None and row.gross_profit < 0)
        if abnormal:
            root["abnormal_count"] += 1
        for group, value, fallback in [
            ("客户", row.customer_name, "未识别客户"),
            ("商品", row.product_name, "未识别商品"),
            ("业务员", row.employee_name, "未识别业务员"),
            ("仓库", row.warehouse_name, "未识别仓库"),
        ]:
            _add_process_category(root, "sales_detail", [group, _blank_label(value, fallback)], abnormal)
    return _sort_category_tree(root)


def _inventory_hierarchy(rows: list[InventorySnapshot]) -> dict:
    root = _category_root("inventory_snapshot", "全部库存")
    root["count"] = len(rows)
    for row in rows:
        abnormal = bool(_inventory_attention_reasons(row))
        if abnormal:
            root["abnormal_count"] += 1
        for group, value, fallback in [
            ("仓库", row.warehouse_name, "未识别仓库"),
            ("供货商", row.default_supplier, "未识别供货商"),
            ("库存状态", row.inventory_status, "未识别状态"),
            ("商品", row.product_name, "未识别商品"),
        ]:
            _add_process_category(root, "inventory_snapshot", [group, _blank_label(value, fallback)], abnormal)
    return _sort_category_tree(root)


def _purchase_hierarchy(rows: list[PurchaseDetail]) -> dict:
    root = _category_root("purchase_detail", "全部采购")
    root["count"] = len(rows)
    for row in rows:
        abnormal = bool(row.purchase_amount is not None and row.purchase_amount < 0)
        if abnormal:
            root["abnormal_count"] += 1
        for group, value, fallback in [
            ("供应商", row.supplier_name, "未识别供应商"),
            ("商品", row.product_name, "未识别商品"),
            ("采购员", row.employee_name, "未识别采购员"),
            ("仓库", row.warehouse_name, "未识别仓库"),
        ]:
            _add_process_category(root, "purchase_detail", [group, _blank_label(value, fallback)], abnormal)
    return _sort_category_tree(root)


def _account_balance_hierarchy(rows: list[AccountBalanceSnapshot]) -> dict:
    root = _category_root("account_balance", "全部往来")
    root["count"] = len(rows)
    for row in rows:
        abnormal = bool(
            (row.ar_balance is not None and row.ar_balance != 0)
            or (row.ap_balance is not None and row.ap_balance != 0)
            or (row.advance_receipt_balance is not None and row.advance_receipt_balance != 0)
            or (row.advance_payment_balance is not None and row.advance_payment_balance != 0)
        )
        if abnormal:
            root["abnormal_count"] += 1
        _add_process_category(root, "account_balance", ["结算单位", _blank_label(row.settlement_unit_name, "未识别结算单位")], abnormal)
        for label, matched in [
            ("应收非零", row.ar_balance is not None and row.ar_balance != 0),
            ("应付非零", row.ap_balance is not None and row.ap_balance != 0),
            ("预收非零", row.advance_receipt_balance is not None and row.advance_receipt_balance != 0),
            ("预付非零", row.advance_payment_balance is not None and row.advance_payment_balance != 0),
            ("往来余额为零", row.current_closing_balance is not None and row.current_closing_balance == 0),
            ("往来余额非零", row.current_closing_balance is not None and row.current_closing_balance != 0),
        ]:
            if matched:
                _add_process_category(root, "account_balance", ["余额类型", label], abnormal)
    return _sort_category_tree(root)


def _account_ledger_hierarchy(rows: list[AccountLedgerEntry]) -> dict:
    root = _category_root("account_ledger", "全部往来明细")
    root["count"] = len(rows)
    role_labels = {"opening": "期初", "closing": "期末", "transaction": "明细"}
    for row in rows:
        abnormal = bool(_account_attention_reasons(row))
        if abnormal:
            root["abnormal_count"] += 1
        for group, value, fallback in [
            ("结算单位", row.settlement_unit_name, "未识别结算单位"),
            ("单据类型", row.document_type, "未识别类型"),
            ("经手人", row.handler_name, "未识别经手人"),
            ("行角色", role_labels.get(row.row_role, row.row_role), "明细"),
        ]:
            _add_process_category(root, "account_ledger", [group, _blank_label(value, fallback)], abnormal)
    return _sort_category_tree(root)


@router.get("/sales-details/page")
def list_sales_details_page(
    q: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    customer_code: str | None = None,
    product_code: str | None = None,
    warehouse_name: str | None = None,
    employee_name: str | None = None,
    category_path: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("sales_detail.view")),
) -> dict:
    safe_limit = _safe_limit(limit)
    safe_offset = _safe_offset(offset)
    stmt = _sales_base_stmt(
        q=q,
        date_from=date_from,
        date_to=date_to,
        customer_code=customer_code,
        product_code=product_code,
        warehouse_name=warehouse_name,
        employee_name=employee_name,
    )
    stmt = _apply_sales_category(stmt, _parse_category_path(category_path))
    stmt = apply_data_scope(stmt, SalesDetail, db, current_user, "sales_detail")
    total = _count_stmt(db, stmt)
    rows = list(
        db.scalars(
            stmt.order_by(SalesDetail.document_date.desc().nullslast(), SalesDetail.id.desc())
            .offset(safe_offset)
            .limit(safe_limit)
        ).all()
    )
    return {
        "items": serialize_many_with_field_rules(db, current_user, "sales_detail", rows),
        "total": total,
        "limit": safe_limit,
        "offset": safe_offset,
        "summary": _sales_summary(
            db,
            current_user,
            stmt,
            date_from=date_from,
            date_to=date_to,
            product_code=product_code,
            warehouse_name=warehouse_name,
        ),
    }


@router.get("/sales-details/{sales_detail_id}")
def get_sales_detail(
    sales_detail_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("sales_detail.view")),
) -> dict:
    stmt = select(SalesDetail).where(SalesDetail.id == sales_detail_id)
    stmt = apply_data_scope(stmt, SalesDetail, db, current_user, "sales_detail")
    row = db.scalar(stmt)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sales detail not found")
    return serialize_with_field_rules(db, current_user, "sales_detail", row)


@router.get("/sales-details/hierarchy/tree")
def sales_detail_hierarchy(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("sales_detail.view")),
) -> dict:
    stmt = apply_data_scope(select(SalesDetail), SalesDetail, db, current_user, "sales_detail")
    return _sales_hierarchy(list(db.scalars(stmt).all()))


@router.patch("/sales-details/{sales_detail_id}")
def update_sales_detail(
    sales_detail_id: int,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("sales_detail.edit")),
) -> dict:
    stmt = apply_data_scope(select(SalesDetail).where(SalesDetail.id == sales_detail_id), SalesDetail, db, current_user, "sales_detail")
    row = db.scalar(stmt)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sales detail not found")
    _apply_patch(row, _clean_patch(payload, SALES_EDITABLE_FIELDS))
    from app.services.inventory_flow_service import rebuild_inventory_flow
    rebuild_inventory_flow(db)
    db.commit()
    db.refresh(row)
    return serialize_with_field_rules(db, current_user, "sales_detail", row)


@router.get("/inventory-snapshots/page")
def list_inventory_snapshots_page(
    q: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    product_code: str | None = None,
    default_supplier: str | None = None,
    inventory_status: str | None = None,
    warehouse_name: str | None = None,
    attention_state: AttentionState | None = None,
    attention_reason: str | None = None,
    snapshot_scope: SnapshotScope = "all",
    batch_id: int | None = None,
    category_path: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("inventory_snapshot.view")),
) -> dict:
    safe_limit = _safe_limit(limit)
    safe_offset = _safe_offset(offset)
    stmt = _inventory_base_stmt(
        q=q,
        date_from=date_from,
        date_to=date_to,
        product_code=product_code,
        default_supplier=default_supplier,
        inventory_status=inventory_status,
        warehouse_name=warehouse_name,
    )
    stmt, _selected_batch_id = _apply_snapshot_scope(
        db,
        stmt,
        model=InventorySnapshot,
        file_type="inventory_snapshot",
        snapshot_scope=snapshot_scope,
        batch_id=batch_id,
        date_from=date_from,
        date_to=date_to,
    )
    stmt = _apply_inventory_category(stmt, _parse_category_path(category_path))
    stmt = apply_data_scope(stmt, InventorySnapshot, db, current_user, "inventory_snapshot")
    attention_base_stmt = stmt
    stmt = _apply_attention_filter(
        stmt,
        conditions=_inventory_attention_conditions(InventorySnapshot),
        labels=INVENTORY_ATTENTION_LABELS,
        attention_state=attention_state,
        attention_reason=attention_reason,
    )
    total = _count_stmt(db, stmt)
    rows = list(
        db.scalars(
            stmt.order_by(InventorySnapshot.data_date.desc().nullslast(), InventorySnapshot.product_code, InventorySnapshot.id)
            .offset(safe_offset)
            .limit(safe_limit)
        ).all()
    )
    items = serialize_many_with_field_rules(db, current_user, "inventory_snapshot", rows)
    for item, row in zip(items, rows):
        _add_attention_fields(item, _inventory_attention_reasons(row))
    return {
        "items": items,
        "total": total,
        "limit": safe_limit,
        "offset": safe_offset,
        "summary": _inventory_summary(db, stmt),
        "attention_summary": _attention_summary(
            db,
            attention_base_stmt,
            condition_factory=_inventory_attention_conditions,
            labels=INVENTORY_ATTENTION_LABELS,
        ),
    }


@router.get("/inventory-snapshots/{snapshot_id}")
def get_inventory_snapshot(
    snapshot_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("inventory_snapshot.view")),
) -> dict:
    stmt = select(InventorySnapshot).where(InventorySnapshot.id == snapshot_id)
    stmt = apply_data_scope(stmt, InventorySnapshot, db, current_user, "inventory_snapshot")
    row = db.scalar(stmt)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inventory snapshot not found")
    return _add_attention_fields(
        serialize_with_field_rules(db, current_user, "inventory_snapshot", row),
        _inventory_attention_reasons(row),
    )


@router.get("/inventory-snapshots/hierarchy/tree")
def inventory_snapshot_hierarchy(
    date_from: date | None = None,
    date_to: date | None = None,
    snapshot_scope: SnapshotScope = "all",
    batch_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("inventory_snapshot.view")),
) -> dict:
    stmt, _selected_batch_id = _apply_snapshot_scope(
        db,
        _inventory_base_stmt(
            q=None,
            date_from=date_from,
            date_to=date_to,
            product_code=None,
            default_supplier=None,
            inventory_status=None,
            warehouse_name=None,
        ),
        model=InventorySnapshot,
        file_type="inventory_snapshot",
        snapshot_scope=snapshot_scope,
        batch_id=batch_id,
        date_from=date_from,
        date_to=date_to,
    )
    stmt = apply_data_scope(stmt, InventorySnapshot, db, current_user, "inventory_snapshot")
    return _inventory_hierarchy(list(db.scalars(stmt).all()))


@router.patch("/inventory-snapshots/{snapshot_id}")
def update_inventory_snapshot(
    snapshot_id: int,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("inventory_snapshot.edit")),
) -> dict:
    if "stock_qty" in payload:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "inventory_snapshot_read_only",
                "message": "账面库存来自上游进销存，不能在管理中心直接修改。请通过正式业务单据修正后重新同步。",
                "module": "inventory",
                "resource_type": "inventory_snapshot",
                "resource_id": snapshot_id,
                "retryable": False,
                "action_path": "/exceptions?domain=inventory",
            },
        )
    stmt = apply_data_scope(select(InventorySnapshot).where(InventorySnapshot.id == snapshot_id), InventorySnapshot, db, current_user, "inventory_snapshot")
    row = db.scalar(stmt)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inventory snapshot not found")
    _apply_patch(row, _clean_patch(payload, INVENTORY_EDITABLE_FIELDS))
    from app.services.inventory_flow_service import rebuild_inventory_flow
    rebuild_inventory_flow(db)
    db.commit()
    db.refresh(row)
    return _add_attention_fields(
        serialize_with_field_rules(db, current_user, "inventory_snapshot", row),
        _inventory_attention_reasons(row),
    )


@router.get("/purchase-details/page")
def list_purchase_details_page(
    q: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    supplier_code: str | None = None,
    product_code: str | None = None,
    warehouse_name: str | None = None,
    employee_name: str | None = None,
    category_path: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("purchase_detail.view")),
) -> dict:
    safe_limit = _safe_limit(limit)
    safe_offset = _safe_offset(offset)
    stmt = _purchase_base_stmt(
        q=q,
        date_from=date_from,
        date_to=date_to,
        supplier_code=supplier_code,
        product_code=product_code,
        warehouse_name=warehouse_name,
        employee_name=employee_name,
    )
    stmt = _apply_purchase_category(stmt, _parse_category_path(category_path))
    stmt = apply_data_scope(stmt, PurchaseDetail, db, current_user, "purchase_detail")
    total = _count_stmt(db, stmt)
    rows = list(
        db.scalars(
            stmt.order_by(PurchaseDetail.document_date.desc().nullslast(), PurchaseDetail.id.desc())
            .offset(safe_offset)
            .limit(safe_limit)
        ).all()
    )
    return {
        "items": serialize_many_with_field_rules(db, current_user, "purchase_detail", rows),
        "total": total,
        "limit": safe_limit,
        "offset": safe_offset,
        "summary": _purchase_summary(db, stmt),
    }


@router.get("/purchase-details/{purchase_detail_id}")
def get_purchase_detail(
    purchase_detail_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("purchase_detail.view")),
) -> dict:
    stmt = select(PurchaseDetail).where(PurchaseDetail.id == purchase_detail_id)
    stmt = apply_data_scope(stmt, PurchaseDetail, db, current_user, "purchase_detail")
    row = db.scalar(stmt)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Purchase detail not found")
    return serialize_with_field_rules(db, current_user, "purchase_detail", row)


@router.get("/purchase-details/hierarchy/tree")
def purchase_detail_hierarchy(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("purchase_detail.view")),
) -> dict:
    stmt = apply_data_scope(select(PurchaseDetail), PurchaseDetail, db, current_user, "purchase_detail")
    return _purchase_hierarchy(list(db.scalars(stmt).all()))


@router.patch("/purchase-details/{purchase_detail_id}")
def update_purchase_detail(
    purchase_detail_id: int,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("purchase_detail.edit")),
) -> dict:
    stmt = apply_data_scope(select(PurchaseDetail).where(PurchaseDetail.id == purchase_detail_id), PurchaseDetail, db, current_user, "purchase_detail")
    row = db.scalar(stmt)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Purchase detail not found")
    _apply_patch(row, _clean_patch(payload, PURCHASE_EDITABLE_FIELDS))
    from app.services.inventory_flow_service import rebuild_inventory_flow
    rebuild_inventory_flow(db)
    db.commit()
    db.refresh(row)
    return serialize_with_field_rules(db, current_user, "purchase_detail", row)


@router.get("/account-balances/page")
def list_account_balances_page(
    q: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    settlement_unit_code: str | None = None,
    settlement_unit_name: str | None = None,
    balance_type: str | None = None,
    category_path: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("account_balance.view")),
) -> dict:
    safe_limit = _safe_limit(limit)
    safe_offset = _safe_offset(offset)
    stmt = _account_balance_base_stmt(
        q=q,
        date_from=date_from,
        date_to=date_to,
        settlement_unit_code=settlement_unit_code,
        settlement_unit_name=settlement_unit_name,
        balance_type=balance_type,
    )
    stmt = _apply_account_balance_category(stmt, _parse_category_path(category_path))
    stmt = apply_data_scope(stmt, AccountBalanceSnapshot, db, current_user, "account_balance")
    total = _count_stmt(db, stmt)
    rows = list(
        db.scalars(
            stmt.order_by(
                AccountBalanceSnapshot.data_date.desc().nullslast(),
                AccountBalanceSnapshot.settlement_unit_code,
                AccountBalanceSnapshot.id,
            )
            .offset(safe_offset)
            .limit(safe_limit)
        ).all()
    )
    return {
        "items": serialize_many_with_field_rules(db, current_user, "account_balance", rows),
        "total": total,
        "limit": safe_limit,
        "offset": safe_offset,
        "summary": _account_balance_summary(db, stmt),
    }


@router.get("/account-balances/{balance_id}")
def get_account_balance(
    balance_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("account_balance.view")),
) -> dict:
    stmt = select(AccountBalanceSnapshot).where(AccountBalanceSnapshot.id == balance_id)
    stmt = apply_data_scope(stmt, AccountBalanceSnapshot, db, current_user, "account_balance")
    row = db.scalar(stmt)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account balance not found")
    return serialize_with_field_rules(db, current_user, "account_balance", row)


@router.get("/account-balances/hierarchy/tree")
def account_balance_hierarchy(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("account_balance.view")),
) -> dict:
    stmt = apply_data_scope(select(AccountBalanceSnapshot), AccountBalanceSnapshot, db, current_user, "account_balance")
    return _account_balance_hierarchy(list(db.scalars(stmt).all()))


@router.patch("/account-balances/{balance_id}")
def update_account_balance(
    balance_id: int,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("account_balance.edit")),
) -> dict:
    stmt = apply_data_scope(select(AccountBalanceSnapshot).where(AccountBalanceSnapshot.id == balance_id), AccountBalanceSnapshot, db, current_user, "account_balance")
    row = db.scalar(stmt)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account balance not found")
    _apply_patch(row, _clean_patch(payload, ACCOUNT_BALANCE_EDITABLE_FIELDS))
    db.commit()
    db.refresh(row)
    return serialize_with_field_rules(db, current_user, "account_balance", row)


@router.get("/account-ledger/page")
def list_account_ledger_page(
    q: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    settlement_unit_code: str | None = None,
    settlement_unit_name: str | None = None,
    document_type: str | None = None,
    row_role: str | None = None,
    attention_state: AttentionState | None = None,
    attention_reason: str | None = None,
    snapshot_scope: SnapshotScope = "all",
    batch_id: int | None = None,
    category_path: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("account_ledger.view")),
) -> dict:
    safe_limit = _safe_limit(limit)
    safe_offset = _safe_offset(offset)
    stmt = _account_ledger_base_stmt(
        q=q,
        date_from=date_from,
        date_to=date_to,
        settlement_unit_code=settlement_unit_code,
        settlement_unit_name=settlement_unit_name,
        document_type=document_type,
        row_role=row_role,
    )
    stmt, _selected_batch_id = _apply_snapshot_scope(
        db,
        stmt,
        model=AccountLedgerEntry,
        file_type="account_ledger",
        snapshot_scope=snapshot_scope,
        batch_id=batch_id,
        date_from=date_from,
        date_to=date_to,
    )
    stmt = _apply_account_ledger_category(stmt, _parse_category_path(category_path))
    stmt = apply_data_scope(stmt, AccountLedgerEntry, db, current_user, "account_ledger")
    attention_base_stmt = stmt.where(AccountLedgerEntry.row_role == "closing")
    if attention_state is not None or attention_reason is not None:
        stmt = stmt.where(AccountLedgerEntry.row_role == "closing")
    stmt = _apply_attention_filter(
        stmt,
        conditions=_account_attention_conditions(AccountLedgerEntry),
        labels=ACCOUNT_ATTENTION_LABELS,
        attention_state=attention_state,
        attention_reason=attention_reason,
    )
    total = _count_stmt(db, stmt)
    rows = list(
        db.scalars(
            stmt.order_by(
                AccountLedgerEntry.data_date.desc().nullslast(),
                AccountLedgerEntry.settlement_unit_code,
                AccountLedgerEntry.row_number,
                AccountLedgerEntry.id,
            )
            .offset(safe_offset)
            .limit(safe_limit)
        ).all()
    )
    items = serialize_many_with_field_rules(db, current_user, "account_ledger", rows)
    for item, row in zip(items, rows):
        _add_attention_fields(item, _account_attention_reasons(row), applicable=row.row_role == "closing")
    return {
        "items": items,
        "total": total,
        "limit": safe_limit,
        "offset": safe_offset,
        "summary": _account_ledger_summary(db, stmt),
        "attention_summary": _attention_summary(
            db,
            attention_base_stmt,
            condition_factory=_account_attention_conditions,
            labels=ACCOUNT_ATTENTION_LABELS,
        ),
    }


@router.get("/account-ledger/{entry_id}")
def get_account_ledger_entry(
    entry_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("account_ledger.view")),
) -> dict:
    stmt = select(AccountLedgerEntry).where(AccountLedgerEntry.id == entry_id)
    stmt = apply_data_scope(stmt, AccountLedgerEntry, db, current_user, "account_ledger")
    row = db.scalar(stmt)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account ledger entry not found")
    return _add_attention_fields(
        serialize_with_field_rules(db, current_user, "account_ledger", row),
        _account_attention_reasons(row),
        applicable=row.row_role == "closing",
    )


@router.get("/account-ledger/hierarchy/tree")
def account_ledger_hierarchy(
    date_from: date | None = None,
    date_to: date | None = None,
    row_role: str | None = None,
    snapshot_scope: SnapshotScope = "all",
    batch_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("account_ledger.view")),
) -> dict:
    stmt, _selected_batch_id = _apply_snapshot_scope(
        db,
        _account_ledger_base_stmt(
            q=None,
            date_from=date_from,
            date_to=date_to,
            settlement_unit_code=None,
            settlement_unit_name=None,
            document_type=None,
            row_role=row_role,
        ),
        model=AccountLedgerEntry,
        file_type="account_ledger",
        snapshot_scope=snapshot_scope,
        batch_id=batch_id,
        date_from=date_from,
        date_to=date_to,
    )
    stmt = apply_data_scope(stmt, AccountLedgerEntry, db, current_user, "account_ledger")
    return _account_ledger_hierarchy(list(db.scalars(stmt).all()))


@router.patch("/account-ledger/{entry_id}")
def update_account_ledger_entry(
    entry_id: int,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("account_ledger.edit")),
) -> dict:
    stmt = apply_data_scope(select(AccountLedgerEntry).where(AccountLedgerEntry.id == entry_id), AccountLedgerEntry, db, current_user, "account_ledger")
    row = db.scalar(stmt)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account ledger entry not found")
    patch = _clean_patch(payload, ACCOUNT_LEDGER_EDITABLE_FIELDS)
    _apply_patch(row, patch)
    if "document_type" in patch:
        row.row_role = "opening" if row.document_type == "期初" else "closing" if row.document_type == "期末" else "transaction"
    db.commit()
    db.refresh(row)
    return _add_attention_fields(
        serialize_with_field_rules(db, current_user, "account_ledger", row),
        _account_attention_reasons(row),
        applicable=row.row_role == "closing",
    )


def _sales_summary(
    db: Session,
    current_user: User,
    stmt: Select[tuple[SalesDetail]],
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    product_code: str | None = None,
    warehouse_name: str | None = None,
) -> dict:
    filtered = stmt.order_by(None).subquery()
    row = db.execute(
        select(
            func.count().label("rows"),
            func.count(func.distinct(filtered.c.document_no)).label("documents"),
            func.count(func.distinct(filtered.c.customer_code)).label("customers"),
            func.count(func.distinct(filtered.c.product_code)).label("products"),
            func.coalesce(func.sum(filtered.c.sale_qty_base), 0).label("sale_qty_base"),
            func.coalesce(func.sum(filtered.c.amount_tax_total), 0).label("amount_tax_total"),
            func.coalesce(func.sum(filtered.c.amount_after_discount), 0).label("amount_after_discount"),
            func.coalesce(func.sum(filtered.c.cost_amount), 0).label("cost_amount"),
            func.coalesce(func.sum(filtered.c.gross_profit), 0).label("gross_profit"),
        )
    ).mappings().one()
    summary = {key: _jsonable(value) for key, value in dict(row).items()}
    amount = Decimal(str(summary.get("amount_tax_total") or 0))
    gross_profit = Decimal(str(summary.get("gross_profit") or 0))
    summary["gross_margin_rate"] = _jsonable((gross_profit / amount * Decimal("100")) if amount else None)
    hidden_fields = {
        rule.field_name
        for rule in get_field_permission_rules(db, current_user, "sales_detail")
        if rule.permission_type in {"hidden", "masked"}
    }
    if "cost_amount" in hidden_fields:
        summary["cost_amount"] = None
    if "gross_profit" in hidden_fields:
        summary["gross_profit"] = None
        summary["gross_margin_rate"] = None
    flow_stmt = select(InventoryFlowLedger.anomaly_type, func.count()).where(InventoryFlowLedger.sales_qty > 0)
    if date_from:
        flow_stmt = flow_stmt.where(InventoryFlowLedger.data_date >= date_from)
    if date_to:
        flow_stmt = flow_stmt.where(InventoryFlowLedger.data_date <= date_to)
    if product_code:
        flow_stmt = flow_stmt.where(InventoryFlowLedger.product_code == product_code)
    if warehouse_name:
        flow_stmt = flow_stmt.where(InventoryFlowLedger.warehouse_name == warehouse_name)
    flow_rows = db.execute(flow_stmt.group_by(InventoryFlowLedger.anomaly_type)).all()
    flow_counts = {str(anomaly_type or "normal"): int(count or 0) for anomaly_type, count in flow_rows}
    summary["inventory_abnormal_rows"] = sum(count for anomaly_type, count in flow_counts.items() if anomaly_type != "normal")
    summary["zero_stock_sales"] = flow_counts.get("sales_zero_stock", 0)
    summary["negative_stock_sales"] = flow_counts.get("sales_negative_stock", 0)
    summary["without_stock_sales"] = flow_counts.get("sales_without_stock", 0)
    return summary


def _inventory_summary(db: Session, stmt: Select[tuple[InventorySnapshot]]) -> dict:
    filtered = stmt.order_by(None).subquery()
    row = db.execute(
        select(
            func.count().label("rows"),
            func.count(func.distinct(filtered.c.product_code)).label("products"),
            func.count(func.distinct(filtered.c.default_supplier)).label("suppliers"),
            func.count(func.distinct(func.coalesce(filtered.c.warehouse_name, "未识别仓库"))).label("warehouses"),
            func.coalesce(func.sum(filtered.c.stock_qty), 0).label("stock_qty"),
            func.coalesce(func.sum(filtered.c.stock_inventory_qty), 0).label("stock_inventory_qty"),
            func.coalesce(func.sum(filtered.c.locked_base_qty), 0).label("locked_base_qty"),
            func.coalesce(func.sum(filtered.c.cost_amount), 0).label("cost_amount"),
        )
    ).mappings().one()
    summary = {key: _jsonable(value) for key, value in dict(row).items()}
    positive_rows = db.scalar(select(func.count()).select_from(filtered).where(filtered.c.stock_qty > 0)) or 0
    zero_rows = db.scalar(select(func.count()).select_from(filtered).where(filtered.c.stock_qty == 0)) or 0
    negative_rows = db.scalar(select(func.count()).select_from(filtered).where(filtered.c.stock_qty < 0)) or 0
    locked_rows = db.scalar(select(func.count()).select_from(filtered).where(filtered.c.locked_base_qty > 0)) or 0
    summary["positive_rows"] = positive_rows
    summary["zero_rows"] = zero_rows
    summary["negative_rows"] = negative_rows
    summary["locked_rows"] = locked_rows
    summary["abnormal_rows"] = (
        db.scalar(
            select(func.count())
            .select_from(filtered)
            .where(or_(filtered.c.stock_qty < 0, filtered.c.locked_base_qty > 0))
        )
        or 0
    )
    return summary


def _purchase_summary(db: Session, stmt: Select[tuple[PurchaseDetail]]) -> dict:
    filtered = stmt.order_by(None).subquery()
    row = db.execute(
        select(
            func.count().label("rows"),
            func.count(func.distinct(filtered.c.document_no)).label("documents"),
            func.count(func.distinct(filtered.c.supplier_code)).label("suppliers"),
            func.count(func.distinct(filtered.c.product_code)).label("products"),
            func.coalesce(func.sum(filtered.c.purchase_qty_base), 0).label("purchase_qty_base"),
            func.coalesce(func.sum(filtered.c.amount_tax_total), 0).label("amount_tax_total"),
            func.coalesce(func.sum(filtered.c.amount_after_discount), 0).label("amount_after_discount"),
            func.coalesce(func.sum(filtered.c.purchase_amount), 0).label("purchase_amount"),
            func.coalesce(func.sum(filtered.c.discount_amount), 0).label("discount_amount"),
            func.coalesce(func.sum(filtered.c.tax_amount), 0).label("tax_amount"),
        )
    ).mappings().one()
    return {key: _jsonable(value) for key, value in dict(row).items()}


def _account_balance_summary(db: Session, stmt: Select[tuple[AccountBalanceSnapshot]]) -> dict:
    filtered = stmt.order_by(None).subquery()
    row = db.execute(
        select(
            func.count().label("rows"),
            func.count(func.distinct(filtered.c.settlement_unit_code)).label("settlement_units"),
            func.coalesce(func.sum(filtered.c.current_opening_balance), 0).label("current_opening_balance"),
            func.coalesce(func.sum(filtered.c.current_amount), 0).label("current_amount"),
            func.coalesce(func.sum(filtered.c.current_closing_balance), 0).label("current_closing_balance"),
            func.coalesce(func.sum(filtered.c.ar_balance), 0).label("ar_balance"),
            func.coalesce(func.sum(filtered.c.ap_balance), 0).label("ap_balance"),
            func.coalesce(func.sum(filtered.c.advance_receipt_balance), 0).label("advance_receipt_balance"),
            func.coalesce(func.sum(filtered.c.advance_payment_balance), 0).label("advance_payment_balance"),
        )
    ).mappings().one()
    summary = {key: _jsonable(value) for key, value in dict(row).items()}
    summary["ar_rows"] = db.scalar(select(func.count()).select_from(filtered).where(filtered.c.ar_balance != 0)) or 0
    summary["ap_rows"] = db.scalar(select(func.count()).select_from(filtered).where(filtered.c.ap_balance != 0)) or 0
    summary["advance_receipt_rows"] = db.scalar(select(func.count()).select_from(filtered).where(filtered.c.advance_receipt_balance != 0)) or 0
    summary["advance_payment_rows"] = db.scalar(select(func.count()).select_from(filtered).where(filtered.c.advance_payment_balance != 0)) or 0
    summary["zero_rows"] = db.scalar(select(func.count()).select_from(filtered).where(filtered.c.current_closing_balance == 0)) or 0
    summary["risk_rows"] = (
        db.scalar(
            select(func.count())
            .select_from(filtered)
            .where(
                or_(
                    filtered.c.ar_balance != 0,
                    filtered.c.ap_balance != 0,
                    filtered.c.advance_receipt_balance != 0,
                    filtered.c.advance_payment_balance != 0,
                )
            )
        )
        or 0
    )
    return summary


def _account_ledger_summary(db: Session, stmt: Select[tuple[AccountLedgerEntry]]) -> dict:
    filtered = stmt.order_by(None).subquery()
    base_row = db.execute(
        select(
            func.count().label("rows"),
            func.count(func.distinct(filtered.c.settlement_unit_code)).label("settlement_units"),
        )
    ).mappings().one()
    closing_effective_date = func.coalesce(filtered.c.balance_date, filtered.c.data_date)
    latest_closing_date = db.scalar(
        select(func.max(closing_effective_date)).select_from(filtered).where(filtered.c.row_role == "closing")
    )
    latest_closing = db.execute(
        select(
            func.coalesce(func.sum(filtered.c.current_balance), 0).label("current_balance"),
            func.coalesce(func.sum(filtered.c.ar_amount), 0).label("ar_amount"),
            func.coalesce(func.sum(filtered.c.ap_amount), 0).label("ap_amount"),
            func.coalesce(func.sum(filtered.c.advance_receipt_amount), 0).label("advance_receipt_amount"),
            func.coalesce(func.sum(filtered.c.advance_payment_amount), 0).label("advance_payment_amount"),
            func.count().label("balance_rows"),
            func.count().filter(filtered.c.ar_amount != 0).label("non_zero_ar_rows"),
            func.count().filter(filtered.c.ap_amount != 0).label("non_zero_ap_rows"),
        )
        .select_from(filtered)
        .where(filtered.c.row_role == "closing", closing_effective_date == latest_closing_date)
    ).mappings().one()
    transaction = db.execute(
        select(
            func.count(func.distinct(filtered.c.document_no)).label("documents"),
            func.coalesce(func.sum(filtered.c.received_amount), 0).label("received_amount"),
            func.coalesce(func.sum(filtered.c.paid_amount), 0).label("paid_amount"),
        )
        .select_from(filtered)
        .where(filtered.c.row_role == "transaction")
    ).mappings().one()
    summary = {key: _jsonable(value) for key, value in dict(base_row).items()}
    summary.update({key: _jsonable(value) for key, value in dict(latest_closing).items()})
    summary.update({key: _jsonable(value) for key, value in dict(transaction).items()})
    summary["opening_rows"] = db.scalar(select(func.count()).select_from(filtered).where(filtered.c.row_role == "opening")) or 0
    summary["closing_rows"] = db.scalar(select(func.count()).select_from(filtered).where(filtered.c.row_role == "closing")) or 0
    summary["transaction_rows"] = db.scalar(select(func.count()).select_from(filtered).where(filtered.c.row_role == "transaction")) or 0
    latest_date = latest_closing_date or db.scalar(select(func.max(filtered.c.data_date)).select_from(filtered))
    summary["latest_data_date"] = latest_date.isoformat() if latest_date else None
    return summary


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    return value

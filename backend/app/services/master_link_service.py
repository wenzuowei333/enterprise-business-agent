from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    AccountLedgerEntry,
    CustomerMaster,
    ImportBatch,
    MasterLinkIssue,
    ProductMaster,
    PurchaseDetail,
    SalesDetail,
    SupplierMaster,
    User,
)


PROCESS_LINK_FILE_TYPES = {"sales_detail", "purchase_detail", "account_ledger"}
OPEN_ISSUE_STATUSES = {"open"}


ISSUE_LABELS = {
    "missing_customer": "缺客户档案",
    "missing_supplier": "缺供应商档案",
    "missing_product": "缺商品档案",
    "cross_role_customer_in_supplier": "客户存在于供应商档案",
    "cross_role_supplier_in_customer": "供应商存在于客户档案",
    "missing_settlement_unit": "结算单位未匹配",
}


def rebuild_master_link_issues(db: Session, *, batch_id: int | None = None) -> dict[str, int]:
    if batch_id is not None:
        batch = db.get(ImportBatch, batch_id)
        if batch is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch not found")
        issues = rebuild_batch_master_link_issues(db, batch)
        return {"batches": 1, "issues": len(issues)}

    batches = list(
        db.scalars(
            select(ImportBatch)
            .where(ImportBatch.file_type.in_(PROCESS_LINK_FILE_TYPES))
            .order_by(ImportBatch.id)
        ).all()
    )
    issue_count = 0
    for batch in batches:
        issue_count += len(rebuild_batch_master_link_issues(db, batch))
    return {"batches": len(batches), "issues": issue_count}


def rebuild_batch_master_link_issues(
    db: Session,
    batch: ImportBatch,
    rows: list[dict[str, Any]] | None = None,
) -> list[MasterLinkIssue]:
    if batch.file_type not in PROCESS_LINK_FILE_TYPES:
        _replace_batch_issues(db, batch, [])
        return []
    context = _master_lookup_context(db)
    source_rows = rows if rows is not None else _load_committed_batch_rows(db, batch)
    issue_data = _collect_issue_data(batch.file_type, source_rows, context)
    return _replace_batch_issues(db, batch, issue_data)


def resolve_master_link_issue(
    db: Session,
    issue_id: int,
    *,
    user: User,
    resolution_type: str,
    note: str | None = None,
) -> MasterLinkIssue:
    issue = db.get(MasterLinkIssue, issue_id)
    if issue is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Master link issue not found")
    issue.status = "ignored" if resolution_type == "ignore" else "resolved"
    issue.resolution_type = resolution_type
    issue.resolved_by_user_id = user.id
    issue.resolved_at = datetime.now(timezone.utc)
    issue.resolution_note = (note or "").strip() or None
    return issue


def master_link_issue_summary(db: Session) -> dict[str, int]:
    issues = db.scalars(select(MasterLinkIssue).where(MasterLinkIssue.status == "open")).all()
    summary: dict[str, int] = {"total": 0}
    for issue in issues:
        summary["total"] += 1
        summary[issue.issue_type] = summary.get(issue.issue_type, 0) + 1
        summary[issue.expected_master_kind] = summary.get(issue.expected_master_kind, 0) + 1
    return summary


def _replace_batch_issues(db: Session, batch: ImportBatch, issue_data: list[dict[str, Any]]) -> list[MasterLinkIssue]:
    resolved_keys = {
        _issue_key(issue)
        for issue in db.scalars(select(MasterLinkIssue).where(MasterLinkIssue.batch_id == batch.id, MasterLinkIssue.status != "open")).all()
    }
    db.execute(delete(MasterLinkIssue).where(MasterLinkIssue.batch_id == batch.id, MasterLinkIssue.status == "open"))
    result: list[MasterLinkIssue] = []
    for data in issue_data:
        if _data_key(data) in resolved_keys:
            continue
        values = dict(data)
        values.pop("source_file_type", None)
        issue = MasterLinkIssue(batch_id=batch.id, source_file_type=batch.file_type, status="open", **values)
        db.add(issue)
        result.append(issue)
    db.flush()
    return result


def _issue_key(issue: MasterLinkIssue) -> tuple[str, str, str, str, str]:
    return (
        issue.source_file_type or "",
        issue.issue_type or "",
        issue.reference_code or "",
        issue.reference_name or "",
        issue.expected_master_kind or "",
    )


def _data_key(data: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        data.get("source_file_type") or "",
        data.get("issue_type") or "",
        data.get("reference_code") or "",
        data.get("reference_name") or "",
        data.get("expected_master_kind") or "",
    )


def _master_lookup_context(db: Session) -> dict[str, Any]:
    customers = list(db.scalars(select(CustomerMaster)).all())
    suppliers = list(db.scalars(select(SupplierMaster)).all())
    products = list(db.scalars(select(ProductMaster)).all())
    return {
        "customer_codes": {item.customer_code for item in customers if item.customer_code},
        "customer_names": {item.customer_name for item in customers if item.customer_name},
        "supplier_codes": {item.supplier_code for item in suppliers if item.supplier_code},
        "supplier_names": {item.supplier_name for item in suppliers if item.supplier_name},
        "product_codes": {item.product_code for item in products if item.product_code},
        "product_names": {item.product_name for item in products if item.product_name},
        "customer_by_code": {item.customer_code: item for item in customers if item.customer_code},
        "customer_by_name": {item.customer_name: item for item in customers if item.customer_name},
        "supplier_by_code": {item.supplier_code: item for item in suppliers if item.supplier_code},
        "supplier_by_name": {item.supplier_name: item for item in suppliers if item.supplier_name},
    }


def _load_committed_batch_rows(db: Session, batch: ImportBatch) -> list[dict[str, Any]]:
    if batch.file_type == "sales_detail":
        rows = db.scalars(select(SalesDetail).where(SalesDetail.batch_id == batch.id)).all()
        return [
            {
                "customer_code": row.customer_code,
                "customer_name": row.customer_name,
                "product_code": row.product_code,
                "product_name": row.product_name,
                "document_no": row.document_no,
                "document_date": row.document_date,
                "amount_after_discount": row.amount_after_discount,
                "sale_qty_base": row.sale_qty_base,
            }
            for row in rows
        ]
    if batch.file_type == "purchase_detail":
        rows = db.scalars(select(PurchaseDetail).where(PurchaseDetail.batch_id == batch.id)).all()
        return [
            {
                "supplier_code": row.supplier_code,
                "supplier_name": row.supplier_name,
                "product_code": row.product_code,
                "product_name": row.product_name,
                "document_no": row.document_no,
                "document_date": row.document_date,
                "amount_after_discount": row.amount_after_discount,
                "purchase_amount": row.purchase_amount,
                "purchase_qty_base": row.purchase_qty_base,
            }
            for row in rows
        ]
    if batch.file_type == "account_ledger":
        rows = db.scalars(select(AccountLedgerEntry).where(AccountLedgerEntry.batch_id == batch.id)).all()
        return [
            {
                "settlement_unit_code": row.settlement_unit_code,
                "settlement_unit_name": row.settlement_unit_name,
                "document_no": row.document_no,
                "document_date": row.document_date or row.balance_date or row.data_date,
                "document_amount": row.document_amount,
                "ar_amount": row.ar_amount,
                "ap_amount": row.ap_amount,
            }
            for row in rows
        ]
    return []


def _collect_issue_data(file_type: str, rows: list[dict[str, Any]], context: dict[str, Any]) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str, str, str], dict[str, Any]] = {}

    def add_issue(
        *,
        issue_type: str,
        expected_master_kind: str,
        reference_code: str | None,
        reference_name: str | None,
        document_no: str | None,
        seen_date: date | None,
        amount: Decimal | None,
        quantity: Decimal | None = None,
        counterpart_master_kind: str | None = None,
        counterpart_code: str | None = None,
        counterpart_name: str | None = None,
    ) -> None:
        key = (issue_type, expected_master_kind, reference_code or "", reference_name or "")
        bucket = buckets.get(key)
        if bucket is None:
            bucket = {
                "issue_type": issue_type,
                "expected_master_kind": expected_master_kind,
                "reference_code": reference_code,
                "reference_name": reference_name,
                "counterpart_master_kind": counterpart_master_kind,
                "counterpart_code": counterpart_code,
                "counterpart_name": counterpart_name,
                "first_seen_date": seen_date,
                "last_seen_date": seen_date,
                "affected_rows": 0,
                "affected_documents": 0,
                "amount_total": Decimal("0"),
                "quantity_total": Decimal("0"),
                "source_file_type": file_type,
                "source_json": {
                    "label": ISSUE_LABELS.get(issue_type, issue_type),
                    "document_nos": [],
                },
            }
            buckets[key] = bucket
        bucket["affected_rows"] += 1
        docs = bucket["source_json"]["document_nos"]
        if document_no and document_no not in docs:
            docs.append(document_no)
            bucket["affected_documents"] += 1
        if seen_date:
            bucket["first_seen_date"] = min([d for d in [bucket.get("first_seen_date"), seen_date] if d])
            bucket["last_seen_date"] = max([d for d in [bucket.get("last_seen_date"), seen_date] if d])
        if amount is not None:
            bucket["amount_total"] = (bucket["amount_total"] or Decimal("0")) + amount
        if quantity is not None:
            bucket["quantity_total"] = (bucket["quantity_total"] or Decimal("0")) + quantity

    for row in rows:
        if file_type == "sales_detail":
            customer_code = _clean(row.get("customer_code"))
            customer_name = _clean(row.get("customer_name"))
            product_code = _clean(row.get("product_code"))
            product_name = _clean(row.get("product_name"))
            seen_date = _to_date(row.get("document_date"))
            amount = _to_decimal(row.get("amount_after_discount"))
            if customer_code and customer_code not in context["customer_codes"]:
                counterpart = context["supplier_by_code"].get(customer_code) or (context["supplier_by_name"].get(customer_name) if customer_name else None)
                add_issue(
                    issue_type="cross_role_customer_in_supplier" if counterpart else "missing_customer",
                    expected_master_kind="customers",
                    reference_code=customer_code,
                    reference_name=customer_name,
                    document_no=_clean(row.get("document_no")),
                    seen_date=seen_date,
                    amount=amount,
                    counterpart_master_kind="suppliers" if counterpart else None,
                    counterpart_code=getattr(counterpart, "supplier_code", None),
                    counterpart_name=getattr(counterpart, "supplier_name", None),
                )
            if product_code and product_code not in context["product_codes"]:
                add_issue(
                    issue_type="missing_product",
                    expected_master_kind="products",
                    reference_code=product_code,
                    reference_name=product_name,
                    document_no=_clean(row.get("document_no")),
                    seen_date=seen_date,
                    amount=amount,
                    quantity=_to_decimal(row.get("sale_qty_base")),
                )
        elif file_type == "purchase_detail":
            supplier_code = _clean(row.get("supplier_code"))
            supplier_name = _clean(row.get("supplier_name"))
            product_code = _clean(row.get("product_code"))
            product_name = _clean(row.get("product_name"))
            seen_date = _to_date(row.get("document_date"))
            amount = _to_decimal(row.get("purchase_amount")) or _to_decimal(row.get("amount_after_discount"))
            if supplier_code and supplier_code not in context["supplier_codes"]:
                counterpart = context["customer_by_code"].get(supplier_code) or (context["customer_by_name"].get(supplier_name) if supplier_name else None)
                add_issue(
                    issue_type="cross_role_supplier_in_customer" if counterpart else "missing_supplier",
                    expected_master_kind="suppliers",
                    reference_code=supplier_code,
                    reference_name=supplier_name,
                    document_no=_clean(row.get("document_no")),
                    seen_date=seen_date,
                    amount=amount,
                    counterpart_master_kind="customers" if counterpart else None,
                    counterpart_code=getattr(counterpart, "customer_code", None),
                    counterpart_name=getattr(counterpart, "customer_name", None),
                )
            if product_code and product_code not in context["product_codes"]:
                add_issue(
                    issue_type="missing_product",
                    expected_master_kind="products",
                    reference_code=product_code,
                    reference_name=product_name,
                    document_no=_clean(row.get("document_no")),
                    seen_date=seen_date,
                    amount=amount,
                    quantity=_to_decimal(row.get("purchase_qty_base")),
                )
        elif file_type == "account_ledger":
            code = _clean(row.get("settlement_unit_code"))
            name = _clean(row.get("settlement_unit_name"))
            if not code and not name:
                continue
            code_matched = bool(code and (code in context["customer_codes"] or code in context["supplier_codes"]))
            name_matched = bool(name and (name in context["customer_names"] or name in context["supplier_names"]))
            if not code_matched and not name_matched:
                add_issue(
                    issue_type="missing_settlement_unit",
                    expected_master_kind="settlement_units",
                    reference_code=code,
                    reference_name=name,
                    document_no=_clean(row.get("document_no")),
                    seen_date=_to_date(row.get("document_date")),
                    amount=_to_decimal(row.get("ar_amount")) or _to_decimal(row.get("ap_amount")) or _to_decimal(row.get("document_amount")),
                )

    issues = list(buckets.values())
    for issue in issues:
        doc_nos = issue.get("source_json", {}).get("document_nos", [])
        issue["source_json"]["document_nos"] = doc_nos[:20]
        issue["source_json"]["document_count_sampled"] = len(doc_nos)
        if issue["amount_total"] == Decimal("0"):
            issue["amount_total"] = None
        if issue["quantity_total"] == Decimal("0"):
            issue["quantity_total"] = None
    return sorted(issues, key=lambda item: (item["issue_type"], item.get("reference_code") or "", item.get("reference_name") or ""))


def _clean(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def _to_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None

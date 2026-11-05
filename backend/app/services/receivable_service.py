from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.models import AccountLedgerEntry, ReceivableCheckResult, ReceivableSnapshot

RECEIVABLE_RESULT_TYPES = {
    "amount_mismatch",
    "missing_in_ledger",
    "missing_in_receivable_query",
    "unit_name_mismatch",
    "duplicate_unit",
}


def rebuild_receivable_checks(db: Session, *, batch_id: int | None = None) -> dict:
    if batch_id is not None:
        db.execute(delete(ReceivableCheckResult).where(ReceivableCheckResult.batch_id == batch_id))
        stmt = select(ReceivableSnapshot).where(ReceivableSnapshot.batch_id == batch_id)
        active_batch_id = batch_id
    else:
        db.execute(delete(ReceivableCheckResult))
        active_batch_id = _latest_receivable_snapshot_batch_id(db)
        if active_batch_id is None:
            return {
                "total_rows": 0,
                "unmatched_rows": 0,
                "risk_rows": 0,
            }
        stmt = select(ReceivableSnapshot).where(ReceivableSnapshot.batch_id == active_batch_id)

    rows = list(
        db.scalars(
            stmt.order_by(
                ReceivableSnapshot.data_date.desc().nullslast(),
                ReceivableSnapshot.customer_code,
                ReceivableSnapshot.customer_name,
                ReceivableSnapshot.id,
            )
        ).all()
    )

    row_dates = {row.data_date for row in rows if row.data_date is not None}
    if batch_id is not None and row_dates:
        db.execute(
            delete(ReceivableCheckResult).where(
                ReceivableCheckResult.receivable_snapshot_id.is_(None),
                ReceivableCheckResult.data_date.in_(row_dates),
            )
        )

    total_rows = len(rows)
    risk_rows = 0
    duplicate_rows = _build_receivable_duplicate_results(db, rows)
    risk_rows += duplicate_rows

    for row in rows:
        ledger_matches = _matching_ledger_entries(db, row)
        if not ledger_matches:
            row.match_status = "unmatched"
            row.matched_customer_code = None
            row.matched_customer_name = None
            db.add(_result(row, "missing_in_ledger", "warning", message="应收查询表未找到对应的往来明细期初或期末应收行"))
            risk_rows += 1
            continue

        ledger = ledger_matches[0]
        row.match_status = "matched_by_code" if row.customer_code else "matched_by_name"
        row.matched_customer_code = ledger.settlement_unit_code
        row.matched_customer_name = ledger.settlement_unit_name

        if len(ledger_matches) > 1:
            db.add(
                _result(
                    row,
                    "duplicate_unit",
                    "warning",
                    account_ar_balance=ledger.ar_amount,
                    message="往来明细中同一结算单位和日期存在多条期初或期末应收行",
                    source_extra={"ledger_entry_ids": [item.id for item in ledger_matches]},
                )
            )
            risk_rows += 1

        if row.customer_code and ledger.settlement_unit_code == row.customer_code:
            if row.customer_name and ledger.settlement_unit_name and row.customer_name != ledger.settlement_unit_name:
                db.add(
                    _result(
                        row,
                        "unit_name_mismatch",
                        "warning",
                        account_ar_balance=ledger.ar_amount,
                        message="结算单位编号一致，但应收查询表与往来明细名称不一致",
                        source_extra=_ledger_source(ledger),
                    )
                )
                risk_rows += 1

        if _decimal(ledger.ar_amount) != _decimal(row.ar_balance):
            db.add(
                _result(
                    row,
                    "amount_mismatch",
                    "danger",
                    account_ar_balance=ledger.ar_amount,
                    diff_amount=_decimal(row.ar_balance) - _decimal(ledger.ar_amount),
                    message="应收查询金额与往来明细应收金额不一致",
                    source_extra=_ledger_source(ledger),
                )
            )
            risk_rows += 1

    missing_in_receivable_query = _build_missing_receivable_query_results(
        db,
        data_dates=row_dates,
        result_batch_id=active_batch_id,
    )
    risk_rows += missing_in_receivable_query
    unmatched_stmt = select(func.count()).where(ReceivableSnapshot.match_status == "unmatched")
    if batch_id is not None:
        unmatched_stmt = unmatched_stmt.where(ReceivableSnapshot.batch_id == batch_id)

    return {
        "total_rows": total_rows,
        "unmatched_rows": db.scalar(unmatched_stmt) or 0,
        "risk_rows": risk_rows,
    }


def _latest_receivable_snapshot_batch_id(db: Session) -> int | None:
    return db.scalar(
        select(ReceivableSnapshot.batch_id)
        .where(ReceivableSnapshot.batch_id.is_not(None))
        .order_by(ReceivableSnapshot.batch_id.desc(), ReceivableSnapshot.id.desc())
        .limit(1)
    )


def receivable_summary(db: Session) -> dict:
    latest_date = db.scalar(select(func.max(ReceivableSnapshot.data_date)))
    if latest_date is None:
        return {
            "latest_data_date": None,
            "rows": 0,
            "customers": 0,
            "ar_balance": "0.00",
            "unmatched_rows": 0,
            "risk_rows": 0,
        }

    rows_stmt = select(ReceivableSnapshot).where(ReceivableSnapshot.data_date == latest_date)
    filtered = rows_stmt.order_by(None).subquery()
    row = db.execute(
        select(
            func.count().label("rows"),
            func.count(func.distinct(func.coalesce(filtered.c.customer_code, filtered.c.customer_name))).label("customers"),
            func.coalesce(func.sum(filtered.c.ar_balance), 0).label("ar_balance"),
        )
    ).mappings().one()
    risk_rows = db.scalar(select(func.count()).where(ReceivableCheckResult.data_date == latest_date)) or 0
    return {
        "latest_data_date": latest_date.isoformat(),
        "rows": int(row["rows"] or 0),
        "customers": int(row["customers"] or 0),
        "ar_balance": f"{_decimal(row['ar_balance']):.2f}",
        "unmatched_rows": db.scalar(select(func.count()).select_from(filtered).where(filtered.c.match_status == "unmatched")) or 0,
        "risk_rows": risk_rows,
    }


def _matching_ledger_entries(db: Session, row: ReceivableSnapshot) -> list[AccountLedgerEntry]:
    if row.data_date is None:
        return []
    stmt = select(AccountLedgerEntry).where(
        AccountLedgerEntry.row_role.in_(["opening", "closing"]),
        AccountLedgerEntry.balance_date == row.data_date,
    )
    if row.customer_code:
        stmt = stmt.where(AccountLedgerEntry.settlement_unit_code == row.customer_code)
    elif row.customer_name:
        stmt = stmt.where(AccountLedgerEntry.settlement_unit_name == row.customer_name)
    else:
        return []
    return list(db.scalars(stmt.order_by(AccountLedgerEntry.id)).all())


def _build_receivable_duplicate_results(db: Session, rows: list[ReceivableSnapshot]) -> int:
    counts: dict[tuple[str | None, str], list[ReceivableSnapshot]] = {}
    for row in rows:
        unit_key = row.customer_code or row.customer_name
        if not unit_key:
            continue
        key = (row.data_date.isoformat() if row.data_date else None, unit_key)
        counts.setdefault(key, []).append(row)
    risk_rows = 0
    for duplicates in counts.values():
        if len(duplicates) <= 1:
            continue
        for row in duplicates:
            db.add(_result(row, "duplicate_unit", "warning", message="应收查询表中同一结算单位和日期存在重复行"))
            risk_rows += 1
    return risk_rows


def _build_missing_receivable_query_results(db: Session, *, data_dates: set[date] | None = None, result_batch_id: int | None = None) -> int:
    stmt = select(AccountLedgerEntry).where(
        AccountLedgerEntry.row_role.in_(["opening", "closing"]),
        AccountLedgerEntry.balance_date.is_not(None),
        AccountLedgerEntry.ar_amount != 0,
    )
    if data_dates is not None:
        if not data_dates:
            return 0
        stmt = stmt.where(AccountLedgerEntry.balance_date.in_(data_dates))
    rows = list(
        db.scalars(
            stmt.order_by(
                AccountLedgerEntry.balance_date.desc().nullslast(),
                AccountLedgerEntry.settlement_unit_code,
                AccountLedgerEntry.settlement_unit_name,
                AccountLedgerEntry.id,
            )
        ).all()
    )
    seen_keys: set[tuple[str | None, str]] = set()
    risk_rows = 0
    for ledger in rows:
        unit_key = ledger.settlement_unit_code or ledger.settlement_unit_name
        if not unit_key:
            continue
        key = (
            ledger.balance_date.isoformat() if ledger.balance_date else None,
            unit_key,
        )
        if key in seen_keys:
            db.add(
                _ledger_result(
                    ledger,
                    "duplicate_unit",
                    "warning",
                    account_ar_balance=ledger.ar_amount,
                    message="往来明细中同一结算单位和日期存在重复期初或期末应收行",
                    batch_id=result_batch_id,
                )
            )
            risk_rows += 1
            continue
        seen_keys.add(key)
        if _receivable_query_exists_for_ledger(db, ledger):
            continue
        db.add(
            _ledger_result(
                ledger,
                "missing_in_receivable_query",
                "warning",
                account_ar_balance=ledger.ar_amount,
                message="往来明细存在期初或期末应收金额，但未找到对应应收查询表记录",
                batch_id=result_batch_id,
            )
        )
        risk_rows += 1
    return risk_rows


def _receivable_query_exists_for_ledger(db: Session, ledger: AccountLedgerEntry) -> bool:
    if ledger.balance_date is None:
        return False
    predicates = []
    if ledger.settlement_unit_code:
        predicates.append(ReceivableSnapshot.customer_code == ledger.settlement_unit_code)
    elif ledger.settlement_unit_name:
        predicates.append(ReceivableSnapshot.customer_name == ledger.settlement_unit_name)
    if not predicates:
        return False
    return bool(
        db.scalar(
            select(ReceivableSnapshot.id)
            .where(ReceivableSnapshot.data_date == ledger.balance_date, or_(*predicates))
            .limit(1)
        )
    )


def _ledger_source(ledger: AccountLedgerEntry) -> dict:
    return {
        "ledger_entry_id": ledger.id,
        "ledger_row_number": ledger.row_number,
        "ledger_row_role": ledger.row_role,
        "ledger_data_date": ledger.data_date.isoformat() if ledger.data_date else None,
        "ledger_balance_date": ledger.balance_date.isoformat() if ledger.balance_date else None,
        "ledger_period_start": ledger.period_start.isoformat() if ledger.period_start else None,
        "ledger_period_end": ledger.period_end.isoformat() if ledger.period_end else None,
        "ledger_document_type": ledger.document_type,
    }


def _result(
    row: ReceivableSnapshot,
    result_type: str,
    severity: str,
    *,
    account_ar_balance: Decimal | None = None,
    previous_ar_balance: Decimal | None = None,
    diff_amount: Decimal | None = None,
    overdue_days: int | None = None,
    recent_sales_amount: Decimal | None = None,
    message: str | None = None,
    source_extra: dict | None = None,
) -> ReceivableCheckResult:
    source_json = {
        "row_number": row.row_number,
        "aging_label": row.aging_label,
        "remark": row.remark,
    }
    if source_extra:
        source_json.update(source_extra)
    return ReceivableCheckResult(
        batch_id=row.batch_id,
        receivable_snapshot_id=row.id,
        result_type=result_type,
        severity=severity,
        data_date=row.data_date,
        customer_code=row.customer_code,
        customer_name=row.customer_name,
        matched_customer_code=row.matched_customer_code,
        matched_customer_name=row.matched_customer_name,
        receivable_ar_balance=row.ar_balance,
        account_ar_balance=account_ar_balance,
        previous_ar_balance=previous_ar_balance,
        diff_amount=diff_amount,
        overdue_days=overdue_days,
        recent_sales_amount=recent_sales_amount,
        message=message,
        source_json=source_json,
    )


def _ledger_result(
    ledger: AccountLedgerEntry,
    result_type: str,
    severity: str,
    *,
    account_ar_balance: Decimal | None = None,
    diff_amount: Decimal | None = None,
    message: str | None = None,
    batch_id: int | None = None,
) -> ReceivableCheckResult:
    return ReceivableCheckResult(
        batch_id=batch_id or ledger.batch_id,
        receivable_snapshot_id=None,
        result_type=result_type,
        severity=severity,
        data_date=ledger.balance_date or ledger.data_date,
        customer_code=ledger.settlement_unit_code,
        customer_name=ledger.settlement_unit_name,
        matched_customer_code=None,
        matched_customer_name=None,
        receivable_ar_balance=None,
        account_ar_balance=account_ar_balance,
        previous_ar_balance=None,
        diff_amount=diff_amount,
        overdue_days=None,
        recent_sales_amount=None,
        message=message,
        source_json=_ledger_source(ledger),
    )


def _decimal(value: object) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))

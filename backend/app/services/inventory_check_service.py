from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
import shutil
import uuid

import pandas as pd
from fastapi import UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import InventoryCheckBatch, InventoryCheckResult, InventoryCheckRow, InventoryFlowLedger, InventorySnapshot, ProductMaster, User
from app.services.audit_service import write_audit_log
from app.services.import_service import (
    clean_value,
    infer_data_date_from_upload,
    json_safe_row,
    json_safe_value,
    normalize_header,
    read_raw_upload_table,
    to_decimal,
    unique_headers,
)


FIELD_ALIASES = {
    "product_code": ["商品编号", "商品编码", "存货编码", "货品编号", "商品代码", "SKU", "sku", "product_code"],
    "product_name": ["商品名称", "货品名称", "存货名称", "产品名称", "product_name"],
    "warehouse_name": ["仓库", "仓库名称", "所属仓库", "warehouse_name"],
    "platform_stock_qty": [
        "账面库存_数量",
        "账面库存数量",
        "账面库存_库存数量",
        "库存数量",
        "实时库存",
        "平台库存",
        "可售库存",
        "stock_qty",
        "quantity",
    ],
}

RESULT_TYPES = {"quantity_mismatch", "missing_in_system", "missing_in_upload", "invalid_row", "missing_product_master"}


@dataclass
class ParsedInventoryRow:
    row_number: int
    product_code: str | None
    product_name: str | None
    warehouse_name: str | None
    platform_stock_qty: Decimal | None
    raw_row: dict
    error_message: str | None = None


@dataclass
class SystemInventoryItem:
    product_code: str
    product_name: str | None
    warehouse_name: str | None
    warehouse_scope: str | None
    stock_qty: Decimal
    data_date: date | None
    basis_type: str
    raw_snapshot: dict


def create_inventory_check_batch(db: Session, *, file: UploadFile, data_date: date | None, user: User) -> InventoryCheckBatch:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".xlsx", ".xls", ".csv"}:
        raise ValueError("Unsupported file extension")

    batch_no = f"CHK{datetime.now():%Y%m%d%H%M%S}-{uuid.uuid4().hex[:8]}"
    upload_root = Path(settings.upload_root).resolve() / "inventory_checks" / batch_no
    upload_root.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename or f"{batch_no}{suffix}").name
    raw_path = upload_root / safe_name
    with raw_path.open("wb") as output:
        shutil.copyfileobj(file.file, output)

    raw = read_raw_upload_table(raw_path)
    inferred_date, _source = infer_data_date_from_upload(raw, "inventory_snapshot", safe_name)
    resolved_date = data_date or inferred_date or date.today()
    df, headers, mapping = table_from_check_raw(raw)

    batch = InventoryCheckBatch(
        batch_no=batch_no,
        file_name=safe_name,
        data_date=resolved_date,
        uploaded_by=user.id,
        status="completed",
        raw_file_path=str(raw_path),
        header_json=headers,
        mapping_json=mapping,
        total_rows=len(df.index),
    )
    db.add(batch)
    db.flush()

    run_inventory_check(db, batch, raw=raw)
    write_audit_log(
        db,
        action_type="inventory_check_upload",
        resource_type="inventory_check",
        resource_id=batch.batch_no,
        user=user,
        after_data={
            "file_name": batch.file_name,
            "data_date": batch.data_date.isoformat() if batch.data_date else None,
            "total_rows": batch.total_rows,
            "difference_rows": batch.difference_rows,
            "missing_in_system_rows": batch.missing_in_system_rows,
            "missing_in_upload_rows": batch.missing_in_upload_rows,
            "invalid_rows": batch.invalid_rows,
        },
    )
    return batch


def rebuild_inventory_check_batch(db: Session, *, batch: InventoryCheckBatch, user: User) -> InventoryCheckBatch:
    raw_path = Path(batch.raw_file_path)
    if not raw_path.exists():
        raise ValueError("Original inventory check file not found")
    before = inventory_check_summary(db, batch.id)
    raw = read_raw_upload_table(raw_path)
    run_inventory_check(db, batch, raw=raw)
    write_audit_log(
        db,
        action_type="inventory_check_rebuild",
        resource_type="inventory_check",
        resource_id=batch.batch_no,
        user=user,
        before_data=before,
        after_data={
            "file_name": batch.file_name,
            "data_date": batch.data_date.isoformat() if batch.data_date else None,
            "total_rows": batch.total_rows,
            "matched_rows": batch.matched_rows,
            "difference_rows": batch.difference_rows,
            "missing_in_system_rows": batch.missing_in_system_rows,
            "missing_in_upload_rows": batch.missing_in_upload_rows,
            "invalid_rows": batch.invalid_rows,
            "duplicate_upload_rows": batch.duplicate_upload_rows,
            "mapping_json": batch.mapping_json,
            "result_summary": inventory_check_summary(db, batch.id),
        },
    )
    return batch


def run_inventory_check(db: Session, batch: InventoryCheckBatch, *, raw: pd.DataFrame) -> None:
    df, headers, mapping = table_from_check_raw(raw)
    parsed_rows = parse_inventory_rows(df, mapping)
    db.execute(delete(InventoryCheckRow).where(InventoryCheckRow.batch_id == batch.id))
    db.execute(delete(InventoryCheckResult).where(InventoryCheckResult.batch_id == batch.id))

    batch.header_json = headers
    batch.mapping_json = mapping
    batch.total_rows = len(parsed_rows)
    batch.status = "completed"

    valid_by_key: dict[tuple[str, str | None], list[ParsedInventoryRow]] = defaultdict(list)
    invalid_count = 0
    for parsed in parsed_rows:
        row_status = "invalid" if parsed.error_message else "valid"
        if parsed.error_message:
            invalid_count += 1
        elif parsed.product_code:
            valid_by_key[(parsed.product_code, parsed.warehouse_name)].append(parsed)
        db.add(
            InventoryCheckRow(
                batch_id=batch.id,
                row_number=parsed.row_number,
                product_code=parsed.product_code,
                product_name=parsed.product_name,
                warehouse_name=parsed.warehouse_name,
                platform_stock_qty=parsed.platform_stock_qty,
                row_status=row_status,
                error_message=parsed.error_message,
                raw_row_json=parsed.raw_row,
            )
        )

    product_codes = set(
        db.scalars(
            select(ProductMaster.product_code).where(ProductMaster.product_code.is_not(None), ProductMaster.product_code != "")
        ).all()
    )
    system_by_key = load_system_inventory(db, batch.data_date)
    upload_has_warehouse = any(warehouse_name for _code, warehouse_name in valid_by_key)
    upload_codes = {code for code, _warehouse_name in valid_by_key}

    matched_rows = 0
    duplicate_upload_rows = 0
    result_count = 0
    missing_in_system = 0
    missing_in_upload = 0

    for (code, warehouse_name), rows in valid_by_key.items():
        platform_qty = sum((row.platform_stock_qty or Decimal("0") for row in rows), Decimal("0"))
        duplicate = len(rows) > 1
        if duplicate:
            duplicate_upload_rows += len(rows) - 1
        product_name = next((row.product_name for row in rows if row.product_name), None)
        if code not in product_codes:
            missing_in_system += 1
            result_count += 1
            db.add(
                result_from_upload(
                    batch.id,
                    "missing_product_master",
                    code,
                    product_name,
                    warehouse_name,
                    platform_qty,
                    None,
                    None,
                    rows,
                    duplicate,
                    None,
                )
            )
            continue

        system_item = system_by_key.get((code, warehouse_name)) or (system_by_key.get((code, None)) if not warehouse_name else None)
        if system_item is None:
            missing_in_system += 1
            result_count += 1
            db.add(result_from_upload(batch.id, "missing_in_system", code, product_name, warehouse_name, platform_qty, None, None, rows, duplicate, None))
            continue
        diff = platform_qty - system_item.stock_qty
        if diff == 0:
            matched_rows += 1
            continue
        result_count += 1
        db.add(result_from_upload(batch.id, "quantity_mismatch", code, product_name or system_item.product_name, warehouse_name or system_item.warehouse_name, platform_qty, system_item.stock_qty, diff, rows, duplicate, system_item))

    for (code, warehouse_name), item in system_by_key.items():
        if warehouse_name is None:
            continue
        if upload_has_warehouse:
            if (code, warehouse_name) in valid_by_key or (code, None) in valid_by_key:
                continue
        elif code in upload_codes:
            continue
        missing_in_upload += 1
        result_count += 1
        db.add(
            InventoryCheckResult(
                batch_id=batch.id,
                result_type="missing_in_upload",
                product_code=code,
                product_name=item.product_name,
                warehouse_name=item.warehouse_name,
                warehouse_scope=item.warehouse_scope,
                platform_stock_qty=None,
                system_stock_qty=item.stock_qty,
                diff_qty=None,
                system_data_date=item.data_date,
                duplicate_in_upload=False,
                source_row_numbers=[],
                platform_row_json=None,
                system_snapshot_json=item.raw_snapshot,
            )
        )

    for parsed in parsed_rows:
        if not parsed.error_message:
            continue
        result_count += 1
        db.add(
            InventoryCheckResult(
                batch_id=batch.id,
                result_type="invalid_row",
                product_code=parsed.product_code,
                product_name=parsed.product_name,
                warehouse_name=parsed.warehouse_name,
                warehouse_scope=None,
                platform_stock_qty=parsed.platform_stock_qty,
                system_stock_qty=None,
                diff_qty=None,
                system_data_date=None,
                duplicate_in_upload=False,
                source_row_numbers=[parsed.row_number],
                platform_row_json={"error_message": parsed.error_message, "raw_row": parsed.raw_row},
                system_snapshot_json=None,
            )
        )

    batch.matched_rows = matched_rows
    batch.difference_rows = result_count
    batch.missing_in_system_rows = missing_in_system
    batch.missing_in_upload_rows = missing_in_upload
    batch.invalid_rows = invalid_count
    batch.duplicate_upload_rows = duplicate_upload_rows


def inventory_check_summary(db: Session, batch_id: int) -> dict[str, object]:
    rows = db.execute(
        select(InventoryCheckResult.result_type, func.count())
        .where(InventoryCheckResult.batch_id == batch_id)
        .group_by(InventoryCheckResult.result_type)
    ).all()
    return {result_type: int(count or 0) for result_type, count in rows}


def table_from_check_raw(raw: pd.DataFrame) -> tuple[pd.DataFrame, list[str], dict[str, str]]:
    raw = raw.fillna("")
    header_index = detect_check_header_index(raw)
    headers = unique_headers(raw.iloc[header_index].tolist())
    data = raw.iloc[header_index + 1 :].copy()
    data.columns = headers
    data["__row_number"] = [int(index) + 1 for index in data.index]
    data = data.loc[~data.drop(columns=["__row_number"]).apply(lambda row: all(clean_value(value) is None for value in row), axis=1)]
    mapping = build_check_mapping(headers)
    return data.reset_index(drop=True), headers, mapping


def detect_check_header_index(raw: pd.DataFrame) -> int:
    best_index = 0
    best_score = 0
    max_scan_rows = min(len(raw.index), 80)
    all_aliases = {alias for aliases in FIELD_ALIASES.values() for alias in aliases}
    for index in range(max_scan_rows):
        values = {normalize_header(value) for value in raw.iloc[index].tolist() if normalize_header(value)}
        score = sum(1 for alias in all_aliases if alias in values)
        if score > best_score:
            best_index = index
            best_score = score
    return best_index


def build_check_mapping(headers: list[str]) -> dict[str, str]:
    normalized_headers = {normalize_header(header): header for header in headers}
    mapping: dict[str, str] = {}
    for canonical, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            normalized_alias = normalize_header(alias)
            if normalized_alias in normalized_headers:
                mapping[canonical] = normalized_headers[normalized_alias]
                break
    return mapping


def parse_inventory_rows(df: pd.DataFrame, mapping: dict[str, str]) -> list[ParsedInventoryRow]:
    rows: list[ParsedInventoryRow] = []
    for index, raw_row in enumerate(df.to_dict(orient="records"), start=2):
        row_number = int(raw_row.get("__row_number") or index)
        raw = json_safe_row(raw_row)
        product_code = clean_value(raw_row.get(mapping.get("product_code", "")))
        product_name = clean_value(raw_row.get(mapping.get("product_name", "")))
        warehouse_name = clean_value(raw_row.get(mapping.get("warehouse_name", "")))
        stock_qty = to_decimal(raw_row.get(mapping.get("platform_stock_qty", "")))
        errors: list[str] = []
        if not product_code:
            errors.append("缺少商品编号")
        if stock_qty is None:
            errors.append("库存数量无法识别")
        rows.append(
            ParsedInventoryRow(
                row_number=row_number,
                product_code=product_code,
                product_name=product_name,
                warehouse_name=warehouse_name,
                platform_stock_qty=stock_qty,
                raw_row=raw,
                error_message="；".join(errors) if errors else None,
            )
        )
    return rows


def load_system_inventory(db: Session, data_date: date | None = None) -> dict[tuple[str, str | None], SystemInventoryItem]:
    result = load_flow_system_inventory(db, data_date)
    snapshot_result = load_snapshot_system_inventory(db, data_date)
    for key, item in snapshot_result.items():
        result.setdefault(key, item)
    return result


def load_flow_system_inventory(db: Session, data_date: date | None = None) -> dict[tuple[str, str | None], SystemInventoryItem]:
    stmt = select(InventoryFlowLedger).where(InventoryFlowLedger.product_code.is_not(None), InventoryFlowLedger.product_code != "")
    if data_date is not None:
        stmt = stmt.where(InventoryFlowLedger.data_date <= data_date)
    rows = list(
        db.scalars(
            stmt.order_by(
                InventoryFlowLedger.product_code,
                InventoryFlowLedger.warehouse_scope,
                InventoryFlowLedger.warehouse_name,
                InventoryFlowLedger.data_date.desc(),
                InventoryFlowLedger.id.desc(),
            )
        ).all()
    )
    latest_by_key: dict[tuple[str, str | None, str | None], InventoryFlowLedger] = {}
    for row in rows:
        code = clean_value(row.product_code)
        if not code:
            continue
        key = (code, clean_value(row.warehouse_name), row.warehouse_scope)
        latest_by_key.setdefault(key, row)

    result: dict[tuple[str, str | None], SystemInventoryItem] = {}
    product_totals: dict[str, list[SystemInventoryItem]] = defaultdict(list)
    for (code, warehouse_name, warehouse_scope), row in latest_by_key.items():
        stock_qty = decimal_or_none(row.calculated_closing_qty)
        if stock_qty is None:
            stock_qty = decimal_or_none(row.snapshot_stock_qty)
        if stock_qty is None:
            continue
        item = SystemInventoryItem(
            product_code=code,
            product_name=row.product_name,
            warehouse_name=warehouse_name,
            warehouse_scope=warehouse_scope,
            stock_qty=stock_qty,
            data_date=row.data_date,
            basis_type="inventory_flow",
            raw_snapshot={
                "basis_type": "inventory_flow",
                "basis_label": "流转结存",
                "flow_id": row.id,
                "data_date": row.data_date.isoformat() if row.data_date else None,
                "warehouse_name": warehouse_name,
                "warehouse_scope": warehouse_scope,
                "opening_stock_qty": json_safe_value(row.opening_stock_qty),
                "purchase_qty": json_safe_value(row.purchase_qty),
                "sales_qty": json_safe_value(row.sales_qty),
                "calculated_closing_qty": json_safe_value(row.calculated_closing_qty),
                "snapshot_stock_qty": json_safe_value(row.snapshot_stock_qty),
                "diff_qty": json_safe_value(row.diff_qty),
                "anomaly_type": row.anomaly_type,
            },
        )
        result[(code, warehouse_name)] = item
        product_totals[code].append(item)

    for code, items in product_totals.items():
        scoped_items = [item for item in items if item.warehouse_scope != "all"] or items
        stock_qty = sum((item.stock_qty for item in scoped_items), Decimal("0"))
        latest_date = max((item.data_date for item in scoped_items if item.data_date), default=None)
        first = scoped_items[0]
        result[(code, None)] = SystemInventoryItem(
            product_code=code,
            product_name=first.product_name,
            warehouse_name=None,
            warehouse_scope="all",
            stock_qty=stock_qty,
            data_date=latest_date,
            basis_type="inventory_flow",
            raw_snapshot={
                "basis_type": "inventory_flow",
                "basis_label": "流转结存",
                "warehouse_scope": "all",
                "data_date": latest_date.isoformat() if latest_date else None,
                "row_count": len(scoped_items),
                "stock_qty": str(stock_qty),
                "items": [item.raw_snapshot for item in scoped_items[:20]],
            },
        )
    return result


def load_snapshot_system_inventory(db: Session, data_date: date | None = None) -> dict[tuple[str, str | None], SystemInventoryItem]:
    stmt = select(
        InventorySnapshot.product_code.label("product_code"),
        InventorySnapshot.warehouse_name.label("warehouse_name"),
        InventorySnapshot.warehouse_scope.label("warehouse_scope"),
        func.max(InventorySnapshot.data_date).label("data_date"),
    ).where(InventorySnapshot.product_code.is_not(None), InventorySnapshot.product_code != "", InventorySnapshot.data_date.is_not(None))
    if data_date is not None:
        stmt = stmt.where(InventorySnapshot.data_date <= data_date)
    latest_dates = (
        stmt.group_by(InventorySnapshot.product_code, InventorySnapshot.warehouse_name, InventorySnapshot.warehouse_scope)
        .subquery()
    )
    rows = list(
        db.scalars(
            select(InventorySnapshot)
            .join(
                latest_dates,
                (InventorySnapshot.product_code == latest_dates.c.product_code)
                & (InventorySnapshot.warehouse_name.is_not_distinct_from(latest_dates.c.warehouse_name))
                & (InventorySnapshot.warehouse_scope == latest_dates.c.warehouse_scope)
                & (InventorySnapshot.data_date == latest_dates.c.data_date),
            )
            .order_by(InventorySnapshot.product_code, InventorySnapshot.id)
        ).all()
    )
    grouped: dict[tuple[str, str | None, str | None], list[InventorySnapshot]] = defaultdict(list)
    for row in rows:
        code = clean_value(row.product_code)
        if code:
            grouped[(code, clean_value(row.warehouse_name), row.warehouse_scope)].append(row)
    result: dict[tuple[str, str | None], SystemInventoryItem] = {}
    product_totals: dict[str, list[InventorySnapshot]] = defaultdict(list)
    for (code, warehouse_name, warehouse_scope), items in grouped.items():
        stock_qty = sum((Decimal(str(item.stock_qty or 0)) for item in items), Decimal("0"))
        first = items[0]
        item = SystemInventoryItem(
            product_code=code,
            product_name=first.product_name,
            warehouse_name=warehouse_name,
            warehouse_scope=warehouse_scope,
            stock_qty=stock_qty,
            data_date=first.data_date,
            basis_type="inventory_snapshot",
            raw_snapshot={
                "basis_type": "inventory_snapshot",
                "basis_label": "库存快照",
                "row_count": len(items),
                "data_date": first.data_date.isoformat() if first.data_date else None,
                "warehouse_name": warehouse_name,
                "warehouse_scope": warehouse_scope,
                "stock_qty": str(stock_qty),
                "items": [snapshot_json(item) for item in items[:20]],
            },
        )
        result[(code, warehouse_name)] = item
        product_totals[code].extend(items)
    for code, items in product_totals.items():
        stock_qty = sum((Decimal(str(item.stock_qty or 0)) for item in items), Decimal("0"))
        first = items[0]
        result[(code, None)] = SystemInventoryItem(
            product_code=code,
            product_name=first.product_name,
            warehouse_name=None,
            warehouse_scope="all",
            stock_qty=stock_qty,
            data_date=first.data_date,
            basis_type="inventory_snapshot",
            raw_snapshot={
                "basis_type": "inventory_snapshot",
                "basis_label": "库存快照",
                "row_count": len(items),
                "data_date": first.data_date.isoformat() if first.data_date else None,
                "warehouse_scope": "all",
                "stock_qty": str(stock_qty),
                "items": [snapshot_json(item) for item in items[:20]],
            },
        )
    return result


def decimal_or_none(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def result_from_upload(
    batch_id: int,
    result_type: str,
    product_code: str,
    product_name: str | None,
    warehouse_name: str | None,
    platform_qty: Decimal,
    system_qty: Decimal | None,
    diff_qty: Decimal | None,
    rows: list[ParsedInventoryRow],
    duplicate: bool,
    system_item: SystemInventoryItem | None,
) -> InventoryCheckResult:
    return InventoryCheckResult(
        batch_id=batch_id,
        result_type=result_type,
        product_code=product_code,
        product_name=product_name,
        warehouse_name=warehouse_name,
        warehouse_scope=system_item.warehouse_scope if system_item else None,
        platform_stock_qty=platform_qty,
        system_stock_qty=system_qty,
        diff_qty=diff_qty,
        system_data_date=system_item.data_date if system_item else None,
        duplicate_in_upload=duplicate,
        source_row_numbers=[row.row_number for row in rows],
        platform_row_json={"row_count": len(rows), "stock_qty": str(platform_qty), "items": [row.raw_row for row in rows[:20]]},
        system_snapshot_json=system_item.raw_snapshot if system_item else None,
    )


def snapshot_json(row: InventorySnapshot) -> dict:
    return {
        "id": row.id,
        "data_date": row.data_date.isoformat() if row.data_date else None,
        "product_code": row.product_code,
        "product_name": row.product_name,
        "warehouse_name": row.warehouse_name,
        "warehouse_scope": row.warehouse_scope,
        "stock_qty": json_safe_value(row.stock_qty),
        "stock_inventory_qty": json_safe_value(row.stock_inventory_qty),
        "stock_inventory_unit": row.stock_inventory_unit,
        "default_supplier": row.default_supplier,
    }


def serialize_inventory_check_batch(batch: InventoryCheckBatch) -> dict:
    return {
        "id": batch.id,
        "batch_no": batch.batch_no,
        "file_name": batch.file_name,
        "data_date": batch.data_date.isoformat() if batch.data_date else None,
        "uploaded_by": batch.uploaded_by,
        "status": batch.status,
        "total_rows": batch.total_rows,
        "matched_rows": batch.matched_rows,
        "difference_rows": batch.difference_rows,
        "missing_in_system_rows": batch.missing_in_system_rows,
        "missing_in_upload_rows": batch.missing_in_upload_rows,
        "invalid_rows": batch.invalid_rows,
        "duplicate_upload_rows": batch.duplicate_upload_rows,
        "raw_file_path": batch.raw_file_path,
        "header_json": batch.header_json,
        "mapping_json": batch.mapping_json,
        "created_at": batch.created_at.isoformat() if batch.created_at else None,
        "updated_at": batch.updated_at.isoformat() if batch.updated_at else None,
    }


def serialize_inventory_check_result(row: InventoryCheckResult) -> dict:
    system_snapshot = row.system_snapshot_json or {}
    return {
        "id": row.id,
        "batch_id": row.batch_id,
        "result_type": row.result_type,
        "product_code": row.product_code,
        "product_name": row.product_name,
        "warehouse_name": row.warehouse_name,
        "platform_stock_qty": json_safe_value(row.platform_stock_qty),
        "system_stock_qty": json_safe_value(row.system_stock_qty),
        "diff_qty": json_safe_value(row.diff_qty),
        "system_data_date": row.system_data_date.isoformat() if row.system_data_date else None,
        "system_basis_type": system_snapshot.get("basis_type"),
        "system_basis_label": system_snapshot.get("basis_label"),
        "duplicate_in_upload": row.duplicate_in_upload,
        "source_row_numbers": row.source_row_numbers or [],
        "platform_row_json": row.platform_row_json,
        "system_snapshot_json": row.system_snapshot_json,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def serialize_inventory_check_row(row: InventoryCheckRow) -> dict:
    return {
        "id": row.id,
        "batch_id": row.batch_id,
        "row_number": row.row_number,
        "product_code": row.product_code,
        "product_name": row.product_name,
        "warehouse_name": row.warehouse_name,
        "platform_stock_qty": json_safe_value(row.platform_stock_qty),
        "row_status": row.row_status,
        "error_message": row.error_message,
        "raw_row_json": row.raw_row_json,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }

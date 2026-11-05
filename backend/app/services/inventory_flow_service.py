from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import InventoryFlowLedger, InventorySnapshot, PurchaseDetail, SalesDetail
from app.services.import_service import clean_value, json_safe_value


SUMMARY_WAREHOUSE = "所辖仓库"
NORMAL = "normal"


@dataclass(frozen=True)
class FlowKey:
    data_date: date
    warehouse_name: str
    warehouse_scope: str
    product_code: str


@dataclass
class FlowBucket:
    product_name: str | None = None
    purchase_qty: Decimal = Decimal("0")
    sales_qty: Decimal = Decimal("0")
    snapshot_stock_qty: Decimal | None = None
    source_batch_ids: set[int] | None = None
    source_counts: dict[str, int] | None = None

    def __post_init__(self) -> None:
        if self.source_batch_ids is None:
            self.source_batch_ids = set()
        if self.source_counts is None:
            self.source_counts = {"sales": 0, "purchase": 0, "snapshot": 0}


def rebuild_after_sales_import(db: Session, batch_id: int) -> None:
    rebuild_inventory_flow(db, trigger_batch_id=batch_id)


def rebuild_after_purchase_import(db: Session, batch_id: int) -> None:
    rebuild_inventory_flow(db, trigger_batch_id=batch_id)


def rebuild_after_inventory_import(db: Session, batch_id: int) -> None:
    rebuild_inventory_flow(db, trigger_batch_id=batch_id)


def rebuild_inventory_flow(db: Session, *, trigger_batch_id: int | None = None) -> dict[str, int]:
    db.execute(delete(InventoryFlowLedger))
    buckets = build_flow_buckets(db)
    snapshots = load_snapshot_index(db)
    all_snapshot_products = {(code, scope) for code, scope, _warehouse in snapshots["product_scopes"]}

    created = 0
    for key in sorted(buckets, key=lambda item: (item.data_date, item.warehouse_name, item.product_code)):
        bucket = buckets[key]
        opening_stock = latest_stock_before(snapshots["by_key"], key)
        snapshot_stock = bucket.snapshot_stock_qty
        if bucket.purchase_qty == 0 and bucket.sales_qty == 0 and snapshot_stock is not None:
            calculated = snapshot_stock
        else:
            calculated = (opening_stock if opening_stock is not None else Decimal("0")) + bucket.purchase_qty - bucket.sales_qty
        diff = calculated - snapshot_stock if snapshot_stock is not None else None
        flags = anomaly_flags_for(key, bucket, opening_stock, snapshot_stock, calculated, diff, snapshots, all_snapshot_products)
        anomaly_type = flags[0] if flags else NORMAL
        db.add(
            InventoryFlowLedger(
                data_date=key.data_date,
                warehouse_name=key.warehouse_name,
                warehouse_scope=key.warehouse_scope,
                product_code=key.product_code,
                product_name=bucket.product_name,
                opening_stock_qty=opening_stock,
                purchase_qty=bucket.purchase_qty,
                sales_qty=bucket.sales_qty,
                calculated_closing_qty=calculated,
                snapshot_stock_qty=snapshot_stock,
                diff_qty=diff,
                anomaly_type=anomaly_type,
                anomaly_flags=flags,
                source_batch_ids=sorted(bucket.source_batch_ids or []),
                source_counts=bucket.source_counts,
            )
        )
        created += 1
    return {"created": created, "trigger_batch_id": trigger_batch_id or 0}


def build_flow_buckets(db: Session) -> dict[FlowKey, FlowBucket]:
    buckets: dict[FlowKey, FlowBucket] = {}

    for row in db.execute(
        select(
            SalesDetail.data_date,
            SalesDetail.warehouse_name,
            SalesDetail.product_code,
            func.max(SalesDetail.product_name),
            func.coalesce(func.sum(SalesDetail.sale_qty_base), 0),
            func.count(),
            func.array_agg(func.distinct(SalesDetail.batch_id)),
        )
        .where(SalesDetail.data_date.is_not(None), SalesDetail.product_code.is_not(None), SalesDetail.product_code != "")
        .group_by(SalesDetail.data_date, SalesDetail.warehouse_name, SalesDetail.product_code)
    ):
        data_date, warehouse_name, product_code, product_name, qty, count, batch_ids = row
        key = flow_key(data_date, product_code, warehouse_name, "specific")
        bucket = buckets.setdefault(key, FlowBucket(product_name=product_name))
        bucket.product_name = bucket.product_name or product_name
        bucket.sales_qty += decimal_or_zero(qty)
        bucket.source_counts["sales"] = int(count or 0)
        bucket.source_batch_ids.update(batch_ids or [])

    for row in db.execute(
        select(
            PurchaseDetail.data_date,
            PurchaseDetail.warehouse_name,
            PurchaseDetail.product_code,
            func.max(PurchaseDetail.product_name),
            func.coalesce(func.sum(PurchaseDetail.purchase_qty_base), 0),
            func.count(),
            func.array_agg(func.distinct(PurchaseDetail.batch_id)),
        )
        .where(PurchaseDetail.data_date.is_not(None), PurchaseDetail.product_code.is_not(None), PurchaseDetail.product_code != "")
        .group_by(PurchaseDetail.data_date, PurchaseDetail.warehouse_name, PurchaseDetail.product_code)
    ):
        data_date, warehouse_name, product_code, product_name, qty, count, batch_ids = row
        key = flow_key(data_date, product_code, warehouse_name, "specific")
        bucket = buckets.setdefault(key, FlowBucket(product_name=product_name))
        bucket.product_name = bucket.product_name or product_name
        bucket.purchase_qty += decimal_or_zero(qty)
        bucket.source_counts["purchase"] = int(count or 0)
        bucket.source_batch_ids.update(batch_ids or [])

    for row in db.execute(
        select(
            InventorySnapshot.data_date,
            InventorySnapshot.warehouse_name,
            InventorySnapshot.warehouse_scope,
            InventorySnapshot.product_code,
            func.max(InventorySnapshot.product_name),
            func.coalesce(func.sum(InventorySnapshot.stock_qty), 0),
            func.count(),
            func.array_agg(func.distinct(InventorySnapshot.batch_id)),
        )
        .where(InventorySnapshot.data_date.is_not(None), InventorySnapshot.product_code.is_not(None), InventorySnapshot.product_code != "")
        .group_by(InventorySnapshot.data_date, InventorySnapshot.warehouse_name, InventorySnapshot.warehouse_scope, InventorySnapshot.product_code)
    ):
        data_date, warehouse_name, warehouse_scope, product_code, product_name, qty, count, batch_ids = row
        key = flow_key(data_date, product_code, warehouse_name, warehouse_scope or "unknown")
        bucket = buckets.setdefault(key, FlowBucket(product_name=product_name))
        bucket.product_name = bucket.product_name or product_name
        bucket.snapshot_stock_qty = decimal_or_zero(qty)
        bucket.source_counts["snapshot"] = int(count or 0)
        bucket.source_batch_ids.update(batch_ids or [])

    return buckets


def load_snapshot_index(db: Session) -> dict[str, Any]:
    by_key: dict[tuple[str, str, str], list[tuple[date, Decimal]]] = defaultdict(list)
    product_scopes: set[tuple[str, str, str]] = set()
    rows = db.execute(
        select(
            InventorySnapshot.data_date,
            InventorySnapshot.product_code,
            InventorySnapshot.warehouse_name,
            InventorySnapshot.warehouse_scope,
            func.coalesce(func.sum(InventorySnapshot.stock_qty), 0),
        )
        .where(InventorySnapshot.data_date.is_not(None), InventorySnapshot.product_code.is_not(None), InventorySnapshot.product_code != "")
        .group_by(InventorySnapshot.data_date, InventorySnapshot.product_code, InventorySnapshot.warehouse_name, InventorySnapshot.warehouse_scope)
    ).all()
    for data_date, product_code, warehouse_name, warehouse_scope, qty in rows:
        scope = warehouse_scope or "unknown"
        warehouse = normalized_warehouse(warehouse_name, scope)
        code = str(product_code)
        by_key[(code, scope, warehouse)].append((data_date, decimal_or_zero(qty)))
        product_scopes.add((code, scope, warehouse))
    for values in by_key.values():
        values.sort(key=lambda item: item[0])
    return {"by_key": by_key, "product_scopes": product_scopes}


def latest_stock_before(by_key: dict[tuple[str, str, str], list[tuple[date, Decimal]]], key: FlowKey) -> Decimal | None:
    values = by_key.get((key.product_code, key.warehouse_scope, key.warehouse_name), [])
    latest: Decimal | None = None
    for snapshot_date, qty in values:
        if snapshot_date < key.data_date:
            latest = qty
        else:
            break
    return latest


def anomaly_flags_for(
    key: FlowKey,
    bucket: FlowBucket,
    opening_stock: Decimal | None,
    snapshot_stock: Decimal | None,
    calculated: Decimal,
    diff: Decimal | None,
    snapshots: dict[str, Any],
    all_snapshot_products: set[tuple[str, str]],
) -> list[str]:
    flags: list[str] = []
    has_sales = bucket.sales_qty > 0
    has_purchase_or_sales = bucket.sales_qty > 0 or bucket.purchase_qty > 0
    has_exact_snapshot_product = (key.product_code, key.warehouse_scope, key.warehouse_name) in snapshots["product_scopes"]
    has_summary_snapshot_product = (key.product_code, "all") in all_snapshot_products

    if key.warehouse_scope == "specific" and not clean_value(key.warehouse_name):
        flags.append("warehouse_unmatched")
    if has_sales and not has_exact_snapshot_product and has_summary_snapshot_product:
        flags.append("summary_stock_only")
    elif has_sales and not has_exact_snapshot_product and opening_stock is None and snapshot_stock is None:
        flags.append("sales_without_stock")
    if has_sales and opening_stock == 0:
        flags.append("sales_zero_stock")
    if has_purchase_or_sales and calculated < 0:
        flags.append("sales_negative_stock")
    if diff is not None and diff != 0:
        flags.append("closing_mismatch")
    return flags


def flow_key(data_date: date, product_code: str, warehouse_name: str | None, warehouse_scope: str | None) -> FlowKey:
    scope = warehouse_scope or "unknown"
    return FlowKey(
        data_date=data_date,
        warehouse_name=normalized_warehouse(warehouse_name, scope),
        warehouse_scope=scope,
        product_code=str(product_code),
    )


def normalized_warehouse(value: str | None, scope: str) -> str:
    text = clean_value(value)
    if text:
        return text
    if scope == "all":
        return SUMMARY_WAREHOUSE
    return "未识别仓库"


def decimal_or_zero(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def serialize_inventory_flow(row: InventoryFlowLedger) -> dict[str, Any]:
    return {
        "id": row.id,
        "data_date": row.data_date.isoformat() if row.data_date else None,
        "warehouse_name": row.warehouse_name,
        "warehouse_scope": row.warehouse_scope,
        "product_code": row.product_code,
        "product_name": row.product_name,
        "opening_stock_qty": json_safe_value(row.opening_stock_qty),
        "purchase_qty": json_safe_value(row.purchase_qty),
        "sales_qty": json_safe_value(row.sales_qty),
        "calculated_closing_qty": json_safe_value(row.calculated_closing_qty),
        "snapshot_stock_qty": json_safe_value(row.snapshot_stock_qty),
        "diff_qty": json_safe_value(row.diff_qty),
        "anomaly_type": row.anomaly_type,
        "anomaly_flags": row.anomaly_flags or [],
        "source_batch_ids": row.source_batch_ids or [],
        "source_counts": row.source_counts or {},
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def inventory_flow_status_label(anomaly_type: str) -> str:
    return {
        "normal": "正常",
        "sales_without_stock": "无库存记录",
        "sales_zero_stock": "零库存销售",
        "sales_negative_stock": "负库存",
        "closing_mismatch": "结存不一致",
        "warehouse_unmatched": "仓库未匹配",
        "summary_stock_only": "仅汇总仓",
    }.get(anomaly_type, anomaly_type)

from __future__ import annotations
import hashlib
import json
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import ImportBatch, InventorySnapshot


def latest_committed_inventory_batch(db: Session) -> ImportBatch | None:
    return db.scalar(
        select(ImportBatch)
        .join(InventorySnapshot, InventorySnapshot.batch_id == ImportBatch.id)
        .where(ImportBatch.file_type == "inventory_snapshot", ImportBatch.status == "committed")
        .order_by(
            InventorySnapshot.data_date.desc().nullslast(),
            ImportBatch.data_date.desc().nullslast(),
            ImportBatch.uploaded_at.desc(),
            ImportBatch.id.desc(),
        )
        .limit(1)
    )


def _case_fingerprint(row: InventorySnapshot, reason_code: str) -> str:
    identity = {
        "product": (row.product_code or row.product_name or f"snapshot:{row.id}").strip().casefold(),
        "warehouse": (row.warehouse_name or "unknown").strip().casefold(),
        "warehouse_scope": row.warehouse_scope or "unknown",
        "reason": reason_code,
    }
    return hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _evidence_version(row: InventorySnapshot, reason_code: str) -> str:
    payload = {
        "snapshot_id": row.id,
        "batch_id": row.batch_id,
        "data_date": row.data_date.isoformat() if row.data_date else None,
        "stock_qty": str(row.stock_qty) if row.stock_qty is not None else None,
        "locked_qty": str(row.locked_base_qty) if row.locked_base_qty is not None else None,
        "unit_relation": row.unit_relation,
        "reason": reason_code,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _anomaly_reasons(row: InventorySnapshot) -> list[str]:
    reasons: list[str] = []
    if Decimal(row.stock_qty or 0) < 0:
        reasons.append("negative_stock")
    if Decimal(row.locked_base_qty or 0) > 0:
        reasons.append("locked_stock")
    return reasons

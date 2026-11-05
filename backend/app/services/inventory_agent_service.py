from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    ImportBatch,
    InventoryAnomalyCase,
    InventoryCheckBatch,
    InventoryRemediationAction,
    InventorySnapshot,
    WorkItem,
)
from app.services.crm_project_service import generated_code


ANOMALY_STATUSES = {"open", "diagnosed", "blocked", "executing", "resolved"}
REMEDIATION_ACTION_TYPES = {
    "rebuild_inventory_flow",
    "rerun_inventory_check",
    "reimport_latest_snapshot",
    "create_upstream_adjustment",
    "reverse_or_repost_document",
}
UPSTREAM_ACTION_TYPES = {
    "reimport_latest_snapshot",
    "create_upstream_adjustment",
    "reverse_or_repost_document",
}
MISSING_WAREHOUSE_VALUES = {"", "-", "未识别仓库", "unknown", "none", "null"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


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


def _acquire_sync_lock(db: Session) -> None:
    bind = db.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        db.execute(select(func.pg_advisory_xact_lock(481927401)))


def sync_inventory_anomaly_cases(db: Session) -> ImportBatch | None:
    _acquire_sync_lock(db)
    batch = latest_committed_inventory_batch(db)
    if batch is None:
        return None
    rows = list(
        db.scalars(
            select(InventorySnapshot).where(
                InventorySnapshot.batch_id == batch.id,
                or_(
                    func.coalesce(InventorySnapshot.stock_qty, 0) < 0,
                    func.coalesce(InventorySnapshot.locked_base_qty, 0) > 0,
                ),
            )
        ).all()
    )
    existing = {
        row.fingerprint: row
        for row in db.scalars(select(InventoryAnomalyCase)).all()
    }
    current_fingerprints: set[str] = set()
    now = utcnow()
    for snapshot in rows:
        for reason_code in _anomaly_reasons(snapshot):
            fingerprint = _case_fingerprint(snapshot, reason_code)
            current_fingerprints.add(fingerprint)
            case = existing.get(fingerprint)
            if case is None:
                case = InventoryAnomalyCase(
                    case_no=generated_code("INVCASE"),
                    fingerprint=fingerprint,
                    reason_code=reason_code,
                    severity="high" if reason_code == "negative_stock" else "medium",
                    status="open",
                    detected_at=now,
                    evidence_version=_evidence_version(snapshot, reason_code),
                )
                db.add(case)
                existing[fingerprint] = case
            previous_version = case.evidence_version
            case.snapshot_id = snapshot.id
            case.batch_id = snapshot.batch_id
            case.data_date = snapshot.data_date
            case.product_code = snapshot.product_code
            case.product_name = snapshot.product_name
            case.warehouse_name = snapshot.warehouse_name
            case.warehouse_scope = snapshot.warehouse_scope
            case.stock_qty = snapshot.stock_qty
            case.locked_qty = snapshot.locked_base_qty
            case.evidence_version = _evidence_version(snapshot, reason_code)
            if case.status == "resolved" or (previous_version and previous_version != case.evidence_version):
                case.status = "open"
                case.resolved_at = None
                case.resolution_note = None
                if previous_version and previous_version != case.evidence_version:
                    case.root_cause = None
                    case.confidence = None
                    case.diagnosis_json = None
                    case.recommended_action = None
                    case.expected_result = None
                    case.diagnosed_at = None
    for fingerprint, case in existing.items():
        if fingerprint in current_fingerprints or case.status == "resolved":
            continue
        case.status = "resolved"
        case.resolved_at = now
        case.resolution_note = "异常未出现在最新已提交库存快照中。"
    db.flush()
    return batch


def serialize_anomaly_case(case: InventoryAnomalyCase) -> dict[str, Any]:
    return {
        "id": case.id,
        "case_no": case.case_no,
        "snapshot_id": case.snapshot_id,
        "batch_id": case.batch_id,
        "data_date": case.data_date,
        "product_code": case.product_code,
        "product_name": case.product_name,
        "warehouse_name": case.warehouse_name,
        "warehouse_scope": case.warehouse_scope,
        "reason_code": case.reason_code,
        "severity": case.severity,
        "status": case.status,
        "stock_qty": case.stock_qty,
        "locked_qty": case.locked_qty,
        "evidence_version": case.evidence_version,
        "root_cause": case.root_cause,
        "confidence": case.confidence,
        "recommended_action": case.recommended_action,
        "expected_result": case.expected_result,
        "resolution_note": case.resolution_note,
        "detected_at": case.detected_at,
        "diagnosed_at": case.diagnosed_at,
        "resolved_at": case.resolved_at,
        "created_at": case.created_at,
        "updated_at": case.updated_at,
    }


def serialize_remediation_action(action: InventoryRemediationAction) -> dict[str, Any]:
    return {
        "id": action.id,
        "action_no": action.action_no,
        "case_id": action.case_id,
        "requested_by_key_id": action.requested_by_key_id,
        "action_type": action.action_type,
        "status": action.status,
        "allowed": action.allowed,
        "blockers": action.blockers_json or [],
        "parameters": action.parameters_json or {},
        "impact": action.impact_json or {},
        "evidence_version": action.evidence_version,
        "idempotency_key": action.idempotency_key,
        "result": action.result_json,
        "verification": action.verification_json,
        "compensation": action.compensation_json,
        "upstream_reference": action.upstream_reference,
        "error_message": action.error_message,
        "validation_expires_at": action.validation_expires_at,
        "started_at": action.started_at,
        "completed_at": action.completed_at,
        "created_at": action.created_at,
        "updated_at": action.updated_at,
    }


def _warehouse_missing(value: str | None) -> bool:
    return (value or "").strip().casefold() in MISSING_WAREHOUSE_VALUES


def _decimal_parameter(parameters: dict[str, Any], key: str) -> Decimal | None:
    value = parameters.get(key)
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def remediation_blockers(
    db: Session,
    case: InventoryAnomalyCase,
    action_type: str,
    parameters: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if action_type not in REMEDIATION_ACTION_TYPES:
        blockers.append("unsupported_action")
        return blockers
    if case.status == "resolved":
        blockers.append("case_already_resolved")
    if case.status == "executing":
        blockers.append("case_execution_in_progress")
    if case.confidence is None or Decimal(case.confidence) < Decimal("0.95"):
        blockers.append("confidence_below_0_95")
    if _warehouse_missing(case.warehouse_name):
        blockers.append("warehouse_missing")
    snapshot = db.get(InventorySnapshot, case.snapshot_id) if case.snapshot_id else None
    if snapshot is None:
        blockers.append("snapshot_missing")
    elif not (snapshot.unit_relation or "").strip():
        blockers.append("unit_relation_missing")
    latest = latest_committed_inventory_batch(db)
    if latest is None or latest.id != case.batch_id:
        blockers.append("stale_inventory_batch")
    if latest is not None:
        newer_pending = db.scalar(
            select(func.count(ImportBatch.id)).where(
                ImportBatch.file_type == "inventory_snapshot",
                ImportBatch.uploaded_at > latest.uploaded_at,
                ImportBatch.status.notin_(["committed", "failed"]),
            )
        ) or 0
        if newer_pending:
            blockers.append("inventory_import_in_progress")
    concurrent = db.scalar(
        select(func.count(InventoryRemediationAction.id)).where(
            InventoryRemediationAction.case_id == case.id,
            InventoryRemediationAction.status == "executing",
        )
    ) or 0
    if concurrent:
        blockers.append("action_in_progress")
    if action_type == "rerun_inventory_check":
        check = db.scalar(
            select(InventoryCheckBatch).order_by(InventoryCheckBatch.created_at.desc(), InventoryCheckBatch.id.desc()).limit(1)
        )
        if check is None:
            blockers.append("inventory_check_missing")
        elif not Path(check.raw_file_path).is_file():
            blockers.append("inventory_check_source_missing")
        elif check.uploaded_by is None:
            blockers.append("inventory_check_operator_missing")
    if action_type in UPSTREAM_ACTION_TYPES:
        if not settings.inventory_agent_upstream_actions_enabled:
            blockers.append("upstream_connector_disabled")
        adjustment_qty = _decimal_parameter(parameters, "adjustment_qty")
        if adjustment_qty is not None and abs(adjustment_qty) > Decimal(str(settings.inventory_agent_max_adjustment_qty)):
            blockers.append("adjustment_exceeds_policy_limit")
    return list(dict.fromkeys(blockers))


def remediation_impact(case: InventoryAnomalyCase, action_type: str, parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_no": case.case_no,
        "product_code": case.product_code,
        "warehouse_name": case.warehouse_name,
        "data_date": case.data_date.isoformat() if case.data_date else None,
        "current_stock_qty": str(case.stock_qty) if case.stock_qty is not None else None,
        "action_type": action_type,
        "parameters": parameters,
        "source_of_truth": "upstream_erp",
        "modifies_inventory_snapshot": False,
    }


def ensure_blocked_work_item(db: Session, case: InventoryAnomalyCase, blockers: list[str]) -> WorkItem:
    existing = db.scalar(
        select(WorkItem).where(
            WorkItem.source_type == "inventory_anomaly_agent",
            WorkItem.source_id == case.case_no,
            WorkItem.status.in_(["open", "processing"]),
        )
    )
    if existing is not None:
        existing.detail = f"智能体自动修复被策略阻止：{', '.join(blockers)}"
        return existing
    item = WorkItem(
        item_no=generated_code("WI"),
        source_type="inventory_anomaly_agent",
        source_id=case.case_no,
        resource_type="inventory_anomaly_case",
        resource_id=str(case.id),
        item_type="inventory_anomaly_review",
        title=f"库存异常待人工处理：{case.product_code or case.product_name or case.case_no}",
        detail=f"智能体自动修复被策略阻止：{', '.join(blockers)}",
        priority="high" if case.severity == "high" else "normal",
        status="open",
    )
    db.add(item)
    return item

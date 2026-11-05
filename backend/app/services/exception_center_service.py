from __future__ import annotations

import hashlib
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import String, and_, case as sql_case, cast, exists, false, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    ExceptionAction,
    ExceptionBackgroundJob,
    ExceptionCase,
    ExceptionDiagnosis,
    ExceptionDiagnosisJob,
    ExceptionEvent,
    ExceptionEvidence,
    ExceptionNotification,
    ExceptionPolicy,
    ApprovalEvent,
    ApprovalInstance,
    CrmFollowup,
    CrmProjectCustomerTask,
    CustomerMaster,
    DataCalendarRule,
    ImportBatch,
    ImportError,
    InventoryAnomalyCase,
    InventoryCheckBatch,
    InventoryCheckResult,
    InventoryFlowLedger,
    InventorySnapshot,
    PurchaseDetail,
    SalesDetail,
    User,
)
from app.services.data_quality_risk_service import build_data_quality_risk_alerts
from app.services.inventory_agent_service import latest_committed_inventory_batch, sync_inventory_anomaly_cases
from app.services.access_control_service import get_data_scope_rule
from app.services.approval_access_service import visible_approval_resource_ids_stmt
from app.services.crm_access_service import crm_followup_scope_filter, crm_task_scope_filter
from app.services.permission_service import get_final_permission_codes, has_permission
from app.core.config import settings


CASE_STATUSES = {"open", "action_required", "processing", "blocked", "resolved", "ignored"}
CASE_DOMAINS = {"inventory", "receivable", "master_data", "import", "crm", "approval"}
OCCURRENCE_TYPES = {"baseline", "new", "reopened"}
ACTION_SOURCE_PERMISSIONS = {
    "rebuild_inventory_flow": "inventory_check.upload",
    "rerun_inventory_check": "inventory_check.upload",
    "rebuild_receivable_checks": "receivable.check",
    "rebuild_master_link_issues": "import.commit",
    "revalidate_import_batch": "import.commit",
}
ACTION_DOMAINS = {
    "rebuild_inventory_flow": {"inventory"},
    "rerun_inventory_check": {"inventory"},
    "rebuild_receivable_checks": {"receivable"},
    "rebuild_master_link_issues": {"master_data"},
    "revalidate_import_batch": {"import"},
}
ACTION_TTL_MINUTES = 10
EXCEPTION_SYNC_ADVISORY_LOCK_KEY = 481927402
SEVERITY_RANK = {"warning": 1, "high": 2, "critical": 3}
INVENTORY_CHECK_SOURCE_TYPES = {"latest_inventory_check", "inventory_check_result", "inventory_flow_ledger"}
RERUN_INVENTORY_CHECK_SOURCE_TYPES = {"latest_inventory_check", "inventory_check_result"}
INVENTORY_SNAPSHOT_SOURCE_TYPES = {"inventory_anomaly_case", "inventory_snapshot_quality"}
SOURCE_BATCH_KINDS = {"import", "inventory_check", "legacy"}
TARGET_RESOURCE_DOMAINS = {
    "crm": {"crm_project_task", "crm_followup"},
    "approval": {"approval_instance"},
}
INVENTORY_CHECK_BATCH_SOURCE_TYPES = {"latest_inventory_check", "inventory_check_result"}
IMPORT_BATCH_SOURCE_TYPES = {
    "inventory_anomaly_case",
    "inventory_flow_ledger",
    "inventory_snapshot_quality",
    "latest_receivable_check",
    "import_batch",
    "data_calendar_rule",
    "master_link_issue",
}
ACTION_BATCH_KINDS = {
    "rebuild_inventory_flow": "import",
    "rerun_inventory_check": "inventory_check",
    "rebuild_receivable_checks": "import",
    "rebuild_master_link_issues": "import",
    "revalidate_import_batch": "import",
}
SUPPORTED_ACTION_TYPES = frozenset(ACTION_DOMAINS)
# The policy may narrow this set for a release. An absent setting preserves
# the historical behavior so existing environments remain backward compatible.
ACTION_POLICY_SETTING_KEY = "allowed_action_types"
QUANTITY_TOLERANCE = Decimal("0.0001")
MASTER_ACTIVITY_WINDOW_DAYS = 365
AGGREGATED_EVIDENCE_SAMPLE_LIMIT = 50
RULE_QUALITY_SCAN_JOB_SAMPLE_LIMIT = 10_000
ACTIVE_MASTER_STATUSES = {"", "active", "enabled", "normal"}
MISSING_WAREHOUSE_VALUES = {
    "",
    "-",
    "unknown",
    "none",
    "null",
    "n/a",
    "na",
    "\u672a\u8bc6\u522b\u4ed3\u5e93",
    "\u672a\u77e5\u4ed3\u5e93",
}
DEFAULT_RULE_VERSION = "2026-07-28.v1"
CALIBRATED_RULE_VERSIONS = {
    "inventory.negative_stock": "2026-07-28.v2",
    "inventory.locked_stock": "2026-07-28.v2",
    "inventory_flow.closing_mismatch": "2026-07-28.v2",
    "inventory_flow.warehouse_missing": "2026-07-28.v2",
    "inventory_check.quantity_mismatch": "2026-07-28.v2",
    "inventory_check.warehouse_missing": "2026-07-28.v2",
    "inventory_check.sync_lag": "2026-07-28.v2",
    "inventory_snapshot.warehouse_missing": "2026-07-28.v2",
    "master_completeness.customer": "2026-07-28.v2",
    "master_completeness.supplier": "2026-07-28.v2",
    "master_completeness.product": "2026-07-28.v2",
    "crm.task_close_state_mismatch": "2026-07-29.v1",
    "crm.followup_binding_mismatch": "2026-07-29.v1",
    "approval.terminal_integrity_mismatch": "2026-07-29.v1",
}
DOMAIN_ROOT_CAUSE_CODES = {
    "inventory": [
        "true_negative_stock",
        "missing_purchase",
        "duplicate_sale",
        "warehouse_mismatch",
        "warehouse_missing",
        "unit_conversion_error",
        "stale_snapshot",
        "import_error",
        "snapshot_mismatch",
        "missing_product_master",
        "insufficient_evidence",
    ],
    "receivable": [
        "amount_mismatch",
        "missing_counterparty",
        "duplicate_record",
        "stale_data",
        "import_error",
        "master_data_mismatch",
        "insufficient_evidence",
    ],
    "master_data": [
        "missing_customer_master",
        "missing_supplier_master",
        "missing_product_master",
        "role_mismatch",
        "incomplete_master_data",
        "insufficient_evidence",
    ],
    "import": [
        "import_error",
        "duplicate_import",
        "stale_data",
        "invalid_rows",
        "uncommitted_batch",
        "insufficient_evidence",
    ],
}
AI_DIAGNOSIS_DOMAINS = frozenset(DOMAIN_ROOT_CAUSE_CODES)
ROLLOUT_DOMAIN_MODES = frozenset({"off", "shadow", "visible"})
ROLLOUT_CONTROLLED_DOMAINS = frozenset({"crm", "approval"})
logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_exception_domain_modes(settings_json: Any) -> dict[str, str]:
    settings_json = settings_json if isinstance(settings_json, dict) else {}
    configured = settings_json.get("domain_modes") if isinstance(settings_json.get("domain_modes"), dict) else {}
    modes: dict[str, str] = {}
    for domain in ROLLOUT_CONTROLLED_DOMAINS:
        value = str(configured.get(domain) or "off").strip().lower()
        modes[domain] = value if value in ROLLOUT_DOMAIN_MODES else "off"
    return modes


def exception_domain_modes(db: Session) -> dict[str, str]:
    modes = {domain: "visible" for domain in CASE_DOMAINS - ROLLOUT_CONTROLLED_DOMAINS}
    policy = db.scalar(select(ExceptionPolicy).where(ExceptionPolicy.policy_key == "default"))
    modes.update(normalize_exception_domain_modes(policy.settings_json if policy else None))
    return modes


def exception_shadow_baseline_pending_domains(
    db: Session,
    domains: set[str] | list[str] | tuple[str, ...],
) -> set[str]:
    requested_domains = set(domains) & ROLLOUT_CONTROLLED_DOMAINS
    if not requested_domains:
        return set()
    policy = db.scalar(select(ExceptionPolicy).where(ExceptionPolicy.policy_key == "default"))
    settings_json = policy.settings_json if policy and isinstance(policy.settings_json, dict) else {}
    modes = normalize_exception_domain_modes(settings_json)
    rollout = settings_json.get("domain_rollout") if isinstance(settings_json.get("domain_rollout"), dict) else {}
    pending: set[str] = set()
    for domain in requested_domains:
        if modes.get(domain) != "shadow":
            continue
        state = rollout.get(domain) if isinstance(rollout.get(domain), dict) else {}
        if not state.get("baseline_completed_at"):
            pending.add(domain)
    return pending


def exception_case_sync_target(case: ExceptionCase) -> dict[str, Any]:
    if case.resource_type in TARGET_RESOURCE_DOMAINS.get(case.domain, set()) and case.resource_id:
        return {
            "target_resource_type": case.resource_type,
            "target_resource_id": case.resource_id,
        }
    return {"target_fingerprint": case.fingerprint}


def _hash_json(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _rule_version(rule_code: str) -> str:
    return CALIBRATED_RULE_VERSIONS.get(rule_code, DEFAULT_RULE_VERSION)


def _source_batch_kind_for_source(source_type: Any) -> str:
    normalized = str(source_type or "")
    if normalized in INVENTORY_CHECK_BATCH_SOURCE_TYPES:
        return "inventory_check"
    if normalized in IMPORT_BATCH_SOURCE_TYPES:
        return "import"
    return "legacy"


def _normalize_candidate_batch_kind(candidate: dict[str, Any]) -> None:
    if candidate.get("source_batch_id") is None:
        candidate["source_batch_kind"] = None
        return
    kind = candidate.get("source_batch_kind")
    if kind not in SOURCE_BATCH_KINDS:
        candidate["source_batch_kind"] = _source_batch_kind_for_source(candidate.get("source_type"))


def _bounded_evidence_sample(values: list[Any]) -> dict[str, Any]:
    total = len(values)
    return {
        "total": total,
        "sample": values[:AGGREGATED_EVIDENCE_SAMPLE_LIMIT],
        "truncated": total > AGGREGATED_EVIDENCE_SAMPLE_LIMIT,
        # Track changes outside the retained sample without expanding API/model payloads.
        "digest": _hash_json(values),
    }


def _within_quantity_tolerance(value: Any) -> bool:
    parsed = _decimal(value)
    return parsed is not None and abs(parsed) <= QUANTITY_TOLERANCE


def _normalized_warehouse(value: Any) -> str | None:
    normalized = str(value or "").strip()
    return None if normalized.casefold() in MISSING_WAREHOUSE_VALUES else normalized


def _case_no(fingerprint: str) -> str:
    return f"EXC-{utcnow():%Y%m%d}-{fingerprint[:12].upper()}"


def _domain_for_alert(alert: dict[str, Any]) -> str:
    source = str(alert.get("source") or "")
    rule_code = str(alert.get("rule_code") or "")
    if source == "latest_inventory_check" or rule_code.startswith("check.inventory_"):
        return "inventory"
    if source == "latest_receivable_check" or rule_code.startswith("check.receivable_"):
        return "receivable"
    return "master_data"


def _severity(value: str | None) -> str:
    return {"warning": "warning", "risk": "high", "danger": "critical"}.get(value or "", value or "warning")


def _action_path(domain: str, alert: dict[str, Any]) -> str:
    if domain == "inventory":
        metadata = alert.get("metadata") or {}
        batch_id = metadata.get("batch_id")
        return f"/inventory?tab=check&batch_id={batch_id}" if batch_id else "/inventory?tab=check"
    if domain == "receivable":
        metadata = alert.get("metadata") or {}
        query = {
            "tab": "check",
            "q": alert.get("code") or alert.get("name") or "",
            "result_type": metadata.get("result_type") or "",
        }
        return f"/account-balance?{urlencode(query)}"
    resource_type = alert.get("resource_type")
    master_kind = {
        "customer": "customers",
        "supplier": "suppliers",
        "product": "products",
    }.get(resource_type)
    if master_kind:
        query = {
            "kind": master_kind,
            "open": alert.get("code") or alert.get("name") or "",
        }
        return f"/master-data?{urlencode(query)}"
    return "/master-data?view=quality"


def _alert_candidate(alert: dict[str, Any]) -> dict[str, Any]:
    domain = _domain_for_alert(alert)
    metadata = alert.get("metadata") or {}
    identity = {
        "domain": domain,
        "rule_code": alert.get("rule_code"),
        "resource_type": alert.get("resource_type"),
        "resource_code": alert.get("code"),
        "resource_name": alert.get("name"),
        "source": alert.get("source"),
        # Batch IDs describe evidence freshness, not the business identity of
        # an anomaly. Keep warehouse in the identity so the same product can
        # still have independent cases in different locations.
        "warehouse_name": metadata.get("warehouse_name"),
    }
    evidence = {
        "kind": "deterministic_rule",
        "rule_code": alert.get("rule_code"),
        "rule_description": alert.get("rule_description"),
        "reason": alert.get("reason"),
        "expected_rule": alert.get("closure_hint"),
        "recommended_action": alert.get("action"),
        "resource": {
            "type": alert.get("resource_type"),
            "code": alert.get("code"),
            "name": alert.get("name"),
        },
        "data_window": {
            "first_seen_date": alert.get("first_seen_date"),
            "last_seen_date": alert.get("last_seen_date"),
        },
        "affected": {
            "rows": alert.get("affected_rows") or 0,
            "documents": alert.get("affected_documents") or 0,
            "amount": alert.get("affected_amount"),
            "quantity": alert.get("affected_quantity"),
        },
        "source": alert.get("source"),
        "metadata": metadata,
    }
    return {
        "fingerprint": _hash_json(identity),
        "domain": domain,
        "rule_code": str(alert.get("rule_code") or "unknown"),
        "title": str(alert.get("rule_name") or alert.get("reason") or "数据异常"),
        "severity": _severity(alert.get("level")),
        "resource_type": alert.get("resource_type"),
        "resource_id": str(metadata.get("result_id") or metadata.get("issue_ids", [None])[0] or "") or None,
        "resource_code": alert.get("code"),
        "resource_name": alert.get("name"),
        "source_type": str(alert.get("source") or "data_quality_rule"),
        "source_id": None,
        "source_batch_id": metadata.get("batch_id"),
        "data_date": alert.get("last_seen_date") or alert.get("first_seen_date"),
        "reason": str(alert.get("reason") or alert.get("rule_description") or "检测到数据异常"),
        "initial_guidance": alert.get("action"),
        "action_path": _action_path(domain, alert),
        "affected_rows": alert.get("affected_rows") or 0,
        "affected_amount": _decimal(alert.get("affected_amount")),
        "affected_quantity": _decimal(alert.get("affected_quantity")),
        "metadata": metadata,
        "evidence": evidence,
    }


def _inventory_candidates(db: Session) -> list[dict[str, Any]]:
    sync_inventory_anomaly_cases(db)
    cases = list(db.scalars(select(InventoryAnomalyCase).where(InventoryAnomalyCase.status != "resolved")).all())
    result: list[dict[str, Any]] = []
    for source in cases:
        measured_quantity = source.stock_qty if source.reason_code == "negative_stock" else source.locked_qty
        if _within_quantity_tolerance(measured_quantity):
            continue
        identity = {"domain": "inventory", "inventory_case": source.fingerprint}
        evidence = {
            "kind": "inventory_anomaly_case",
            "inventory_case_no": source.case_no,
            "snapshot_id": source.snapshot_id,
            "batch_id": source.batch_id,
            "data_date": source.data_date,
            "product": {"code": source.product_code, "name": source.product_name},
            "warehouse": {"name": source.warehouse_name, "scope": source.warehouse_scope},
            "observed": {"stock_qty": source.stock_qty, "locked_qty": source.locked_qty},
            "reason_code": source.reason_code,
        }
        result.append(
            {
                "fingerprint": _hash_json(identity),
                "domain": "inventory",
                "rule_code": f"inventory.{source.reason_code}",
                "title": "库存数量异常" if source.reason_code == "negative_stock" else "库存锁定异常",
                "severity": "critical" if source.reason_code == "negative_stock" else "high",
                "resource_type": "inventory_snapshot",
                "resource_id": str(source.snapshot_id) if source.snapshot_id else None,
                "resource_code": source.product_code,
                "resource_name": source.product_name,
                "source_type": "inventory_anomaly_case",
                "source_id": str(source.id),
                "source_batch_id": source.batch_id,
                "inventory_anomaly_case_id": source.id,
                "data_date": source.data_date,
                "reason": "库存结存为负数" if source.reason_code == "negative_stock" else "存在锁定库存数量",
                "initial_guidance": "核对仓库、单位换算和上游进销存单据；不得直接修改库存快照。",
                "action_path": f"/inventory?{urlencode({'attention_state': 'needs_attention', 'product_code': source.product_code or ''})}",
                "affected_rows": 1,
                "affected_quantity": source.stock_qty if source.reason_code == "negative_stock" else source.locked_qty,
                "metadata": {"inventory_case_no": source.case_no},
                "evidence": evidence,
            }
        )
    result.extend(_inventory_flow_candidates(db))
    result.extend(_inventory_check_candidates(db))
    result.extend(_inventory_snapshot_quality_candidates(db))
    return result


def _inventory_flow_candidates(db: Session) -> list[dict[str, Any]]:
    latest_date = db.scalar(select(func.max(InventoryFlowLedger.data_date)))
    if latest_date is None:
        return []
    rows = list(
        db.scalars(
            select(InventoryFlowLedger).where(
                InventoryFlowLedger.data_date == latest_date,
                InventoryFlowLedger.anomaly_type != "normal",
            ).order_by(InventoryFlowLedger.id)
        ).all()
    )
    result = []
    missing_warehouse_rows: list[InventoryFlowLedger] = []
    for row in rows:
        normalized_warehouse = _normalized_warehouse(row.warehouse_name)
        if row.anomaly_type == "closing_mismatch" and _within_quantity_tolerance(row.diff_qty):
            continue
        if normalized_warehouse is None:
            missing_warehouse_rows.append(row)
            continue
        identity = {
            "domain": "inventory",
            "rule_code": f"inventory_flow.{row.anomaly_type}",
            "product_code": row.product_code,
            "warehouse_name": normalized_warehouse,
        }
        evidence = {
            "kind": "inventory_flow",
            "flow_id": row.id,
            "data_date": row.data_date,
            "product": {"code": row.product_code, "name": row.product_name},
            "warehouse": {"name": row.warehouse_name, "scope": row.warehouse_scope},
            "calculation": {
                "opening_stock_qty": row.opening_stock_qty,
                "purchase_qty": row.purchase_qty,
                "sales_qty": row.sales_qty,
                "calculated_closing_qty": row.calculated_closing_qty,
                "snapshot_stock_qty": row.snapshot_stock_qty,
                "diff_qty": row.diff_qty,
            },
            "anomaly_type": row.anomaly_type,
            "anomaly_flags": row.anomaly_flags or [],
            "source_batch_ids": row.source_batch_ids or [],
        }
        source_batch_ids = row.source_batch_ids or []
        result.append(
            {
                "fingerprint": _hash_json(identity),
                "domain": "inventory",
                "rule_code": f"inventory_flow.{row.anomaly_type}",
                "title": {
                    "closing_mismatch": "库存流转结存不一致",
                    "warehouse_unmatched": "库存仓库无法匹配",
                    "sales_without_stock": "销售发生时无库存记录",
                    "sales_zero_stock": "零库存销售",
                    "sales_negative_stock": "负库存销售",
                    "summary_stock_only": "库存仅有汇总仓记录",
                }.get(row.anomaly_type, "库存流转异常"),
                "severity": "critical" if row.anomaly_type in {"sales_negative_stock", "warehouse_unmatched"} else "high",
                "resource_type": "inventory_flow",
                "resource_id": str(row.id),
                "resource_code": row.product_code,
                "resource_name": row.product_name,
                "source_type": "inventory_flow_ledger",
                "source_id": str(row.id),
                "source_batch_id": int(source_batch_ids[-1]) if source_batch_ids else None,
                "data_date": row.data_date,
                "reason": f"最新库存流转结果标记为 {row.anomaly_type}",
                "initial_guidance": "核对期初、采购、销售、仓库映射与权威库存快照后重建库存流转。",
                "action_path": f"/inventory?{urlencode({'tab': 'check', 'check_tab': 'flow', 'product_code': row.product_code, 'warehouse_name': row.warehouse_name, 'anomaly_type': row.anomaly_type})}",
                "affected_rows": 1,
                "affected_quantity": row.diff_qty,
                "metadata": {"anomaly_flags": row.anomaly_flags or []},
                "evidence": evidence,
            }
        )
    if missing_warehouse_rows:
        source_batch_ids = sorted(
            {
                int(batch_id)
                for row in missing_warehouse_rows
                for batch_id in (row.source_batch_ids or [])
            }
        )
        evidence_rows = [
            {
                "flow_id": row.id,
                "product_code": row.product_code,
                "product_name": row.product_name,
                "warehouse_name": row.warehouse_name,
                "anomaly_type": row.anomaly_type,
                "diff_qty": row.diff_qty,
            }
            for row in missing_warehouse_rows
        ]
        evidence = {
            "kind": "inventory_flow_warehouse_missing",
            "data_date": latest_date,
            "rows": _bounded_evidence_sample(evidence_rows),
            "source_batch_ids": _bounded_evidence_sample(source_batch_ids),
        }
        warehouse_values = sorted({str(row.warehouse_name or "") for row in missing_warehouse_rows})
        action_query = {
            "tab": "check",
            "check_tab": "flow",
            "date_from": latest_date.isoformat(),
            "date_to": latest_date.isoformat(),
        }
        if len(warehouse_values) == 1:
            action_query["warehouse_name"] = warehouse_values[0]
        result.append(
            {
                "fingerprint": _hash_json({"domain": "inventory", "rule_code": "inventory_flow.warehouse_missing"}),
                "domain": "inventory",
                "rule_code": "inventory_flow.warehouse_missing",
                "title": "库存流转缺少仓库",
                "severity": "warning",
                "resource_type": "inventory_flow",
                "resource_id": None,
                "resource_code": None,
                "resource_name": "最新库存流转",
                "source_type": "inventory_flow_ledger",
                "source_id": None,
                "source_batch_id": source_batch_ids[-1] if source_batch_ids else None,
                "data_date": latest_date,
                "reason": f"最新库存流转中有 {len(missing_warehouse_rows)} 条记录无法识别仓库。",
                "initial_guidance": "先补齐仓库映射，再重建库存流转并复检。",
                "action_path": f"/inventory?{urlencode(action_query)}",
                "affected_rows": len(missing_warehouse_rows),
                "metadata": {
                    "systemic": True,
                    "flow_ids": _bounded_evidence_sample([row.id for row in missing_warehouse_rows]),
                },
                "evidence": evidence,
            }
        )
    return result


def _inventory_check_candidates(db: Session) -> list[dict[str, Any]]:
    latest_batch = db.scalar(
        select(InventoryCheckBatch)
        .where(InventoryCheckBatch.status == "completed")
        .order_by(InventoryCheckBatch.data_date.desc().nullslast(), InventoryCheckBatch.id.desc())
        .limit(1)
    )
    if latest_batch is None:
        return []
    result_types = {"quantity_mismatch", "missing_in_system", "missing_in_upload", "invalid_row"}
    rows = list(
        db.scalars(
            select(InventoryCheckResult).where(
                InventoryCheckResult.batch_id == latest_batch.id,
                InventoryCheckResult.result_type.in_(result_types),
            ).order_by(InventoryCheckResult.id)
        ).all()
    )
    result = []
    sync_lag_rows: list[InventoryCheckResult] = []
    missing_warehouse_rows: list[InventoryCheckResult] = []
    for row in rows:
        normalized_warehouse = _normalized_warehouse(row.warehouse_name)
        if (
            row.result_type in {"quantity_mismatch", "missing_in_system", "missing_in_upload"}
            and latest_batch.data_date is not None
            and row.system_data_date is not None
            and latest_batch.data_date != row.system_data_date
        ):
            sync_lag_rows.append(row)
            continue
        if normalized_warehouse is None and row.result_type != "invalid_row":
            missing_warehouse_rows.append(row)
            continue
        if row.result_type == "quantity_mismatch" and _within_quantity_tolerance(row.diff_qty):
            continue
        identity = {
            "domain": "inventory",
            "rule_code": f"inventory_check.{row.result_type}",
            "product": row.product_code or row.product_name or f"result:{row.id}",
            "warehouse": normalized_warehouse,
        }
        evidence = {
            "kind": "inventory_check",
            "batch": {"id": latest_batch.id, "batch_no": latest_batch.batch_no, "data_date": latest_batch.data_date},
            "result_id": row.id,
            "result_type": row.result_type,
            "product": {"code": row.product_code, "name": row.product_name},
            "warehouse": {"name": row.warehouse_name, "scope": row.warehouse_scope},
            "platform_stock_qty": row.platform_stock_qty,
            "system_stock_qty": row.system_stock_qty,
            "diff_qty": row.diff_qty,
            "system_data_date": row.system_data_date,
            "source_row_numbers": row.source_row_numbers or [],
        }
        result.append(
            {
                "fingerprint": _hash_json(identity),
                "domain": "inventory",
                "rule_code": f"inventory_check.{row.result_type}",
                "title": {
                    "quantity_mismatch": "库存核验数量不一致",
                    "missing_in_system": "系统库存缺少商品",
                    "missing_in_upload": "上传库存缺少商品",
                    "invalid_row": "库存核验存在无效行",
                }[row.result_type],
                "severity": "high" if row.result_type in {"quantity_mismatch", "missing_in_system"} else "warning",
                "resource_type": "inventory_check_result",
                "resource_id": str(row.id),
                "resource_code": row.product_code,
                "resource_name": row.product_name,
                "source_type": "inventory_check_result",
                "source_id": str(row.id),
                "source_batch_id": latest_batch.id,
                "data_date": latest_batch.data_date,
                "reason": f"最新库存核验出现 {row.result_type}",
                "initial_guidance": "核对上传行、商品编码、仓库和系统库存基准后重跑核验。",
                "action_path": f"/inventory?{urlencode({'tab': 'check', 'batch_id': latest_batch.id, 'result_type': row.result_type, 'q': row.product_code or row.product_name or ''})}",
                "affected_rows": len(row.source_row_numbers or []) or 1,
                "affected_quantity": row.diff_qty,
                "metadata": {"inventory_check_batch_no": latest_batch.batch_no, "original_result_type": row.result_type},
                "evidence": evidence,
            }
        )
    if missing_warehouse_rows:
        evidence_rows = [
            {
                "result_id": row.id,
                "result_type": row.result_type,
                "product_code": row.product_code,
                "product_name": row.product_name,
                "warehouse_name": row.warehouse_name,
                "diff_qty": row.diff_qty,
                "source_row_numbers": _bounded_evidence_sample(row.source_row_numbers or []),
            }
            for row in missing_warehouse_rows
        ]
        evidence = {
            "kind": "inventory_check_warehouse_missing",
            "batch": {"id": latest_batch.id, "batch_no": latest_batch.batch_no, "data_date": latest_batch.data_date},
            "rows": _bounded_evidence_sample(evidence_rows),
        }
        result.append(
            {
                "fingerprint": _hash_json({"domain": "inventory", "rule_code": "inventory_check.warehouse_missing"}),
                "domain": "inventory",
                "rule_code": "inventory_check.warehouse_missing",
                "title": "库存核验缺少仓库",
                "severity": "warning",
                "resource_type": "inventory_check_batch",
                "resource_id": str(latest_batch.id),
                "resource_code": latest_batch.batch_no,
                "resource_name": latest_batch.file_name,
                "source_type": "inventory_check_result",
                "source_id": None,
                "source_batch_id": latest_batch.id,
                "data_date": latest_batch.data_date,
                "reason": f"本次库存核验中有 {len(missing_warehouse_rows)} 条记录无法识别仓库。",
                "initial_guidance": "先统一补齐仓库映射，再重跑库存核验。",
                "action_path": f"/inventory?{urlencode({'tab': 'check', 'batch_id': latest_batch.id})}",
                "affected_rows": sum(len(row.source_row_numbers or []) or 1 for row in missing_warehouse_rows),
                "metadata": {
                    "systemic": True,
                    "inventory_check_batch_no": latest_batch.batch_no,
                    "result_ids": _bounded_evidence_sample([row.id for row in missing_warehouse_rows]),
                },
                "evidence": evidence,
            }
        )
    if sync_lag_rows:
        system_dates = sorted({row.system_data_date.isoformat() for row in sync_lag_rows if row.system_data_date})
        identity = {"domain": "inventory", "rule_code": "inventory_check.sync_lag"}
        evidence = {
            "kind": "inventory_check_sync_lag",
            "batch": {"id": latest_batch.id, "batch_no": latest_batch.batch_no, "data_date": latest_batch.data_date},
            "system_data_dates": system_dates,
            "suppressed_result_ids": _bounded_evidence_sample([row.id for row in sync_lag_rows]),
        }
        result.append(
            {
                "fingerprint": _hash_json(identity),
                "domain": "inventory",
                "rule_code": "inventory_check.sync_lag",
                "title": "库存核验数据日期不同步",
                "severity": "warning",
                "resource_type": "inventory_check_batch",
                "resource_id": str(latest_batch.id),
                "resource_code": latest_batch.batch_no,
                "resource_name": latest_batch.file_name,
                "source_type": "inventory_check_result",
                "source_id": None,
                "source_batch_id": latest_batch.id,
                "data_date": latest_batch.data_date,
                "reason": "平台核验日期与系统库存日期不一致，已暂缓数量差异判定。",
                "initial_guidance": "先同步同一数据日期的库存快照，再重跑库存核验。",
                "action_path": f"/inventory?{urlencode({'tab': 'check', 'batch_id': latest_batch.id})}",
                "affected_rows": len(sync_lag_rows),
                "metadata": {"inventory_check_batch_no": latest_batch.batch_no, "system_data_dates": system_dates},
                "evidence": evidence,
            }
        )
    return result


def _inventory_snapshot_quality_candidates(db: Session) -> list[dict[str, Any]]:
    batch = latest_committed_inventory_batch(db)
    if batch is None:
        return []
    rows = list(
        db.scalars(
            select(InventorySnapshot)
            .where(InventorySnapshot.batch_id == batch.id)
            .order_by(InventorySnapshot.id)
        ).all()
    )
    result = []
    missing_warehouse_rows: list[InventorySnapshot] = []
    for row in rows:
        rules = []
        if _normalized_warehouse(row.warehouse_name) is None:
            missing_warehouse_rows.append(row)
        if not (row.unit_relation or "").strip():
            rules.append(("unit_relation_missing", "库存快照缺少单位换算", "单位换算关系未填写"))
        for reason_code, title, reason in rules:
            identity = {
                "domain": "inventory",
                "rule_code": f"inventory_snapshot.{reason_code}",
                "product": row.product_code or row.product_name or f"snapshot:{row.id}",
                "warehouse": row.warehouse_name,
            }
            evidence = {
                "kind": "inventory_snapshot_quality",
                "snapshot_id": row.id,
                "batch_id": batch.id,
                "data_date": row.data_date,
                "product": {"code": row.product_code, "name": row.product_name},
                "warehouse": {"name": row.warehouse_name, "scope": row.warehouse_scope},
                "unit_relation": row.unit_relation,
                "stock_qty": row.stock_qty,
                "reason_code": reason_code,
            }
            result.append(
                {
                    "fingerprint": _hash_json(identity),
                    "domain": "inventory",
                    "rule_code": f"inventory_snapshot.{reason_code}",
                    "title": title,
                    "severity": "high",
                    "resource_type": "inventory_snapshot",
                    "resource_id": str(row.id),
                    "resource_code": row.product_code,
                    "resource_name": row.product_name,
                    "source_type": "inventory_snapshot_quality",
                    "source_id": str(row.id),
                    "source_batch_id": batch.id,
                    "data_date": row.data_date,
                    "reason": reason,
                    "initial_guidance": "补齐上游仓库或单位关系后重新导入权威库存快照。",
                    "action_path": f"/inventory?{urlencode({'batch_id': batch.id, 'product_code': row.product_code or ''})}",
                    "affected_rows": 1,
                    "metadata": {"reason_code": reason_code},
                    "evidence": evidence,
                }
            )
    if missing_warehouse_rows:
        evidence_rows = [
            {
                "snapshot_id": row.id,
                "row_number": row.row_number,
                "product_code": row.product_code,
                "product_name": row.product_name,
                "warehouse_name": row.warehouse_name,
                "warehouse_scope": row.warehouse_scope,
                "stock_qty": row.stock_qty,
            }
            for row in missing_warehouse_rows
        ]
        evidence = {
            "kind": "inventory_snapshot_warehouse_missing",
            "batch": {
                "id": batch.id,
                "batch_no": batch.batch_no,
                "file_name": batch.file_name,
                "data_date": batch.data_date,
            },
            "rows": _bounded_evidence_sample(evidence_rows),
        }
        result.append(
            {
                "fingerprint": _hash_json({"domain": "inventory", "rule_code": "inventory_snapshot.warehouse_missing"}),
                "domain": "inventory",
                "rule_code": "inventory_snapshot.warehouse_missing",
                "title": "库存快照缺少仓库",
                "severity": "warning",
                "resource_type": "inventory_snapshot_batch",
                "resource_id": str(batch.id),
                "resource_code": batch.batch_no,
                "resource_name": batch.file_name,
                "source_type": "inventory_snapshot_quality",
                "source_id": None,
                "source_batch_id": batch.id,
                "data_date": batch.data_date,
                "reason": f"最新库存快照中有 {len(missing_warehouse_rows)} 条记录无法识别仓库。",
                "initial_guidance": "先在上游系统统一补齐仓库映射，再重新导入权威库存快照。",
                "action_path": f"/inventory?{urlencode({'batch_id': batch.id})}",
                "affected_rows": len(missing_warehouse_rows),
                "metadata": {
                    "systemic": True,
                    "reason_code": "warehouse_missing",
                    "snapshot_ids": _bounded_evidence_sample([row.id for row in missing_warehouse_rows]),
                },
                "evidence": evidence,
            }
        )
    return result


def _import_candidates(db: Session) -> list[dict[str, Any]]:
    now = utcnow()
    stale_before = now - timedelta(hours=24)
    batches = list(
        db.scalars(
            select(ImportBatch).where(
                or_(
                    ImportBatch.status.in_(("failed", "error")),
                    ImportBatch.error_rows > 0,
                    (ImportBatch.status.in_(("uploaded", "validated"))) & (ImportBatch.uploaded_at < stale_before),
                )
            )
        ).all()
    )
    result: list[dict[str, Any]] = []
    for batch in batches:
        errors = list(
            db.scalars(select(ImportError).where(ImportError.batch_id == batch.id).order_by(ImportError.row_number).limit(50)).all()
        )
        if batch.status in {"failed", "error"}:
            rule_code, title, severity = "import.batch_failed", "导入批次失败", "critical"
        elif batch.error_rows > 0:
            rule_code, title, severity = "import.rows_invalid", "导入数据存在错误行", "high"
        else:
            rule_code, title, severity = "import.not_committed", "导入批次长期未提交", "warning"
        identity = {"domain": "import", "rule_code": rule_code, "batch_id": batch.id}
        evidence = {
            "kind": "import_batch",
            "batch": {
                "id": batch.id,
                "batch_no": batch.batch_no,
                "file_name": batch.file_name,
                "file_type": batch.file_type,
                "status": batch.status,
                "data_date": batch.data_date,
                "uploaded_at": batch.uploaded_at,
                "total_rows": batch.total_rows,
                "success_rows": batch.success_rows,
                "error_rows": batch.error_rows,
            },
            "errors": [
                {"id": row.id, "row_number": row.row_number, "error_type": row.error_type, "error_message": row.error_message}
                for row in errors
            ],
            "errors_truncated": len(errors) < (batch.error_rows or 0),
        }
        result.append(
            {
                "fingerprint": _hash_json(identity),
                "domain": "import",
                "rule_code": rule_code,
                "title": title,
                "severity": severity,
                "resource_type": "import_batch",
                "resource_id": str(batch.id),
                "resource_code": batch.batch_no,
                "resource_name": batch.file_name,
                "source_type": "import_batch",
                "source_id": str(batch.id),
                "source_batch_id": batch.id,
                "data_date": batch.data_date,
                "reason": errors[0].error_message if errors else title,
                "initial_guidance": "查看错误行并修正源文件；未提交批次可重新执行校验。",
                "action_path": f"/imports?batch={batch.id}&tab=history",
                "affected_rows": batch.error_rows or 0,
                "metadata": {"file_type": batch.file_type, "batch_status": batch.status},
                "evidence": evidence,
            }
        )
    result.extend(_duplicate_import_candidates(db))
    result.extend(_stale_data_candidates(db))
    return result


def _duplicate_import_candidates(db: Session) -> list[dict[str, Any]]:
    batches = list(
        db.scalars(
            select(ImportBatch)
            .where(ImportBatch.content_sha256.is_not(None))
            .order_by(ImportBatch.id)
        ).all()
    )
    latest_committed_by_content: dict[tuple[str, str], ImportBatch] = {}
    result: list[dict[str, Any]] = []
    for batch in batches:
        content_sha256 = str(batch.content_sha256 or "")
        if len(content_sha256) != 64 or any(character not in "0123456789abcdef" for character in content_sha256.casefold()):
            continue
        key = (batch.file_type, content_sha256)
        original = latest_committed_by_content.get(key)
        if original is not None:
            identity = {"domain": "import", "rule_code": "import.duplicate_content", "batch_id": batch.id}
            evidence = {
                "kind": "duplicate_import",
                "content_sha256": content_sha256,
                "file_type": batch.file_type,
                "original_batch": {
                    "id": original.id,
                    "batch_no": original.batch_no,
                    "file_name": original.file_name,
                    "status": original.status,
                    "data_date": original.data_date,
                    "uploaded_at": original.uploaded_at,
                },
                "duplicate_batch": {
                    "id": batch.id,
                    "batch_no": batch.batch_no,
                    "file_name": batch.file_name,
                    "status": batch.status,
                    "data_date": batch.data_date,
                    "uploaded_at": batch.uploaded_at,
                },
            }
            result.append(
                {
                    "fingerprint": _hash_json(identity),
                    "domain": "import",
                    "rule_code": "import.duplicate_content",
                    "title": "导入文件内容重复",
                    "severity": "warning",
                    "resource_type": "import_batch",
                    "resource_id": str(batch.id),
                    "resource_code": batch.batch_no,
                    "resource_name": batch.file_name,
                    "source_type": "import_batch",
                    "source_id": str(batch.id),
                    "source_batch_id": batch.id,
                    "data_date": batch.data_date,
                    "reason": f"文件内容与已提交批次 {original.batch_no} 完全一致",
                    "initial_guidance": "核对重复批次；若本次上传无必要，请勿继续提交。",
                    "action_path": f"/imports?batch={batch.id}&tab=history",
                    "affected_rows": batch.total_rows or 0,
                    "metadata": {"original_batch_id": original.id, "content_sha256": content_sha256},
                    "evidence": evidence,
                }
            )
        if batch.status == "committed":
            latest_committed_by_content[key] = batch
    return result


def _stale_data_candidates(db: Session) -> list[dict[str, Any]]:
    expected_date = utcnow().astimezone(ZoneInfo(settings.exception_schedule_timezone)).date() - timedelta(days=1)
    rules = list(
        db.scalars(
            select(DataCalendarRule).where(
                DataCalendarRule.is_enabled.is_(True),
                DataCalendarRule.is_required.is_(True),
                DataCalendarRule.frequency == "daily",
            )
        ).all()
    )
    result = []
    for rule in rules:
        latest = db.scalar(
            select(ImportBatch)
            .where(ImportBatch.file_type == rule.file_type, ImportBatch.status == "committed")
            .order_by(ImportBatch.data_date.desc().nullslast(), ImportBatch.uploaded_at.desc(), ImportBatch.id.desc())
            .limit(1)
        )
        latest_date = latest.data_date if latest else None
        if latest_date is not None and latest_date >= expected_date:
            continue
        overdue_days = (expected_date - latest_date).days if latest_date else None
        identity = {"domain": "import", "rule_code": "import.data_stale", "calendar_rule": rule.rule_code, "file_type": rule.file_type}
        evidence = {
            "kind": "data_freshness",
            "calendar_rule": {
                "rule_code": rule.rule_code,
                "file_type": rule.file_type,
                "label": rule.label,
                "frequency": rule.frequency,
                "deadline_hour": rule.deadline_hour,
                "owner_role": rule.owner_role,
            },
            "latest_committed_batch": {
                "id": latest.id if latest else None,
                "batch_no": latest.batch_no if latest else None,
                "data_date": latest_date,
                "uploaded_at": latest.uploaded_at if latest else None,
            },
            "expected_data_date": expected_date,
            "overdue_days": overdue_days,
        }
        result.append(
            {
                "fingerprint": _hash_json(identity),
                "domain": "import",
                "rule_code": "import.data_stale",
                "title": f"{rule.label}数据长期缺失",
                "severity": "high" if latest_date is None or (overdue_days or 0) >= 3 else "warning",
                "resource_type": "data_calendar_rule",
                "resource_id": str(rule.id),
                "resource_code": rule.file_type,
                "resource_name": rule.label,
                "source_type": "data_calendar_rule",
                "source_id": str(rule.id),
                "source_batch_id": latest.id if latest else None,
                "data_date": latest_date,
                "reason": f"期望数据日期为 {expected_date.isoformat()}，最新已提交日期为 {latest_date.isoformat() if latest_date else '无'}。",
                "initial_guidance": f"核对并导入最新的{rule.label}数据。",
                "action_path": f"/imports?{urlencode({'file_type': rule.file_type})}",
                "affected_rows": 1,
                "metadata": {"calendar_rule_code": rule.rule_code, "expected_data_date": expected_date.isoformat(), "overdue_days": overdue_days},
                "evidence": evidence,
            }
        )
    return result


def _crm_task_candidates(db: Session, target_id: int | None = None) -> list[dict[str, Any]]:
    stmt = select(CrmProjectCustomerTask).where(
        or_(
            and_(CrmProjectCustomerTask.status == "closed", CrmProjectCustomerTask.is_closed.is_(False)),
            and_(CrmProjectCustomerTask.status != "closed", CrmProjectCustomerTask.is_closed.is_(True)),
        )
    )
    if target_id is not None:
        stmt = stmt.where(CrmProjectCustomerTask.id == target_id)
    tasks = list(db.scalars(stmt.order_by(CrmProjectCustomerTask.id)).all())
    result: list[dict[str, Any]] = []
    for task in tasks:
        identity = {"domain": "crm", "rule_code": "crm.task_close_state_mismatch", "task_id": task.id}
        evidence = {
            "kind": "crm_task_close_state",
            "task_id": task.id,
            "task_code": task.task_code,
            "project_id": task.project_id,
            "customer_code": task.customer_code,
            "status": task.status,
            "is_closed": task.is_closed,
            "updated_at": task.updated_at,
        }
        result.append(
            {
                "fingerprint": _hash_json(identity),
                "domain": "crm",
                "rule_code": "crm.task_close_state_mismatch",
                "title": "CRM 任务关闭状态不一致",
                "severity": "high",
                "resource_type": "crm_project_task",
                "resource_id": str(task.id),
                "resource_code": task.task_code,
                "resource_name": task.customer_code,
                "source_type": "crm_project_task",
                "source_id": str(task.id),
                "source_batch_id": None,
                "data_date": task.updated_at.date() if task.updated_at else None,
                "reason": f"任务状态为 {task.status}，但关闭标记为 {'是' if task.is_closed else '否'}。",
                "initial_guidance": "核对任务关闭动作及状态同步逻辑，修正后重新执行确定性复检。",
                "action_path": f"/crm/tasks?{urlencode({'task_id': task.id})}",
                "affected_rows": 1,
                "metadata": {},
                "evidence": evidence,
            }
        )
    return result


def _crm_followup_candidates(db: Session, target_id: int | None = None) -> list[dict[str, Any]]:
    stmt = (
        select(
            CrmFollowup,
            CrmProjectCustomerTask.id.label("task_record_id"),
            CrmProjectCustomerTask.project_id.label("task_project_id"),
            CrmProjectCustomerTask.customer_code.label("task_customer_code"),
        )
        .outerjoin(CrmProjectCustomerTask, CrmProjectCustomerTask.id == CrmFollowup.task_id)
        .where(
            or_(
                CrmProjectCustomerTask.id.is_(None),
                CrmFollowup.project_id != CrmProjectCustomerTask.project_id,
                CrmFollowup.customer_code != CrmProjectCustomerTask.customer_code,
            )
        )
    )
    if target_id is not None:
        stmt = stmt.where(CrmFollowup.id == target_id)
    rows = list(db.execute(stmt.order_by(CrmFollowup.id)).all())
    result: list[dict[str, Any]] = []
    for followup, task_record_id, task_project_id, task_customer_code in rows:
        identity = {"domain": "crm", "rule_code": "crm.followup_binding_mismatch", "followup_id": followup.id}
        evidence = {
            "kind": "crm_followup_binding",
            "followup_id": followup.id,
            "followup_task_id": followup.task_id,
            "followup_project_id": followup.project_id,
            "followup_customer_code": followup.customer_code,
            "task_id": task_record_id,
            "task_project_id": task_project_id,
            "task_customer_code": task_customer_code,
        }
        result.append(
            {
                "fingerprint": _hash_json(identity),
                "domain": "crm",
                "rule_code": "crm.followup_binding_mismatch",
                "title": "CRM 跟进记录绑定关系不一致",
                "severity": "high",
                "resource_type": "crm_followup",
                "resource_id": str(followup.id),
                "resource_code": followup.followup_no,
                "resource_name": followup.customer_code,
                "source_type": "crm_followup",
                "source_id": str(followup.id),
                "source_batch_id": None,
                "data_date": followup.updated_at.date() if followup.updated_at else followup.followup_date,
                "reason": "跟进记录绑定的任务、项目或客户关系不一致。",
                "initial_guidance": "核对跟进记录所属任务，并通过正式业务流程修正项目与客户绑定。",
                "action_path": f"/crm/followups?{urlencode({'followup_id': followup.id})}",
                "affected_rows": 1,
                "metadata": {},
                "evidence": evidence,
            }
        )
    return result


def _approval_candidates(db: Session, target_id: int | None = None) -> list[dict[str, Any]]:
    latest_event_id = (
        select(ApprovalEvent.id)
        .where(ApprovalEvent.approval_id == ApprovalInstance.id, ApprovalEvent.to_status.is_not(None))
        .order_by(ApprovalEvent.created_at.desc(), ApprovalEvent.id.desc())
        .limit(1)
        .correlate(ApprovalInstance)
        .scalar_subquery()
    )
    latest_event_status = (
        select(ApprovalEvent.to_status)
        .where(ApprovalEvent.approval_id == ApprovalInstance.id, ApprovalEvent.to_status.is_not(None))
        .order_by(ApprovalEvent.created_at.desc(), ApprovalEvent.id.desc())
        .limit(1)
        .correlate(ApprovalInstance)
        .scalar_subquery()
    )
    latest_event_at = (
        select(ApprovalEvent.created_at)
        .where(ApprovalEvent.approval_id == ApprovalInstance.id, ApprovalEvent.to_status.is_not(None))
        .order_by(ApprovalEvent.created_at.desc(), ApprovalEvent.id.desc())
        .limit(1)
        .correlate(ApprovalInstance)
        .scalar_subquery()
    )
    stmt = select(
        ApprovalInstance,
        latest_event_id.label("latest_event_id"),
        latest_event_status.label("latest_event_status"),
        latest_event_at.label("latest_event_at"),
    ).where(
        ApprovalInstance.status.in_(("completed", "approved", "rejected", "cancelled")),
        or_(
            ApprovalInstance.reviewed_at.is_(None),
            ApprovalInstance.closed_at.is_(None),
            latest_event_id.is_(None),
            latest_event_status != ApprovalInstance.status,
        ),
    )
    if target_id is not None:
        stmt = stmt.where(ApprovalInstance.id == target_id)
    rows = list(db.execute(stmt.order_by(ApprovalInstance.id)).all())
    result: list[dict[str, Any]] = []
    for approval, event_id, event_status, event_at in rows:
        identity = {
            "domain": "approval",
            "rule_code": "approval.terminal_integrity_mismatch",
            "approval_id": approval.id,
        }
        evidence = {
            "kind": "approval_terminal_integrity",
            "approval_id": approval.id,
            "status": approval.status,
            "reviewed_at": approval.reviewed_at,
            "closed_at": approval.closed_at,
            "latest_state_event_id": event_id,
            "latest_state_event_status": event_status,
            "latest_state_event_at": event_at,
        }
        result.append(
            {
                "fingerprint": _hash_json(identity),
                "domain": "approval",
                "rule_code": "approval.terminal_integrity_mismatch",
                "title": "审批终态完整性不一致",
                "severity": "high",
                "resource_type": "approval_instance",
                "resource_id": str(approval.id),
                "resource_code": approval.approval_no,
                "resource_name": approval.approval_type,
                "source_type": "approval_instance",
                "source_id": str(approval.id),
                "source_batch_id": None,
                "data_date": approval.updated_at.date() if approval.updated_at else None,
                "reason": "审批已进入终态，但终态时间或最新状态事件不完整。",
                "initial_guidance": "核对审批终态写入与状态事件，修正后重新执行确定性复检。",
                "action_path": f"/crm/work?{urlencode({'view': 'approvals', 'approval_id': approval.id})}",
                "affected_rows": 1,
                "metadata": {},
                "evidence": evidence,
            }
        )
    return result


def _recent_business_codes(db: Session) -> dict[str, set[str] | None]:
    def codes_in_window(model: Any, code_column: Any) -> set[str] | None:
        latest_date = db.scalar(
            select(func.max(model.data_date))
            .join(ImportBatch, ImportBatch.id == model.batch_id)
            .where(ImportBatch.status == "committed")
        )
        if latest_date is None:
            return None
        cutoff = latest_date - timedelta(days=MASTER_ACTIVITY_WINDOW_DAYS)
        return {
            str(code).strip()
            for code in db.scalars(
                select(code_column)
                .join(ImportBatch, ImportBatch.id == model.batch_id)
                .where(
                    ImportBatch.status == "committed",
                    model.data_date >= cutoff,
                    code_column.is_not(None),
                )
                .distinct()
            ).all()
            if str(code).strip()
        }

    customer_codes = codes_in_window(SalesDetail, SalesDetail.customer_code)
    supplier_codes = codes_in_window(PurchaseDetail, PurchaseDetail.supplier_code)
    sales_product_codes = codes_in_window(SalesDetail, SalesDetail.product_code)
    purchase_product_codes = codes_in_window(PurchaseDetail, PurchaseDetail.product_code)
    inventory_batch = latest_committed_inventory_batch(db)
    inventory_product_codes = (
        {
            str(code).strip()
            for code in db.scalars(
                select(InventorySnapshot.product_code)
                .where(InventorySnapshot.batch_id == inventory_batch.id, InventorySnapshot.product_code.is_not(None))
                .distinct()
            ).all()
            if str(code).strip()
        }
        if inventory_batch is not None
        else None
    )
    product_sources = (sales_product_codes, purchase_product_codes, inventory_product_codes)
    product_codes = None if all(source is None for source in product_sources) else set().union(
        *(source or set() for source in product_sources)
    )
    return {
        "customer_master": customer_codes,
        "supplier_master": supplier_codes,
        "product_master": product_codes,
    }


def _all_risk_candidates(db: Session) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    recent_codes = _recent_business_codes(db)
    latest_completed_check_id = db.scalar(
        select(InventoryCheckBatch.id)
        .where(InventoryCheckBatch.status == "completed")
        .order_by(InventoryCheckBatch.data_date.desc().nullslast(), InventoryCheckBatch.id.desc())
        .limit(1)
    )
    offset = 0
    while True:
        page = build_data_quality_risk_alerts(db, limit=500, offset=offset)
        for item in page["items"]:
            source = str(item.get("source") or "")
            metadata = item.get("metadata") or {}
            if source in recent_codes:
                master_status = str(metadata.get("status") or "").strip().casefold()
                if master_status not in ACTIVE_MASTER_STATUSES:
                    continue
                active_codes = recent_codes[source]
                resource_code = str(item.get("code") or "").strip()
                if active_codes is not None and resource_code not in active_codes:
                    continue
            if source == "latest_inventory_check" and metadata.get("batch_id") != latest_completed_check_id:
                continue
            result.append(_alert_candidate(item))
        offset += len(page["items"])
        if offset >= page["total"] or not page["items"]:
            return result


def _upsert_candidate(
    db: Session,
    candidate: dict[str, Any],
    now: datetime,
    scan_trigger: str,
    *,
    allow_notification: bool = True,
) -> tuple[ExceptionCase, bool, bool]:
    _normalize_candidate_batch_kind(candidate)
    fingerprint = candidate.pop("fingerprint")
    case = db.scalar(select(ExceptionCase).where(ExceptionCase.fingerprint == fingerprint))
    created = case is None
    candidate["rule_version"] = candidate.get("rule_version") or _rule_version(str(candidate.get("rule_code") or "unknown"))
    evidence = _json_safe(candidate.pop("evidence"))
    evidence["rule_version"] = candidate["rule_version"]
    metadata = _json_safe(candidate.pop("metadata", {}))
    evidence_version = _hash_json(evidence)
    evidence_changed = False
    severity_upgraded = False
    if case is None:
        metadata["first_detected_trigger"] = scan_trigger
        occurrence_type = "baseline" if scan_trigger == "baseline" else "new"
        occurrence_cycle = 0 if occurrence_type == "baseline" else 1
        case = ExceptionCase(
            case_no=_case_no(fingerprint),
            fingerprint=fingerprint,
            evidence_version=evidence_version,
            status="open",
            occurrence_type=occurrence_type,
            occurrence_cycle=occurrence_cycle,
            detected_at=now,
            last_seen_at=now,
            metadata_json=metadata,
            **candidate,
        )
        db.add(case)
        db.flush()
        db.add(ExceptionEvent(case_id=case.id, event_type="detected", to_status="open", detail_json={"evidence_version": evidence_version}))
    else:
        previous_status = case.status
        previous_severity = case.severity
        previous_occurrence_type = case.occurrence_type
        previous_occurrence_cycle = case.occurrence_cycle
        previous_rule_version = case.rule_version
        legacy_baseline = previous_occurrence_type == "baseline" and previous_rule_version == "legacy-v1"
        evidence_changed = case.evidence_version != evidence_version
        for key, value in candidate.items():
            setattr(case, key, value)
        case.metadata_json = metadata
        case.last_seen_at = now
        case.evidence_version = evidence_version
        severity_upgraded = SEVERITY_RANK.get(candidate["severity"], 0) > SEVERITY_RANK.get(previous_severity, 0)
        ignored_deadline = case.ignored_until
        ignored_now = (
            now.replace(tzinfo=None)
            if ignored_deadline is not None and ignored_deadline.tzinfo is None
            else now
        )
        ignored_expired = (
            previous_status == "ignored"
            and ignored_deadline is not None
            and ignored_deadline <= ignored_now
        )
        baseline_first_refresh = (
            legacy_baseline
            and not severity_upgraded
            and previous_status != "resolved"
            and not ignored_expired
        )
        if baseline_first_refresh:
            # The occurrence migration adds rule_version to the evidence hash. Treat
            # that one-time recalibration as history maintenance, not a new alert.
            case.occurrence_type = "baseline"
            case.occurrence_cycle = 0
            metadata["baseline_refreshed_trigger"] = scan_trigger
            case.metadata_json = metadata
            db.add(
                ExceptionEvent(
                    case_id=case.id,
                    event_type="baseline_refreshed",
                    from_status=previous_status,
                    to_status=case.status,
                    created_at=now,
                    detail_json={
                        "evidence_changed": evidence_changed,
                        "evidence_version": evidence_version,
                        "previous_severity": previous_severity,
                        "severity": candidate["severity"],
                        "previous_rule_version": previous_rule_version,
                        "rule_version": case.rule_version,
                    },
                )
            )
        else:
            ignored_reactivated = case.status == "ignored" and (
                evidence_changed
                or severity_upgraded
                or ignored_expired
            )
            reactivated = case.status == "resolved" or ignored_reactivated
            if reactivated:
                case.occurrence_type = "reopened"
                case.occurrence_cycle = max(0, case.occurrence_cycle or 0) + 1
                metadata["reopened_trigger"] = scan_trigger
                case.metadata_json = metadata
            elif case.occurrence_type == "baseline" and (evidence_changed or severity_upgraded):
                # A changed historical baseline is actionable from this point forward,
                # but it was never closed, so it is a new occurrence rather than a reopen.
                case.occurrence_type = "new"
                case.occurrence_cycle = max(0, case.occurrence_cycle or 0) + 1
                metadata["baseline_change_trigger"] = scan_trigger
                case.metadata_json = metadata
            if reactivated or evidence_changed or severity_upgraded:
                case.status = "open"
                case.resolved_at = None
                case.verified_at = None
                case.resolution_note = None
                case.ignored_until = None
                case.due_at = None
                if reactivated:
                    event_type = "reopened"
                elif severity_upgraded:
                    event_type = "severity_upgraded"
                else:
                    event_type = "evidence_changed"
                db.add(
                    ExceptionEvent(
                        case_id=case.id,
                        event_type=event_type,
                        from_status=previous_status,
                        to_status="open",
                        created_at=now,
                        detail_json={
                            "evidence_changed": evidence_changed,
                            "evidence_version": evidence_version,
                            "previous_severity": previous_severity,
                            "severity": candidate["severity"],
                            "previous_occurrence_type": previous_occurrence_type,
                            "occurrence_type": case.occurrence_type,
                            "previous_occurrence_cycle": previous_occurrence_cycle,
                            "occurrence_cycle": case.occurrence_cycle,
                        },
                    )
                )
    evidence_row = db.scalar(
        select(ExceptionEvidence).where(
            ExceptionEvidence.case_id == case.id,
            ExceptionEvidence.evidence_version == evidence_version,
        )
    )
    if evidence_row is None:
        db.add(ExceptionEvidence(case_id=case.id, evidence_version=evidence_version, data_json=evidence))
    if created or evidence_changed or severity_upgraded or case.assignee_user_id is None or case.due_at is None:
        _assign_and_notify_case(db, case, now, allow_notification=allow_notification)
    return case, created, evidence_changed


def _assign_and_notify_case(
    db: Session,
    case: ExceptionCase,
    now: datetime,
    *,
    allow_notification: bool = True,
) -> None:
    owner_role = "business_middle_office" if case.domain in {"receivable", "crm", "approval"} else "data_middle_office"
    owners = list(
        db.scalars(
            select(User).where(
                User.is_active.is_(True),
                User.status == "active",
                User.role == owner_role,
            ).order_by(User.id)
        ).all()
    )
    if not owners:
        owners = list(
            db.scalars(
                select(User).where(User.is_active.is_(True), User.status == "active", User.role == "admin").order_by(User.id)
            ).all()
        )
    if case.assignee_user_id is None and owners:
        case.assignee_user_id = owners[0].id
    policy = db.scalar(select(ExceptionPolicy).where(ExceptionPolicy.policy_key == "default"))
    policy_settings = policy.settings_json if policy and isinstance(policy.settings_json, dict) else {}
    sla_hours = policy_settings.get("sla_hours", {}) if isinstance(policy_settings.get("sla_hours", {}), dict) else {}
    default_hours = {"critical": 4, "high": 24, "warning": 72}
    hours = int(sla_hours.get(case.severity, default_hours.get(case.severity, 72)))
    case.due_at = case.due_at or now + timedelta(hours=max(1, hours))
    if not allow_notification or case.occurrence_type == "baseline":
        return
    if case.severity not in {"high", "critical"}:
        return
    recipients = owners
    for user in recipients:
        existing = db.scalar(
            select(ExceptionNotification.id).where(
                ExceptionNotification.case_id == case.id,
                ExceptionNotification.user_id == user.id,
                ExceptionNotification.notification_type == "high_risk",
                ExceptionNotification.evidence_version == case.evidence_version,
                ExceptionNotification.occurrence_cycle == case.occurrence_cycle,
            )
        )
        if existing:
            continue
        db.add(
            ExceptionNotification(
                case_id=case.id,
                user_id=user.id,
                notification_type="high_risk",
                evidence_version=case.evidence_version,
                occurrence_cycle=case.occurrence_cycle,
                title=f"{case.severity.upper()} 异常：{case.title}",
                message=f"{case.reason} 案件编号：{case.case_no}",
            )
        )


def restore_default_assignment(db: Session, case: ExceptionCase, now: datetime | None = None) -> None:
    _assign_and_notify_case(db, case, now or utcnow(), allow_notification=False)


def _acquire_exception_sync_lock(db: Session) -> None:
    bind = db.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        db.execute(select(func.pg_advisory_xact_lock(EXCEPTION_SYNC_ADVISORY_LOCK_KEY)))


def acquire_exception_case_mutation_lock(db: Session) -> None:
    """Serialize multi-case scans and user mutations before any case row lock."""
    _acquire_exception_sync_lock(db)


def sync_exception_cases(
    db: Session,
    domains: set[str] | list[str] | tuple[str, ...] | None = None,
    source_batch_id: int | None = None,
    source_batch_kind: str | None = None,
    scan_trigger: str = "refresh",
    target_fingerprint: str | None = None,
    target_resource_type: str | None = None,
    target_resource_id: str | int | None = None,
) -> dict[str, Any]:
    _acquire_exception_sync_lock(db)
    now = utcnow()
    requested_domains = set(domains or CASE_DOMAINS)
    invalid_domains = requested_domains - CASE_DOMAINS
    if invalid_domains:
        raise ValueError(f"Unsupported exception domains: {', '.join(sorted(invalid_domains))}")
    domain_modes = exception_domain_modes(db)
    selected_domains = {domain for domain in requested_domains if domain_modes.get(domain) != "off"}
    baseline_pending_domains = (
        set()
        if scan_trigger == "baseline"
        else exception_shadow_baseline_pending_domains(db, selected_domains)
    )
    selected_domains -= baseline_pending_domains
    if source_batch_kind is not None and source_batch_kind not in SOURCE_BATCH_KINDS:
        raise ValueError(f"Unsupported source batch kind: {source_batch_kind}")
    if (target_resource_type is None) != (target_resource_id is None):
        raise ValueError("target_resource_type and target_resource_id must be provided together")
    normalized_target_id: int | None = None
    if target_resource_type is not None:
        if len(requested_domains) != 1:
            raise ValueError("Target exception scans require exactly one domain")
        target_domain = next(iter(requested_domains))
        supported_types = TARGET_RESOURCE_DOMAINS.get(target_domain, set())
        if target_resource_type not in supported_types:
            raise ValueError(f"Unsupported target resource for {target_domain}: {target_resource_type}")
        try:
            normalized_target_id = int(target_resource_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("target_resource_id must be a positive integer") from exc
        if normalized_target_id <= 0:
            raise ValueError("target_resource_id must be a positive integer")
    candidates: list[dict[str, Any]] = []
    if target_resource_type == "crm_project_task" and "crm" in selected_domains:
        candidates.extend(_crm_task_candidates(db, normalized_target_id))
    elif target_resource_type == "crm_followup" and "crm" in selected_domains:
        candidates.extend(_crm_followup_candidates(db, normalized_target_id))
    elif target_resource_type == "approval_instance" and "approval" in selected_domains:
        candidates.extend(_approval_candidates(db, normalized_target_id))
    elif target_resource_type is None:
        if "inventory" in selected_domains:
            candidates.extend(_inventory_candidates(db))
        if selected_domains & {"inventory", "receivable", "master_data"}:
            candidates.extend(item for item in _all_risk_candidates(db) if item["domain"] in selected_domains)
        if "import" in selected_domains:
            candidates.extend(_import_candidates(db))
        if "crm" in selected_domains:
            candidates.extend(_crm_task_candidates(db))
            candidates.extend(_crm_followup_candidates(db))
        if "approval" in selected_domains:
            candidates.extend(_approval_candidates(db))
    for candidate in candidates:
        _normalize_candidate_batch_kind(candidate)
    if source_batch_id is not None:
        candidates = [item for item in candidates if item.get("source_batch_id") == source_batch_id]
    if source_batch_kind is not None:
        candidates = [item for item in candidates if item.get("source_batch_kind") == source_batch_kind]
    if target_fingerprint is not None:
        candidates = [item for item in candidates if item.get("fingerprint") == target_fingerprint]
    # Inventory cases also surface through data-quality checks; the fingerprint keeps distinct rules explicit.
    seen: set[str] = set()
    created = 0
    updated = 0
    newly_detected = 0
    reopened = 0
    for raw in candidates:
        candidate = dict(raw)
        seen.add(candidate["fingerprint"])
        candidate_mode = domain_modes.get(str(candidate.get("domain")), "visible")
        case, was_created, changed = _upsert_candidate(
            db,
            candidate,
            now,
            scan_trigger,
            allow_notification=candidate_mode != "shadow",
        )
        created += int(was_created)
        updated += int(not was_created and changed)
        newly_detected += int(
            (was_created and case.occurrence_type == "new")
            or (not was_created and changed and case.occurrence_type == "new")
        )
        reopened += int(not was_created and changed and case.occurrence_type == "reopened")

    resolved = 0
    managed_sources = {
        "inventory_anomaly_case",
        "inventory_flow_ledger",
        "inventory_check_result",
        "inventory_snapshot_quality",
        "latest_inventory_check",
        "latest_receivable_check",
        "master_link_issue",
        "customer_master",
        "supplier_master",
        "product_master",
        "import_batch",
        "data_calendar_rule",
        "crm_project_task",
        "crm_followup",
        "approval_instance",
    }
    stmt = select(ExceptionCase).where(
        ExceptionCase.source_type.in_(managed_sources),
        ExceptionCase.domain.in_(selected_domains),
        or_(
            ExceptionCase.status.in_(("open", "action_required", "processing", "blocked")),
            and_(ExceptionCase.status == "ignored", ExceptionCase.ignored_until.is_not(None), ExceptionCase.ignored_until <= now),
        ),
    )
    if source_batch_id is not None:
        stmt = stmt.where(ExceptionCase.source_batch_id == source_batch_id)
    if source_batch_kind is not None:
        stmt = stmt.where(ExceptionCase.source_batch_kind == source_batch_kind)
    if target_fingerprint is not None:
        stmt = stmt.where(ExceptionCase.fingerprint == target_fingerprint)
    if target_resource_type is not None:
        stmt = stmt.where(
            ExceptionCase.resource_type == target_resource_type,
            ExceptionCase.resource_id == str(normalized_target_id),
        )
    open_cases = list(
        db.scalars(
            stmt
        ).all()
    )
    for case in open_cases:
        if case.fingerprint in seen:
            continue
        previous_status = case.status
        case.status = "resolved"
        case.resolved_at = now
        case.verified_at = now
        case.resolution_note = "最新确定性扫描未再发现该异常。"
        db.add(ExceptionEvent(case_id=case.id, event_type="auto_resolved", from_status=previous_status, to_status="resolved"))
        resolved += 1
    db.flush()
    return {
        "domains": sorted(selected_domains),
        "requested_domains": sorted(requested_domains),
        "domain_modes": {domain: domain_modes[domain] for domain in sorted(requested_domains)},
        "baseline_pending_domains": sorted(baseline_pending_domains),
        "source_batch_id": source_batch_id,
        "source_batch_kind": source_batch_kind,
        "target_fingerprint": target_fingerprint,
        "target_resource_type": target_resource_type,
        "target_resource_id": str(normalized_target_id) if normalized_target_id is not None else None,
        "scan_trigger": scan_trigger,
        "scanned": len(candidates),
        "created": created,
        "new": newly_detected,
        "reopened": reopened,
        "evidence_updated": updated,
        "resolved": resolved,
    }


def run_full_exception_scan(db: Session) -> dict[str, Any]:
    return sync_exception_cases(db, scan_trigger="full")


def run_incremental_exception_scan(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    raw_domains = payload.get("domains")
    domains = set(raw_domains) if raw_domains else None
    source_batch_id = payload.get("source_batch_id")
    source_batch_kind = payload.get("source_batch_kind")
    target_resource_type = payload.get("target_resource_type")
    target_resource_id = payload.get("target_resource_id")
    if (source_batch_kind is None) != (source_batch_id is None):
        raise ValueError("source_batch_kind and source_batch_id must be provided together")
    if source_batch_kind is not None and str(source_batch_kind) not in SOURCE_BATCH_KINDS:
        raise ValueError(f"Unsupported source batch kind: {source_batch_kind}")
    normalized_batch_id = int(source_batch_id) if source_batch_id is not None else None
    if normalized_batch_id is not None and normalized_batch_id <= 0:
        raise ValueError("source_batch_id must be a positive integer")
    if (target_resource_type is None) != (target_resource_id is None):
        raise ValueError("target_resource_type and target_resource_id must be provided together")
    return sync_exception_cases(
        db,
        domains=domains,
        source_batch_id=normalized_batch_id,
        source_batch_kind=str(source_batch_kind) if source_batch_kind is not None else None,
        scan_trigger="incremental",
        target_resource_type=str(target_resource_type) if target_resource_type is not None else None,
        target_resource_id=target_resource_id,
    )


def enqueue_incremental_exception_scan_safely(
    db: Session,
    *,
    domains: list[str],
    source_batch_kind: str | None = None,
    source_batch_id: int | None = None,
    target_resource_type: str | None = None,
    target_resource_id: str | int | None = None,
) -> bool:
    """Queue post-commit-quality work without making the source transaction depend on the queue."""
    if not settings.exception_center_enabled:
        return False
    try:
        domain_modes = exception_domain_modes(db)
        baseline_pending_domains = exception_shadow_baseline_pending_domains(db, set(domains))
        enabled_domains = sorted(
            domain
            for domain in set(domains)
            if domain_modes.get(domain) in {"shadow", "visible"}
            and domain not in baseline_pending_domains
        )
        if not enabled_domains:
            return False
        with db.begin_nested():
            from app.services.exception_task_service import enqueue_incremental_scan

            enqueue_incremental_scan(
                db,
                domains=enabled_domains,
                source_batch_kind=source_batch_kind,
                source_batch_id=source_batch_id,
                target_resource_type=target_resource_type,
                target_resource_id=target_resource_id,
            )
        return True
    except Exception:
        logger.exception(
            "Failed to enqueue exception incremental scan domains=%s source_batch_kind=%s source_batch_id=%s target_resource_type=%s target_resource_id=%s",
            sorted(domains),
            source_batch_kind,
            source_batch_id,
            target_resource_type,
            target_resource_id,
        )
        return False


def can_view_case(db: Session, user: User, case: ExceptionCase) -> bool:
    return db.scalar(
        scoped_exception_stmt(db, user).with_only_columns(ExceptionCase.id).where(ExceptionCase.id == case.id).limit(1)
    ) is not None


def source_permissions_for_case(case: ExceptionCase) -> tuple[str, ...]:
    if case.domain == "inventory":
        if case.source_type in INVENTORY_CHECK_SOURCE_TYPES:
            return ("inventory_check.view",)
        return ("inventory_snapshot.view",)
    if case.domain == "receivable":
        return ("receivable.view",)
    if case.domain == "import":
        return ("import.view",)
    if case.domain == "master_data":
        mapping = {
            "customer": "customer.view",
            "supplier": "supplier.view",
            "product": "product.view",
        }
        permission = mapping.get(case.resource_type or "")
        return (permission,) if permission else ("import.view",)
    if case.domain == "crm":
        if case.resource_type == "crm_project_task":
            return ("crm_task.view",)
        if case.resource_type == "crm_followup":
            return ("crm_followup.view",)
    if case.domain == "approval":
        return ("approval.view",)
    return ()


def _customer_scope_condition(db: Session, user: User):  # noqa: ANN201
    rule = get_data_scope_rule(db, user, "customer")
    if rule is None or rule.scope_mode == "all":
        return True
    if rule.scope_mode == "own":
        if not user.employee_code:
            return select(CustomerMaster.id).where(
                CustomerMaster.customer_code == ExceptionCase.resource_code,
                CustomerMaster.salesperson_employee_code.is_(None),
            ).exists()
        return select(CustomerMaster.id).where(
            CustomerMaster.customer_code == ExceptionCase.resource_code,
            CustomerMaster.salesperson_employee_code == user.employee_code,
        ).exists()
    if rule.scope_mode == "assigned":
        value = rule.scope_value
        values = value if isinstance(value, list) else value.get("values", []) if isinstance(value, dict) else []
        return ExceptionCase.resource_code.in_([str(item) for item in values]) if values else false()
    if rule.scope_mode == "custom" and isinstance(rule.scope_value, dict) and rule.scope_value.get("mode") == "none":
        return false()
    return false()


def _case_resource_scope_condition(db: Session, user: User, resource_type: str):  # noqa: ANN201
    rule = get_data_scope_rule(db, user, resource_type)
    if rule is None or rule.scope_mode == "all":
        return True
    if rule.scope_mode == "assigned":
        # apply_data_scope only supports assigned scopes on models with customer_code or employee_code.
        # Inventory snapshots, product/supplier masters, receivables and import batches expose neither.
        return false()
    if rule.scope_mode == "custom" and isinstance(rule.scope_value, dict) and rule.scope_value.get("mode") == "none":
        return false()
    return false()


def _crm_task_case_scope_condition(db: Session, user: User):  # noqa: ANN201
    visible_ids = crm_task_scope_filter(select(cast(CrmProjectCustomerTask.id, String)), db, user)
    return ExceptionCase.resource_id.in_(visible_ids)


def _crm_followup_case_scope_condition(db: Session, user: User):  # noqa: ANN201
    visible_ids = crm_followup_scope_filter(select(cast(CrmFollowup.id, String)), db, user)
    return ExceptionCase.resource_id.in_(visible_ids)


GLOBAL_SCAN_DOMAIN_ACCESS: dict[str, tuple[set[str], set[str]]] = {
    "inventory": (
        {"inventory_snapshot.view", "inventory_check.view"},
        {"inventory_snapshot"},
    ),
    "receivable": (
        {"receivable.view"},
        {"customer", "receivable"},
    ),
    "master_data": (
        {"customer.view", "supplier.view", "product.view", "import.view"},
        {"customer", "supplier", "product", "import_batch"},
    ),
    "import": (
        {"import.view"},
        {"import_batch"},
    ),
    "crm": (
        {"crm_task.view", "crm_followup.view"},
        {"crm_task", "crm_followup"},
    ),
    "approval": (
        {"approval.view"},
        {"approval"},
    ),
}


def can_run_global_exception_scan(
    db: Session,
    user: User,
    domains: set[str] | list[str] | tuple[str, ...] | None,
) -> bool:
    requested_domains = set(domains or CASE_DOMAINS)
    if not requested_domains or requested_domains - CASE_DOMAINS:
        return False
    domain_modes = exception_domain_modes(db)
    selected_domains = {domain for domain in requested_domains if domain_modes.get(domain) != "off"}
    if not selected_domains:
        return False
    permissions = set(get_final_permission_codes(db, user))
    required_permissions: set[str] = set()
    required_scopes: set[str] = set()
    for domain in selected_domains:
        domain_permissions, domain_scopes = GLOBAL_SCAN_DOMAIN_ACCESS[domain]
        required_permissions.update(domain_permissions)
        required_scopes.update(domain_scopes)
    if not required_permissions.issubset(permissions):
        return False
    return all(
        (rule := get_data_scope_rule(db, user, resource_type)) is None or rule.scope_mode == "all"
        for resource_type in required_scopes
    )


def scoped_exception_stmt(db: Session, user: User, occurrence_type: str | None = None):  # noqa: ANN201
    if occurrence_type is not None and occurrence_type not in OCCURRENCE_TYPES:
        raise ValueError(f"Unsupported occurrence type: {occurrence_type}")
    permissions = set(get_final_permission_codes(db, user))
    if "exception_center.view" not in permissions:
        return select(ExceptionCase).where(false())
    conditions = []
    domain_modes = exception_domain_modes(db)
    if permissions & {"inventory_snapshot.view", "inventory_check.view"}:
        inventory_conditions = []
        if "inventory_snapshot.view" in permissions:
            inventory_conditions.append(ExceptionCase.source_type.in_(INVENTORY_SNAPSHOT_SOURCE_TYPES))
        if "inventory_check.view" in permissions:
            inventory_conditions.append(
                ExceptionCase.source_type.in_(INVENTORY_CHECK_SOURCE_TYPES)
            )
        conditions.append(
            and_(
                ExceptionCase.domain == "inventory",
                or_(*inventory_conditions),
                _case_resource_scope_condition(db, user, "inventory_snapshot"),
            )
        )
    if "receivable.view" in permissions:
        conditions.append(
            and_(
                ExceptionCase.domain == "receivable",
                _customer_scope_condition(db, user),
                _case_resource_scope_condition(db, user, "receivable"),
            )
        )
    if "import.view" in permissions:
        import_scope = _case_resource_scope_condition(db, user, "import_batch")
        conditions.append(and_(ExceptionCase.domain == "import", import_scope))
        conditions.append(
            and_(
                ExceptionCase.domain == "master_data",
                ExceptionCase.resource_type.notin_(("customer", "supplier", "product")),
                import_scope,
            )
        )
    if "customer.view" in permissions:
        conditions.append(and_(ExceptionCase.domain == "master_data", ExceptionCase.resource_type == "customer", _customer_scope_condition(db, user)))
    if "supplier.view" in permissions:
        conditions.append(
            and_(
                ExceptionCase.domain == "master_data",
                ExceptionCase.resource_type == "supplier",
                _case_resource_scope_condition(db, user, "supplier"),
            )
        )
    if "product.view" in permissions:
        conditions.append(
            and_(
                ExceptionCase.domain == "master_data",
                ExceptionCase.resource_type == "product",
                _case_resource_scope_condition(db, user, "product"),
            )
        )
    crm_mode = domain_modes.get("crm")
    crm_access_enabled = crm_mode == "visible" or (
        crm_mode == "shadow" and "exception_center.policy_manage" in permissions
    )
    if crm_access_enabled:
        if "crm_task.view" in permissions:
            conditions.append(
                and_(
                    ExceptionCase.domain == "crm",
                    ExceptionCase.resource_type == "crm_project_task",
                    _crm_task_case_scope_condition(db, user),
                )
            )
        if "crm_followup.view" in permissions:
            conditions.append(
                and_(
                    ExceptionCase.domain == "crm",
                    ExceptionCase.resource_type == "crm_followup",
                    _crm_followup_case_scope_condition(db, user),
                )
            )
    approval_mode = domain_modes.get("approval")
    approval_access_enabled = approval_mode == "visible" or (
        approval_mode == "shadow" and "exception_center.policy_manage" in permissions
    )
    if approval_access_enabled:
        conditions.append(
            and_(
                ExceptionCase.domain == "approval",
                ExceptionCase.resource_id.in_(visible_approval_resource_ids_stmt(db, user)),
            )
        )
    stmt = select(ExceptionCase).where(or_(*conditions)) if conditions else select(ExceptionCase).where(false())
    if occurrence_type is not None:
        stmt = stmt.where(ExceptionCase.occurrence_type == occurrence_type)
    return stmt


def visible_case_ids(db: Session, user: User) -> list[int]:
    return list(db.scalars(scoped_exception_stmt(db, user).with_only_columns(ExceptionCase.id)).all())


_UNSET = object()


def serialize_case(
    db: Session,
    case: ExceptionCase,
    *,
    diagnosis_value: Any = _UNSET,
    assignee_name_value: Any = _UNSET,
    active_job_value: Any = _UNSET,
    current_user_id: int | None = None,
) -> dict[str, Any]:
    diagnosis = diagnosis_value
    if diagnosis_value is _UNSET:
        diagnosis_row = db.scalar(
            select(ExceptionDiagnosis)
            .where(ExceptionDiagnosis.case_id == case.id, ExceptionDiagnosis.evidence_version == case.evidence_version)
            .order_by(ExceptionDiagnosis.id.desc())
            .limit(1)
        )
        diagnosis = serialize_diagnoses(db, [diagnosis_row])[0] if diagnosis_row else None
    assignee_name = assignee_name_value
    if assignee_name_value is _UNSET:
        assignee = db.get(User, case.assignee_user_id) if case.assignee_user_id else None
        assignee_name = assignee.real_name if assignee else None
    active_job = active_job_value
    if active_job_value is _UNSET:
        active_job = db.scalar(
            select(ExceptionDiagnosisJob)
            .where(
                ExceptionDiagnosisJob.case_id == case.id,
                ExceptionDiagnosisJob.evidence_version == case.evidence_version,
                ExceptionDiagnosisJob.status.in_(("queued", "processing")),
            )
            .order_by(ExceptionDiagnosisJob.id.desc())
            .limit(1)
        )
    processing_kind = None
    if active_job is not None:
        processing_kind = "manual_diagnosis" if active_job.trigger_type == "manual" else "scheduled_diagnosis"
    elif case.status == "processing":
        processing_kind = "background_scan"
    now = utcnow()
    due_at = case.due_at
    if due_at is None:
        sla_status = "no_due_date"
    else:
        comparison_now = now if due_at.tzinfo else now.replace(tzinfo=None)
        if due_at < comparison_now:
            sla_status = "overdue"
        elif due_at <= comparison_now + timedelta(hours=24):
            sla_status = "due_soon"
        else:
            sla_status = "on_track"
    return {
        "id": case.id,
        "case_no": case.case_no,
        "domain": case.domain,
        "diagnosis_supported": case.domain in AI_DIAGNOSIS_DOMAINS,
        "rule_code": case.rule_code,
        "title": case.title,
        "severity": case.severity,
        "status": case.status,
        "occurrence_type": case.occurrence_type,
        "occurrence_cycle": case.occurrence_cycle,
        "rule_version": case.rule_version,
        "resource_type": case.resource_type,
        "resource_id": case.resource_id,
        "resource_code": case.resource_code,
        "resource_name": case.resource_name,
        "source_type": case.source_type,
        "source_id": case.source_id,
        "source_batch_kind": case.source_batch_kind,
        "source_batch_id": case.source_batch_id,
        "data_date": case.data_date,
        "evidence_version": case.evidence_version,
        "reason": case.reason,
        "initial_guidance": case.initial_guidance,
        "action_path": case.action_path,
        "affected_rows": case.affected_rows,
        "affected_amount": case.affected_amount,
        "affected_quantity": case.affected_quantity,
        "assignee_user_id": case.assignee_user_id,
        "assignee_name": assignee_name,
        "due_at": case.due_at,
        "detected_at": case.detected_at,
        "last_seen_at": case.last_seen_at,
        "resolved_at": case.resolved_at,
        "ignored_until": case.ignored_until,
        "resolution_note": case.resolution_note,
        "verified_at": case.verified_at,
        "sla_status": sla_status,
        "is_mine": bool(current_user_id is not None and case.assignee_user_id == current_user_id),
        "metadata": case.metadata_json or {},
        "diagnosis": diagnosis,
        "processing_kind": processing_kind,
    }


def serialize_cases(
    db: Session,
    cases: list[ExceptionCase],
    *,
    current_user_id: int | None = None,
) -> list[dict[str, Any]]:
    if not cases:
        return []
    case_ids = [case.id for case in cases]
    diagnoses = list(
        db.scalars(
            select(ExceptionDiagnosis)
            .where(ExceptionDiagnosis.case_id.in_(case_ids))
            .order_by(ExceptionDiagnosis.diagnosed_at, ExceptionDiagnosis.id)
        ).all()
    )
    serialized_diagnoses = serialize_diagnoses(db, diagnoses)
    diagnosis_map = {
        (row.case_id, row.evidence_version): payload
        for row, payload in zip(diagnoses, serialized_diagnoses, strict=True)
    }
    assignee_ids = {case.assignee_user_id for case in cases if case.assignee_user_id}
    users = list(db.scalars(select(User).where(User.id.in_(assignee_ids))).all()) if assignee_ids else []
    assignee_map = {user.id: user.real_name for user in users}
    active_jobs = list(
        db.scalars(
            select(ExceptionDiagnosisJob)
            .where(
                ExceptionDiagnosisJob.case_id.in_(case_ids),
                ExceptionDiagnosisJob.status.in_(("queued", "processing")),
            )
            .order_by(ExceptionDiagnosisJob.id)
        ).all()
    )
    active_job_map = {(job.case_id, job.evidence_version): job for job in active_jobs}
    return [
        serialize_case(
            db,
            case,
            diagnosis_value=diagnosis_map.get((case.id, case.evidence_version)),
            assignee_name_value=assignee_map.get(case.assignee_user_id),
            active_job_value=active_job_map.get((case.id, case.evidence_version)),
            current_user_id=current_user_id,
        )
        for case in cases
    ]


def _optional_nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _unique_diagnosis_index(pairs: list[tuple[Any, int]]) -> dict[Any, int]:
    candidates: dict[Any, int | None] = {}
    for key, diagnosis_id in pairs:
        if key is None:
            continue
        if key in candidates and candidates[key] != diagnosis_id:
            candidates[key] = None
        else:
            candidates[key] = diagnosis_id
    return {key: diagnosis_id for key, diagnosis_id in candidates.items() if diagnosis_id is not None}


def diagnosis_model_call_metadata(
    db: Session,
    diagnoses: list[ExceptionDiagnosis],
) -> dict[int, dict[str, Any]]:
    """Recover non-sensitive model input telemetry from immutable diagnosed events."""
    if not diagnoses:
        return {}
    diagnosis_ids = {row.id for row in diagnoses}
    job_ids = {row.job_id for row in diagnoses if row.job_id is not None}
    job_numbers = dict(
        db.execute(
            select(ExceptionDiagnosisJob.id, ExceptionDiagnosisJob.job_no).where(
                ExceptionDiagnosisJob.id.in_(job_ids)
            )
        ).all()
    ) if job_ids else {}
    by_job_id = _unique_diagnosis_index(
        [(row.job_id, row.id) for row in diagnoses if row.job_id is not None]
    )
    by_job_no = _unique_diagnosis_index(
        [(job_numbers.get(row.job_id), row.id) for row in diagnoses if row.job_id is not None]
    )
    by_request_id = _unique_diagnosis_index([(row.request_id, row.id) for row in diagnoses])
    by_case_evidence = _unique_diagnosis_index(
        [((row.case_id, row.evidence_version), row.id) for row in diagnoses]
    )
    events = list(
        db.scalars(
            select(ExceptionEvent)
            .where(
                ExceptionEvent.case_id.in_({row.case_id for row in diagnoses}),
                ExceptionEvent.event_type == "diagnosed",
            )
            .order_by(ExceptionEvent.created_at, ExceptionEvent.id)
        ).all()
    )
    result: dict[int, dict[str, Any]] = {}
    for event in events:
        detail = event.detail_json if isinstance(event.detail_json, dict) else {}
        model_call = detail.get("model_call")
        if not isinstance(model_call, dict):
            continue
        diagnosis_id = _optional_nonnegative_int(detail.get("diagnosis_id"))
        if diagnosis_id not in diagnosis_ids:
            diagnosis_id = by_job_id.get(_optional_nonnegative_int(detail.get("job_id")))
        if diagnosis_id is None:
            diagnosis_id = by_job_no.get(detail.get("job_no"))
        if diagnosis_id is None:
            diagnosis_id = by_request_id.get(model_call.get("request_id"))
        if diagnosis_id is None:
            evidence_version = detail.get("evidence_version")
            if evidence_version is not None:
                diagnosis_id = by_case_evidence.get((event.case_id, str(evidence_version)))
        if diagnosis_id is None:
            continue
        result[diagnosis_id] = model_call
    return result


def serialize_diagnoses(
    db: Session,
    diagnoses: list[ExceptionDiagnosis],
) -> list[dict[str, Any]]:
    metadata = diagnosis_model_call_metadata(db, diagnoses)
    return [serialize_diagnosis(row, model_call_metadata=metadata.get(row.id)) for row in diagnoses]


def serialize_diagnosis(
    row: ExceptionDiagnosis,
    *,
    model_call_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    model_call_metadata = model_call_metadata or {}
    evidence_truncated = model_call_metadata.get("evidence_truncated")
    return {
        "id": row.id,
        "evidence_version": row.evidence_version,
        "root_cause_code": row.root_cause_code,
        "summary": row.summary,
        "confidence": row.confidence,
        "disposition": row.disposition,
        "evidence_refs": row.evidence_refs_json or [],
        "impact": row.impact_json or {},
        "recommended_steps": row.recommended_steps_json or [],
        "missing_evidence": row.missing_evidence_json or [],
        "model_name": row.model_name,
        "request_id": row.request_id,
        "prompt_version": row.prompt_version,
        "contract_version": row.contract_version,
        "provider_request_id": row.provider_request_id,
        "latency_ms": row.latency_ms,
        "prompt_tokens": row.prompt_tokens,
        "completion_tokens": row.completion_tokens,
        "total_tokens": row.total_tokens,
        "evidence_bytes": _optional_nonnegative_int(model_call_metadata.get("evidence_bytes")),
        "evidence_approx_tokens": _optional_nonnegative_int(
            model_call_metadata.get("evidence_approx_tokens")
        ),
        "evidence_truncated": evidence_truncated if isinstance(evidence_truncated, bool) else None,
        "diagnosed_at": row.diagnosed_at,
        "feedback_rating": row.feedback_rating,
        "feedback_note": row.feedback_note,
        "feedback_by_user_id": row.feedback_by_user_id,
        "feedback_at": row.feedback_at,
    }


def exception_rule_quality_summary(
    db: Session,
    user: User,
    *,
    domain: str | None = None,
    rule_code: str | None = None,
    scan_window_days: int = 30,
) -> dict[str, Any]:
    if scan_window_days < 1 or scan_window_days > 90:
        raise ValueError("scan_window_days must be between 1 and 90")
    generated_at = utcnow()
    scan_window_start = generated_at - timedelta(days=scan_window_days)
    visible_stmt = scoped_exception_stmt(db, user).order_by(None)
    if domain:
        visible_stmt = visible_stmt.where(ExceptionCase.domain == domain)
    if rule_code:
        visible_stmt = visible_stmt.where(ExceptionCase.rule_code == rule_code)
    visible = visible_stmt.with_only_columns(
        ExceptionCase.id,
        ExceptionCase.domain,
        ExceptionCase.rule_code,
        ExceptionCase.rule_version,
        ExceptionCase.status,
        ExceptionCase.occurrence_type,
        ExceptionCase.last_seen_at,
    ).subquery()
    evidence_changes = (
        select(
            ExceptionEvent.case_id.label("case_id"),
            func.count().label("evidence_changed_events"),
        )
        .where(ExceptionEvent.event_type == "evidence_changed")
        .group_by(ExceptionEvent.case_id)
        .subquery()
    )

    def metric_columns() -> tuple[Any, ...]:
        return (
            func.count().label("total"),
            func.sum(
                sql_case(
                    (visible.c.status.in_(("open", "action_required", "processing", "blocked")), 1),
                    else_=0,
                )
            ).label("active"),
            func.sum(sql_case((visible.c.occurrence_type == "baseline", 1), else_=0)).label("baseline"),
            func.sum(sql_case((visible.c.occurrence_type == "new", 1), else_=0)).label("new"),
            func.sum(sql_case((visible.c.occurrence_type == "reopened", 1), else_=0)).label("reopened"),
            func.sum(sql_case((visible.c.status == "ignored", 1), else_=0)).label("ignored"),
            func.sum(sql_case((visible.c.status == "resolved", 1), else_=0)).label("resolved"),
            func.coalesce(func.sum(evidence_changes.c.evidence_changed_events), 0).label(
                "evidence_changed_events"
            ),
            func.max(visible.c.last_seen_at).label("latest_seen_at"),
        )

    joined_from = visible.outerjoin(evidence_changes, evidence_changes.c.case_id == visible.c.id)
    domain_rows = db.execute(
        select(visible.c.domain, *metric_columns())
        .select_from(joined_from)
        .group_by(visible.c.domain)
        .order_by(visible.c.domain)
    ).mappings().all()
    rule_rows = db.execute(
        select(
            visible.c.domain,
            visible.c.rule_code,
            visible.c.rule_version,
            *metric_columns(),
        )
        .select_from(joined_from)
        .group_by(visible.c.domain, visible.c.rule_code, visible.c.rule_version)
        .order_by(visible.c.domain, visible.c.rule_code, visible.c.rule_version)
    ).mappings().all()
    domain_modes = exception_domain_modes(db)
    domain_metrics: dict[str, dict[str, Any]] = {}
    for row in domain_rows:
        domain_name = str(row["domain"])
        domain_metrics[domain_name] = {
            "domain": domain_name,
            "domain_mode": domain_modes.get(domain_name, "off"),
            "total": int(row["total"] or 0),
            "active": int(row["active"] or 0),
            "baseline": int(row["baseline"] or 0),
            "new": int(row["new"] or 0),
            "reopened": int(row["reopened"] or 0),
            "ignored": int(row["ignored"] or 0),
            "resolved": int(row["resolved"] or 0),
            "evidence_changed_events": int(row["evidence_changed_events"] or 0),
            "latest_seen_at": row["latest_seen_at"],
            "false_positive_rate": None,
            "scan_job_metrics_available": False,
            "queued_scan_jobs": None,
            "failed_scan_jobs": None,
            "scan_latency_p95_ms": None,
        }

    visible_domains = set(domain_metrics)
    job_metric_domains = {
        domain_name
        for domain_name in visible_domains
        if can_run_global_exception_scan(db, user, {domain_name})
    }
    scan_latencies: dict[str, list[int]] = {domain_name: [] for domain_name in job_metric_domains}
    scan_job_sample_size = 0
    scan_job_metrics_truncated = False
    for domain_name in job_metric_domains:
        domain_metrics[domain_name]["scan_job_metrics_available"] = True
        domain_metrics[domain_name]["queued_scan_jobs"] = 0
        domain_metrics[domain_name]["failed_scan_jobs"] = 0
    if job_metric_domains:
        scan_jobs = list(
            db.execute(
                select(
                    ExceptionBackgroundJob.payload_json,
                    ExceptionBackgroundJob.status,
                    ExceptionBackgroundJob.started_at,
                    ExceptionBackgroundJob.completed_at,
                ).where(
                    ExceptionBackgroundJob.job_type.in_(("full_scan", "incremental_scan")),
                    ExceptionBackgroundJob.created_at >= scan_window_start,
                )
                .order_by(ExceptionBackgroundJob.created_at.desc(), ExceptionBackgroundJob.id.desc())
                .limit(RULE_QUALITY_SCAN_JOB_SAMPLE_LIMIT + 1)
            ).all()
        )
        scan_job_metrics_truncated = len(scan_jobs) > RULE_QUALITY_SCAN_JOB_SAMPLE_LIMIT
        scan_jobs = scan_jobs[:RULE_QUALITY_SCAN_JOB_SAMPLE_LIMIT]
        scan_job_sample_size = len(scan_jobs)
        for job in scan_jobs:
            payload = job.payload_json if isinstance(job.payload_json, dict) else {}
            job_input = payload.get("input") if isinstance(payload.get("input"), dict) else payload
            raw_domains = job_input.get("domains")
            job_domains = (
                {str(item) for item in raw_domains if str(item) in job_metric_domains}
                if isinstance(raw_domains, list) and raw_domains
                else set(job_metric_domains)
            )
            for domain_name in job_domains:
                metrics = domain_metrics[domain_name]
                if job.status == "queued":
                    metrics["queued_scan_jobs"] += 1
                elif job.status == "failed":
                    metrics["failed_scan_jobs"] += 1
                if job.started_at is None or job.completed_at is None:
                    continue
                started_at = job.started_at
                completed_at = job.completed_at
                if started_at.tzinfo is None and completed_at.tzinfo is not None:
                    completed_at = completed_at.replace(tzinfo=None)
                elif started_at.tzinfo is not None and completed_at.tzinfo is None:
                    started_at = started_at.replace(tzinfo=None)
                latency_ms = int(max(0, (completed_at - started_at).total_seconds() * 1000))
                scan_latencies[domain_name].append(latency_ms)
        for domain_name, latencies in scan_latencies.items():
            if not latencies:
                continue
            ordered = sorted(latencies)
            percentile_index = max(0, ((95 * len(ordered) + 99) // 100) - 1)
            domain_metrics[domain_name]["scan_latency_p95_ms"] = ordered[percentile_index]

    rules = []
    for row in rule_rows:
        domain_name = str(row["domain"])
        rules.append(
            {
                "domain": domain_name,
                "domain_mode": domain_modes.get(domain_name, "off"),
                "rule_code": str(row["rule_code"]),
                "rule_version": str(row["rule_version"]),
                "total": int(row["total"] or 0),
                "active": int(row["active"] or 0),
                "baseline": int(row["baseline"] or 0),
                "new": int(row["new"] or 0),
                "reopened": int(row["reopened"] or 0),
                "ignored": int(row["ignored"] or 0),
                "resolved": int(row["resolved"] or 0),
                "evidence_changed_events": int(row["evidence_changed_events"] or 0),
                "latest_seen_at": row["latest_seen_at"],
                "false_positive_rate": None,
            }
        )
    return {
        "generated_at": generated_at,
        "scan_job_window_days": scan_window_days,
        "scan_job_window_start": scan_window_start,
        "scan_job_window_end": generated_at,
        "scan_job_sample_limit": RULE_QUALITY_SCAN_JOB_SAMPLE_LIMIT,
        "scan_job_sample_size": scan_job_sample_size,
        "scan_job_metrics_truncated": scan_job_metrics_truncated,
        "domains": list(domain_metrics.values()),
        "rules": rules,
    }


def diagnosis_quality_summary(
    db: Session,
    user: User,
    *,
    domain: str | None = None,
    rule_code: str | None = None,
    diagnosed_from: datetime | None = None,
    diagnosed_to: datetime | None = None,
) -> dict[str, Any]:
    visible = scoped_exception_stmt(db, user).with_only_columns(ExceptionCase.id).subquery()
    stmt = (
        select(ExceptionDiagnosis, ExceptionCase)
        .join(ExceptionCase, ExceptionCase.id == ExceptionDiagnosis.case_id)
        .where(ExceptionDiagnosis.case_id.in_(select(visible.c.id)))
    )
    if domain:
        stmt = stmt.where(ExceptionCase.domain == domain)
    if rule_code:
        stmt = stmt.where(ExceptionCase.rule_code == rule_code)
    if diagnosed_from:
        stmt = stmt.where(ExceptionDiagnosis.diagnosed_at >= diagnosed_from)
    if diagnosed_to:
        stmt = stmt.where(ExceptionDiagnosis.diagnosed_at <= diagnosed_to)
    rows = list(db.execute(stmt.order_by(ExceptionDiagnosis.diagnosed_at.desc())).all())
    evidence_rows = list(
        db.scalars(
            select(ExceptionEvidence).where(
                ExceptionEvidence.case_id.in_([diagnosis.case_id for diagnosis, _ in rows] or [-1])
            )
        ).all()
    )
    evidence_map = {(row.case_id, row.evidence_version): row.data_json for row in evidence_rows}

    def grouped(values: list[str | None]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for value in values:
            key = str(value or "unknown")
            counts[key] = counts.get(key, 0) + 1
        return counts

    def usage_is_complete(diagnosis: ExceptionDiagnosis) -> bool:
        return all(
            value is not None
            for value in (
                diagnosis.prompt_tokens,
                diagnosis.completion_tokens,
                diagnosis.total_tokens,
            )
        )

    def bucketed(key_getter) -> list[dict[str, Any]]:  # noqa: ANN001
        grouped_rows: dict[str, list[tuple[ExceptionDiagnosis, ExceptionCase]]] = {}
        for diagnosis, case in rows:
            key = str(key_getter(diagnosis, case) or "unknown")
            grouped_rows.setdefault(key, []).append((diagnosis, case))
        result: list[dict[str, Any]] = []
        for key, bucket_rows in grouped_rows.items():
            ratings = [diagnosis.feedback_rating for diagnosis, _ in bucket_rows if diagnosis.feedback_rating]
            confidences = [float(diagnosis.confidence) for diagnosis, _ in bucket_rows]
            latencies = [diagnosis.latency_ms for diagnosis, _ in bucket_rows if diagnosis.latency_ms is not None]
            usage_reported_count = sum(
                1 for diagnosis, _ in bucket_rows if usage_is_complete(diagnosis)
            )
            usage_missing_count = len(bucket_rows) - usage_reported_count
            helpful = ratings.count("helpful")
            partial = ratings.count("partial")
            rated = len(ratings)
            result.append(
                {
                    "key": key,
                    "label": key,
                    "diagnoses": len(bucket_rows),
                    "rated": rated,
                    "helpful": helpful,
                    "partial": partial,
                    "incorrect": ratings.count("incorrect"),
                    "positive_rate": ((helpful + partial) / rated) if rated else None,
                    "average_confidence": (sum(confidences) / len(confidences)) if confidences else None,
                    "average_latency_ms": (sum(latencies) / len(latencies)) if latencies else None,
                    "total_tokens": sum(diagnosis.total_tokens or 0 for diagnosis, _ in bucket_rows),
                    "usage_reported_count": usage_reported_count,
                    "usage_missing_count": usage_missing_count,
                    "usage_completeness_rate": usage_reported_count / len(bucket_rows),
                }
            )
        return sorted(result, key=lambda item: (-item["diagnoses"], item["key"]))

    def resolution_hours(diagnosis: ExceptionDiagnosis, case: ExceptionCase) -> float | None:
        if case.resolved_at is None:
            return None
        diagnosed_at = diagnosis.diagnosed_at
        resolved_at = case.resolved_at
        if resolved_at.tzinfo is None and diagnosed_at.tzinfo is not None:
            diagnosed_at = diagnosed_at.replace(tzinfo=None)
        elif resolved_at.tzinfo is not None and diagnosed_at.tzinfo is None:
            diagnosed_at = diagnosed_at.replace(tzinfo=timezone.utc)
        elapsed = (resolved_at - diagnosed_at).total_seconds() / 3600
        return elapsed if elapsed >= 0 else None

    feedback = [diagnosis.feedback_rating for diagnosis, _ in rows if diagnosis.feedback_rating]
    reference_total = 0
    reference_valid = 0
    for diagnosis, _case in rows:
        evidence_text = json.dumps(
            evidence_map.get((diagnosis.case_id, diagnosis.evidence_version), {}),
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        ).casefold()
        for raw_ref in diagnosis.evidence_refs_json or []:
            reference = str(raw_ref).strip()
            if not reference:
                continue
            reference_total += 1
            suffix = reference.rsplit(":", 1)[-1].strip().casefold()
            if reference.casefold() in evidence_text or (suffix and suffix in evidence_text):
                reference_valid += 1
    total = len(rows)
    usage_reported_count = sum(1 for diagnosis, _ in rows if usage_is_complete(diagnosis))
    usage_missing_count = total - usage_reported_count
    confidences = [float(diagnosis.confidence) for diagnosis, _ in rows]
    latencies = [diagnosis.latency_ms for diagnosis, _ in rows if diagnosis.latency_ms is not None]
    all_resolution_hours = [
        value
        for diagnosis, case in rows
        if (value := resolution_hours(diagnosis, case)) is not None
    ]
    helpful = feedback.count("helpful")
    partial = feedback.count("partial")
    incorrect = feedback.count("incorrect")
    rated = len(feedback)
    rule_buckets = bucketed(lambda diagnosis, case: case.rule_code)
    rules = []
    for bucket in rule_buckets:
        matching = [(diagnosis, case) for diagnosis, case in rows if str(case.rule_code or "unknown") == bucket["key"]]
        rule_resolution_hours = [
            value
            for diagnosis, case in matching
            if (value := resolution_hours(diagnosis, case)) is not None
        ]
        rules.append(
            {
                "domain": matching[0][1].domain if matching else None,
                "rule_code": bucket["key"],
                "diagnoses": bucket["diagnoses"],
                "feedback_count": bucket["rated"],
                "helpful": bucket["helpful"],
                "partial": bucket["partial"],
                "incorrect": bucket["incorrect"],
                "helpful_rate": (bucket["helpful"] / bucket["rated"]) if bucket["rated"] else None,
                "average_confidence": bucket["average_confidence"],
                "average_resolution_hours": (
                    sum(rule_resolution_hours) / len(rule_resolution_hours)
                    if rule_resolution_hours
                    else None
                ),
            }
        )
    diagnosed_times = [diagnosis.diagnosed_at for diagnosis, _ in rows]
    return {
        "generated_at": utcnow(),
        "period_start": min(diagnosed_times) if diagnosed_times else diagnosed_from,
        "period_end": max(diagnosed_times) if diagnosed_times else diagnosed_to,
        "total_diagnoses": total,
        "feedback_count": rated,
        "feedback_rate": (rated / total) if total else None,
        "helpful_rate": (helpful / rated) if rated else None,
        "feedback_coverage_rate": (rated / total) if total else None,
        "rated_diagnoses": rated,
        "helpful": helpful,
        "partial": partial,
        "incorrect": incorrect,
        "unrated": max(0, total - rated),
        "positive_rate": ((helpful + partial) / rated) if rated else None,
        "evidence_citation_rate": (
            sum(1 for diagnosis, _ in rows if diagnosis.evidence_refs_json) / total
            if total
            else None
        ),
        "evidence_reference_valid_rate": (reference_valid / reference_total) if reference_total else None,
        "average_confidence": (sum(confidences) / len(confidences)) if confidences else None,
        "average_latency_ms": (sum(latencies) / len(latencies)) if latencies else None,
        "average_resolution_hours": (
            sum(all_resolution_hours) / len(all_resolution_hours)
            if all_resolution_hours
            else None
        ),
        "prompt_tokens": sum(diagnosis.prompt_tokens or 0 for diagnosis, _ in rows),
        "completion_tokens": sum(diagnosis.completion_tokens or 0 for diagnosis, _ in rows),
        "total_tokens": sum(diagnosis.total_tokens or 0 for diagnosis, _ in rows),
        "usage_reported_count": usage_reported_count,
        "usage_missing_count": usage_missing_count,
        "usage_completeness_rate": (usage_reported_count / total) if total else None,
        "by_feedback": grouped([diagnosis.feedback_rating for diagnosis, _ in rows if diagnosis.feedback_rating]),
        "by_disposition": grouped([diagnosis.disposition for diagnosis, _ in rows]),
        "by_root_cause_code": bucketed(lambda diagnosis, case: diagnosis.root_cause_code),
        "by_contract_version": bucketed(lambda diagnosis, case: diagnosis.contract_version),
        "by_domain": bucketed(lambda diagnosis, case: case.domain),
        "by_rule": rule_buckets,
        "by_model": bucketed(lambda diagnosis, case: diagnosis.model_name),
        "by_prompt_version": bucketed(lambda diagnosis, case: diagnosis.prompt_version),
        "rules": rules,
    }


def create_diagnosis_job(
    db: Session,
    case: ExceptionCase,
    user_id: int | None,
    trigger_type: str = "manual",
    force: bool = False,
) -> tuple[ExceptionDiagnosisJob, bool]:
    locked_case = db.scalar(select(ExceptionCase).where(ExceptionCase.id == case.id).with_for_update())
    if locked_case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exception case not found")
    case = locked_case
    if case.domain not in AI_DIAGNOSIS_DOMAINS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "exception_diagnosis_not_supported",
                "message": f"AI diagnosis is not supported for the {case.domain} exception domain",
                "module": "exceptions",
                "resource_type": case.resource_type,
                "resource_id": case.resource_id,
                "case_no": case.case_no,
                "retryable": False,
                "action_path": f"/exceptions?open={case.case_no}",
            },
        )
    if case.status in {"resolved", "ignored"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Resolved or ignored exception cases cannot be diagnosed",
        )
    existing_diagnosis = db.scalar(
        select(ExceptionDiagnosis).where(
            ExceptionDiagnosis.case_id == case.id,
            ExceptionDiagnosis.evidence_version == case.evidence_version,
        )
    )
    if existing_diagnosis is not None and not force:
        job = db.scalar(
            select(ExceptionDiagnosisJob)
            .where(
                ExceptionDiagnosisJob.case_id == case.id,
                ExceptionDiagnosisJob.evidence_version == case.evidence_version,
                ExceptionDiagnosisJob.status == "completed",
            )
            .order_by(ExceptionDiagnosisJob.id.desc())
            .limit(1)
        )
        if job:
            return job, True
    active = db.scalar(
        select(ExceptionDiagnosisJob).where(
            ExceptionDiagnosisJob.case_id == case.id,
            ExceptionDiagnosisJob.evidence_version == case.evidence_version,
            ExceptionDiagnosisJob.status.in_(("queued", "processing")),
        )
    )
    if active:
        return active, True
    job = ExceptionDiagnosisJob(
        job_no=f"EXJOB-{utcnow():%Y%m%d%H%M%S}-{secrets.token_hex(4).upper()}",
        case_id=case.id,
        evidence_version=case.evidence_version,
        trigger_type=trigger_type,
        status="queued",
        requested_by_user_id=user_id,
        available_at=utcnow(),
    )
    try:
        with db.begin_nested():
            db.add(job)
            db.flush()
    except IntegrityError:
        active = db.scalar(
            select(ExceptionDiagnosisJob)
            .where(
                ExceptionDiagnosisJob.case_id == case.id,
                ExceptionDiagnosisJob.evidence_version == case.evidence_version,
                ExceptionDiagnosisJob.status.in_(("queued", "processing")),
            )
            .order_by(ExceptionDiagnosisJob.id.desc())
            .limit(1)
        )
        if active is not None:
            return active, True
        raise
    previous_status = case.status
    case.status = "processing"
    db.add(
        ExceptionEvent(
            case_id=case.id,
            event_type="diagnosis_queued",
            from_status=previous_status,
            to_status="processing",
            actor_user_id=user_id,
            detail_json={"job_no": job.job_no},
        )
    )
    return job, False


def serialize_job(job: ExceptionDiagnosisJob, case_no: str, reused: bool = False) -> dict[str, Any]:
    return {
        "id": job.id,
        "job_no": job.job_no,
        "case_no": case_no,
        "evidence_version": job.evidence_version,
        "trigger_type": job.trigger_type,
        "status": job.status,
        "reused": reused,
        "error_message": job.error_message,
        "requested_by_user_id": job.requested_by_user_id,
        "attempts": job.attempts,
        "attempt_count": job.attempts,
        "max_attempts": max(1, settings.exception_job_max_attempts),
        "available_at": job.available_at,
        "lease_owner": job.lease_owner,
        "lease_expires_at": job.lease_expires_at,
        "cancel_requested_at": job.cancel_requested_at,
        "cancel_requested_by_user_id": job.cancel_requested_by_user_id,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "cancellable": job.status in {"queued", "processing"},
        "retryable": job.status in {"failed", "cancelled"},
    }


def enqueue_due_ai_diagnoses(db: Session, limit: int = 50) -> list[ExceptionDiagnosisJob]:
    policy = default_policy(db)
    if (
        not settings.exception_ai_enabled
        or not policy.is_enabled
        or not policy.scheduled_ai_enabled
    ):
        return []
    safe_limit = max(1, min(limit, policy.scheduled_ai_batch_limit, 500))
    stale_cutoff = utcnow() - timedelta(hours=max(1, policy.stale_diagnosis_hours))
    current_diagnosis_exists = exists(
        select(ExceptionDiagnosis.id).where(
            ExceptionDiagnosis.case_id == ExceptionCase.id,
            ExceptionDiagnosis.evidence_version == ExceptionCase.evidence_version,
        )
    )
    active_job_exists = exists(
        select(ExceptionDiagnosisJob.id).where(
            ExceptionDiagnosisJob.case_id == ExceptionCase.id,
            ExceptionDiagnosisJob.evidence_version == ExceptionCase.evidence_version,
            ExceptionDiagnosisJob.status.in_(("queued", "processing")),
        )
    )
    current_change_exists = exists(
        select(ExceptionEvent.id).where(
            ExceptionEvent.case_id == ExceptionCase.id,
            ExceptionEvent.event_type.in_(("reopened", "severity_upgraded")),
            ExceptionEvent.created_at >= ExceptionCase.last_seen_at,
        )
    )
    severity_priority = sql_case(
        (ExceptionCase.severity == "critical", 3),
        (ExceptionCase.severity == "high", 2),
        (ExceptionCase.severity == "warning", 1),
        else_=0,
    )
    occurrence_priority = sql_case(
        (ExceptionCase.occurrence_type.in_(("new", "reopened")), 1),
        else_=0,
    )
    rows = list(
        db.scalars(
            select(ExceptionCase)
            .where(
                ExceptionCase.status.in_(("open", "action_required", "blocked")),
                ExceptionCase.domain.in_(AI_DIAGNOSIS_DOMAINS),
                ~ExceptionCase.rule_code.like("master_completeness.%"),
                ~current_diagnosis_exists,
                ~active_job_exists,
                or_(
                    ExceptionCase.occurrence_type.in_(("new", "reopened")),
                    and_(
                        ExceptionCase.occurrence_type == "baseline",
                        or_(ExceptionCase.detected_at <= stale_cutoff, current_change_exists),
                    ),
                ),
            )
            .order_by(
                occurrence_priority.desc(),
                severity_priority.desc(),
                ExceptionCase.last_seen_at.desc(),
                ExceptionCase.id.desc(),
            )
            .limit(safe_limit)
        ).all()
    )
    jobs: list[ExceptionDiagnosisJob] = []
    for case in rows:
        comparable_cutoff = stale_cutoff if case.detected_at.tzinfo else stale_cutoff.replace(tzinfo=None)
        is_stale_backfill = case.occurrence_type == "baseline" and case.detected_at <= comparable_cutoff
        job, reused = create_diagnosis_job(db, case, None, "scheduled")
        if not reused:
            jobs.append(job)
            if is_stale_backfill:
                db.add(
                    ExceptionEvent(
                        case_id=case.id,
                        event_type="diagnosis_stale_backfill_queued",
                        to_status="processing",
                        detail_json={"job_no": job.job_no, "stale_diagnosis_hours": policy.stale_diagnosis_hours},
                    )
                )
    return jobs


def create_exception_digest_notifications(db: Session) -> int:
    domain_modes = exception_domain_modes(db)
    notification_domains = [domain for domain, mode in domain_modes.items() if mode == "visible"]
    active_cases = list(
        db.scalars(
            select(ExceptionCase).where(
                ExceptionCase.status.notin_(("resolved", "ignored")),
                ExceptionCase.domain.in_(notification_domains),
            )
        ).all()
    )
    if not active_cases:
        return 0
    users = list(db.scalars(select(User).where(User.is_active.is_(True), User.status == "active")).all())
    created = 0
    for user in users:
        visible = [case for case in active_cases if can_view_case(db, user, case)]
        if not visible:
            continue
        critical = sum(1 for case in visible if case.severity in {"critical", "high"})
        local_date = utcnow().astimezone(ZoneInfo(settings.exception_schedule_timezone)).date().isoformat()
        marker = _hash_json({"date": local_date, "cases": sorted((case.id, case.evidence_version) for case in visible)})
        notification = db.scalar(
            select(ExceptionNotification).where(
                ExceptionNotification.user_id == user.id,
                ExceptionNotification.notification_type == "daily_digest",
                ExceptionNotification.evidence_version == marker,
            )
        )
        if notification:
            continue
        first = visible[0]
        db.add(
            ExceptionNotification(
                case_id=first.id,
                user_id=user.id,
                notification_type="daily_digest",
                evidence_version=marker,
                title="异常巡检日报",
                message=f"当前有 {len(visible)} 项待处理异常，其中高风险 {critical} 项。",
            )
        )
        created += 1
    return created


def _require_exception_actions_enabled() -> None:
    if not settings.exception_actions_enabled:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Exception actions are disabled")


def _action_parameters_are_valid(parameters: dict[str, Any]) -> bool:
    if set(parameters) - {"batch_id"}:
        return False
    batch_id = parameters.get("batch_id")
    return batch_id is None or (isinstance(batch_id, int) and not isinstance(batch_id, bool) and batch_id > 0)


def configured_exception_action_types(db: Session) -> frozenset[str]:
    policy = db.scalar(select(ExceptionPolicy).where(ExceptionPolicy.policy_key == "default"))
    settings_json = policy.settings_json if policy and isinstance(policy.settings_json, dict) else {}
    configured = settings_json.get(ACTION_POLICY_SETTING_KEY)
    if configured is None:
        return SUPPORTED_ACTION_TYPES
    if not isinstance(configured, (list, tuple, set)):
        return frozenset()
    return frozenset(str(action_type) for action_type in configured) & SUPPORTED_ACTION_TYPES


def _action_blockers(
    db: Session,
    case: ExceptionCase,
    action_type: str,
    parameters: dict[str, Any],
    user: User,
    *,
    excluding_action_id: int | None = None,
) -> list[str]:
    blockers: list[str] = []
    parameters_are_valid = _action_parameters_are_valid(parameters)
    if not parameters_are_valid:
        blockers.append("invalid_parameters")
    if action_type not in ACTION_DOMAINS:
        blockers.append("unsupported_action")
    elif action_type not in configured_exception_action_types(db):
        blockers.append("action_disabled_by_policy")
    elif case.domain not in ACTION_DOMAINS[action_type]:
        blockers.append("action_not_allowed_for_domain")
    if case.status in {"resolved", "ignored"}:
        blockers.append("case_not_active")
    source_permission = ACTION_SOURCE_PERMISSIONS.get(action_type)
    if source_permission and not has_permission(db, user, source_permission):
        blockers.append(f"missing_permission:{source_permission}")
    requested_batch_id = parameters.get("batch_id") if parameters_are_valid else None
    if requested_batch_id is not None and requested_batch_id != case.source_batch_id:
        blockers.append("batch_id_mismatch")
    if case.source_batch_id is None:
        blockers.append("source_batch_id_required")
    required_batch_kind = ACTION_BATCH_KINDS.get(action_type)
    if case.source_batch_id is not None and required_batch_kind is not None and case.source_batch_kind != required_batch_kind:
        blockers.append("batch_kind_incompatible")
    effective_batch_id = (
        case.source_batch_id
        if action_type != "rerun_inventory_check" or case.source_type in RERUN_INVENTORY_CHECK_SOURCE_TYPES
        else None
    )
    if action_type in {"rerun_inventory_check", "revalidate_import_batch"} and not effective_batch_id:
        blockers.append("batch_id_required")
    if action_type == "rerun_inventory_check" and case.source_type not in RERUN_INVENTORY_CHECK_SOURCE_TYPES:
        blockers.append("batch_source_incompatible")
    executing_stmt = select(ExceptionAction.id).where(
        ExceptionAction.case_id == case.id,
        ExceptionAction.status == "executing",
    )
    if excluding_action_id is not None:
        executing_stmt = executing_stmt.where(ExceptionAction.id != excluding_action_id)
    if db.scalar(executing_stmt.limit(1)):
        blockers.append("case_execution_in_progress")
    pending_file_types = {
        "rebuild_inventory_flow": {"inventory_snapshot", "sales_detail", "purchase_detail"},
        "rerun_inventory_check": {"inventory_snapshot"},
        "rebuild_receivable_checks": {"receivable_snapshot", "account_ledger"},
        "rebuild_master_link_issues": {"sales_detail", "purchase_detail", "account_ledger"},
    }.get(action_type)
    if pending_file_types and _has_newer_pending_import(db, pending_file_types):
        blockers.append("source_import_in_progress")
    if effective_batch_id and parameters_are_valid and "batch_id_mismatch" not in blockers:
        batch_model = InventoryCheckBatch if action_type == "rerun_inventory_check" else ImportBatch
        batch = db.get(batch_model, int(effective_batch_id))
        if batch is None:
            blockers.append("batch_not_found")
        elif action_type == "revalidate_import_batch" and batch.status == "committed":
            blockers.append("import_batch_already_committed")
    return blockers


def available_exception_action_types(db: Session, case: ExceptionCase, user: User) -> list[str]:
    """Return actions the user may enter without creating validation records."""
    if not settings.exception_actions_enabled or not has_permission(db, user, "exception_center.action_execute"):
        return []
    return sorted(
        action_type
        for action_type in configured_exception_action_types(db)
        if not _action_blockers(db, case, action_type, {}, user)
    )


def validate_action(db: Session, case: ExceptionCase, action_type: str, parameters: dict[str, Any], user: User) -> tuple[ExceptionAction, str]:
    _require_exception_actions_enabled()
    blockers = _action_blockers(db, case, action_type, parameters, user)
    token = secrets.token_urlsafe(32)
    action = ExceptionAction(
        action_no=f"EXACT-{utcnow():%Y%m%d%H%M%S}-{secrets.token_hex(4).upper()}",
        case_id=case.id,
        action_type=action_type,
        status="validated" if not blockers else "blocked",
        allowed=not blockers,
        blockers_json=blockers,
        parameters_json=parameters,
        impact_json={
            "domain": case.domain,
            "resource_id": case.resource_id,
            "source_batch_kind": case.source_batch_kind,
            "batch_id": case.source_batch_id,
            "scope": "global_derived_inventory" if action_type == "rebuild_inventory_flow" else "source_batch",
        },
        evidence_version=case.evidence_version,
        validation_token_hash=hashlib.sha256(token.encode()).hexdigest(),
        validation_expires_at=utcnow() + timedelta(minutes=ACTION_TTL_MINUTES),
        requested_by_user_id=user.id,
    )
    db.add(action)
    db.flush()
    return action, token


def _has_newer_pending_import(db: Session, file_types: set[str]) -> bool:
    latest_committed_at = db.scalar(
        select(func.max(ImportBatch.uploaded_at)).where(
            ImportBatch.file_type.in_(file_types),
            ImportBatch.status == "committed",
        )
    )
    stmt = select(ImportBatch.id).where(
        ImportBatch.file_type.in_(file_types),
        ImportBatch.status.notin_(("committed", "failed")),
    )
    if latest_committed_at is not None:
        stmt = stmt.where(ImportBatch.uploaded_at > latest_committed_at)
    return db.scalar(stmt.limit(1)) is not None


def _acquire_action_idempotency_lock(db: Session, idempotency_key: str) -> None:
    bind = db.get_bind()
    if bind is None or bind.dialect.name != "postgresql":
        return
    lock_name = f"exception_action:idempotency:{idempotency_key}"
    lock_key = int.from_bytes(hashlib.sha256(lock_name.encode("utf-8")).digest()[:8], byteorder="big", signed=True)
    db.execute(select(func.pg_advisory_xact_lock(lock_key)))


def _safe_action_error(exc: Exception) -> str:
    return {
        "ValueError": "action_validation_failed",
        "IntegrityError": "action_conflict",
        "OperationalError": "action_database_unavailable",
        "TimeoutError": "action_timed_out",
    }.get(type(exc).__name__, "action_execution_failed")


def _lock_exception_case_for_action(db: Session, case_id: int) -> ExceptionCase | None:
    return db.scalar(select(ExceptionCase).where(ExceptionCase.id == case_id).with_for_update())


def _action_token_expired(action: ExceptionAction) -> bool:
    expires_at = action.validation_expires_at
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return not expires_at or expires_at <= utcnow()


def _assert_action_token_binding(action: ExceptionAction | None, case_id: int, user_id: int) -> ExceptionAction:
    if action is None or action.case_id != case_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid validation token")
    if action.requested_by_user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Validation token belongs to another user")
    return action


def _assert_action_matches_case_evidence(action: ExceptionAction, case: ExceptionCase) -> None:
    if action.evidence_version != case.evidence_version:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Evidence changed; validate again")
    validated_batch_id = (action.impact_json or {}).get("batch_id")
    if validated_batch_id != case.source_batch_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Source batch changed; validate again")
    validated_batch_kind = (action.impact_json or {}).get("source_batch_kind")
    if validated_batch_kind != case.source_batch_kind:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Source batch kind changed; validate again")


def execute_action(db: Session, case: ExceptionCase, token: str, idempotency_key: str, user: User) -> ExceptionAction:
    _require_exception_actions_enabled()
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    action = _assert_action_token_binding(
        db.scalar(select(ExceptionAction).where(ExceptionAction.validation_token_hash == token_hash)),
        case.id,
        user.id,
    )
    replaying = bool(action.idempotency_key)
    if replaying:
        if action.idempotency_key != idempotency_key:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Validation token already used")
    else:
        if not action.allowed or action.status != "validated":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Action is not allowed")
        if _action_token_expired(action):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Validation token expired")
        _assert_action_matches_case_evidence(action, case)

    # Synchronizers acquire this advisory lock before touching case rows. Do
    # the same here so action execution cannot deadlock with a concurrent scan.
    _acquire_exception_sync_lock(db)
    _acquire_action_idempotency_lock(db, idempotency_key)

    action = _assert_action_token_binding(
        db.scalar(select(ExceptionAction).where(ExceptionAction.validation_token_hash == token_hash).with_for_update()),
        case.id,
        user.id,
    )
    if action.idempotency_key:
        if action.idempotency_key != idempotency_key:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Validation token already used")
    locked_case = _lock_exception_case_for_action(db, action.case_id)
    if locked_case is None or locked_case.id != case.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exception case not found")
    if not can_view_case(db, user, locked_case):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exception case not found")
    if action.idempotency_key:
        return action
    existing = db.scalar(select(ExceptionAction).where(ExceptionAction.idempotency_key == idempotency_key))
    if existing:
        if existing.case_id != case.id or existing.action_type != action.action_type or existing.requested_by_user_id != user.id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Idempotency key belongs to another action")
        return existing
    if not action.allowed or action.status != "validated":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Action is not allowed")
    if _action_token_expired(action):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Validation token expired")
    _assert_action_matches_case_evidence(action, locked_case)
    blockers = _action_blockers(
        db,
        locked_case,
        action.action_type,
        action.parameters_json or {},
        user,
        excluding_action_id=action.id,
    )
    if blockers:
        if any(blocker.startswith("missing_permission:") for blocker in blockers):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Source permission is no longer available")
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"message": "Action conditions changed; validate again", "blockers": blockers})

    action.idempotency_key = idempotency_key
    action.status = "executing"
    action.started_at = utcnow()
    locked_case.status = "processing"
    db.flush()
    try:
        with db.begin_nested():
            result = _run_action(db, locked_case, action, user)
            scan_result = run_full_exception_scan(db)
        action.result_json = result
        action.status = "completed"
        action.completed_at = utcnow()
        db.flush()
        db.refresh(locked_case)
        action.verification_json = {"case_status": locked_case.status, "scan": scan_result}
        db.add(ExceptionEvent(case_id=locked_case.id, event_type="action_completed", actor_user_id=user.id, detail_json={"action_no": action.action_no, "action_type": action.action_type}))
    except Exception as exc:
        safe_error = _safe_action_error(exc)
        action.status = "failed"
        action.error_message = safe_error
        action.completed_at = utcnow()
        locked_case.status = "blocked"
        db.add(ExceptionEvent(case_id=locked_case.id, event_type="action_failed", actor_user_id=user.id, to_status="blocked", detail_json={"action_no": action.action_no, "error_code": safe_error}))
        db.flush()
    return action


def _run_action(db: Session, case: ExceptionCase, action: ExceptionAction, user: User) -> dict[str, Any]:
    if action.action_type == "rebuild_inventory_flow":
        from app.services.inventory_flow_service import rebuild_inventory_flow

        return rebuild_inventory_flow(db, trigger_batch_id=case.source_batch_id)
    if action.action_type == "rerun_inventory_check":
        from app.services.inventory_check_service import rebuild_inventory_check_batch

        if case.source_batch_id is None:
            raise ValueError("Inventory check batch is required")
        batch_id = int(case.source_batch_id)
        batch = db.get(InventoryCheckBatch, batch_id)
        if batch is None:
            raise ValueError("Inventory check batch not found")
        rebuilt = rebuild_inventory_check_batch(db, batch=batch, user=user)
        return {"batch_id": rebuilt.id, "batch_no": rebuilt.batch_no, "status": rebuilt.status}
    if action.action_type == "rebuild_receivable_checks":
        from app.services.receivable_service import rebuild_receivable_checks

        return rebuild_receivable_checks(db, batch_id=int(case.source_batch_id) if case.source_batch_id else None)
    if action.action_type == "rebuild_master_link_issues":
        from app.services.master_link_service import rebuild_master_link_issues

        return rebuild_master_link_issues(db, batch_id=int(case.source_batch_id) if case.source_batch_id else None)
    if action.action_type == "revalidate_import_batch":
        from app.services.import_service import validate_batch

        if case.source_batch_id is None:
            raise ValueError("Import batch is required")
        batch_id = int(case.source_batch_id)
        batch = db.get(ImportBatch, batch_id)
        if batch is None:
            raise ValueError("Import batch not found")
        if batch.status == "committed":
            raise ValueError("Committed import batches cannot be revalidated")
        validated = validate_batch(db, batch)
        return {"batch_id": validated.id, "batch_no": validated.batch_no, "status": validated.status, "error_rows": validated.error_rows}
    raise ValueError("Unsupported action")


def serialize_action(action: ExceptionAction, case_no: str, *, token: str | None = None) -> dict[str, Any]:
    return {
        "id": action.id,
        "action_no": action.action_no,
        "case_no": case_no,
        "action_type": action.action_type,
        "status": action.status,
        "allowed": action.allowed,
        "blockers": action.blockers_json or [],
        "impact": action.impact_json or {},
        "evidence_version": action.evidence_version,
        "validation_token": token if action.allowed else None,
        "validation_expires_at": action.validation_expires_at,
        "result": action.result_json,
        "verification": action.verification_json,
        "error_message": action.error_message,
        "created_at": action.created_at,
        "completed_at": action.completed_at,
    }


def summary_for_cases(db: Session, user: User, occurrence_type: str | None = None) -> dict[str, Any]:
    scoped = scoped_exception_stmt(db, user, occurrence_type=occurrence_type).order_by(None).subquery()
    now = utcnow()
    due_soon_at = now + timedelta(hours=24)
    active = scoped.c.status.notin_(("resolved", "ignored"))
    total = db.scalar(select(func.count()).select_from(scoped)) or 0
    statuses = dict(db.execute(select(scoped.c.status, func.count()).group_by(scoped.c.status)).all())
    domains = dict(db.execute(select(scoped.c.domain, func.count()).group_by(scoped.c.domain)).all())
    severities = dict(db.execute(select(scoped.c.severity, func.count()).group_by(scoped.c.severity)).all())
    occurrence_types = dict(
        db.execute(select(scoped.c.occurrence_type, func.count()).group_by(scoped.c.occurrence_type)).all()
    )
    unread = db.scalar(
        select(func.count(ExceptionNotification.id)).where(
            ExceptionNotification.user_id == user.id,
            ExceptionNotification.is_read.is_(False),
            ExceptionNotification.archived_at.is_(None),
            ExceptionNotification.case_id.in_(select(scoped.c.id)),
        )
    ) or 0
    policy = default_policy(db)
    manual_ai_enabled = bool(policy.is_enabled and policy.manual_ai_enabled)
    assigned_to_me = int(
        db.scalar(select(func.count()).select_from(scoped).where(active, scoped.c.assignee_user_id == user.id)) or 0
    )
    unassigned = int(
        db.scalar(select(func.count()).select_from(scoped).where(active, scoped.c.assignee_user_id.is_(None))) or 0
    )
    overdue = int(
        db.scalar(select(func.count()).select_from(scoped).where(active, scoped.c.due_at.is_not(None), scoped.c.due_at < now)) or 0
    )
    due_soon = int(
        db.scalar(
            select(func.count()).select_from(scoped).where(
                active,
                scoped.c.due_at >= now,
                scoped.c.due_at <= due_soon_at,
            )
        )
        or 0
    )
    return {
        "total": total,
        "open": statuses.get("open", 0),
        "action_required": statuses.get("action_required", 0),
        "processing": statuses.get("processing", 0),
        "blocked": statuses.get("blocked", 0),
        "resolved": statuses.get("resolved", 0),
        "ignored": statuses.get("ignored", 0),
        "unread_notifications": unread,
        "ai_enabled": bool(settings.exception_ai_enabled and manual_ai_enabled),
        "ai_chat_enabled": bool(
            settings.exception_ai_enabled
            and settings.exception_ai_global_enabled
            and settings.exception_ai_chat_enabled
        ),
        "ai_case_analysis_enabled": bool(
            settings.exception_ai_case_analysis_enabled
            and settings.exception_ai_enabled
            and settings.exception_ai_global_enabled
            and settings.exception_ai_chat_enabled
        ),
        "manual_ai_enabled": manual_ai_enabled,
        "scheduled_ai_enabled": bool(policy.is_enabled and policy.scheduled_ai_enabled),
        "full_scan_enabled": bool(policy.is_enabled and policy.full_scan_enabled),
        "digest_enabled": bool(policy.is_enabled and policy.digest_enabled),
        "assigned_to_me": assigned_to_me,
        "mine": assigned_to_me,
        "unassigned": unassigned,
        "overdue": overdue,
        "due_soon": due_soon,
        "actions_enabled": bool(settings.exception_actions_enabled),
        "by_domain": dict(domains),
        "by_severity": dict(severities),
        "by_occurrence": dict(occurrence_types),
    }


def default_policy(db: Session) -> ExceptionPolicy:
    policy = db.scalar(select(ExceptionPolicy).where(ExceptionPolicy.policy_key == "default"))
    if policy is None:
        policy = ExceptionPolicy(
            policy_key="default",
            manual_ai_enabled=False,
            scheduled_ai_enabled=False,
            full_scan_enabled=False,
            digest_enabled=False,
            ai_concurrency=1,
            manual_ai_daily_limit=max(0, settings.exception_manual_ai_daily_limit),
            scheduled_ai_daily_limit=max(0, settings.exception_scheduled_ai_daily_limit),
            scheduled_ai_batch_limit=max(1, settings.exception_scheduled_ai_batch_size),
        )
        db.add(policy)
        db.flush()
    return policy

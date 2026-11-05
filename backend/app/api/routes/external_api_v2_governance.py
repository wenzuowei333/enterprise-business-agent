from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import AuditLog, CrmProject, CustomerMaster, ExternalApiKey, ExternalApiUsageLog
from app.schemas.external_api import (
    ExternalChangeEvent,
    ExternalChangeFeedData,
    ExternalEnvelope,
    ExternalUsageItem,
    ExternalUsageSummaryData,
)
from app.services.external_api_service import (
    apply_external_customer_scope,
    apply_external_project_scope,
    audit_external_request,
    decode_external_cursor,
    encode_external_cursor,
    external_limit,
    external_meta,
    external_permission_enabled,
    external_scope_is_restricted,
    require_external_permission,
)


router = APIRouter(prefix="/api/external/v2", tags=["external-agent-api-v2-governance"])


RESOURCE_PERMISSIONS = {
    "crm_project": "can_read_projects",
    "crm_project_review": "can_read_projects",
    "crm_task": "can_read_tasks",
    "crm_project_task": "can_read_tasks",
    "crm_project_customer_task": "can_read_tasks",
    "work_item": "can_read_tasks",
    "crm_followup": "can_read_followups",
    "approval": "can_read_approvals",
    "approval_instance": "can_read_approvals",
    "customer": "can_read_customers",
    "customer_master": "can_read_customers",
    "customer_business_profile": "can_read_customers",
    "crm_customer_profile": "can_read_customers",
    "customer_portrait": "can_read_judgements",
    "crm_project_insight": "can_read_judgements",
    "product": "can_read_products",
    "product_master": "can_read_products",
    "supplier": "can_read_suppliers",
    "supplier_master": "can_read_suppliers",
    "sales_detail": "can_read_sales_summary",
    "purchase_detail": "can_read_purchase_summary",
    "inventory_snapshot": "can_read_inventory_summary",
    "inventory_check": "can_read_inventory_summary",
    "receivable": "can_read_receivables",
    "account_balance": "can_read_receivables",
    "master_link_issue": "can_read_data_quality",
    "import_batch": "can_read_data_quality",
}

GLOBAL_RESOURCE_TYPES = {
    "product",
    "product_master",
    "supplier",
    "supplier_master",
    "purchase_detail",
    "inventory_snapshot",
    "inventory_check",
    "master_link_issue",
    "import_batch",
}
CUSTOMER_RESOURCE_TYPES = {
    "customer",
    "customer_master",
    "customer_business_profile",
    "crm_customer_profile",
    "customer_portrait",
}
PROJECT_RESOURCE_TYPES = {"crm_project", "crm_project_review"}
FORBIDDEN_FIELD_PARTS = {
    "password",
    "token",
    "hash",
    "secret",
    "raw",
    "payload",
    "result_json",
    "source_json",
    "payment_json",
    "profile_json",
    "quality_json",
}


def _payload_dict(row: AuditLog) -> dict[str, Any]:
    if isinstance(row.after_data, dict):
        return row.after_data
    if isinstance(row.before_data, dict):
        return row.before_data
    return {}


def _nested_value(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        if key in value:
            return value[key]
        for nested in value.values():
            result = _nested_value(nested, key)
            if result is not None:
                return result
    elif isinstance(value, list):
        for nested in value:
            result = _nested_value(nested, key)
            if result is not None:
                return result
    return None


def _int_value(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _event_scope(row: AuditLog) -> tuple[int | None, str | None]:
    payload = _payload_dict(row)
    project_id = _int_value(_nested_value(payload, "project_id"))
    customer_code = _nested_value(payload, "customer_code")
    if row.resource_type in PROJECT_RESOURCE_TYPES and project_id is None:
        project_id = _int_value(row.resource_id)
    if row.resource_type in CUSTOMER_RESOURCE_TYPES and not customer_code:
        customer_code = row.resource_id
    return project_id, str(customer_code) if customer_code else None


def _changed_fields(row: AuditLog) -> list[str]:
    before = row.before_data if isinstance(row.before_data, dict) else {}
    after = row.after_data if isinstance(row.after_data, dict) else {}
    fields = set(before) | set(after)
    return sorted(
        field
        for field in fields
        if not any(part in field.lower() for part in FORBIDDEN_FIELD_PARTS)
    )[:50]


def _event_visible(
    row: AuditLog,
    api_key: ExternalApiKey,
    visible_project_ids: set[int],
    visible_customer_codes: set[str],
) -> tuple[bool, int | None, str | None]:
    permission = RESOURCE_PERMISSIONS.get(row.resource_type)
    if permission is None or not external_permission_enabled(api_key, permission):
        return False, None, None
    project_id, customer_code = _event_scope(row)
    if not external_scope_is_restricted(api_key) or row.resource_type in GLOBAL_RESOURCE_TYPES:
        return True, project_id, customer_code
    if project_id is not None:
        return project_id in visible_project_ids, project_id, customer_code
    if customer_code:
        return customer_code in visible_customer_codes, project_id, customer_code
    return False, project_id, customer_code


@router.get("/changes", response_model=ExternalEnvelope[ExternalChangeFeedData])
def external_v2_changes(
    request: Request,
    cursor: str | None = None,
    resource_type: str | None = None,
    limit: int = 100,
    api_key: ExternalApiKey = Depends(require_external_permission("can_read_changes")),
    db: Session = Depends(get_db),
) -> ExternalEnvelope[ExternalChangeFeedData]:
    limit_value = external_limit(limit)
    parsed_cursor = decode_external_cursor(cursor)
    cursor_id = parsed_cursor[1] if parsed_cursor else 0
    scan_limit = min(max(limit_value * 20, 500), 5000)
    stmt = select(AuditLog).where(
        AuditLog.id > cursor_id,
        AuditLog.action_type != "external_api_read",
    )
    if resource_type:
        stmt = stmt.where(AuditLog.resource_type == resource_type)
    scanned = list(db.scalars(stmt.order_by(AuditLog.id.asc()).limit(scan_limit + 1)).all())
    visible_project_ids = set(db.scalars(apply_external_project_scope(select(CrmProject.id), api_key)).all())
    visible_customer_codes = set(
        db.scalars(apply_external_customer_scope(select(CustomerMaster.customer_code), api_key)).all()
    )
    events: list[ExternalChangeEvent] = []
    last_scanned: AuditLog | None = None
    for row in scanned[:scan_limit]:
        last_scanned = row
        visible, project_id, customer_code = _event_visible(
            row, api_key, visible_project_ids, visible_customer_codes
        )
        if not visible:
            continue
        events.append(
            ExternalChangeEvent(
                change_id=row.id,
                action=row.action_type,
                resource_type=row.resource_type,
                resource_id=row.resource_id,
                project_id=project_id,
                customer_code=customer_code,
                changed_fields=_changed_fields(row),
                deleted=any(value in row.action_type.lower() for value in ("delete", "remove", "revoke")),
                occurred_at=row.created_at,
            )
        )
        if len(events) > limit_value:
            break
    has_more = len(events) > limit_value or len(scanned) > scan_limit
    items = events[:limit_value]
    if len(events) > limit_value:
        last_visible_id = items[-1].change_id
        last_scanned = next(row for row in scanned if row.id == last_visible_id)
    next_cursor = (
        encode_external_cursor(last_scanned.created_at, last_scanned.id)
        if has_more and last_scanned is not None
        else None
    )
    audit_external_request(db, request, api_key, "/changes", {"count": len(items)})
    return ExternalEnvelope(
        data=ExternalChangeFeedData(items=items, count=len(items)),
        meta=external_meta(request, next_cursor=next_cursor, has_more=has_more),
    )


@router.get("/usage", response_model=ExternalEnvelope[ExternalUsageSummaryData])
def external_v2_usage(
    request: Request,
    limit: int = 20,
    api_key: ExternalApiKey = Depends(require_external_permission("can_read_audit_summary")),
    db: Session = Depends(get_db),
) -> ExternalEnvelope[ExternalUsageSummaryData]:
    limit_value = external_limit(limit, maximum=100)
    current_usage_id = getattr(request.state, "external_usage_log_id", None)
    if current_usage_id is not None:
        current = db.get(ExternalApiUsageLog, current_usage_id)
        if current is not None:
            current.status_code = 200
            db.flush()
    now = datetime.now(timezone.utc)
    minute_start = now.replace(second=0, microsecond=0)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    minute_count = db.scalar(
        select(func.count(ExternalApiUsageLog.id)).where(
            ExternalApiUsageLog.key_id == api_key.key_id,
            ExternalApiUsageLog.created_at >= minute_start,
        )
    ) or 0
    day_conditions = (
        ExternalApiUsageLog.key_id == api_key.key_id,
        ExternalApiUsageLog.created_at >= day_start,
    )
    day_count = db.scalar(select(func.count(ExternalApiUsageLog.id)).where(*day_conditions)) or 0
    success_count = db.scalar(
        select(func.count(ExternalApiUsageLog.id)).where(
            *day_conditions,
            ExternalApiUsageLog.status_code >= 200,
            ExternalApiUsageLog.status_code < 400,
        )
    ) or 0
    error_count = db.scalar(
        select(func.count(ExternalApiUsageLog.id)).where(
            *day_conditions,
            ExternalApiUsageLog.status_code >= 400,
        )
    ) or 0
    recent = list(
        db.scalars(
            select(ExternalApiUsageLog)
            .where(*day_conditions)
            .order_by(ExternalApiUsageLog.id.desc())
            .limit(limit_value)
        ).all()
    )
    data = ExternalUsageSummaryData(
        minute_count=int(minute_count),
        minute_limit=api_key.rate_limit_per_minute,
        day_count=int(day_count),
        day_limit=api_key.daily_request_limit,
        success_count=int(success_count),
        error_count=int(error_count),
        recent=[
            ExternalUsageItem(
                request_id=row.request_id,
                endpoint=row.endpoint,
                method=row.method,
                status_code=row.status_code,
                duration_ms=row.duration_ms,
                response_count=row.response_count,
                created_at=row.created_at,
            )
            for row in recent
        ],
        calculated_at=now,
    )
    audit_external_request(db, request, api_key, "/usage", {"count": len(recent)})
    return ExternalEnvelope(data=data, meta=external_meta(request))

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.api.routes.crm_projects import (
    create_crm_followup_approval_draft,
    list_crm_linked_customers_page,
    list_crm_tasks_page,
    update_crm_linked_customer_profile,
)
from app.api.routes.crm_leads import _scoped_lead, create_lead_followup, list_leads
from app.core.config import settings
from app.core.database import get_db
from app.models import AuditLog, CrmLeadFollowup, CrmProject, CustomerMaster, MobileOperationLog, MobileSession, User
from app.schemas.crm import CrmFollowupApprovalDraftCreate
from app.schemas.crm import CrmLeadFollowupCreate, CrmLeadFollowupPublic
from app.schemas.master_data import CustomerMasterUpdate
from app.schemas.mobile import (
    MobileDevicePublic,
    MobileNotificationPreferencesUpdate,
    MobileSyncOperation,
    MobileSyncOperationBatch,
    MobileSyncOperationResult,
)
from app.services.audit_service import write_audit_log
from app.services.mobile_sync_service import (
    current_mobile_scope_revision,
    is_newer_than_cursor,
    mobile_operation_payload_hash,
    mobile_scope_revision,
    normalize_mobile_operation_payload,
    parse_sync_cursor,
)
from app.services.permission_service import get_final_permission_codes, has_permission


router = APIRouter(prefix="/mobile", tags=["mobile-round4"])
LEAD_FOLLOWUP_OPERATION_ACTION = "crm_lead_followup_create"


def _all_linked_customers(db: Session, current_user: User) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    offset = 0
    while offset < 5000:
        page = list_crm_linked_customers_page(
            limit=50,
            offset=offset,
            db=db,
            current_user=current_user,
        )
        batch = jsonable_encoder(page.items)
        items.extend(batch)
        offset += len(batch)
        if not batch or offset >= page.total:
            break
    return items


def _all_tasks(db: Session, current_user: User) -> list[dict[str, Any]]:
    if not has_permission(db, current_user, "crm_task.view"):
        return []
    items: list[dict[str, Any]] = []
    offset = 0
    while offset < 5000:
        page = list_crm_tasks_page(
            limit=50,
            offset=offset,
            db=db,
            current_user=current_user,
        )
        batch = jsonable_encoder(page.items)
        items.extend(batch)
        offset += len(batch)
        if not batch or offset >= page.total:
            break
    project_ids = {int(item["project_id"]) for item in items if item.get("project_id") is not None}
    projects = {
        row.id: row
        for row in db.scalars(select(CrmProject).where(CrmProject.id.in_(project_ids))).all()
    } if project_ids else {}
    for item in items:
        project = projects.get(item.get("project_id"))
        if project is not None:
            item["project_name"] = project.project_name
            item["project_code"] = project.project_code
            item["project_status"] = project.status
    return items


def _all_leads(db: Session, current_user: User) -> list[dict[str, Any]]:
    if not has_permission(db, current_user, "crm_lead.view"):
        return []
    items: list[dict[str, Any]] = []
    offset = 0
    while offset < 5000:
        page = list_leads(limit=50, offset=offset, db=db, current_user=current_user)
        batch = jsonable_encoder(page.items)
        items.extend(batch)
        offset += len(batch)
        if not batch or offset >= page.total:
            break
    return items


def _require_mobile_lead_offline() -> None:
    if not (settings.mobile_feature_lead_pool and settings.mobile_feature_lead_offline):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mobile lead offline feature is unavailable")


def _mobile_lead_operation_history_enabled() -> bool:
    return settings.mobile_feature_lead_pool and settings.mobile_feature_lead_offline


def _mobile_lead_followup_no(operation: MobileSyncOperation, current_user: User) -> str:
    value = f"{current_user.id}:{operation.device_id}:{operation.client_operation_id}"
    return f"MOBLF-{hashlib.sha256(value.encode('utf-8')).hexdigest()[:24].upper()}"


def _existing_mobile_lead_followup(
    operation: MobileSyncOperation,
    *,
    db: Session,
    current_user: User,
) -> CrmLeadFollowup | None:
    try:
        lead_id = int(operation.resource_id or operation.payload.get("lead_id"))
    except (TypeError, ValueError):
        return None
    return db.scalar(
        select(CrmLeadFollowup).where(
            CrmLeadFollowup.lead_id == lead_id,
            CrmLeadFollowup.created_by_user_id == current_user.id,
            CrmLeadFollowup.followup_no == _mobile_lead_followup_no(operation, current_user),
        )
    )


def _mobile_lead_followup_result(followup: CrmLeadFollowup) -> tuple[str, str, dict[str, Any]]:
    public = CrmLeadFollowupPublic.model_validate(followup)
    return "crm_lead_followup", str(followup.id), jsonable_encoder(public)


def _finalize_operation(
    row: MobileOperationLog,
    *,
    status_value: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    result: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    db: Session,
) -> MobileSyncOperationResult:
    row.status = status_value
    if resource_type is not None:
        row.resource_type = resource_type
    if resource_id is not None:
        row.resource_id = resource_id
    row.result_json = result
    row.error_json = error
    row.applied_at = datetime.now(timezone.utc) if status_value == "applied" else None
    db.commit()
    return _existing_operation_result(row)


def _mobile_device_public(row: MobileSession, current_device_id: str | None = None) -> MobileDevicePublic:
    return MobileDevicePublic(
        id=row.id,
        device_id=row.device_id,
        device_name=row.device_name,
        app_version=row.app_version,
        android_version=row.android_version,
        device_model=row.device_model,
        last_used_at=row.last_used_at,
        last_sync_at=row.last_sync_at,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        is_current=bool(current_device_id and row.device_id == current_device_id),
        notification_preferences={
            "approval": True,
            "task": True,
            "risk": True,
            **(row.notification_preferences_json or {}),
        },
    )


@router.get("/sync/pull")
def mobile_sync_pull(
    cursor: str | None = None,
    client_scope_revision: str | None = Query(default=None, alias="scope_revision"),
    device_id: str | None = Query(default=None, max_length=160),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    permissions = get_final_permission_codes(db, current_user)
    lead_pool_enabled = settings.mobile_feature_lead_pool
    scope_revision = current_mobile_scope_revision(
        db,
        current_user,
        permissions,
        include_leads=lead_pool_enabled,
    )
    full_snapshot = not cursor or client_scope_revision != scope_revision
    parsed_cursor = None if full_snapshot else parse_sync_cursor(cursor)
    if cursor and not full_snapshot and parsed_cursor is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="同步游标格式无效")

    all_customers = _all_linked_customers(db, current_user)
    all_tasks = _all_tasks(db, current_user)
    all_leads = _all_leads(db, current_user) if lead_pool_enabled else []
    customers = all_customers
    tasks = all_tasks
    leads = all_leads
    if not full_snapshot and parsed_cursor is not None:
        customers = [
            item
            for item in customers
            if is_newer_than_cursor(item.get("customer_updated_at"), parsed_cursor)
            or is_newer_than_cursor(item.get("last_activity_at"), parsed_cursor)
            or is_newer_than_cursor(item.get("profile_updated_at"), parsed_cursor)
        ]
        tasks = [item for item in tasks if is_newer_than_cursor(item.get("updated_at"), parsed_cursor)]
        leads = [item for item in leads if is_newer_than_cursor(item.get("updated_at"), parsed_cursor)]

    now = datetime.now(timezone.utc)
    if device_id:
        session = db.scalar(
            select(MobileSession).where(
                MobileSession.user_id == current_user.id,
                MobileSession.device_id == device_id,
                MobileSession.revoked_at.is_(None),
            )
        )
        if session is not None:
            session.last_sync_at = now
            db.commit()

    return {
        "next_cursor": now.isoformat(),
        "scope_revision": scope_revision,
        "server_time": now.isoformat(),
        "full_snapshot": full_snapshot,
        "upserts": {"customers": customers, "tasks": tasks, "leads": leads},
        "deletions": {"customers": [], "tasks": [], "leads": []},
        "authoritative_keys": {
            "customers": [item.get("customer_code") for item in all_customers] if full_snapshot else [],
            "tasks": [str(item.get("id")) for item in all_tasks] if full_snapshot else [],
            "leads": [str(item.get("id")) for item in all_leads] if full_snapshot else [],
        },
        "dictionary": {
            "task_statuses": ["not_started", "in_progress", "need_support", "blocked", "closed"],
            "operation_statuses": ["applied", "conflict", "rejected", "retryable_error", "processing"],
        },
    }


def _existing_operation_result(row: MobileOperationLog) -> MobileSyncOperationResult:
    return MobileSyncOperationResult(
        client_operation_id=row.client_operation_id,
        status=row.status,
        resource_type=row.resource_type,
        resource_id=row.resource_id,
        result=row.result_json,
        error=row.error_json,
    )


def _customer_profile_conflicts(db: Session, operation: MobileSyncOperation) -> list[dict[str, Any]]:
    customer_code = operation.resource_id or str(operation.payload.get("customer_code") or "")
    customer = db.scalar(select(CustomerMaster).where(CustomerMaster.customer_code == customer_code))
    if customer is None or operation.base_updated_at is None or customer.updated_at is None:
        return []
    server_updated_at = customer.updated_at if customer.updated_at.tzinfo else customer.updated_at.replace(tzinfo=timezone.utc)
    base_updated_at = operation.base_updated_at if operation.base_updated_at.tzinfo else operation.base_updated_at.replace(tzinfo=timezone.utc)
    if server_updated_at <= base_updated_at:
        return []
    changes = dict(operation.payload.get("changes") or operation.payload.get("profile") or {})
    base_values = dict(operation.payload.get("base_values") or {})
    conflicts: list[dict[str, Any]] = []
    for field, local_value in changes.items():
        server_value = getattr(customer, field, None)
        if field not in base_values or jsonable_encoder(server_value) != jsonable_encoder(base_values[field]):
            conflicts.append(
                {
                    "field": field,
                    "local_value": local_value,
                    "server_value": jsonable_encoder(server_value),
                    "base_value": base_values.get(field),
                    "server_updated_at": server_updated_at.isoformat(),
                }
            )
    return conflicts


def _apply_operation(
    operation: MobileSyncOperation,
    *,
    request: Request,
    db: Session,
    current_user: User,
) -> tuple[str, str | None, dict[str, Any]]:
    if operation.action_type == LEAD_FOLLOWUP_OPERATION_ACTION:
        _require_mobile_lead_offline()
        if not has_permission(db, current_user, "crm_lead.edit"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing CRM permission: crm_lead.edit")
        try:
            lead_id = int(operation.resource_id or operation.payload.get("lead_id"))
        except (TypeError, ValueError):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Server lead ID is required for offline followup") from None
        _scoped_lead(db, current_user, lead_id)
        followup_data = dict(operation.payload.get("followup") or operation.payload)
        followup_data.pop("lead_id", None)
        followup_data["followup_no"] = _mobile_lead_followup_no(operation, current_user)
        existing_followup = _existing_mobile_lead_followup(operation, db=db, current_user=current_user)
        if existing_followup is not None:
            return _mobile_lead_followup_result(existing_followup)
        followup = create_lead_followup(
            lead_id=lead_id,
            payload=CrmLeadFollowupCreate.model_validate(followup_data),
            request=request,
            db=db,
            current_user=current_user,
        )
        return _mobile_lead_followup_result(followup)

    if operation.action_type in {"followup.create", "support.create"}:
        payload_data = dict(operation.payload)
        if operation.action_type == "support.create":
            followup = dict(payload_data.get("followup") or {})
            followup["need_support"] = True
            payload_data["followup"] = followup
        payload = CrmFollowupApprovalDraftCreate.model_validate(payload_data)
        approval = create_crm_followup_approval_draft(
            payload=payload,
            request=request,
            db=db,
            current_user=current_user,
        )
        return "approval_instance", str(approval.id), {
            "approval_id": approval.id,
            "approval_no": approval.approval_no,
            "status": approval.status,
        }

    if operation.action_type == "customer_profile.patch":
        customer_code = operation.resource_id or str(operation.payload.get("customer_code") or "")
        if not customer_code:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="客户编号不能为空")
        conflicts = _customer_profile_conflicts(db, operation)
        if conflicts:
            return "customer_master", customer_code, {"conflicts": conflicts}
        changes = operation.payload.get("changes") or operation.payload.get("profile") or {}
        result = update_crm_linked_customer_profile(
            customer_code=customer_code,
            payload=CustomerMasterUpdate.model_validate(changes),
            request=request,
            db=db,
            current_user=current_user,
        )
        return "customer_master", customer_code, jsonable_encoder(result)

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不支持的移动同步操作")


def _process_operation(
    operation: MobileSyncOperation,
    *,
    request: Request,
    db: Session,
    current_user: User,
) -> MobileSyncOperationResult:
    if operation.action_type == LEAD_FOLLOWUP_OPERATION_ACTION:
        _require_mobile_lead_offline()

    request_payload = operation.model_dump(mode="json")
    payload_hash = mobile_operation_payload_hash(request_payload)
    existing = db.scalar(
        select(MobileOperationLog).where(
            MobileOperationLog.user_id == current_user.id,
            MobileOperationLog.device_id == operation.device_id,
            MobileOperationLog.client_operation_id == operation.client_operation_id,
        )
    )
    if existing is not None:
        if existing.payload_hash != payload_hash:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="相同操作编号对应的提交内容不一致")
        if existing.status != "processing" or operation.action_type != LEAD_FOLLOWUP_OPERATION_ACTION:
            return _existing_operation_result(existing)
        row = existing
    else:
        row = MobileOperationLog(
            user_id=current_user.id,
            device_id=operation.device_id,
            client_operation_id=operation.client_operation_id,
            action_type=operation.action_type,
            payload_hash=payload_hash,
            status="processing",
            resource_type=operation.resource_type,
            resource_id=operation.resource_id,
            request_json=request_payload,
        )
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            existing = db.scalar(
                select(MobileOperationLog).where(
                    MobileOperationLog.user_id == current_user.id,
                    MobileOperationLog.device_id == operation.device_id,
                    MobileOperationLog.client_operation_id == operation.client_operation_id,
                )
            )
            if existing is None:
                raise
            if existing.payload_hash != payload_hash:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="相同操作编号对应的提交内容不一致")
            if existing.status != "processing" or operation.action_type != LEAD_FOLLOWUP_OPERATION_ACTION:
                return _existing_operation_result(existing)
            row = existing

    try:
        resource_type, resource_id, result = _apply_operation(
            operation,
            request=request,
            db=db,
            current_user=current_user,
        )
        return _finalize_operation(
            row,
            status_value="conflict" if result.get("conflicts") else "applied",
            resource_type=resource_type,
            resource_id=resource_id,
            result=result,
            db=db,
        )
    except HTTPException as exc:
        db.rollback()
        recovered = _existing_mobile_lead_followup(operation, db=db, current_user=current_user)
        if operation.action_type == LEAD_FOLLOWUP_OPERATION_ACTION and recovered is not None:
            resource_type, resource_id, result = _mobile_lead_followup_result(recovered)
            return _finalize_operation(
                row,
                status_value="applied",
                resource_type=resource_type,
                resource_id=resource_id,
                result=result,
                db=db,
            )
        return _finalize_operation(
            row,
            status_value="rejected" if 400 <= exc.status_code < 500 else "retryable_error",
            error={"code": f"http_{exc.status_code}", "message": str(exc.detail)},
            db=db,
        )
    except Exception:
        db.rollback()
        recovered = _existing_mobile_lead_followup(operation, db=db, current_user=current_user)
        if operation.action_type == LEAD_FOLLOWUP_OPERATION_ACTION and recovered is not None:
            resource_type, resource_id, result = _mobile_lead_followup_result(recovered)
            return _finalize_operation(
                row,
                status_value="applied",
                resource_type=resource_type,
                resource_id=resource_id,
                result=result,
                db=db,
            )
        return _finalize_operation(
            row,
            status_value="retryable_error",
            error={"code": "sync_failed", "message": "同步失败，请稍后重试"},
            db=db,
        )


@router.post("/sync/operations")
def mobile_sync_operations(
    payload: MobileSyncOperationBatch,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    results = [
        _process_operation(operation, request=request, db=db, current_user=current_user)
        for operation in payload.operations
    ]
    return {"items": [item.model_dump(mode="json") for item in results], "total": len(results)}


@router.get("/sync/status")
def mobile_sync_status(
    device_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    stmt = select(MobileOperationLog).where(MobileOperationLog.user_id == current_user.id)
    if not _mobile_lead_operation_history_enabled():
        stmt = stmt.where(MobileOperationLog.action_type != LEAD_FOLLOWUP_OPERATION_ACTION)
    if device_id:
        stmt = stmt.where(MobileOperationLog.device_id == device_id)
    rows = list(db.scalars(stmt.order_by(MobileOperationLog.id.desc()).limit(100)).all())
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    return {
        "counts": counts,
        "latest": [jsonable_encoder(_existing_operation_result(row)) for row in rows[:20]],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/operations/summary")
def mobile_operations_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    stmt = select(MobileOperationLog.status, func.count(MobileOperationLog.id)).where(
        MobileOperationLog.user_id == current_user.id
    )
    if not _mobile_lead_operation_history_enabled():
        stmt = stmt.where(MobileOperationLog.action_type != LEAD_FOLLOWUP_OPERATION_ACTION)
    rows = db.execute(stmt.group_by(MobileOperationLog.status)).all()
    return {"counts": {status_value: int(count) for status_value, count in rows}}


@router.get("/operations/{client_operation_id}")
def mobile_operation_detail(
    client_operation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MobileSyncOperationResult:
    stmt = select(MobileOperationLog).where(
        MobileOperationLog.user_id == current_user.id,
        MobileOperationLog.client_operation_id == client_operation_id,
    )
    if not _mobile_lead_operation_history_enabled():
        stmt = stmt.where(MobileOperationLog.action_type != LEAD_FOLLOWUP_OPERATION_ACTION)
    row = db.scalar(stmt)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="同步操作不存在")
    return _existing_operation_result(row)


@router.get("/devices")
def mobile_devices(
    current_device_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    rows = list(
        db.scalars(
            select(MobileSession)
            .where(MobileSession.user_id == current_user.id)
            .order_by(MobileSession.revoked_at.asc().nullsfirst(), MobileSession.last_used_at.desc().nullslast())
        ).all()
    )
    return {
        "items": [item.model_dump(mode="json") for item in (_mobile_device_public(row, current_device_id) for row in rows)],
        "total": len(rows),
    }


@router.delete("/devices/{session_id}")
def mobile_revoke_device(
    session_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    row = db.scalar(
        select(MobileSession).where(
            MobileSession.id == session_id,
            MobileSession.user_id == current_user.id,
        )
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="设备会话不存在")
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
    write_audit_log(
        db,
        action_type="mobile_revoke_device",
        resource_type="mobile_session",
        resource_id=str(row.id),
        user=current_user,
        request=request,
        after_data={"device_id": row.device_id, "device_name": row.device_name},
    )
    db.commit()
    return {"status": "revoked", "session_id": row.id}


@router.patch("/devices/{session_id}/notifications")
def mobile_update_notification_preferences(
    session_id: int,
    payload: MobileNotificationPreferencesUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MobileDevicePublic:
    row = db.scalar(
        select(MobileSession).where(
            MobileSession.id == session_id,
            MobileSession.user_id == current_user.id,
            MobileSession.revoked_at.is_(None),
        )
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="设备会话不存在")
    row.notification_preferences_json = payload.model_dump()
    db.commit()
    db.refresh(row)
    return _mobile_device_public(row)


def _percentile(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return int(ordered[index])


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


@router.get("/admin/operations/overview")
def mobile_admin_operations_overview(
    days: int = Query(default=7, ge=1, le=30),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    if current_user.role != "admin" and not has_permission(db, current_user, "settings.view"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权查看移动端运维数据")
    since = datetime.now(timezone.utc) - timedelta(days=days)
    sessions = list(db.scalars(select(MobileSession).where(MobileSession.created_at >= since)).all())
    active_sessions = [
        row
        for row in sessions
        if row.revoked_at is None and _aware(row.last_used_at or row.created_at) >= since
    ]
    version_distribution: dict[str, int] = {}
    for row in active_sessions:
        key = row.app_version or "未知版本"
        version_distribution[key] = version_distribution.get(key, 0) + 1

    operation_rows = list(
        db.scalars(
            select(MobileOperationLog)
            .where(MobileOperationLog.created_at >= since)
            .order_by(MobileOperationLog.id.desc())
        ).all()
    )
    operation_counts: dict[str, int] = {}
    for row in operation_rows:
        operation_counts[row.status] = operation_counts.get(row.status, 0) + 1
    terminal_total = sum(operation_counts.get(key, 0) for key in ("applied", "conflict", "rejected", "retryable_error"))
    sync_success_rate = round(operation_counts.get("applied", 0) * 100 / terminal_total, 2) if terminal_total else 100.0

    telemetry_logs = list(
        db.scalars(
            select(AuditLog)
            .where(AuditLog.action_type == "mobile_client_telemetry", AuditLog.created_at >= since)
            .order_by(AuditLog.id.desc())
            .limit(1000)
        ).all()
    )
    event_counts: dict[str, int] = {}
    error_codes: dict[str, int] = {}
    durations: list[int] = []
    recent_errors: list[dict[str, Any]] = []
    for log in telemetry_logs:
        payload = log.after_data if isinstance(log.after_data, dict) else {}
        for event in payload.get("events", []) if isinstance(payload.get("events"), list) else []:
            if not isinstance(event, dict):
                continue
            event_type = str(event.get("event_type") or "unknown")
            event_counts[event_type] = event_counts.get(event_type, 0) + 1
            if isinstance(event.get("duration_ms"), int):
                durations.append(int(event["duration_ms"]))
            code = str(event.get("code") or "")
            if code:
                error_codes[code] = error_codes.get(code, 0) + 1
            if event_type in {"crash", "api_error", "upload_error"} and len(recent_errors) < 20:
                recent_errors.append(
                    {
                        "event_type": event_type,
                        "code": code or None,
                        "route": event.get("route"),
                        "request_id": event.get("request_id"),
                        "app_version": event.get("app_version"),
                        "occurred_at": event.get("occurred_at"),
                    }
                )

    return {
        "days": days,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "active_devices": len(active_sessions),
        "total_sessions": len(sessions),
        "version_distribution": version_distribution,
        "operations": operation_counts,
        "sync_success_rate": sync_success_rate,
        "pending_operations": operation_counts.get("processing", 0),
        "conflicts": operation_counts.get("conflict", 0),
        "telemetry": {
            "event_counts": event_counts,
            "error_codes": error_codes,
            "api_p50_ms": _percentile(durations, 0.50),
            "api_p95_ms": _percentile(durations, 0.95),
            "recent_errors": recent_errors,
        },
        "latest_operations": [
            {
                "id": row.id,
                "action_type": row.action_type,
                "status": row.status,
                "resource_type": row.resource_type,
                "resource_id": row.resource_id,
                "device_id": row.device_id,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in operation_rows[:20]
        ],
    }


@router.get("/admin/devices")
def mobile_admin_devices(
    q: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅管理员可管理移动设备会话")
    stmt = select(MobileSession, User).join(User, User.id == MobileSession.user_id)
    if q and q.strip():
        keyword = f"%{q.strip()}%"
        stmt = stmt.where(
            User.username.ilike(keyword)
            | User.real_name.ilike(keyword)
            | MobileSession.device_name.ilike(keyword)
            | MobileSession.device_model.ilike(keyword)
        )
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = int(db.scalar(count_stmt) or 0)
    rows = db.execute(
        stmt.order_by(MobileSession.revoked_at.asc().nullsfirst(), MobileSession.last_used_at.desc().nullslast())
        .offset(offset)
        .limit(limit)
    ).all()
    return {
        "items": [
            {
                **_mobile_device_public(session).model_dump(mode="json"),
                "user_id": user.id,
                "username": user.username,
                "user_label": user.real_name or user.username,
            }
            for session, user in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.delete("/admin/devices/{session_id}")
def mobile_admin_revoke_device(
    session_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅管理员可管理移动设备会话")
    row = db.get(MobileSession, session_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="设备会话不存在")
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
    write_audit_log(
        db,
        action_type="admin_revoke_mobile_device",
        resource_type="mobile_session",
        resource_id=str(row.id),
        user=current_user,
        request=request,
        after_data={"target_user_id": row.user_id, "device_id": row.device_id, "device_name": row.device_name},
    )
    db.commit()
    return {"status": "revoked", "session_id": row.id}


__all__ = [
    "mobile_scope_revision",
    "normalize_mobile_operation_payload",
    "router",
]

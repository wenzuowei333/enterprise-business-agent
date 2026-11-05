from __future__ import annotations

import hashlib
import ipaddress
import base64
import binascii
import json
import uuid
from datetime import datetime, timedelta, timezone
from time import perf_counter
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import String, and_, cast, func, or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import (
    CrmFollowup,
    CrmProject,
    CrmProjectCustomerTask,
    CustomerMaster,
    ExternalApiKey,
    ExternalApiUsageLog,
    WorkItem,
)
from app.schemas.external_api import ExternalResponseMeta
from app.services.audit_service import write_audit_log


EXTERNAL_PERMISSION_LABELS = {
    "can_read_projects": ("projects.read", "projects", "读取项目及项目进展"),
    "can_read_customers": ("customers.read", "customers", "读取授权客户资料"),
    "can_read_followups": ("followups.read", "followups", "读取授权跟进记录"),
    "can_read_judgements": ("judgements.read", "judgements", "读取授权画像与业务判断"),
    "can_read_tasks": ("tasks.read", "tasks", "读取授权客户任务"),
    "can_read_approvals": ("approvals.read", "approvals", "读取授权审批摘要"),
    "can_read_audit_summary": ("usage.read", "usage", "读取当前凭证调用摘要"),
    "can_read_products": ("products.read", "products", "读取安全商品主数据"),
    "can_read_suppliers": ("suppliers.read", "suppliers", "读取安全供应商主数据"),
    "can_read_sales_summary": ("sales.summary.read", "sales", "读取授权客户销售汇总"),
    "can_read_purchase_summary": ("purchases.summary.read", "purchases", "读取采购汇总"),
    "can_read_inventory_summary": ("inventory.summary.read", "inventory", "读取库存汇总"),
    "can_read_receivables": ("receivables.summary.read", "receivables", "读取授权客户应收汇总"),
    "can_read_data_quality": ("data_quality.read", "data_quality", "读取数据质量汇总"),
    "can_read_changes": ("changes.read", "changes", "读取授权资源变更事件"),
    "can_read_inventory_anomalies": ("inventory.anomalies.read", "inventory", "读取库存异常案件"),
    "can_read_inventory_evidence": ("inventory.evidence.read", "inventory", "读取库存异常证据包"),
    "can_read_sales_details_sensitive": ("sales.details.read_sensitive", "sales", "读取销售敏感经营明细"),
    "can_read_purchase_details_sensitive": ("purchases.details.read_sensitive", "purchases", "读取采购敏感经营明细"),
    "can_read_inventory_checks": ("inventory.checks.read", "inventory", "读取库存核验明细"),
    "can_read_imports": ("imports.read", "imports", "读取导入批次与错误"),
    "can_write_inventory_diagnoses": ("inventory.diagnoses.write", "inventory", "提交库存异常诊断"),
    "can_validate_inventory_actions": ("inventory.actions.validate", "inventory", "预演库存修复动作"),
    "can_execute_inventory_rebuild": ("inventory.actions.execute.rebuild", "inventory", "执行可逆库存重算"),
    "can_execute_inventory_upstream": ("inventory.actions.execute.upstream", "inventory", "执行上游库存修复"),
    "can_read_inventory_action_status": ("inventory.actions.status.read", "inventory", "读取库存修复动作状态"),
}

EXTERNAL_CUSTOMER_FIELD_OPTIONS = {
    "customer_code",
    "customer_name",
    "customer_short_name",
    "customer_type",
    "region",
    "salesperson_employee_code",
    "salesperson_name",
    "contact_name",
    "contact_phone",
    "contact_channel",
    "customer_group_name",
    "customer_tags",
    "customer_tag_profile",
    "address",
    "status",
    "source",
    "profile_updated_at",
    "base_remark",
}


def external_now() -> datetime:
    return datetime.now(timezone.utc)


def external_request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or request.headers.get("x-request-id") or uuid.uuid4().hex


def external_meta(request: Request, *, next_cursor: str | None = None, has_more: bool | None = None) -> ExternalResponseMeta:
    return ExternalResponseMeta(
        request_id=external_request_id(request),
        generated_at=external_now(),
        next_cursor=next_cursor,
        has_more=has_more,
    )


def hash_external_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def external_token_from_request(request: Request) -> str | None:
    auth_header = request.headers.get("authorization") or ""
    if auth_header.lower().startswith("bearer "):
        return auth_header.split(" ", 1)[1].strip()
    api_key = request.headers.get("x-api-key")
    return api_key.strip() if api_key else None


def ip_allowed(client_ip: str | None, allowed_entries: list[str] | None) -> bool:
    entries = [str(item).strip() for item in (allowed_entries or []) if str(item).strip()]
    if not entries:
        return True
    if not client_ip:
        return False
    for entry in entries:
        if client_ip == entry:
            return True
        try:
            if ipaddress.ip_address(client_ip) in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            continue
    return False


def scope_project_ids(api_key: ExternalApiKey) -> list[int]:
    values: list[int] = []
    for value in api_key.scope_project_ids or []:
        try:
            values.append(int(value))
        except (TypeError, ValueError):
            continue
    return list(dict.fromkeys(values))


def allowed_customer_fields(api_key: ExternalApiKey) -> list[str]:
    fields = [str(value) for value in (api_key.allowed_customer_fields or []) if str(value) in EXTERNAL_CUSTOMER_FIELD_OPTIONS]
    for required in ("customer_name", "customer_code"):
        if required not in fields:
            fields.insert(0, required)
    return list(dict.fromkeys(fields))


def external_permissions(api_key: ExternalApiKey) -> dict[str, bool]:
    return {code: external_permission_enabled(api_key, code) for code in EXTERNAL_PERMISSION_LABELS}


def external_permission_enabled(api_key: ExternalApiKey, permission: str) -> bool:
    scopes = api_key.permission_scopes
    if isinstance(scopes, list):
        capability = EXTERNAL_PERMISSION_LABELS[permission][0]
        return capability in {str(value) for value in scopes}
    return bool(getattr(api_key, permission, False))


def external_permission_scopes(api_key: ExternalApiKey) -> list[str]:
    return [
        EXTERNAL_PERMISSION_LABELS[permission][0]
        for permission in EXTERNAL_PERMISSION_LABELS
        if external_permission_enabled(api_key, permission)
    ]


def require_external_key(request: Request, db: Session) -> ExternalApiKey:
    token = external_token_from_request(request)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing external API key")
    now = external_now()
    token_hash = hash_external_token(token)
    row = db.scalar(
        select(ExternalApiKey).where(
            or_(
                ExternalApiKey.key_hash == token_hash,
                and_(
                    ExternalApiKey.previous_key_hash == token_hash,
                    ExternalApiKey.previous_key_expires_at.is_not(None),
                    ExternalApiKey.previous_key_expires_at > now,
                ),
            )
        ).with_for_update()
    )
    if row is None or not row.active or row.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid external API key")
    if row.expires_at is not None and row.expires_at <= now:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Expired external API key")
    client_ip = request.client.host if request.client else None
    if not ip_allowed(client_ip, row.allowed_ips):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Client IP is not allowed")
    minute_start = now.replace(second=0, microsecond=0)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    minute_count = db.scalar(
        select(func.count(ExternalApiUsageLog.id)).where(
            ExternalApiUsageLog.key_id == row.key_id,
            ExternalApiUsageLog.created_at >= minute_start,
        )
    ) or 0
    day_count = db.scalar(
        select(func.count(ExternalApiUsageLog.id)).where(
            ExternalApiUsageLog.key_id == row.key_id,
            ExternalApiUsageLog.created_at >= day_start,
        )
    ) or 0
    if minute_count >= row.rate_limit_per_minute:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="External API minute quota exceeded",
            headers={"Retry-After": "60"},
        )
    if day_count >= row.daily_request_limit:
        retry_seconds = max(1, int(((day_start + timedelta(days=1)) - now).total_seconds()))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="External API daily quota exceeded",
            headers={"Retry-After": str(retry_seconds)},
        )
    row.last_used_at = now
    row.last_used_ip = client_ip
    usage = ExternalApiUsageLog(
        key_id=row.key_id,
        request_id=external_request_id(request),
        endpoint=request.url.path,
        method=request.method,
        client_ip=client_ip,
        user_agent=request.headers.get("user-agent"),
        # Keep quota accounting on the same clock as the request window. This
        # avoids boundary races between application time and DB server time.
        created_at=now,
    )
    db.add(usage)
    db.commit()
    db.refresh(usage)
    db.refresh(row)
    request.state.external_usage_log_id = usage.id
    request.state.external_usage_started_at = perf_counter()
    request.state.external_usage_db = db
    return row


def external_key_dependency(request: Request, db: Session = Depends(get_db)) -> ExternalApiKey:
    return require_external_key(request, db)


def require_external_permission(permission: str):
    if permission not in EXTERNAL_PERMISSION_LABELS:
        raise ValueError(f"Unknown external API permission: {permission}")

    def dependency(api_key: ExternalApiKey = Depends(external_key_dependency)) -> ExternalApiKey:
        if not external_permission_enabled(api_key, permission):
            code = EXTERNAL_PERMISSION_LABELS[permission][0]
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"API key lacks {code}")
        return api_key

    return dependency


def audit_external_request(
    db: Session,
    request: Request,
    api_key: ExternalApiKey,
    endpoint: str,
    detail: dict[str, Any] | None = None,
    *,
    action_type: str = "external_api_read",
) -> None:
    write_audit_log(
        db,
        action_type=action_type,
        resource_type="external_api",
        resource_id=api_key.key_id,
        request=request,
        after_data={"endpoint": endpoint, "request_id": external_request_id(request), **(detail or {})},
    )
    usage_id = getattr(request.state, "external_usage_log_id", None)
    if usage_id is not None and detail and "count" in detail:
        usage = db.get(ExternalApiUsageLog, usage_id)
        if usage is not None:
            usage.response_count = int(detail["count"])
    db.commit()


def finalize_external_usage(request: Request, status_code: int) -> None:
    usage_id = getattr(request.state, "external_usage_log_id", None)
    db = getattr(request.state, "external_usage_db", None)
    if usage_id is None or db is None:
        return
    try:
        usage = db.get(ExternalApiUsageLog, usage_id)
        if usage is None:
            return
        usage.status_code = int(status_code)
        started_at = getattr(request.state, "external_usage_started_at", None)
        if started_at is not None:
            usage.duration_ms = max(0, int((perf_counter() - started_at) * 1000))
        db.commit()
    except Exception:
        db.rollback()


def external_limit(value: int, *, maximum: int = 200) -> int:
    if value < 1 or value > maximum:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Pagination limit must be between 1 and {maximum}",
        )
    return value


def encode_external_cursor(updated_at: datetime, row_id: int) -> str:
    payload = json.dumps([updated_at.isoformat(), int(row_id)], separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_external_cursor(value: str | None) -> tuple[datetime, int] | None:
    if not value:
        return None
    try:
        padded = value + "=" * (-len(value) % 4)
        timestamp, row_id = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        parsed = datetime.fromisoformat(str(timestamp))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed, int(row_id)
    except (binascii.Error, UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid pagination cursor") from exc


def apply_external_cursor(stmt: Any, model: Any, cursor: str | None, *, dialect_name: str | None = None) -> Any:
    parsed = decode_external_cursor(cursor)
    if parsed is None:
        return stmt
    updated_at, row_id = parsed
    if dialect_name == "sqlite":
        # SQLite may store server-default timestamps without fractional seconds,
        # while DateTime bind parameters add `.000000`. Compare the exact stored
        # representation so equal timestamps fall through to the id tiebreaker.
        normalized = updated_at.astimezone(timezone.utc).replace(tzinfo=None) if updated_at.tzinfo else updated_at
        timestamp = normalized.isoformat(sep=" ")
        column = cast(model.updated_at, String)
        return stmt.where(or_(column < timestamp, and_(column == timestamp, model.id < row_id)))
    return stmt.where(or_(model.updated_at < updated_at, and_(model.updated_at == updated_at, model.id < row_id)))


def external_page(rows: list[Any], limit: int) -> tuple[list[Any], str | None, bool]:
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = encode_external_cursor(items[-1].updated_at, items[-1].id) if has_more and items else None
    return items, next_cursor, has_more


def apply_external_project_scope(stmt: Any, api_key: ExternalApiKey) -> Any:
    project_ids = scope_project_ids(api_key)
    if project_ids:
        stmt = stmt.where(CrmProject.id.in_(project_ids))
    if api_key.scope_region:
        stmt = stmt.where(
            select(CrmProjectCustomerTask.id)
            .join(CustomerMaster, CustomerMaster.customer_code == CrmProjectCustomerTask.customer_code)
            .where(CrmProjectCustomerTask.project_id == CrmProject.id, CustomerMaster.region == api_key.scope_region)
            .exists()
        )
    return stmt


def apply_external_customer_scope(stmt: Any, api_key: ExternalApiKey) -> Any:
    project_ids = scope_project_ids(api_key)
    if project_ids:
        stmt = stmt.where(
            select(CrmProjectCustomerTask.id)
            .where(
                CrmProjectCustomerTask.customer_code == CustomerMaster.customer_code,
                CrmProjectCustomerTask.project_id.in_(project_ids),
            )
            .exists()
        )
    if api_key.scope_region:
        stmt = stmt.where(CustomerMaster.region == api_key.scope_region)
    return stmt


def external_scope_is_restricted(api_key: ExternalApiKey) -> bool:
    return bool(api_key.scope_region or scope_project_ids(api_key))


def apply_external_task_scope(stmt: Any, api_key: ExternalApiKey) -> Any:
    project_ids = scope_project_ids(api_key)
    if project_ids:
        stmt = stmt.where(CrmProjectCustomerTask.project_id.in_(project_ids))
    if api_key.scope_region:
        stmt = stmt.where(
            select(CustomerMaster.id)
            .where(
                CustomerMaster.customer_code == CrmProjectCustomerTask.customer_code,
                CustomerMaster.region == api_key.scope_region,
            )
            .exists()
        )
    return stmt


def apply_external_followup_scope(stmt: Any, api_key: ExternalApiKey) -> Any:
    project_ids = scope_project_ids(api_key)
    if project_ids:
        stmt = stmt.where(CrmFollowup.project_id.in_(project_ids))
    if api_key.scope_region:
        stmt = stmt.where(
            select(CustomerMaster.id)
            .where(CustomerMaster.customer_code == CrmFollowup.customer_code, CustomerMaster.region == api_key.scope_region)
            .exists()
        )
    return stmt


def apply_external_work_item_scope(stmt: Any, api_key: ExternalApiKey) -> Any:
    project_ids = scope_project_ids(api_key)
    if project_ids:
        stmt = stmt.where(WorkItem.project_id.in_(project_ids))
    if api_key.scope_region:
        stmt = stmt.where(
            or_(
                WorkItem.customer_code.is_(None),
                select(CustomerMaster.id)
                .where(CustomerMaster.customer_code == WorkItem.customer_code, CustomerMaster.region == api_key.scope_region)
                .exists(),
            )
        )
    return stmt


def get_external_project(db: Session, project_id: int, api_key: ExternalApiKey) -> CrmProject:
    project = db.scalar(apply_external_project_scope(select(CrmProject).where(CrmProject.id == project_id), api_key))
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


def get_external_task(db: Session, task_id: int, api_key: ExternalApiKey) -> CrmProjectCustomerTask:
    task = db.scalar(apply_external_task_scope(select(CrmProjectCustomerTask).where(CrmProjectCustomerTask.id == task_id), api_key))
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task

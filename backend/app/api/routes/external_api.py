from __future__ import annotations

import hashlib
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import and_, false, func, or_, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_permission
from app.core.database import get_db
from app.models import (
    ApprovalInstance,
    AuditLog,
    CrmFollowup,
    CrmProject,
    CrmProjectCustomerTask,
    CustomerMaster,
    CustomerPortraitSnapshot,
    ExternalApiKey,
    ExternalApiUsageLog,
    User,
)
from app.services.audit_service import write_audit_log
from app.services.external_api_service import (
    EXTERNAL_PERMISSION_LABELS,
    external_permission_enabled,
    external_permission_scopes,
    external_permissions,
    require_external_key,
)

management_router = APIRouter(prefix="/external-api", tags=["external-api-management"])
external_router = APIRouter(prefix="/api/external/v1", tags=["external-readonly-api"])

DEFAULT_CUSTOMER_FIELDS = [
    "customer_code",
    "customer_name",
    "customer_short_name",
    "customer_type",
    "region",
    "salesperson_name",
    "status",
]
CUSTOMER_FIELD_OPTIONS = [
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
]
LEGACY_PERMISSION_OPTIONS = [
    ("can_read_projects", "项目数据"),
    ("can_read_customers", "客户资料"),
    ("can_read_followups", "跟进记录"),
    ("can_read_judgements", "画像/判断"),
    ("can_read_tasks", "任务待办"),
    ("can_read_approvals", "审批记录"),
    ("can_read_audit_summary", "审计摘要"),
    ("can_read_products", "商品主数据"),
    ("can_read_suppliers", "供应商主数据"),
    ("can_read_sales_summary", "销售经营汇总"),
    ("can_read_purchase_summary", "采购经营汇总"),
    ("can_read_inventory_summary", "库存经营汇总"),
    ("can_read_receivables", "应收经营汇总"),
    ("can_read_data_quality", "数据质量汇总"),
    ("can_read_changes", "变更事件流"),
]
INVENTORY_AGENT_PERMISSION_OPTIONS = [
    ("can_read_inventory_anomalies", "库存异常案件"),
    ("can_read_inventory_evidence", "库存异常证据包"),
    ("can_read_sales_details_sensitive", "销售敏感经营明细"),
    ("can_read_purchase_details_sensitive", "采购敏感经营明细"),
    ("can_read_inventory_checks", "库存核验明细"),
    ("can_read_imports", "导入批次与错误"),
    ("can_write_inventory_diagnoses", "提交库存异常诊断"),
    ("can_validate_inventory_actions", "预演库存修复动作"),
    ("can_execute_inventory_rebuild", "执行可逆库存重算"),
    ("can_execute_inventory_upstream", "执行上游库存修复（默认关闭）"),
    ("can_read_inventory_action_status", "查看库存修复状态"),
]
PERMISSION_OPTIONS = [*LEGACY_PERMISSION_OPTIONS, *INVENTORY_AGENT_PERMISSION_OPTIONS]
ENDPOINT_CATALOG = [
    {"method": "GET", "path": "/api/external/v2/me", "permission": "有效 Key", "description": "Key 身份、capability scopes、范围与配额。"},
    {"method": "GET", "path": "/api/external/v2/capabilities", "permission": "有效 Key", "description": "发现当前 Key 可用能力。"},
    {"method": "GET", "path": "/api/external/v2/dictionaries", "permission": "有效 Key", "description": "项目、任务、跟进和审批状态字典。"},
    {"method": "GET", "path": "/api/external/v2/overview", "permission": "按域权限", "description": "权限感知执行总览。"},
    {"method": "GET", "path": "/api/external/v2/projects", "permission": "项目数据", "description": "项目列表和进展摘要。"},
    {"method": "GET", "path": "/api/external/v2/projects/{project_id}", "permission": "项目数据", "description": "项目详情和进展。"},
    {"method": "GET", "path": "/api/external/v2/projects/{project_id}/progress", "permission": "项目数据", "description": "确定性进度与闭环状态。"},
    {"method": "GET", "path": "/api/external/v2/projects/{project_id}/tasks", "permission": "任务待办", "description": "项目内可见任务。"},
    {"method": "GET", "path": "/api/external/v2/projects/{project_id}/timeline", "permission": "项目数据", "description": "按域权限组合项目时间线。"},
    {"method": "GET", "path": "/api/external/v2/tasks", "permission": "任务待办", "description": "任务列表。"},
    {"method": "GET", "path": "/api/external/v2/tasks/{task_id}", "permission": "任务待办", "description": "任务详情。"},
    {"method": "GET", "path": "/api/external/v2/followups", "permission": "跟进记录", "description": "已审核通过的跟进事实。"},
    {"method": "GET", "path": "/api/external/v2/work-items", "permission": "任务待办", "description": "支持工作项。"},
    {"method": "GET", "path": "/api/external/v2/approvals", "permission": "审批记录", "description": "脱敏审批摘要。"},
    {"method": "GET", "path": "/api/external/v2/customers", "permission": "客户资料", "description": "范围与字段白名单控制的客户列表。"},
    {"method": "GET", "path": "/api/external/v2/customers/{customer_code}", "permission": "客户资料", "description": "安全客户详情。"},
    {"method": "GET", "path": "/api/external/v2/products", "permission": "商品主数据", "description": "安全商品主数据。"},
    {"method": "GET", "path": "/api/external/v2/products/{product_code}", "permission": "商品主数据", "description": "安全商品详情。"},
    {"method": "GET", "path": "/api/external/v2/suppliers", "permission": "供应商主数据", "description": "安全供应商主数据。"},
    {"method": "GET", "path": "/api/external/v2/suppliers/{supplier_code}", "permission": "供应商主数据", "description": "安全供应商详情。"},
    {"method": "GET", "path": "/api/external/v2/operations/sales-summary", "permission": "销售经营汇总", "description": "授权客户销售聚合。"},
    {"method": "GET", "path": "/api/external/v2/operations/purchase-summary", "permission": "采购经营汇总", "description": "采购聚合。"},
    {"method": "GET", "path": "/api/external/v2/operations/inventory-summary", "permission": "库存经营汇总", "description": "最新库存快照聚合。"},
    {"method": "GET", "path": "/api/external/v2/operations/receivable-summary", "permission": "应收经营汇总", "description": "授权客户应收聚合。"},
    {"method": "GET", "path": "/api/external/v2/data-quality/summary", "permission": "数据质量汇总", "description": "数据质量与导入新鲜度。"},
    {"method": "GET", "path": "/api/external/v2/changes", "permission": "变更事件流", "description": "授权资源脱敏增量事件。"},
    {"method": "GET", "path": "/api/external/v2/usage", "permission": "审计摘要", "description": "当前 Key 自身调用与配额摘要。"},
    {"method": "GET", "path": "/api/external/v2/inventory/anomalies", "permission": "库存异常案件", "description": "最新已提交库存批次中的负库存和锁定库存案件。"},
    {"method": "GET", "path": "/api/external/v2/inventory/anomalies/{case_id}", "permission": "库存异常案件", "description": "库存异常案件详情与证据版本。"},
    {"method": "GET", "path": "/api/external/v2/inventory/anomalies/{case_id}/evidence", "permission": "库存证据及敏感明细", "description": "库存、流转、进销明细、核验和导入证据包。"},
    {"method": "POST", "path": "/api/external/v2/inventory/anomalies/{case_id}/diagnoses", "permission": "提交库存诊断", "description": "保存结构化根因、置信度与建议动作。"},
    {"method": "POST", "path": "/api/external/v2/inventory/actions/validate", "permission": "预演库存修复", "description": "确定性策略校验并签发短期执行令牌。"},
    {"method": "POST", "path": "/api/external/v2/inventory/actions", "permission": "执行库存修复", "description": "凭校验令牌和幂等键执行受控动作。"},
    {"method": "GET", "path": "/api/external/v2/inventory/actions/{action_id}", "permission": "查看修复状态", "description": "读取执行、验证与补偿结果。"},
]


class ExternalApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    owner_name: str | None = Field(default=None, max_length=120)
    scope_region: str | None = Field(default=None, max_length=120)
    scope_project_ids: list[int] | None = None
    allowed_customer_fields: list[str] = Field(default_factory=lambda: list(DEFAULT_CUSTOMER_FIELDS))
    allowed_ips: list[str] | None = None
    expires_at: datetime | None = None
    can_read_projects: bool = True
    can_read_customers: bool = True
    can_read_followups: bool = True
    can_read_judgements: bool = True
    can_read_tasks: bool = False
    can_read_approvals: bool = False
    can_read_audit_summary: bool = False
    can_read_products: bool = False
    can_read_suppliers: bool = False
    can_read_sales_summary: bool = False
    can_read_purchase_summary: bool = False
    can_read_inventory_summary: bool = False
    can_read_receivables: bool = False
    can_read_data_quality: bool = False
    can_read_changes: bool = False
    can_read_inventory_anomalies: bool = False
    can_read_inventory_evidence: bool = False
    can_read_sales_details_sensitive: bool = False
    can_read_purchase_details_sensitive: bool = False
    can_read_inventory_checks: bool = False
    can_read_imports: bool = False
    can_write_inventory_diagnoses: bool = False
    can_validate_inventory_actions: bool = False
    can_execute_inventory_rebuild: bool = False
    can_execute_inventory_upstream: bool = False
    can_read_inventory_action_status: bool = False
    rate_limit_per_minute: int = Field(default=60, ge=1, le=6000)
    daily_request_limit: int = Field(default=10000, ge=1, le=1000000)


class ExternalApiKeyRevoke(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class ExternalApiKeyRotate(BaseModel):
    grace_minutes: int = Field(default=15, ge=0, le=1440)


class ExternalApiKeyCustomerFields(BaseModel):
    allowed_customer_fields: list[str]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _generate_token() -> str:
    return "pb-ext-" + secrets.token_urlsafe(36)


def _generate_key_id() -> str:
    return "ext_" + secrets.token_urlsafe(10).replace("-", "").replace("_", "")[:14]


def _safe_limit(limit: int | None, default: int = 100, maximum: int = 500) -> int:
    try:
        value = int(limit or default)
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, maximum))


def _safe_offset(offset: int | None) -> int:
    try:
        value = int(offset or 0)
    except (TypeError, ValueError):
        value = 0
    return max(0, value)


def _token_from_request(request: Request) -> str | None:
    auth_header = request.headers.get("authorization") or ""
    if auth_header.lower().startswith("bearer "):
        return auth_header.split(" ", 1)[1].strip()
    api_key = request.headers.get("x-api-key")
    return api_key.strip() if api_key else None


def _permission_flags(row: ExternalApiKey) -> dict[str, bool]:
    return external_permissions(row)


def _scope_project_ids(row: ExternalApiKey) -> list[int]:
    raw = row.scope_project_ids or []
    if not isinstance(raw, list):
        return []
    result: list[int] = []
    for value in raw:
        try:
            result.append(int(value))
        except (TypeError, ValueError):
            continue
    return result


def _allowed_customer_fields(row: ExternalApiKey) -> list[str]:
    raw = row.allowed_customer_fields or DEFAULT_CUSTOMER_FIELDS
    fields = [field for field in raw if field in CUSTOMER_FIELD_OPTIONS]
    if "customer_code" not in fields:
        fields.insert(0, "customer_code")
    if "customer_name" not in fields:
        fields.insert(1, "customer_name")
    return list(dict.fromkeys(fields))


def _key_public(row: ExternalApiKey) -> dict[str, Any]:
    return {
        "id": row.id,
        "key_id": row.key_id,
        "name": row.name,
        "owner_name": row.owner_name,
        "key_prefix": row.key_prefix,
        "scope_region": row.scope_region,
        "scope_project_ids": _scope_project_ids(row),
        "allowed_customer_fields": _allowed_customer_fields(row),
        "allowed_ips": row.allowed_ips or [],
        "permissions": _permission_flags(row),
        "permission_scopes": external_permission_scopes(row),
        "rate_limit_per_minute": row.rate_limit_per_minute,
        "daily_request_limit": row.daily_request_limit,
        "previous_key_prefix": row.previous_key_prefix,
        "previous_key_expires_at": row.previous_key_expires_at,
        "rotated_at": row.rotated_at,
        "rotation_count": row.rotation_count,
        "active": row.active,
        "created_by_user_id": row.created_by_user_id,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "expires_at": row.expires_at,
        "last_used_at": row.last_used_at,
        "last_used_ip": row.last_used_ip,
        "revoked_at": row.revoked_at,
        "revoked_reason": row.revoked_reason,
    }


def _require_external_key(request: Request, db: Session) -> ExternalApiKey:
    return require_external_key(request, db)


def _external_key_dependency(request: Request, db: Session = Depends(get_db)) -> ExternalApiKey:
    return _require_external_key(request, db)


def _require_key_permission(permission: str):
    def dependency(api_key: ExternalApiKey = Depends(_external_key_dependency)) -> ExternalApiKey:
        if not external_permission_enabled(api_key, permission):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"API key lacks {permission}")
        return api_key

    return dependency


def _audit_external_read(db: Session, request: Request, api_key: ExternalApiKey, endpoint: str, detail: dict[str, Any] | None = None) -> None:
    write_audit_log(
        db,
        action_type="external_api_read",
        resource_type="external_api",
        resource_id=api_key.key_id,
        request=request,
        after_data={
            "endpoint": endpoint,
            "key_prefix": api_key.key_prefix,
            **(detail or {}),
        },
    )
    db.commit()


def _project_scope_conditions(api_key: ExternalApiKey) -> list[Any]:
    conditions: list[Any] = []
    project_ids = _scope_project_ids(api_key)
    if project_ids:
        conditions.append(CrmProject.id.in_(project_ids))
    if api_key.scope_region:
        conditions.append(
            select(CrmProjectCustomerTask.id)
            .join(CustomerMaster, CustomerMaster.customer_code == CrmProjectCustomerTask.customer_code)
            .where(CrmProjectCustomerTask.project_id == CrmProject.id, CustomerMaster.region == api_key.scope_region)
            .exists()
        )
    return conditions


def _customer_scope_conditions(api_key: ExternalApiKey) -> list[Any]:
    conditions: list[Any] = []
    if api_key.scope_region:
        conditions.append(CustomerMaster.region == api_key.scope_region)
    project_ids = _scope_project_ids(api_key)
    if project_ids:
        conditions.append(
            select(CrmProjectCustomerTask.id)
            .where(
                CrmProjectCustomerTask.customer_code == CustomerMaster.customer_code,
                CrmProjectCustomerTask.project_id.in_(project_ids),
            )
            .exists()
        )
    return conditions


def _apply_project_scope(stmt: Any, api_key: ExternalApiKey) -> Any:
    conditions = _project_scope_conditions(api_key)
    return stmt.where(and_(*conditions)) if conditions else stmt


def _apply_customer_scope(stmt: Any, api_key: ExternalApiKey) -> Any:
    conditions = _customer_scope_conditions(api_key)
    return stmt.where(and_(*conditions)) if conditions else stmt


def _assert_project_visible(db: Session, project_id: int, api_key: ExternalApiKey) -> None:
    row = db.scalar(_apply_project_scope(select(CrmProject.id).where(CrmProject.id == project_id), api_key))
    if row is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="API key cannot access this project")


def _customer_payload(db: Session, customer: CustomerMaster, fields: list[str]) -> dict[str, Any]:
    from app.services.customer_tagging_service import external_customer_tag_profile

    payload = {field: getattr(customer, field, None) for field in fields if field != "customer_tag_profile"}
    if "customer_tag_profile" in fields:
        payload["customer_tag_profile"] = external_customer_tag_profile(db, customer)
    payload["created_at"] = customer.created_at
    payload["updated_at"] = customer.updated_at
    return payload


def _scoped_task_stmt(api_key: ExternalApiKey, *columns: Any) -> Any:
    stmt = (
        select(*columns)
        .select_from(CrmProjectCustomerTask)
        .join(CrmProject, CrmProject.id == CrmProjectCustomerTask.project_id)
        .join(CustomerMaster, CustomerMaster.customer_code == CrmProjectCustomerTask.customer_code)
    )
    return _apply_direct_task_scope(stmt, api_key)


def _apply_direct_task_scope(stmt: Any, api_key: ExternalApiKey) -> Any:
    project_ids = _scope_project_ids(api_key)
    if project_ids:
        stmt = stmt.where(CrmProjectCustomerTask.project_id.in_(project_ids))
    if api_key.scope_region:
        stmt = stmt.where(CustomerMaster.region == api_key.scope_region)
    return stmt


def _apply_direct_followup_scope(stmt: Any, api_key: ExternalApiKey) -> Any:
    project_ids = _scope_project_ids(api_key)
    if project_ids:
        stmt = stmt.where(CrmFollowup.project_id.in_(project_ids))
    if api_key.scope_region:
        stmt = stmt.where(CustomerMaster.region == api_key.scope_region)
    return stmt


def _visible_project_ids(db: Session, api_key: ExternalApiKey) -> list[int]:
    stmt = _apply_project_scope(select(CrmProject.id), api_key)
    return [int(value) for value in db.scalars(stmt).all()]


def _visible_customer_codes(db: Session, api_key: ExternalApiKey) -> list[str]:
    stmt = _apply_customer_scope(select(CustomerMaster.customer_code), api_key)
    return [str(value) for value in db.scalars(stmt).all()]


def _approval_scope_condition(db: Session, api_key: ExternalApiKey) -> Any | None:
    if not api_key.scope_region and not _scope_project_ids(api_key):
        return None
    project_ids = _visible_project_ids(db, api_key)
    customer_codes = _visible_customer_codes(db, api_key)
    conditions: list[Any] = []
    if project_ids:
        conditions.extend(
            [
                and_(ApprovalInstance.resource_type == "crm_project", ApprovalInstance.resource_id.in_([str(value) for value in project_ids])),
                ApprovalInstance.payload_json["project_id"].as_integer().in_(project_ids),
                ApprovalInstance.payload_json["project"]["id"].as_integer().in_(project_ids),
                ApprovalInstance.payload_json["task"]["project_id"].as_integer().in_(project_ids),
                ApprovalInstance.payload_json["followup"]["project_id"].as_integer().in_(project_ids),
            ]
        )
    if customer_codes:
        conditions.extend(
            [
                ApprovalInstance.payload_json["customer_code"].as_string().in_(customer_codes),
                ApprovalInstance.payload_json["task"]["customer_code"].as_string().in_(customer_codes),
                ApprovalInstance.payload_json["followup"]["customer_code"].as_string().in_(customer_codes),
            ]
        )
    return or_(*conditions) if conditions else false()


def _apply_approval_scope(stmt: Any, db: Session, api_key: ExternalApiKey) -> Any:
    condition = _approval_scope_condition(db, api_key)
    return stmt.where(condition) if condition is not None else stmt


def _apply_judgement_scope(stmt: Any, api_key: ExternalApiKey) -> Any:
    conditions: list[Any] = []
    if api_key.scope_region:
        conditions.append(
            select(CustomerMaster.id)
            .where(CustomerMaster.customer_code == CustomerPortraitSnapshot.customer_code, CustomerMaster.region == api_key.scope_region)
            .exists()
        )
    project_ids = _scope_project_ids(api_key)
    if project_ids:
        conditions.append(
            select(CrmProjectCustomerTask.id)
            .where(
                CrmProjectCustomerTask.customer_code == CustomerPortraitSnapshot.customer_code,
                CrmProjectCustomerTask.project_id.in_(project_ids),
            )
            .exists()
        )
    return stmt.where(and_(*conditions)) if conditions else stmt


def _approval_payload(row: ApprovalInstance) -> dict[str, Any]:
    return {
        "id": row.id,
        "approval_no": row.approval_no,
        "approval_type": row.approval_type,
        "resource_type": row.resource_type,
        "resource_id": row.resource_id,
        "title": row.title,
        "status": row.status,
        "priority": row.priority,
        "submitted_at": row.submitted_at,
        "reviewed_at": row.reviewed_at,
        "closed_at": row.closed_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _judgement_payload(row: CustomerPortraitSnapshot) -> dict[str, Any]:
    return {
        "id": row.id,
        "customer_code": row.customer_code,
        "customer_name": row.customer_name,
        "period_start": row.period_start,
        "period_end": row.period_end,
        "data_cutoff_date": row.data_cutoff_date,
        "rule_version": row.rule_version,
        "status": row.status,
        "summary": row.summary_json,
        "tags": row.tag_json,
        "generated_at": row.generated_at,
        "updated_at": row.updated_at,
    }


def _project_payload(db: Session, project: CrmProject, api_key: ExternalApiKey) -> dict[str, Any]:
    task_base = _scoped_task_stmt(api_key, CrmProjectCustomerTask.id).where(CrmProjectCustomerTask.project_id == project.id)
    task_total = db.scalar(select(func.count()).select_from(task_base.order_by(None).subquery())) or 0
    task_closed = db.scalar(
        select(func.count()).select_from(task_base.where(CrmProjectCustomerTask.is_closed.is_(True)).order_by(None).subquery())
    ) or 0
    risk_items = db.scalar(
        select(func.count()).select_from(
            task_base.where(
            or_(
                CrmProjectCustomerTask.need_support.is_(True),
                CrmProjectCustomerTask.need_manager_support.is_(True),
                CrmProjectCustomerTask.need_boss_decision.is_(True),
                CrmProjectCustomerTask.is_blocked.is_(True),
            ),
            ).order_by(None).subquery()
        )
    ) or 0
    data = jsonable_encoder(project)
    data.update(
        {
            "task_total": task_total,
            "task_closed": task_closed,
            "task_open": max(task_total - task_closed, 0),
            "risk_items": risk_items,
        }
    )
    return data


@management_router.get("/catalog", dependencies=[Depends(require_permission("external_api_key.view"))])
def external_api_catalog() -> dict:
    return {
        "base_url": "/api/external/v2",
        "schema_version": "2.0",
        "openapi_url": "/api/openapi.json",
        "customer_field_options": CUSTOMER_FIELD_OPTIONS,
        "default_customer_fields": DEFAULT_CUSTOMER_FIELDS,
        "permission_options": [{"code": code, "label": label} for code, label in PERMISSION_OPTIONS],
        "endpoints": ENDPOINT_CATALOG,
    }


@management_router.get("/keys", dependencies=[Depends(require_permission("external_api_key.view"))])
def external_api_keys(db: Session = Depends(get_db)) -> list[dict]:
    rows = list(db.scalars(select(ExternalApiKey).order_by(ExternalApiKey.created_at.desc(), ExternalApiKey.id.desc())).all())
    return jsonable_encoder([_key_public(row) for row in rows])


@management_router.post("/keys", dependencies=[Depends(require_permission("external_api_key.create"))])
def create_external_api_key(
    payload: ExternalApiKeyCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    flags = {code: bool(getattr(payload, code)) for code, _label in PERMISSION_OPTIONS}
    legacy_codes = {code for code, _label in LEGACY_PERMISSION_OPTIONS}
    legacy_flags = {code: enabled for code, enabled in flags.items() if code in legacy_codes}
    if not any(flags.values()):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one readonly permission is required")
    allowed_fields = [field for field in payload.allowed_customer_fields if field in CUSTOMER_FIELD_OPTIONS]
    if not allowed_fields:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one customer field is required")
    if "customer_code" not in allowed_fields:
        allowed_fields.insert(0, "customer_code")
    if "customer_name" not in allowed_fields:
        allowed_fields.insert(1, "customer_name")

    token = _generate_token()
    key = ExternalApiKey(
        key_id=_generate_key_id(),
        name=payload.name.strip(),
        owner_name=(payload.owner_name or "").strip() or None,
        key_prefix=token[:16],
        key_hash=_hash_token(token),
        scope_region=(payload.scope_region or "").strip() or None,
        scope_project_ids=payload.scope_project_ids or [],
        allowed_customer_fields=list(dict.fromkeys(allowed_fields)),
        allowed_ips=payload.allowed_ips or [],
        expires_at=payload.expires_at,
        permission_scopes=[
            EXTERNAL_PERMISSION_LABELS[code][0]
            for code, enabled in flags.items()
            if enabled
        ],
        rate_limit_per_minute=payload.rate_limit_per_minute,
        daily_request_limit=payload.daily_request_limit,
        created_by_user_id=current_user.id,
        **legacy_flags,
    )
    db.add(key)
    db.flush()
    write_audit_log(
        db,
        action_type="external_api_key_create",
        resource_type="external_api_key",
        resource_id=key.key_id,
        user=current_user,
        request=request,
        after_data=jsonable_encoder({**_key_public(key), "api_key": "shown_once"}),
    )
    db.commit()
    db.refresh(key)
    return jsonable_encoder({"api_key": token, "key": _key_public(key)})


@management_router.post(
    "/keys/{key_id}/rotate",
    dependencies=[Depends(require_permission("external_api_key.create"))],
)
def rotate_external_api_key(
    key_id: str,
    payload: ExternalApiKeyRotate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    key = db.scalar(select(ExternalApiKey).where(ExternalApiKey.key_id == key_id))
    if key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="External API key not found")
    if key.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Revoked external API key cannot be rotated")
    now = _now()
    if payload.grace_minutes > 0:
        key.previous_key_prefix = key.key_prefix
        key.previous_key_hash = key.key_hash
        key.previous_key_expires_at = now + timedelta(minutes=payload.grace_minutes)
    else:
        key.previous_key_prefix = None
        key.previous_key_hash = None
        key.previous_key_expires_at = None
    token = _generate_token()
    key.key_prefix = token[:16]
    key.key_hash = _hash_token(token)
    key.rotated_at = now
    key.rotation_count += 1
    write_audit_log(
        db,
        action_type="external_api_key_rotate",
        resource_type="external_api_key",
        resource_id=key.key_id,
        user=current_user,
        request=request,
        after_data={
            "rotation_count": key.rotation_count,
            "grace_minutes": payload.grace_minutes,
            "previous_key_expires_at": key.previous_key_expires_at.isoformat() if key.previous_key_expires_at else None,
        },
    )
    db.commit()
    db.refresh(key)
    return jsonable_encoder({"api_key": token, "key": _key_public(key)})


@management_router.patch(
    "/keys/{key_id}/customer-fields",
    dependencies=[Depends(require_permission("external_api_key.create"))],
)
def update_external_api_key_customer_fields(
    key_id: str,
    payload: ExternalApiKeyCustomerFields,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    key = db.scalar(select(ExternalApiKey).where(ExternalApiKey.key_id == key_id))
    if key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="External API key not found")
    if key.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Revoked external API key cannot be changed")
    allowed_fields = [field for field in payload.allowed_customer_fields if field in CUSTOMER_FIELD_OPTIONS]
    for required in ("customer_name", "customer_code"):
        if required not in allowed_fields:
            allowed_fields.insert(0, required)
    allowed_fields = list(dict.fromkeys(allowed_fields))
    before_fields = _allowed_customer_fields(key)
    key.allowed_customer_fields = allowed_fields
    write_audit_log(
        db,
        action_type="external_api_key_customer_fields_update",
        resource_type="external_api_key",
        resource_id=key.key_id,
        user=current_user,
        request=request,
        before_data={"allowed_customer_fields": before_fields},
        after_data={"allowed_customer_fields": allowed_fields},
    )
    db.commit()
    db.refresh(key)
    return jsonable_encoder(_key_public(key))


@management_router.get(
    "/keys/{key_id}/usage",
    dependencies=[Depends(require_permission("external_api_key.view"))],
)
def external_api_key_usage(
    key_id: str,
    days: int = Query(default=7, ge=1, le=90),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    key = db.scalar(select(ExternalApiKey).where(ExternalApiKey.key_id == key_id))
    if key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="External API key not found")
    since = _now() - timedelta(days=days)
    rows = list(
        db.scalars(
            select(ExternalApiUsageLog)
            .where(ExternalApiUsageLog.key_id == key_id, ExternalApiUsageLog.created_at >= since)
            .order_by(ExternalApiUsageLog.id.desc())
            .limit(limit)
        ).all()
    )
    total = db.scalar(
        select(func.count(ExternalApiUsageLog.id)).where(
            ExternalApiUsageLog.key_id == key_id,
            ExternalApiUsageLog.created_at >= since,
        )
    ) or 0
    error_count = db.scalar(
        select(func.count(ExternalApiUsageLog.id)).where(
            ExternalApiUsageLog.key_id == key_id,
            ExternalApiUsageLog.created_at >= since,
            ExternalApiUsageLog.status_code >= 400,
        )
    ) or 0
    return jsonable_encoder(
        {
            "key_id": key_id,
            "days": days,
            "total": int(total),
            "error_count": int(error_count),
            "items": [
                {
                    "request_id": row.request_id,
                    "endpoint": row.endpoint,
                    "method": row.method,
                    "status_code": row.status_code,
                    "duration_ms": row.duration_ms,
                    "response_count": row.response_count,
                    "client_ip": row.client_ip,
                    "created_at": row.created_at,
                }
                for row in rows
            ],
        }
    )


@management_router.post("/keys/{key_id}/disable", dependencies=[Depends(require_permission("external_api_key.revoke"))])
def disable_external_api_key(
    key_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    key = db.scalar(select(ExternalApiKey).where(ExternalApiKey.key_id == key_id))
    if key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="External API key not found")
    key.active = False
    write_audit_log(db, action_type="external_api_key_disable", resource_type="external_api_key", resource_id=key.key_id, user=current_user, request=request)
    db.commit()
    db.refresh(key)
    return jsonable_encoder(_key_public(key))


@management_router.post("/keys/{key_id}/enable", dependencies=[Depends(require_permission("external_api_key.revoke"))])
def enable_external_api_key(
    key_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    key = db.scalar(select(ExternalApiKey).where(ExternalApiKey.key_id == key_id))
    if key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="External API key not found")
    if key.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Revoked key cannot be enabled")
    key.active = True
    write_audit_log(db, action_type="external_api_key_enable", resource_type="external_api_key", resource_id=key.key_id, user=current_user, request=request)
    db.commit()
    db.refresh(key)
    return jsonable_encoder(_key_public(key))


@management_router.post("/keys/{key_id}/revoke", dependencies=[Depends(require_permission("external_api_key.revoke"))])
def revoke_external_api_key(
    key_id: str,
    payload: ExternalApiKeyRevoke,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    key = db.scalar(select(ExternalApiKey).where(ExternalApiKey.key_id == key_id))
    if key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="External API key not found")
    key.active = False
    key.revoked_at = _now()
    key.revoked_by_user_id = current_user.id
    key.revoked_reason = payload.reason or "manual_revoke"
    write_audit_log(
        db,
        action_type="external_api_key_revoke",
        resource_type="external_api_key",
        resource_id=key.key_id,
        user=current_user,
        request=request,
        after_data={"reason": key.revoked_reason, "key_prefix": key.key_prefix},
    )
    db.commit()
    db.refresh(key)
    return jsonable_encoder(_key_public(key))


@external_router.get("/me")
def external_api_me(
    request: Request,
    api_key: ExternalApiKey = Depends(_external_key_dependency),
    db: Session = Depends(get_db),
) -> dict:
    _audit_external_read(db, request, api_key, "/me")
    return jsonable_encoder({"key": _key_public(api_key), "readonly": True})


@external_router.get("/overview")
def external_api_overview(
    request: Request,
    api_key: ExternalApiKey = Depends(_external_key_dependency),
    db: Session = Depends(get_db),
) -> dict:
    project_stmt = _apply_project_scope(select(func.count()).select_from(CrmProject), api_key)
    customer_stmt = _apply_customer_scope(select(func.count()).select_from(CustomerMaster), api_key)
    project_count = db.scalar(project_stmt) or 0
    customer_count = db.scalar(customer_stmt) or 0
    followup_stmt = (
        select(func.count())
        .select_from(CrmFollowup)
        .join(CrmProject, CrmProject.id == CrmFollowup.project_id)
        .join(CustomerMaster, CustomerMaster.customer_code == CrmFollowup.customer_code)
    )
    followup_count = db.scalar(_apply_direct_followup_scope(followup_stmt, api_key)) or 0
    task_count = db.scalar(_scoped_task_stmt(api_key, func.count())) or 0
    open_task_count = db.scalar(_scoped_task_stmt(api_key, func.count()).where(CrmProjectCustomerTask.is_closed.is_(False))) or 0
    approval_count = db.scalar(_apply_approval_scope(select(func.count()).select_from(ApprovalInstance), db, api_key)) or 0
    judgement_count = db.scalar(_apply_judgement_scope(select(func.count()).select_from(CustomerPortraitSnapshot), api_key)) or 0
    _audit_external_read(db, request, api_key, "/overview")
    return {
        "key_id": api_key.key_id,
        "readonly": True,
        "stats": {
            "projects": project_count,
            "customers": customer_count,
            "followups": followup_count,
            "judgements": judgement_count,
            "tasks": task_count,
            "open_tasks": open_task_count,
            "approvals": approval_count,
        },
    }


@external_router.get("/projects")
def external_api_projects(
    request: Request,
    q: str | None = None,
    approval_status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    api_key: ExternalApiKey = Depends(_require_key_permission("can_read_projects")),
    db: Session = Depends(get_db),
) -> dict:
    limit_value = _safe_limit(limit)
    offset_value = _safe_offset(offset)
    stmt = select(CrmProject)
    stmt = _apply_project_scope(stmt, api_key)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(CrmProject.project_name.ilike(like), CrmProject.project_code.ilike(like), CrmProject.project_type.ilike(like)))
    if approval_status:
        stmt = stmt.where(CrmProject.approval_status == approval_status)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = list(db.scalars(stmt.order_by(CrmProject.created_at.desc(), CrmProject.id.desc()).limit(limit_value).offset(offset_value)).all())
    _audit_external_read(db, request, api_key, "/projects", {"count": len(rows)})
    return jsonable_encoder(
        {
            "key_id": api_key.key_id,
            "count": len(rows),
            "total": total,
            "limit": limit_value,
            "offset": offset_value,
            "projects": [_project_payload(db, row, api_key) for row in rows],
        }
    )


@external_router.get("/projects/{project_id}")
def external_api_project_detail(
    project_id: int,
    request: Request,
    api_key: ExternalApiKey = Depends(_require_key_permission("can_read_projects")),
    db: Session = Depends(get_db),
) -> dict:
    _assert_project_visible(db, project_id, api_key)
    project = db.get(CrmProject, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    task_base = _scoped_task_stmt(api_key, CrmProjectCustomerTask.id).where(CrmProjectCustomerTask.project_id == project_id)
    summary = {
        "total": db.scalar(select(func.count()).select_from(task_base.order_by(None).subquery())) or 0,
        "closed": db.scalar(
            select(func.count()).select_from(task_base.where(CrmProjectCustomerTask.is_closed.is_(True)).order_by(None).subquery())
        )
        or 0,
        "need_support": db.scalar(
            select(func.count()).select_from(task_base.where(CrmProjectCustomerTask.need_support.is_(True)).order_by(None).subquery())
        )
        or 0,
        "blocked": db.scalar(
            select(func.count()).select_from(task_base.where(CrmProjectCustomerTask.is_blocked.is_(True)).order_by(None).subquery())
        )
        or 0,
    }
    customers: list[dict[str, Any]] = []
    if api_key.can_read_customers:
        fields = _allowed_customer_fields(api_key)
        customer_stmt = (
            select(CustomerMaster, CrmProjectCustomerTask)
            .join(CrmProjectCustomerTask, CrmProjectCustomerTask.customer_code == CustomerMaster.customer_code)
            .where(CrmProjectCustomerTask.project_id == project_id)
        )
        customer_stmt = _apply_direct_task_scope(customer_stmt, api_key)
        for customer, task in db.execute(customer_stmt.order_by(CustomerMaster.customer_code).limit(2000)).all():
            payload = _customer_payload(db, customer, fields)
            payload.update(
                {
                    "task_id": task.id,
                    "task_code": task.task_code,
                    "task_status": task.status,
                    "executor_name": task.executor_name_snapshot,
                    "last_followup_at": task.last_followup_at,
                    "is_closed": task.is_closed,
                }
            )
            customers.append(payload)
    _audit_external_read(db, request, api_key, f"/projects/{project_id}")
    return jsonable_encoder({"key_id": api_key.key_id, "project": _project_payload(db, project, api_key), "summary": summary, "customers": customers, "readonly": True})


@external_router.get("/customers")
def external_api_customers(
    request: Request,
    q: str | None = None,
    region: str | None = None,
    customer_type: str | None = None,
    salesperson: str | None = None,
    customer_status: str | None = None,
    project_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
    api_key: ExternalApiKey = Depends(_require_key_permission("can_read_customers")),
    db: Session = Depends(get_db),
) -> dict:
    limit_value = _safe_limit(limit)
    offset_value = _safe_offset(offset)
    fields = _allowed_customer_fields(api_key)
    stmt = _apply_customer_scope(select(CustomerMaster), api_key)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(CustomerMaster.customer_code.ilike(like), CustomerMaster.customer_name.ilike(like), CustomerMaster.customer_short_name.ilike(like)))
    if region:
        stmt = stmt.where(CustomerMaster.region == region)
    if customer_type:
        stmt = stmt.where(CustomerMaster.customer_type == customer_type)
    if salesperson:
        stmt = stmt.where(or_(CustomerMaster.salesperson_name == salesperson, CustomerMaster.salesperson_employee_code == salesperson))
    if customer_status:
        stmt = stmt.where(CustomerMaster.status == customer_status)
    if project_id is not None:
        _assert_project_visible(db, project_id, api_key)
        stmt = stmt.where(
            select(CrmProjectCustomerTask.id)
            .where(CrmProjectCustomerTask.customer_code == CustomerMaster.customer_code, CrmProjectCustomerTask.project_id == project_id)
            .exists()
        )
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = list(db.scalars(stmt.order_by(CustomerMaster.updated_at.desc(), CustomerMaster.customer_code).limit(limit_value).offset(offset_value)).all())
    items = []
    for customer in rows:
        project_count = db.scalar(select(func.count(func.distinct(CrmProjectCustomerTask.project_id))).where(CrmProjectCustomerTask.customer_code == customer.customer_code)) or 0
        followup_count = db.scalar(select(func.count()).select_from(CrmFollowup).where(CrmFollowup.customer_code == customer.customer_code)) or 0
        payload = _customer_payload(db, customer, fields)
        payload.update({"project_count": project_count, "followup_count": followup_count})
        items.append(payload)
    _audit_external_read(db, request, api_key, "/customers", {"count": len(rows)})
    return jsonable_encoder(
        {
            "key_id": api_key.key_id,
            "count": len(items),
            "total": total,
            "limit": limit_value,
            "offset": offset_value,
            "customer_fields": fields,
            "customers": items,
        }
    )


@external_router.get("/customers/{customer_code}")
def external_api_customer_detail(
    customer_code: str,
    request: Request,
    api_key: ExternalApiKey = Depends(_require_key_permission("can_read_customers")),
    db: Session = Depends(get_db),
) -> dict:
    fields = _allowed_customer_fields(api_key)
    customer = db.scalar(_apply_customer_scope(select(CustomerMaster).where(CustomerMaster.customer_code == customer_code), api_key))
    if customer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    _audit_external_read(db, request, api_key, f"/customers/{customer_code}")
    return jsonable_encoder({"key_id": api_key.key_id, "customer_fields": fields, "customer": _customer_payload(db, customer, fields), "readonly": True})


@external_router.get("/followups")
def external_api_followups(
    request: Request,
    project_id: int | None = None,
    customer_code: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 100,
    offset: int = 0,
    api_key: ExternalApiKey = Depends(_require_key_permission("can_read_followups")),
    db: Session = Depends(get_db),
) -> dict:
    limit_value = _safe_limit(limit)
    offset_value = _safe_offset(offset)
    stmt = select(CrmFollowup, CrmProject, CustomerMaster).join(CrmProject, CrmProject.id == CrmFollowup.project_id).join(CustomerMaster, CustomerMaster.customer_code == CrmFollowup.customer_code)
    stmt = _apply_project_scope(stmt, api_key)
    stmt = _apply_customer_scope(stmt, api_key)
    if project_id is not None:
        _assert_project_visible(db, project_id, api_key)
        stmt = stmt.where(CrmFollowup.project_id == project_id)
    if customer_code:
        stmt = stmt.where(CrmFollowup.customer_code == customer_code)
    if date_from:
        stmt = stmt.where(CrmFollowup.followup_date >= date_from)
    if date_to:
        stmt = stmt.where(CrmFollowup.followup_date <= date_to)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.execute(stmt.order_by(CrmFollowup.created_at.desc()).limit(limit_value).offset(offset_value)).all()
    items = []
    for followup, project, customer in rows:
        payload = jsonable_encoder(followup)
        payload["project_name"] = project.project_name
        payload["customer_name"] = customer.customer_name
        items.append(payload)
    _audit_external_read(db, request, api_key, "/followups", {"count": len(items)})
    return jsonable_encoder({"key_id": api_key.key_id, "count": len(items), "total": total, "limit": limit_value, "offset": offset_value, "followups": items})


@external_router.get("/judgements")
def external_api_judgements(
    request: Request,
    project_id: int | None = None,
    customer_code: str | None = None,
    limit: int = 100,
    offset: int = 0,
    api_key: ExternalApiKey = Depends(_require_key_permission("can_read_judgements")),
    db: Session = Depends(get_db),
) -> dict:
    limit_value = _safe_limit(limit)
    offset_value = _safe_offset(offset)
    stmt = select(CustomerPortraitSnapshot)
    if customer_code:
        stmt = stmt.where(CustomerPortraitSnapshot.customer_code == customer_code)
    if project_id is not None:
        _assert_project_visible(db, project_id, api_key)
        stmt = stmt.where(
            select(CrmProjectCustomerTask.id)
            .where(CrmProjectCustomerTask.customer_code == CustomerPortraitSnapshot.customer_code, CrmProjectCustomerTask.project_id == project_id)
            .exists()
        )
    stmt = _apply_judgement_scope(stmt, api_key)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = list(db.scalars(stmt.order_by(CustomerPortraitSnapshot.generated_at.desc(), CustomerPortraitSnapshot.id.desc()).limit(limit_value).offset(offset_value)).all())
    _audit_external_read(db, request, api_key, "/judgements", {"count": len(rows)})
    return jsonable_encoder(
        {
            "key_id": api_key.key_id,
            "count": len(rows),
            "total": total,
            "limit": limit_value,
            "offset": offset_value,
            "judgements": [_judgement_payload(row) for row in rows],
            "source_mapping": "customer_portrait_snapshot",
        }
    )


@external_router.get("/tasks")
def external_api_tasks(
    request: Request,
    status: str | None = "open",
    project_id: int | None = None,
    customer_code: str | None = None,
    limit: int = 100,
    offset: int = 0,
    api_key: ExternalApiKey = Depends(_require_key_permission("can_read_tasks")),
    db: Session = Depends(get_db),
) -> dict:
    limit_value = _safe_limit(limit)
    offset_value = _safe_offset(offset)
    stmt = (
        select(CrmProjectCustomerTask, CrmProject)
        .join(CrmProject, CrmProject.id == CrmProjectCustomerTask.project_id)
        .join(CustomerMaster, CustomerMaster.customer_code == CrmProjectCustomerTask.customer_code)
    )
    stmt = _apply_direct_task_scope(stmt, api_key)
    if status:
        if status == "open":
            stmt = stmt.where(CrmProjectCustomerTask.is_closed.is_(False))
        else:
            stmt = stmt.where(CrmProjectCustomerTask.status == status)
    if project_id is not None:
        _assert_project_visible(db, project_id, api_key)
        stmt = stmt.where(CrmProjectCustomerTask.project_id == project_id)
    if customer_code:
        stmt = stmt.where(CrmProjectCustomerTask.customer_code == customer_code)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.execute(stmt.order_by(CrmProjectCustomerTask.updated_at.desc(), CrmProjectCustomerTask.id.desc()).limit(limit_value).offset(offset_value)).all()
    items = []
    for task, project in rows:
        payload = jsonable_encoder(task)
        payload["project_name"] = project.project_name
        items.append(payload)
    _audit_external_read(db, request, api_key, "/tasks", {"count": len(items)})
    return jsonable_encoder({"key_id": api_key.key_id, "count": len(items), "total": total, "limit": limit_value, "offset": offset_value, "tasks": items})


@external_router.get("/approvals")
def external_api_approvals(
    request: Request,
    status: str | None = None,
    project_id: int | None = None,
    customer_code: str | None = None,
    limit: int = 100,
    offset: int = 0,
    api_key: ExternalApiKey = Depends(_require_key_permission("can_read_approvals")),
    db: Session = Depends(get_db),
) -> dict:
    limit_value = _safe_limit(limit)
    offset_value = _safe_offset(offset)
    stmt = _apply_approval_scope(select(ApprovalInstance), db, api_key)
    if status:
        stmt = stmt.where(ApprovalInstance.status == status)
    if project_id is not None:
        _assert_project_visible(db, project_id, api_key)
        stmt = stmt.where(ApprovalInstance.resource_type == "crm_project", ApprovalInstance.resource_id == str(project_id))
    if customer_code:
        stmt = stmt.where(
            or_(
                ApprovalInstance.payload_json["customer_code"].as_string() == customer_code,
                ApprovalInstance.payload_json["task"]["customer_code"].as_string() == customer_code,
                ApprovalInstance.payload_json["followup"]["customer_code"].as_string() == customer_code,
            )
        )
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = list(db.scalars(stmt.order_by(ApprovalInstance.created_at.desc(), ApprovalInstance.id.desc()).limit(limit_value).offset(offset_value)).all())
    _audit_external_read(db, request, api_key, "/approvals", {"count": len(rows)})
    return jsonable_encoder({"key_id": api_key.key_id, "count": len(rows), "total": total, "limit": limit_value, "offset": offset_value, "approvals": [_approval_payload(row) for row in rows]})


@external_router.get("/audit-summary")
def external_api_audit_summary(
    request: Request,
    days: int = Query(default=7, ge=1, le=90),
    limit: int = 100,
    api_key: ExternalApiKey = Depends(_require_key_permission("can_read_audit_summary")),
    db: Session = Depends(get_db),
) -> dict:
    limit_value = _safe_limit(limit, default=100, maximum=500)
    cutoff = _now() - timedelta(days=days)
    rows = list(
        db.scalars(
            select(AuditLog)
            .where(
                AuditLog.created_at >= cutoff,
                AuditLog.resource_type == "external_api",
                AuditLog.resource_id == api_key.key_id,
            )
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(limit_value)
        ).all()
    )
    grouped_rows = db.execute(
        select(AuditLog.resource_type, AuditLog.action_type, func.count())
        .where(
            AuditLog.created_at >= cutoff,
            AuditLog.resource_type == "external_api",
            AuditLog.resource_id == api_key.key_id,
        )
        .group_by(AuditLog.resource_type, AuditLog.action_type)
        .order_by(func.count().desc())
        .limit(50)
    ).all()
    grouped = [{"resource_type": resource_type, "action_type": action_type, "count": int(count)} for resource_type, action_type, count in grouped_rows]
    _audit_external_read(db, request, api_key, "/audit-summary", {"count": len(rows)})
    recent = [
        {
            "id": row.id,
            "action_type": row.action_type,
            "endpoint": (row.after_data or {}).get("endpoint") if isinstance(row.after_data, dict) else None,
            "created_at": row.created_at,
        }
        for row in rows
    ]
    return jsonable_encoder({"key_id": api_key.key_id, "days": days, "count": len(rows), "summary": grouped, "recent": recent})

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.api.routes.approvals import (
    _approval_detail,
    _approval_public,
    approve_approval,
    reject_approval,
    request_approval_supplement,
    submit_approval,
    update_approval_draft,
    upload_approval_attachment,
)
from app.services.approval_access_service import visible_approval_or_404, visible_approvals_stmt
from app.api.routes.crm_projects import (
    create_crm_followup_approval_draft,
    create_crm_project_approval_draft,
    get_crm_linked_customer_context,
    get_crm_linked_customer_business_profile,
    get_crm_task_detail,
    list_crm_linked_customers_page,
    list_crm_tasks_page,
    update_crm_linked_customer_business_profile,
    update_crm_linked_customer_profile,
)
from app.api.routes.master_data import list_customers_page
from app.api.routes.work_items import close_work_item, list_work_items_page, resolve_work_item
from app.core.database import get_db
from app.core.config import settings
from app.core.security import create_access_token, verify_password
from app.models import ApprovalInstance, CrmProjectCustomerTask, User, WorkItem
from app.schemas.crm import (
    ApprovalActionRequest,
    ApprovalDraftUpdate,
    CrmFollowupApprovalDraftCreate,
    CrmProjectApprovalDraftCreate,
    WorkItemActionRequest,
)
from app.schemas.master_data import CustomerBusinessProfileUpsert, CustomerMasterUpdate
from app.schemas.identity import UserPublic
from app.schemas.mobile import (
    MobileCustomerOptionPage,
    MobileLoginRequest,
    MobileLogoutResponse,
    MobileProjectSubmissionPage,
    MobileRefreshRequest,
    MobileTokenResponse,
    MobileUserOptionPage,
)
from app.services.audit_service import write_audit_log
from app.services.crm_access_service import crm_task_scope_filter
from app.services.crm_project_service import require_customer, task_executor_snapshot, validate_task_status
from app.services.mobile_session_service import (
    MobileSessionError,
    issue_mobile_session,
    refresh_mobile_session,
    revoke_mobile_session,
)
from app.services.mobile_sync_service import current_mobile_scope_revision
from app.services.permission_service import get_final_permission_codes, has_permission
from app.services.work_item_service import OPEN_WORK_ITEM_STATUSES, work_item_scope_filter
from app.api.routes.mobile_round6 import router as mobile_round6_router
from app.api.routes.mobile_v2 import router as mobile_v2_router

router = APIRouter(prefix="/mobile", tags=["mobile"])
router.include_router(mobile_round6_router)
router.include_router(mobile_v2_router)

MOBILE_NAV = [
    {
        "key": "home",
        "label": "首页",
        "permissions": ["dashboard.view", "crm_task.view", "approval.view", "approval.approve", "crm_lead.view", "crm_lead.approve", "customer_tag.review", "crm_issue.view"],
    },
    {
        "key": "customers",
        "label": "客户",
        "permissions": ["crm_task.view", "crm_customer_profile.view", "crm_business_profile.view", "customer.view", "crm_lead.view"],
    },
    {
        "key": "projects",
        "label": "项目",
        "permissions": ["crm_project.view", "crm_project.create", "crm_task.view", "crm_followup.view", "crm_issue.view", "delivery.view"],
    },
    {
        "key": "approvals",
        "label": "审批",
        "permissions": ["approval.view", "approval.approve", "crm_lead.approve", "customer_tag.review"],
    },
    {
        "key": "data",
        "label": "数据",
        "permissions": [
            "customer.view",
            "product.view",
            "supplier.view",
            "sales_detail.view",
            "purchase_detail.view",
            "inventory_snapshot.view",
            "account_balance.view",
            "inventory_check.view",
            "receivable.view",
        ],
    },
    {
        "key": "exceptions",
        "label": "异常",
        "permissions": ["exception_center.view"],
    },
]


def _safe_limit(limit: int) -> int:
    return max(1, min(limit, 50))


def _safe_offset(offset: int) -> int:
    return max(0, offset)


def _can(db: Session, user: User, *codes: str) -> bool:
    return any(has_permission(db, user, code) for code in codes)


def _visible_nav(db: Session, user: User) -> list[dict[str, Any]]:
    visible = [
        item
        for item in MOBILE_NAV
        if not item["permissions"] or _can(db, user, *item["permissions"])
    ]
    exception_nav_enabled = settings.mobile_feature_exception_center and settings.exception_center_enabled
    if exception_nav_enabled and any(item["key"] == "exceptions" for item in visible):
        return [item for item in visible if item["key"] != "data"]
    return [item for item in visible if item["key"] != "exceptions"]


def _mobile_scope_revision(db: Session, user: User, permissions: list[str]) -> str:
    return current_mobile_scope_revision(db, user, permissions)


def _approval_statuses(scope: str | None) -> list[str]:
    scopes = {
        "pending": ["submitted", "under_review"],
        "need_supplement": ["need_supplement"],
        "active": ["draft", "submitted", "under_review", "need_supplement"],
        "completed": ["completed", "approved"],
        "rejected": ["rejected"],
    }
    return scopes.get((scope or "pending").strip(), scopes["pending"])


def _count(stmt: Any, db: Session) -> int:
    return db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0


def _mobile_token_response(user: User, refresh_token: str) -> MobileTokenResponse:
    access_token = create_access_token(user.username, {"role": user.role, "user_id": user.id, "channel": "android"})
    return MobileTokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.access_token_expire_minutes * 60,
        user=UserPublic.model_validate(user),
    )


@router.post("/auth/login", response_model=MobileTokenResponse)
def mobile_login(
    payload: MobileLoginRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> MobileTokenResponse:
    user = db.scalar(select(User).where(User.username == payload.username.strip()))
    if user is None or not verify_password(payload.password, user.password_hash) or not user.is_active or user.status != "active":
        write_audit_log(
            db,
            action_type="mobile_login_failed",
            resource_type="auth",
            resource_id=payload.username,
            request=request,
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号或密码错误")
    refresh_token, session = issue_mobile_session(
        db,
        user=user,
        device_id=payload.device_id,
        device_name=payload.device_name,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        app_version=payload.app_version,
        android_version=payload.android_version,
        device_model=payload.device_model,
    )
    user.last_login_at = func.now()
    user.last_login_ip = request.client.host if request.client else None
    write_audit_log(
        db,
        action_type="mobile_login_success",
        resource_type="mobile_session",
        resource_id=str(session.id),
        user=user,
        request=request,
        after_data={"device_id": session.device_id, "device_name": session.device_name},
    )
    db.commit()
    return _mobile_token_response(user, refresh_token)


@router.post("/auth/refresh", response_model=MobileTokenResponse)
def mobile_refresh(
    payload: MobileRefreshRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> MobileTokenResponse:
    try:
        next_token, session = refresh_mobile_session(
            db,
            refresh_token=payload.refresh_token,
            device_id=payload.device_id,
        )
    except MobileSessionError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期，请重新登录") from exc
    user = db.get(User, session.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期，请重新登录")
    write_audit_log(
        db,
        action_type="mobile_token_refresh",
        resource_type="mobile_session",
        resource_id=str(session.id),
        user=user,
        request=request,
    )
    db.commit()
    return _mobile_token_response(user, next_token)


@router.post("/auth/logout", response_model=MobileLogoutResponse)
def mobile_logout(
    payload: MobileRefreshRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> MobileLogoutResponse:
    try:
        session = revoke_mobile_session(
            db,
            refresh_token=payload.refresh_token,
            device_id=payload.device_id,
        )
    except MobileSessionError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效") from exc
    user = db.get(User, session.user_id)
    write_audit_log(
        db,
        action_type="mobile_logout",
        resource_type="mobile_session",
        resource_id=str(session.id),
        user=user,
        request=request,
    )
    db.commit()
    return MobileLogoutResponse()


@router.get("/bootstrap")
def mobile_bootstrap(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    permissions = get_final_permission_codes(db, current_user)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "user": jsonable_encoder(current_user),
        "permissions": permissions,
        "scope_revision": _mobile_scope_revision(db, current_user, permissions),
        "navigation": _visible_nav(db, current_user),
        "app": {
            "name": "星河演示管理中心",
            "channel": "android",
            "mvp_scope": "crm-first",
            "page_size": 20,
            "latest_version": settings.mobile_latest_version,
            "latest_version_code": settings.mobile_latest_version_code,
            "minimum_supported_version": settings.mobile_minimum_supported_version,
            "minimum_supported_version_code": settings.mobile_minimum_supported_version_code,
            "download_url": settings.mobile_download_url,
            "apk_sha256": settings.mobile_apk_sha256,
            "update_mode": settings.mobile_update_mode if settings.mobile_update_mode in {"optional", "required"} else "optional",
            "release_notes": settings.mobile_release_notes,
            "onboarding_version": settings.mobile_onboarding_version,
            "help_enabled": settings.mobile_help_enabled,
            "feedback_enabled": settings.mobile_feedback_enabled,
            "mobile_feature_liquid_ui": settings.mobile_feature_liquid_ui,
            "mobile_feature_liquid_full_effect": settings.mobile_feature_liquid_full_effect,
            "mobile_feature_dark_theme": settings.mobile_feature_dark_theme,
            "force_reduced_glass": settings.mobile_force_reduced_glass,
            "ui_theme_version": settings.mobile_ui_theme_version,
            "feature_flags": {
                "project_application": settings.mobile_feature_project_application,
                "crm_customers": settings.mobile_feature_crm_customers,
                "crm_tasks": settings.mobile_feature_crm_tasks,
                "crm_followups": settings.mobile_feature_crm_followups,
                "crm_approvals": settings.mobile_feature_crm_approvals,
                "data_query": settings.mobile_feature_data_query,
                "checks": settings.mobile_feature_checks,
                "notifications": settings.mobile_feature_notifications,
                "scanner": settings.mobile_feature_scanner,
                "manager_dashboard": settings.mobile_feature_manager_dashboard,
                "ai": settings.mobile_feature_ai,
                "offline_read": settings.mobile_feature_offline_read,
                "offline_outbox": settings.mobile_feature_offline_outbox,
                "sync_conflict": settings.mobile_feature_sync_conflict,
                "in_app_update": settings.mobile_feature_in_app_update,
                "device_management": settings.mobile_feature_device_management,
                "operations_console": settings.mobile_feature_operations_console,
                "onboarding": settings.mobile_feature_onboarding,
                "in_app_feedback": settings.mobile_feature_in_app_feedback,
                "voice_input": settings.mobile_feature_voice_input,
                "contact_ocr": settings.mobile_feature_contact_ocr,
                "ai_drafts": settings.mobile_feature_ai_drafts,
                "smart_reminders": settings.mobile_feature_smart_reminders,
                "adoption_dashboard": settings.mobile_feature_adoption_dashboard,
                "exception_center": settings.mobile_feature_exception_center and settings.exception_center_enabled,
                "customer_tags": settings.mobile_feature_customer_tags,
                "fulfillment": settings.mobile_feature_fulfillment,
                "lead_pool": settings.mobile_feature_lead_pool,
                "lead_ocr": settings.mobile_feature_lead_ocr,
                "lead_offline": settings.mobile_feature_lead_offline,
                "lead_conversion": settings.mobile_feature_lead_conversion,
                "lead_product_intent": settings.mobile_feature_lead_product_intent,
                "lead_analytics": settings.mobile_feature_lead_analytics,
                "liquid_ui": settings.mobile_feature_liquid_ui,
                "liquid_full_effect": settings.mobile_feature_liquid_full_effect,
                "dark_theme": settings.mobile_feature_dark_theme,
                "lead_sla": settings.lead_sla,
                "lead_public_pool": settings.lead_public_pool,
                "lead_campaign": settings.lead_campaign,
                "lead_team_dashboard": settings.lead_team_dashboard,
                "lead_bulk_assignment": settings.lead_bulk_assignment,
            },
        },
    }


@router.get("/home")
def mobile_home(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    actions: list[dict[str, Any]] = []
    task_count = 0
    overdue_count = 0
    if _can(db, current_user, "crm_task.view"):
        now = datetime.now(timezone.utc)
        task_stmt = crm_task_scope_filter(select(CrmProjectCustomerTask), db, current_user).where(
            CrmProjectCustomerTask.is_closed.is_(False)
        )
        task_count = _count(task_stmt, db)
        overdue_stmt = task_stmt.where(
            CrmProjectCustomerTask.feedback_due_at.is_not(None),
            CrmProjectCustomerTask.feedback_due_at < now,
        )
        overdue_count = _count(overdue_stmt, db)
        if task_count:
            actions.append({
                "key": "crm_tasks",
                "title": "待推进任务",
                "detail": f"{task_count} 个客户任务待推进",
                "tone": "warn" if overdue_count else "neutral",
                "count": task_count,
                "target": {"page": "tasks"},
            })

    approval_count = 0
    approval_stmt = visible_approvals_stmt(db, current_user).where(
        ApprovalInstance.current_handler_user_id == current_user.id,
        ApprovalInstance.status.in_(["submitted", "under_review"]),
    )
    approval_count = _count(approval_stmt, db)
    if approval_count:
        actions.append({
            "key": "approvals",
            "title": "待我审批",
            "detail": f"{approval_count} 条审批等待处理",
            "tone": "warn",
            "count": approval_count,
            "target": {"page": "approvals"},
        })

    work_item_count = 0
    if _can(db, current_user, "crm_issue.view"):
        item_stmt = work_item_scope_filter(select(WorkItem), db, current_user).where(
            WorkItem.status.in_(sorted(OPEN_WORK_ITEM_STATUSES))
        )
        work_item_count = _count(item_stmt, db)
        if work_item_count:
            actions.append({
                "key": "work_items",
                "title": "待支持事项",
                "detail": f"{work_item_count} 条支持事项未处理",
                "tone": "bad",
                "count": work_item_count,
                "target": {"page": "work_items"},
            })

    draft_count = _count(
        visible_approvals_stmt(db, current_user).where(
            ApprovalInstance.applicant_user_id == current_user.id,
            ApprovalInstance.status == "draft",
        ),
        db,
    )
    supplement_count = _count(
        visible_approvals_stmt(db, current_user).where(
            ApprovalInstance.applicant_user_id == current_user.id,
            ApprovalInstance.status == "need_supplement",
        ),
        db,
    )
    if supplement_count:
        actions.append({
            "key": "need_supplement",
            "title": "待我补充",
            "detail": f"{supplement_count} 条申请需要补充后重新提交",
            "tone": "bad",
            "count": supplement_count,
            "target": {"page": "approvals", "scope": "need_supplement"},
        })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "task_open": task_count,
            "task_overdue": overdue_count,
            "approval_pending": approval_count,
            "work_item_open": work_item_count,
            "draft_count": draft_count,
            "supplement_count": supplement_count,
        },
        "actions": actions,
    }


def _require_project_create(db: Session, user: User) -> None:
    if not has_permission(db, user, "crm_project.create"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="缺少项目申请权限")


@router.get("/users/options", response_model=MobileUserOptionPage)
def mobile_user_options(
    q: str | None = None,
    limit: int = Query(20, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require_project_create(db, current_user)
    safe_limit = _safe_limit(limit)
    safe_offset = _safe_offset(offset)
    stmt = select(User).where(User.is_active.is_(True), User.status == "active")
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.username.ilike(like), User.real_name.ilike(like), User.employee_code.ilike(like)))
    total = _count(stmt, db)
    users = list(db.scalars(stmt.order_by(User.username.asc()).offset(safe_offset).limit(safe_limit)).all())
    return {
        "items": [
            {
                "id": user.id,
                "username": user.username,
                "real_name": user.real_name,
                "employee_code": user.employee_code,
                "role": user.role,
                "label": f"{user.real_name} / {user.username}",
            }
            for user in users
        ],
        "total": total,
        "limit": safe_limit,
        "offset": safe_offset,
    }


@router.get("/customers/options", response_model=MobileCustomerOptionPage)
def mobile_customer_options(
    q: str | None = None,
    limit: int = Query(20, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require_project_create(db, current_user)
    if not has_permission(db, current_user, "customer.view"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="缺少客户查看权限")
    page = list_customers_page(
        q=q,
        limit=_safe_limit(limit),
        offset=_safe_offset(offset),
        db=db,
        current_user=current_user,
    )
    fields = (
        "customer_code",
        "customer_name",
        "customer_short_name",
        "salesperson_employee_code",
        "salesperson_name",
        "contact_name",
        "contact_phone",
        "region",
        "customer_type",
    )
    return {
        "items": [{key: item.get(key) for key in fields} for item in page["items"]],
        "total": page["total"],
        "limit": page["limit"],
        "offset": page["offset"],
    }


@router.get("/projects/my-submissions", response_model=MobileProjectSubmissionPage)
def mobile_project_submissions(
    scope: str | None = "active",
    q: str | None = None,
    limit: int = Query(20, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    safe_limit = _safe_limit(limit)
    safe_offset = _safe_offset(offset)
    stmt = select(ApprovalInstance).where(
        ApprovalInstance.applicant_user_id == current_user.id,
        ApprovalInstance.approval_type == "crm_project_create",
    )
    if scope:
        stmt = stmt.where(ApprovalInstance.status.in_(_approval_statuses(scope)))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(ApprovalInstance.approval_no.ilike(like), ApprovalInstance.title.ilike(like)))
    total = _count(stmt, db)
    rows = list(
        db.scalars(
            stmt.order_by(ApprovalInstance.updated_at.desc(), ApprovalInstance.id.desc())
            .offset(safe_offset)
            .limit(safe_limit)
        ).all()
    )
    return {
        "items": [_approval_public(db, row) for row in rows],
        "total": total,
        "limit": safe_limit,
        "offset": safe_offset,
    }


@router.post("/projects/approval-draft", status_code=status.HTTP_201_CREATED)
def mobile_create_project_approval_draft(
    payload: CrmProjectApprovalDraftCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    _require_project_create(db, current_user)
    return create_crm_project_approval_draft(payload=payload, request=request, db=db, current_user=current_user)


def _mobile_project_payload(
    payload: CrmProjectApprovalDraftCreate,
    db: Session,
    current_user: User,
) -> dict[str, Any]:
    project = payload.project.model_dump()
    project["applicant_user_id"] = current_user.id
    if not project.get("landing_approver_user_id"):
        admin = db.scalar(
            select(User).where(User.username == "admin", User.is_active.is_(True), User.status == "active")
        )
        if admin is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="项目落地审批人缺失")
        project["landing_approver_user_id"] = admin.id
    if not project.get("owner_user_id"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请选择细节审批人")

    participant_ids = list(dict.fromkeys(int(user_id) for user_id in project.get("participant_user_ids") or []))
    project["participant_user_ids"] = participant_ids
    project["progress_cc_user_ids"] = list(
        dict.fromkeys(int(user_id) for user_id in project.get("progress_cc_user_ids") or [])
    )
    for field_name in ("landing_approver_user_id", "owner_user_id"):
        user = db.get(User, project[field_name])
        if user is None or not user.is_active or user.status != "active":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{field_name} 对应账号不可用")
    for field_name in ("participant_user_ids", "progress_cc_user_ids"):
        for user_id in project[field_name]:
            user = db.get(User, user_id)
            if user is None or not user.is_active or user.status != "active":
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{field_name} 包含不可用账号")

    if not payload.tasks:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="项目申请至少需要选择 1 个客户")
    seen: set[str] = set()
    tasks: list[dict[str, Any]] = []
    for task in payload.tasks:
        item = task.model_dump()
        code = item["customer_code"].strip()
        if code in seen:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"客户重复：{code}")
        seen.add(code)
        require_customer(db, code)
        validate_task_status(item["status"])
        task_executor_snapshot(db, item.get("executor_user_id"), item.get("executor_employee_code"))
        executor_id = item.get("executor_user_id")
        if executor_id and participant_ids and int(executor_id) not in participant_ids:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"客户 {code} 的执行人不在一线业务员范围内")
        if not executor_id and not project.get("allow_unassigned_tasks"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"客户 {code} 尚未分配执行人")
        tasks.append(item)
    return {"project": project, "tasks": tasks}


@router.patch("/projects/approval-draft/{approval_id}")
def mobile_update_project_approval_draft(
    approval_id: int,
    payload: CrmProjectApprovalDraftCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    _require_project_create(db, current_user)
    approval = db.get(ApprovalInstance, approval_id)
    if approval is None or approval.approval_type != "crm_project_create" or approval.applicant_user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目申请草稿不存在")
    normalized = _mobile_project_payload(payload, db, current_user)
    return update_approval_draft(
        approval_id=approval_id,
        payload=ApprovalDraftUpdate(
            title=payload.title or f"客户项目立项：{payload.project.project_name}",
            description=payload.description,
            current_handler_user_id=normalized["project"]["landing_approver_user_id"],
            priority=payload.priority,
            payload_json=normalized,
        ),
        request=request,
        db=db,
        current_user=current_user,
    )


@router.post("/projects/approval-draft/{approval_id}/submit")
def mobile_submit_project_approval_draft(
    approval_id: int,
    request: Request,
    payload: ApprovalActionRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    approval = db.get(ApprovalInstance, approval_id)
    if approval is None or approval.approval_type != "crm_project_create" or approval.applicant_user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目申请草稿不存在")
    return submit_approval(
        approval_id=approval_id,
        request=request,
        payload=payload,
        db=db,
        current_user=current_user,
    )


@router.get("/customers/linked")
def mobile_linked_customers(
    q: str | None = None,
    scope: str | None = None,
    limit: int = Query(20, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    return list_crm_linked_customers_page(
        q=q,
        scope=scope,
        limit=_safe_limit(limit),
        offset=_safe_offset(offset),
        db=db,
        current_user=current_user,
    )


@router.get("/customers/{customer_code}/context")
def mobile_customer_context(
    customer_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    return get_crm_linked_customer_context(customer_code=customer_code, db=db, current_user=current_user)


@router.get("/tasks/{task_id}")
def mobile_task_detail(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    return get_crm_task_detail(task_id=task_id, db=db, current_user=current_user)


@router.get("/tasks")
def mobile_tasks(
    q: str | None = None,
    status_value: str | None = None,
    customer_code: str | None = None,
    overdue: bool | None = None,
    is_blocked: bool | None = None,
    need_support: bool | None = None,
    is_closed: bool | None = None,
    limit: int = Query(20, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    if not has_permission(db, current_user, "crm_task.view"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="缺少任务查看权限")
    return list_crm_tasks_page(
        q=q,
        customer_code=customer_code,
        status_value=status_value,
        overdue=overdue,
        is_blocked=is_blocked,
        need_support=need_support,
        is_closed=is_closed,
        limit=_safe_limit(limit),
        offset=_safe_offset(offset),
        db=db,
        current_user=current_user,
    )


@router.post("/followups", status_code=status.HTTP_201_CREATED)
def mobile_create_followup(
    payload: CrmFollowupApprovalDraftCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    if not has_permission(db, current_user, "crm_followup.submit"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="缺少跟进提交权限")
    return create_crm_followup_approval_draft(payload=payload, request=request, db=db, current_user=current_user)


@router.post("/customers/{customer_code}/profile")
def mobile_update_customer_profile(
    customer_code: str,
    payload: CustomerMasterUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    if not has_permission(db, current_user, "crm_customer_profile.submit"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="缺少客户基本资料保存权限")
    return update_crm_linked_customer_profile(
        customer_code=customer_code,
        payload=payload,
        request=request,
        db=db,
        current_user=current_user,
    )


@router.get("/customers/{customer_code}/business-profile")
def mobile_customer_business_profile(
    customer_code: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    if not has_permission(db, current_user, "crm_business_profile.view"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="缺少经营资料查看权限")
    return get_crm_linked_customer_business_profile(
        customer_code=customer_code,
        request=request,
        db=db,
        current_user=current_user,
    )


@router.post("/customers/{customer_code}/business-profile")
def mobile_update_business_profile(
    customer_code: str,
    payload: CustomerBusinessProfileUpsert,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    if not has_permission(db, current_user, "crm_business_profile.submit"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="缺少经营资料保存权限")
    return update_crm_linked_customer_business_profile(
        customer_code=customer_code,
        payload=payload,
        request=request,
        db=db,
        current_user=current_user,
    )


@router.get("/work-items")
def mobile_work_items(
    q: str | None = None,
    open_only: bool = True,
    limit: int = Query(20, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    if not has_permission(db, current_user, "crm_issue.view"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="缺少待支持查看权限")
    return list_work_items_page(
        q=q,
        open_only=open_only,
        limit=_safe_limit(limit),
        offset=_safe_offset(offset),
        db=db,
        current_user=current_user,
    )


@router.post("/work-items/{item_id}/actions")
def mobile_work_item_action(
    item_id: int,
    action: Literal["resolve", "close"],
    payload: WorkItemActionRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    permission = "crm_issue.close" if action == "close" else "crm_issue.handle"
    if not has_permission(db, current_user, permission):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="缺少待支持处理权限")
    if action == "close":
        return close_work_item(item_id=item_id, payload=payload, request=request, db=db, current_user=current_user)
    return resolve_work_item(item_id=item_id, payload=payload, request=request, db=db, current_user=current_user)


@router.get("/approvals")
def mobile_approvals(
    q: str | None = None,
    scope: str | None = "pending",
    mode: Literal["to_handle", "mine"] = "to_handle",
    limit: int = Query(20, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    safe_limit = _safe_limit(limit)
    safe_offset = _safe_offset(offset)
    stmt = visible_approvals_stmt(db, current_user)
    if mode == "mine":
        stmt = stmt.where(
            or_(
                ApprovalInstance.applicant_user_id == current_user.id,
                ApprovalInstance.current_handler_user_id == current_user.id,
            )
        )
    else:
        stmt = stmt.where(ApprovalInstance.current_handler_user_id == current_user.id)
    stmt = stmt.where(ApprovalInstance.status.in_(_approval_statuses(scope)))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                ApprovalInstance.approval_no.ilike(like),
                ApprovalInstance.title.ilike(like),
                ApprovalInstance.description.ilike(like),
                ApprovalInstance.resource_id.ilike(like),
            )
        )
    total = _count(stmt, db)
    rows = list(db.scalars(stmt.order_by(ApprovalInstance.updated_at.desc(), ApprovalInstance.id.desc()).offset(safe_offset).limit(safe_limit)).all())
    return {
        "items": [_approval_public(db, row, current_user) for row in rows],
        "total": total,
        "limit": safe_limit,
        "offset": safe_offset,
    }


@router.get("/approvals/{approval_id}")
def mobile_approval_detail(
    approval_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    approval = visible_approval_or_404(db, current_user, approval_id)
    return _approval_detail(db, approval, current_user)


@router.post("/approvals/{approval_id}/actions")
def mobile_approval_action(
    approval_id: int,
    request: Request,
    action: Literal["approve", "reject", "supplement_request"],
    payload: ApprovalActionRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    action_payload = payload or ApprovalActionRequest()
    if action == "approve":
        return approve_approval(approval_id=approval_id, request=request, payload=action_payload, db=db, current_user=current_user)
    if action == "reject":
        return reject_approval(approval_id=approval_id, request=request, payload=action_payload, db=db, current_user=current_user)
    if action == "supplement_request":
        return request_approval_supplement(approval_id=approval_id, request=request, payload=action_payload, db=db, current_user=current_user)
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported approval action")


@router.post("/approvals/{approval_id}/attachments", status_code=status.HTTP_201_CREATED)
def mobile_upload_approval_attachment(
    approval_id: int,
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    return upload_approval_attachment(
        approval_id=approval_id,
        request=request,
        file=file,
        db=db,
        current_user=current_user,
    )

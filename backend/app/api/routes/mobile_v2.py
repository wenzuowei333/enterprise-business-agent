from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.models import (
    AiActionProposal,
    ApprovalInstance,
    CrmProject,
    CrmProjectCustomerTask,
    CustomerMaster,
    DeliveryTask,
    ExceptionCase,
    MobileOperationLog,
    SalesOrder,
    User,
    WorkItem,
)
from app.api.routes.crm_projects import get_crm_linked_customer_context
from app.api.routes.exceptions import diagnosis_job, exception_detail, request_diagnosis
from app.api.routes.global_ai_actions import execute_controlled_action, validate_controlled_exception_action
from app.schemas.crm import CrmProjectCustomerTaskPublic
from app.schemas.exception_center import DiagnosisRequest
from app.schemas.global_ai import ControlledActionExecuteRequest, ControlledExceptionActionValidationRequest
from app.schemas.fulfillment import DeliveryEventCreate
from app.schemas.mobile import MobileDeliveryEventRequest
from app.services.access_control_service import apply_data_scope
from app.services.approval_access_service import visible_approvals_stmt
from app.services.crm_access_service import crm_project_scope_filter, crm_task_scope_filter
from app.services.permission_service import has_permission
from app.services.customer_tagging_service import customer_tag_profile, require_feature
from app.services.fulfillment_service import apply_delivery_event, serialize_delivery
from app.services.mobile_sync_service import mobile_operation_payload_hash
from app.services.controlled_action_service import (
    controlled_actions_enabled,
    serialize_action_proposal,
    visible_action_proposal_or_404,
    visible_action_proposals_stmt,
)
from app.services.exception_center_service import scoped_exception_stmt, serialize_cases, summary_for_cases
from app.services.work_item_service import OPEN_WORK_ITEM_STATUSES, work_item_scope_filter


router = APIRouter(prefix="/v2", tags=["mobile-v2"])


def _count(db: Session, stmt: Any) -> int:
    return db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0


def _can(db: Session, user: User, permission: str) -> bool:
    return has_permission(db, user, permission)


def _visible_project_stmt(db: Session, user: User) -> Any:
    if _can(db, user, "crm_project.view"):
        return crm_project_scope_filter(select(CrmProject), db, user)
    if _can(db, user, "crm_task.view"):
        visible_project_ids = crm_task_scope_filter(
            select(CrmProjectCustomerTask.project_id).distinct(),
            db,
            user,
        )
        return select(CrmProject).where(CrmProject.id.in_(visible_project_ids))
    return select(CrmProject).where(CrmProject.id == -1)


def _task_item(task: CrmProjectCustomerTask, now: datetime) -> dict[str, Any]:
    overdue = task.feedback_due_at is not None and task.feedback_due_at < now
    return {
        "key": f"task:{task.id}",
        "kind": "task_overdue" if overdue else "task_due",
        "title": task.customer_name_snapshot,
        "subtitle": task.latest_owner_next_action or task.round_target or task.business_issue_point or "客户任务待推进",
        "status_label": "已超期" if overdue else "临近到期",
        "tone": "bad" if overdue else "warn",
        "due_at": task.feedback_due_at,
        "target": {"page": "projects", "task_id": task.id, "project_id": task.project_id},
    }


def _approval_item(approval: ApprovalInstance) -> dict[str, Any]:
    return {
        "key": f"approval:{approval.id}",
        "kind": "approval",
        "title": approval.title,
        "subtitle": "等待我审批",
        "status_label": "待审批",
        "tone": "warn",
        "due_at": approval.submitted_at,
        "target": {"page": "approvals", "approval_id": approval.id},
    }


def _work_item(item: WorkItem) -> dict[str, Any]:
    return {
        "key": f"work_item:{item.id}",
        "kind": "support",
        "title": item.title,
        "subtitle": item.detail or "待支持事项需要处理",
        "status_label": "待支持",
        "tone": "bad" if item.priority in {"high", "urgent"} else "warn",
        "due_at": item.due_at,
        "target": {"page": "work_items", "work_item_id": item.id},
    }


def _timeline_item(
    *,
    key: str,
    kind: str,
    title: str,
    detail: str | None,
    status_value: str | None,
    occurred_at: str | None,
    target: dict[str, Any],
) -> dict[str, Any]:
    return {
        "key": key,
        "kind": kind,
        "title": title,
        "detail": detail,
        "status": status_value,
        "occurred_at": occurred_at,
        "target": target,
    }


def _timeline_sort_key(item: dict[str, Any]) -> tuple[datetime, str]:
    raw_value = str(item.get("occurred_at") or "").strip()
    try:
        occurred_at = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=timezone.utc)
        occurred_at = occurred_at.astimezone(timezone.utc)
    except ValueError:
        occurred_at = datetime.min.replace(tzinfo=timezone.utc)
    return occurred_at, str(item.get("key") or "")


def _execution_project_item(project: CrmProject, task_counts: dict[int, tuple[int, int, int, int]]) -> dict[str, Any]:
    total, open_count, support_count, blocked_count = task_counts.get(project.id, (0, 0, 0, 0))
    return {
        "id": project.id,
        "project_code": project.project_code,
        "project_name": project.project_name,
        "project_type": project.project_type,
        "purpose": project.purpose,
        "status": project.status,
        "approval_status": project.approval_status,
        "start_date": project.start_date,
        "due_date": project.due_date,
        "overdue": bool(project.due_date and project.due_date < date.today() and project.status not in {"closed", "cancelled"}),
        "task_total": total,
        "task_open": open_count,
        "task_need_support": support_count,
        "task_blocked": blocked_count,
        "next_step_action": project.next_step_action,
    }


def _require_mobile_exception_access(db: Session, user: User) -> None:
    if not settings.exception_center_enabled or not settings.mobile_feature_exception_center:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="移动异常中心暂未开放")
    if not _can(db, user, "exception_center.view"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问异常中心")


def _mobile_exception_item(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "id", "case_no", "domain", "diagnosis_supported", "rule_code", "title", "severity", "status",
        "occurrence_type", "resource_type", "resource_id", "resource_code", "resource_name", "source_type",
        "source_batch_kind", "source_batch_id", "data_date", "evidence_version", "reason", "initial_guidance",
        "action_path", "affected_rows", "affected_amount", "affected_quantity", "assignee_user_id",
        "assignee_name", "due_at", "detected_at", "last_seen_at", "sla_status", "is_mine", "processing_kind",
    }
    return {key: value for key, value in payload.items() if key in allowed}


@router.get("/exceptions")
def mobile_v2_exceptions(
    domain: str | None = Query(default=None, pattern="^(inventory|receivable|master_data|import|crm|approval)$"),
    severity: str | None = Query(default=None, pattern="^(warning|high|critical)$"),
    case_status: str | None = Query(default=None, pattern="^(open|action_required|processing|blocked|resolved|ignored)$"),
    assignment: str | None = Query(default=None, pattern="^(mine|unassigned)$"),
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require_mobile_exception_access(db, current_user)
    safe_limit = max(1, min(limit, 50))
    safe_offset = max(0, offset)
    stmt = scoped_exception_stmt(db, current_user)

    if domain:
        stmt = stmt.where(ExceptionCase.domain == domain)
    if severity:
        stmt = stmt.where(ExceptionCase.severity == severity)
    if case_status:
        stmt = stmt.where(ExceptionCase.status == case_status)
    if assignment == "mine":
        stmt = stmt.where(ExceptionCase.assignee_user_id == current_user.id)
    elif assignment == "unassigned":
        stmt = stmt.where(ExceptionCase.assignee_user_id.is_(None))
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(
            ExceptionCase.case_no.ilike(like),
            ExceptionCase.title.ilike(like),
            ExceptionCase.resource_code.ilike(like),
            ExceptionCase.resource_name.ilike(like),
        ))
    total = _count(db, stmt)
    rows = list(
        db.scalars(
            stmt.order_by(
                case((ExceptionCase.severity == "critical", 0), (ExceptionCase.severity == "high", 1), else_=2),
                ExceptionCase.last_seen_at.desc(),
                ExceptionCase.id.desc(),
            ).offset(safe_offset).limit(safe_limit)
        ).all()
    )
    items = [_mobile_exception_item(item) for item in serialize_cases(db, rows, current_user_id=current_user.id)]
    summary = summary_for_cases(db, current_user)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "items": items,
        "total": total,
        "limit": safe_limit,
        "offset": safe_offset,
        "capabilities": {
            "diagnose": _can(db, current_user, "exception_center.diagnose") and settings.exception_ai_enabled,
            "execute_action": _can(db, current_user, "exception_center.action_execute") and settings.exception_actions_enabled,
        },
    }


@router.get("/exceptions/{case_no}")
def mobile_v2_exception_detail(
    case_no: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require_mobile_exception_access(db, current_user)
    payload = exception_detail(case_no=case_no, db=db, current_user=current_user)
    item = _mobile_exception_item(payload)
    item["evidence"] = payload.get("evidence")
    item["diagnoses"] = payload.get("diagnoses", [])
    item["events"] = payload.get("events", [])
    item["active_diagnosis_job"] = payload.get("active_diagnosis_job")
    item["actions"] = [
        {key: value for key, value in action.items() if key not in {"validation_token", "result"}}
        for action in payload.get("actions", [])
    ]
    item["capabilities"] = {
        "diagnose": _can(db, current_user, "exception_center.diagnose") and settings.exception_ai_enabled,
        "execute_action": _can(db, current_user, "exception_center.action_execute") and settings.exception_actions_enabled,
    }
    return item


@router.post("/exceptions/{case_no}/diagnoses", status_code=status.HTTP_202_ACCEPTED)
def mobile_v2_request_diagnosis(
    case_no: str,
    body: DiagnosisRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require_mobile_exception_access(db, current_user)
    if not _can(db, current_user, "exception_center.diagnose"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权发起异常诊断")
    if not settings.exception_ai_enabled:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="异常诊断服务暂未开放")
    return request_diagnosis(
        case_no=case_no,
        body=body,
        db=db,
        feature_enabled=None,
        current_user=current_user,
    )


@router.get("/diagnosis-jobs/{job_id}")
def mobile_v2_diagnosis_job(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require_mobile_exception_access(db, current_user)
    if not _can(db, current_user, "exception_center.diagnose"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权查看诊断任务")
    return diagnosis_job(job_id=job_id, db=db, current_user=current_user)


def _require_mobile_action_access(db: Session, user: User) -> None:
    _require_mobile_exception_access(db, user)
    if not _can(db, user, "exception_center.action_execute"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权执行受控动作")
    if not controlled_actions_enabled() or not settings.exception_ai_high_risk_actions_enabled or not settings.exception_actions_enabled:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="受控动作暂未开放")


@router.get("/ai/actions")
def mobile_v2_ai_actions(
    domain: str | None = Query(default=None, pattern="^(inventory|receivable|master_data|import)$"),
    review_status: str | None = Query(default="pending", pattern="^(pending|accepted|rejected)$"),
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require_mobile_action_access(db, current_user)
    stmt = visible_action_proposals_stmt(db, current_user).where(
        AiActionProposal.source_system == "exception",
        AiActionProposal.resource_type == "exception_case",
    )
    if domain:
        stmt = stmt.where(AiActionProposal.domain == domain)
    if review_status:
        stmt = stmt.where(AiActionProposal.review_status == review_status)
    total = _count(db, stmt)
    rows = list(
        db.scalars(
            stmt.order_by(AiActionProposal.updated_at.desc(), AiActionProposal.id.desc())
            .offset(offset)
            .limit(limit)
        ).all()
    )
    return {
        "items": [serialize_action_proposal(db, current_user, row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/ai/actions/{proposal_no}/validate")
def mobile_v2_validate_ai_action(
    proposal_no: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    _require_mobile_action_access(db, current_user)
    proposal = visible_action_proposal_or_404(db, current_user, proposal_no)
    if proposal.source_system != "exception" or proposal.resource_type != "exception_case" or not proposal.resource_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该提案不支持移动端执行")
    body = ControlledExceptionActionValidationRequest(
        action_type=proposal.action_type,
        parameters=proposal.parameters_json or {},
    )
    return validate_controlled_exception_action(
        case_no=proposal.resource_id,
        body=body,
        request=request,
        db=db,
        current_user=current_user,
    )


@router.post("/ai/actions/{proposal_no}/execute")
def mobile_v2_execute_ai_action(
    proposal_no: str,
    body: ControlledActionExecuteRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    _require_mobile_action_access(db, current_user)
    proposal = visible_action_proposal_or_404(db, current_user, proposal_no)
    if proposal.source_system != "exception" or proposal.resource_type != "exception_case":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该提案不支持移动端执行")
    return execute_controlled_action(
        proposal_no=proposal_no,
        body=body,
        request=request,
        db=db,
        current_user=current_user,
    )


@router.get("/execution")
def mobile_v2_execution(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    projects: list[CrmProject] = []
    task_rows: list[CrmProjectCustomerTask] = []
    project_total = active_project_total = overdue_project_total = 0
    my_task_total = overdue_task_total = support_task_total = blocked_task_total = 0

    if _can(db, current_user, "crm_project.view") or _can(db, current_user, "crm_task.view"):
        project_stmt = _visible_project_stmt(db, current_user)
        project_total = _count(db, project_stmt)
        active_project_stmt = project_stmt.where(CrmProject.status.not_in(["closed", "cancelled"]))
        active_project_total = _count(db, active_project_stmt)
        overdue_project_total = _count(
            db,
            active_project_stmt.where(CrmProject.due_date.is_not(None), CrmProject.due_date < date.today()),
        )
        projects = list(
            db.scalars(
                project_stmt.order_by(CrmProject.due_date.asc().nullslast(), CrmProject.id.desc()).limit(30)
            ).all()
        )

    task_counts: dict[int, tuple[int, int, int, int]] = {}
    if projects and _can(db, current_user, "crm_task.view"):
        project_ids = [project.id for project in projects]
        count_stmt = crm_task_scope_filter(
            select(
                CrmProjectCustomerTask.project_id,
                func.count(CrmProjectCustomerTask.id),
                func.sum(case((CrmProjectCustomerTask.is_closed.is_(False), 1), else_=0)),
                func.sum(case((CrmProjectCustomerTask.need_support.is_(True), 1), else_=0)),
                func.sum(case((CrmProjectCustomerTask.is_blocked.is_(True), 1), else_=0)),
            )
            .where(CrmProjectCustomerTask.project_id.in_(project_ids))
            .group_by(CrmProjectCustomerTask.project_id),
            db,
            current_user,
        )
        count_rows = db.execute(count_stmt).all()
        task_counts = {
            int(project_id): (int(total or 0), int(open_count or 0), int(support_count or 0), int(blocked_count or 0))
            for project_id, total, open_count, support_count, blocked_count in count_rows
        }

    if _can(db, current_user, "crm_task.view"):
        my_task_stmt = crm_task_scope_filter(
            select(CrmProjectCustomerTask).where(CrmProjectCustomerTask.executor_user_id == current_user.id),
            db,
            current_user,
        )
        open_task_stmt = my_task_stmt.where(CrmProjectCustomerTask.is_closed.is_(False))
        my_task_total = _count(db, open_task_stmt)
        overdue_task_total = _count(
            db,
            open_task_stmt.where(
                CrmProjectCustomerTask.feedback_due_at.is_not(None),
                CrmProjectCustomerTask.feedback_due_at < now,
            ),
        )
        support_task_total = _count(db, open_task_stmt.where(CrmProjectCustomerTask.need_support.is_(True)))
        blocked_task_total = _count(db, open_task_stmt.where(CrmProjectCustomerTask.is_blocked.is_(True)))
        task_rows = list(
            db.scalars(
                my_task_stmt
                .order_by(CrmProjectCustomerTask.is_closed.asc(), CrmProjectCustomerTask.feedback_due_at.asc().nullslast(), CrmProjectCustomerTask.id.desc())
                .limit(50)
            ).all()
        )

    pending_approvals = supplement_requests = 0
    if _can(db, current_user, "approval.view") or _can(db, current_user, "approval.approve"):
        approval_stmt = visible_approvals_stmt(db, current_user)
        pending_approvals = _count(
            db,
            approval_stmt.where(
                ApprovalInstance.current_handler_user_id == current_user.id,
                ApprovalInstance.status.in_(["submitted", "under_review"]),
            ),
        )
        supplement_requests = _count(
            db,
            approval_stmt.where(
                ApprovalInstance.applicant_user_id == current_user.id,
                ApprovalInstance.status == "need_supplement",
            ),
        )

    return {
        "generated_at": now.isoformat(),
        "summary": {
            "project_total": project_total,
            "active_projects": active_project_total,
            "overdue_projects": overdue_project_total,
            "my_open_tasks": my_task_total,
            "overdue_tasks": overdue_task_total,
            "support_tasks": support_task_total,
            "blocked_tasks": blocked_task_total,
            "pending_approvals": pending_approvals,
            "supplement_requests": supplement_requests,
        },
        "projects": {
            "items": [_execution_project_item(project, task_counts) for project in projects],
            "total": project_total,
        },
        "my_tasks": {
            "items": jsonable_encoder([CrmProjectCustomerTaskPublic.model_validate(task) for task in task_rows]),
            "total": len(task_rows),
        },
        "capabilities": {
            "create_project": _can(db, current_user, "crm_project.create"),
            "submit_followup": _can(db, current_user, "crm_followup.submit"),
            "view_approvals": _can(db, current_user, "approval.view") or _can(db, current_user, "approval.approve"),
        },
    }


@router.get("/customers/{customer_code}/panorama")
def mobile_v2_customer_panorama(
    customer_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    context = get_crm_linked_customer_context(customer_code=customer_code, db=db, current_user=current_user)
    crm = context.get("crm") if isinstance(context.get("crm"), dict) else {}
    projects = crm.get("projects") if isinstance(crm.get("projects"), list) else []
    tasks = crm.get("tasks") if isinstance(crm.get("tasks"), list) else []
    followups = crm.get("followups") if isinstance(crm.get("followups"), list) else []
    work_items = crm.get("work_items") if isinstance(crm.get("work_items"), list) else []
    approvals = crm.get("approvals") if isinstance(crm.get("approvals"), list) else []
    if not any((projects, tasks, followups, work_items, context.get("business_profile"))):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="客户不在当前数据范围内")

    customer = db.scalar(select(CustomerMaster).where(CustomerMaster.customer_code == customer_code))
    safe_tags: list[dict[str, Any]] = []
    compatibility_tags: list[str] = []
    review_due_count = 0
    can_view_tags = any(
        _can(db, current_user, permission)
        for permission in (
            "customer.view",
            "crm_customer_profile.view",
            "customer_tag.submit",
            "customer_tag.review",
            "customer_tag.history",
        )
    )
    if customer is not None and can_view_tags:
        tag_profile = customer_tag_profile(
            db,
            customer,
            include_history=_can(db, current_user, "customer_tag.history"),
        )
        safe_tags = [
            {
                "id": item.get("id"),
                "name": item.get("tag_name"),
                "category": item.get("category_name") or item.get("category_key"),
                "color": item.get("color_key"),
                "is_primary": bool(item.get("is_primary")),
                "review_date": item.get("review_date"),
                "status": item.get("status"),
            }
            for item in tag_profile.get("assignments", [])
            if item.get("status") == "effective" or _can(db, current_user, "customer_tag.history")
        ]
        compatibility_tags = [str(item) for item in tag_profile.get("compatibility_tags", [])]
        review_due_count = int(tag_profile.get("review_due_count") or 0)

    timeline: list[dict[str, Any]] = []
    for item in followups:
        timeline.append(_timeline_item(
            key=f"followup:{item.get('id')}",
            kind="followup",
            title="客户跟进",
            detail=item.get("customer_feedback") or item.get("current_need") or item.get("next_action"),
            status_value=item.get("review_status"),
            occurred_at=item.get("created_at") or item.get("followup_date"),
            target={"page": "projects", "task_id": item.get("task_id"), "followup_id": item.get("id")},
        ))
    for item in tasks:
        timeline.append(_timeline_item(
            key=f"task:{item.get('id')}",
            kind="task",
            title=item.get("task_code") or "客户任务",
            detail=item.get("latest_owner_next_action") or item.get("round_target") or item.get("business_issue_point"),
            status_value=item.get("status"),
            occurred_at=item.get("updated_at") or item.get("created_at"),
            target={"page": "projects", "task_id": item.get("id"), "project_id": item.get("project_id")},
        ))
    for item in work_items:
        timeline.append(_timeline_item(
            key=f"work_item:{item.get('id')}",
            kind="support",
            title=item.get("title") or "待支持事项",
            detail=item.get("detail"),
            status_value=item.get("status"),
            occurred_at=item.get("updated_at") or item.get("created_at"),
            target={"page": "work_items", "work_item_id": item.get("id")},
        ))
    for item in approvals:
        timeline.append(_timeline_item(
            key=f"approval:{item.get('id')}",
            kind="approval",
            title=item.get("title") or "审批",
            detail=None,
            status_value=item.get("status"),
            occurred_at=item.get("reviewed_at") or item.get("submitted_at") or item.get("created_at"),
            target={"page": "approvals", "approval_id": item.get("id")},
        ))
    timeline.sort(key=_timeline_sort_key, reverse=True)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "customer": context.get("customer") or {"customer_code": customer_code, "customer_name": customer_code},
        "stats": crm.get("stats") or {},
        "tags": {
            "items": safe_tags,
            "compatibility_tags": compatibility_tags,
            "review_due_count": review_due_count,
        },
        "projects": [
            {
                "id": item.get("id"),
                "project_code": item.get("project_code"),
                "project_name": item.get("project_name"),
                "status": item.get("status"),
                "due_date": item.get("due_date"),
                "task_open": item.get("task_open") or 0,
                "task_total": item.get("task_total") or 0,
            }
            for item in projects[:20]
        ],
        "tasks": tasks[:50],
        "timeline": timeline[:30],
        "capabilities": {
            "edit_profile": _can(db, current_user, "crm_customer_profile.submit"),
            "edit_business_profile": _can(db, current_user, "crm_business_profile.submit"),
            "view_tag_history": _can(db, current_user, "customer_tag.history"),
        },
    }


@router.get("/customers/{customer_code}/tags")
def mobile_v2_customer_tags(
    customer_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    if not settings.mobile_feature_customer_tags:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="移动客户标签暂未开放")
    panorama = mobile_v2_customer_panorama(customer_code=customer_code, db=db, current_user=current_user)
    return {
        "generated_at": panorama["generated_at"],
        "customer": panorama["customer"],
        "tags": panorama["tags"],
        "capabilities": {
            "view_history": _can(db, current_user, "customer_tag.history"),
            "submit_change": _can(db, current_user, "customer_tag.submit"),
        },
    }


def _require_mobile_fulfillment(db: Session, user: User, permission: str) -> None:
    if not settings.mobile_feature_fulfillment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="移动配送履约暂未开放")
    if not _can(db, user, permission):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问配送履约")
    require_feature(db, "fulfillment_enabled")


def _visible_delivery_stmt(db: Session, user: User) -> Any:
    visible_customer_codes = apply_data_scope(
        select(CustomerMaster.customer_code),
        CustomerMaster,
        db,
        user,
        "customer",
    )
    visible_order_ids = select(SalesOrder.id).where(SalesOrder.customer_code.in_(visible_customer_codes))
    return select(DeliveryTask).where(DeliveryTask.order_id.in_(visible_order_ids))


def _mobile_delivery_payload(db: Session, delivery: DeliveryTask) -> dict[str, Any]:
    source = serialize_delivery(db, delivery)
    return {
        key: source.get(key)
        for key in (
            "id",
            "delivery_no",
            "order_id",
            "order_no",
            "customer_code",
            "customer_name",
            "status",
            "planned_at",
            "delivery_address",
            "requirements_json",
            "assignee_user_id",
            "signed_by",
            "signed_at",
            "exception_note",
            "created_at",
            "updated_at",
            "events",
        )
    }


@router.get("/deliveries")
def mobile_v2_deliveries(
    q: str | None = None,
    delivery_status: str | None = Query(
        default=None,
        alias="status",
        pattern="^(pending|planned|delivering|delivered|exception|cancelled)$",
    ),
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require_mobile_fulfillment(db, current_user, "delivery.view")
    stmt = _visible_delivery_stmt(db, current_user).join(SalesOrder, SalesOrder.id == DeliveryTask.order_id)
    if delivery_status:
        stmt = stmt.where(DeliveryTask.status == delivery_status)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                DeliveryTask.delivery_no.ilike(like),
                SalesOrder.order_no.ilike(like),
                SalesOrder.customer_code.ilike(like),
                SalesOrder.customer_name_snapshot.ilike(like),
            )
        )
    total = _count(db, stmt)
    rows = list(
        db.scalars(
            stmt.order_by(DeliveryTask.updated_at.desc(), DeliveryTask.id.desc())
            .offset(offset)
            .limit(limit)
        ).all()
    )
    return {
        "items": [_mobile_delivery_payload(db, row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
        "capabilities": {"manage": _can(db, current_user, "delivery.manage")},
    }


@router.post("/deliveries/{delivery_id}/events")
def mobile_v2_add_delivery_event(
    delivery_id: int,
    body: MobileDeliveryEventRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require_mobile_fulfillment(db, current_user, "delivery.manage")
    delivery = db.scalar(
        _visible_delivery_stmt(db, current_user)
        .where(DeliveryTask.id == delivery_id)
        .with_for_update()
    )
    if delivery is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="配送任务不存在或超出数据范围")

    operation_payload = body.model_dump(mode="json", exclude={"idempotency_key"})
    payload_hash = mobile_operation_payload_hash(operation_payload)
    operation = db.scalar(
        select(MobileOperationLog).where(
            MobileOperationLog.user_id == current_user.id,
            MobileOperationLog.device_id == "mobile-v2-delivery",
            MobileOperationLog.client_operation_id == body.idempotency_key,
        )
    )
    if operation is not None:
        if operation.payload_hash != payload_hash:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="幂等键已用于其他配送操作")
        if operation.status == "applied" and operation.result_json:
            return operation.result_json
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="配送操作正在处理中，请稍后刷新")

    expected = body.expected_updated_at
    current = delivery.updated_at
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    if expected.tzinfo is None:
        expected = expected.replace(tzinfo=timezone.utc)
    if current.astimezone(timezone.utc) != expected.astimezone(timezone.utc):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="配送任务已更新，请刷新后重试")

    operation = MobileOperationLog(
        user_id=current_user.id,
        device_id="mobile-v2-delivery",
        client_operation_id=body.idempotency_key,
        action_type="delivery_event_create",
        payload_hash=payload_hash,
        status="processing",
        resource_type="delivery_task",
        resource_id=str(delivery.id),
        request_json={"event_type": body.event_type, "to_status": body.to_status},
    )
    db.add(operation)
    apply_delivery_event(
        db,
        delivery=delivery,
        payload=DeliveryEventCreate(
            event_type=body.event_type,
            to_status=body.to_status,
            note=body.note,
            assignee_user_id=body.assignee_user_id,
            signed_by=body.signed_by,
            signed_at=body.signed_at,
        ),
        operator=current_user,
        request=request,
    )
    db.flush()
    db.refresh(delivery)
    result = jsonable_encoder(_mobile_delivery_payload(db, delivery))
    operation.status = "applied"
    operation.result_json = result
    operation.applied_at = datetime.now(timezone.utc)
    db.commit()
    return result


@router.get("/workbench")
def mobile_v2_workbench(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    local_now = now.astimezone(ZoneInfo(settings.exception_schedule_timezone))
    upcoming_end = now + timedelta(days=3)

    task_count = 0
    overdue_count = 0
    today_task_count = 0
    task_rows: list[CrmProjectCustomerTask] = []
    base_task_stmt = None
    visible_task_stmt = None
    if _can(db, current_user, "crm_task.view"):
        base_task_stmt = crm_task_scope_filter(select(CrmProjectCustomerTask), db, current_user)
        visible_task_stmt = base_task_stmt.where(
            CrmProjectCustomerTask.is_closed.is_(False),
        )
        task_count = _count(db, visible_task_stmt)
        overdue_count = _count(
            db,
            visible_task_stmt.where(
                CrmProjectCustomerTask.feedback_due_at.is_not(None),
                CrmProjectCustomerTask.feedback_due_at < now,
            ),
        )
        due_task_stmt = visible_task_stmt.where(
            CrmProjectCustomerTask.feedback_due_at.is_not(None),
            CrmProjectCustomerTask.feedback_due_at <= upcoming_end,
        )
        today_task_count = _count(db, due_task_stmt)
        task_rows = list(
            db.scalars(
                due_task_stmt
                .order_by(CrmProjectCustomerTask.feedback_due_at.asc(), CrmProjectCustomerTask.id.desc())
                .limit(8)
            ).all()
        )

    approval_stmt = visible_approvals_stmt(db, current_user).where(
        ApprovalInstance.current_handler_user_id == current_user.id,
        ApprovalInstance.status.in_(["submitted", "under_review"]),
    )
    approval_count = _count(db, approval_stmt)
    approval_rows = list(
        db.scalars(
            approval_stmt.order_by(
                case((ApprovalInstance.priority == "urgent", 0), (ApprovalInstance.priority == "high", 1), else_=2),
                ApprovalInstance.submitted_at.asc(),
                ApprovalInstance.id.asc(),
            ).limit(5)
        ).all()
    )

    work_item_count = 0
    work_item_rows: list[WorkItem] = []
    if _can(db, current_user, "crm_issue.view"):
        item_stmt = work_item_scope_filter(select(WorkItem), db, current_user).where(
            WorkItem.status.in_(sorted(OPEN_WORK_ITEM_STATUSES)),
        )
        work_item_count = _count(db, item_stmt)
        work_item_rows = list(
            db.scalars(
                item_stmt.order_by(
                    case((WorkItem.priority == "urgent", 0), (WorkItem.priority == "high", 1), else_=2),
                    WorkItem.due_at.asc(),
                    WorkItem.id.asc(),
                ).limit(5)
            ).all()
        )

    project_stmt = _visible_project_stmt(db, current_user).where(CrmProject.status.in_(["active", "paused"]))
    active_project_count = _count(db, project_stmt)
    project_rows = list(
        db.scalars(
            project_stmt.order_by(
                case(
                    (CrmProject.due_date.is_(None), 2),
                    (CrmProject.due_date < local_now.date(), 0),
                    else_=1,
                ),
                CrmProject.due_date.asc(),
                CrmProject.id.desc(),
            ).limit(5)
        ).all()
    )

    project_task_counts: dict[int, dict[str, int]] = {}
    if project_rows and base_task_stmt is not None:
        project_ids = [project.id for project in project_rows]
        rows = db.execute(
            base_task_stmt.with_only_columns(
                CrmProjectCustomerTask.project_id,
                func.count(CrmProjectCustomerTask.id),
                func.sum(case((CrmProjectCustomerTask.is_closed.is_(False), 1), else_=0)),
            )
            .where(CrmProjectCustomerTask.project_id.in_(project_ids))
            .group_by(CrmProjectCustomerTask.project_id)
        ).all()
        project_task_counts = {
            int(project_id): {"total": int(total or 0), "open": int(open_count or 0)}
            for project_id, total, open_count in rows
        }

    today_items = [*[_task_item(item, now) for item in task_rows], *[_approval_item(item) for item in approval_rows], *[_work_item(item) for item in work_item_rows]]
    tone_order = {"bad": 0, "warn": 1, "neutral": 2}
    kind_order = {"task_overdue": 0, "approval": 1, "support": 2, "task_due": 3}
    today_items.sort(
        key=lambda item: (
            tone_order.get(item["tone"], 3),
            kind_order.get(item["kind"], 4),
            str(item.get("due_at") or ""),
            item["key"],
        )
    )

    return {
        "generated_at": now.isoformat(),
        "date_label": f"{local_now.month}月{local_now.day}日",
        "headline": f"今天有 {active_project_count} 个项目在执行中",
        "summary": {
            "active_projects": active_project_count,
            "open_tasks": task_count,
            "pending_approvals": approval_count,
            "overdue_tasks": overdue_count,
            "open_support": work_item_count,
        },
        "today_queue": {"items": today_items[:12], "total": today_task_count + approval_count + work_item_count},
        "projects": {
            "items": [
                {
                    "id": project.id,
                    "project_code": project.project_code,
                    "project_name": project.project_name,
                    "status": project.status,
                    "due_date": project.due_date,
                    "overdue": project.due_date is not None and project.due_date < local_now.date(),
                    "open_tasks": project_task_counts.get(project.id, {}).get("open", 0),
                    "total_tasks": project_task_counts.get(project.id, {}).get("total", 0),
                }
                for project in project_rows
            ],
            "total": active_project_count,
        },
        "approvals": {
            "items": [
                {
                    "id": approval.id,
                    "approval_no": approval.approval_no,
                    "title": approval.title,
                    "status": approval.status,
                    "priority": approval.priority,
                    "submitted_at": approval.submitted_at,
                }
                for approval in approval_rows[:3]
            ],
            "total": approval_count,
        },
        "shortcuts": {
            "create_project": _can(db, current_user, "crm_project.create"),
            "view_approvals": approval_count > 0 or _can(db, current_user, "approval.view"),
            "view_support": _can(db, current_user, "crm_issue.view"),
        },
    }

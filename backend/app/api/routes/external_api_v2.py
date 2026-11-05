from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import (
    ApprovalInstance,
    CrmFollowup,
    CrmProject,
    CrmProjectCustomerTask,
    CrmProjectReview,
    ExternalApiKey,
    User,
    WorkItem,
)
from app.models.crm import (
    CRM_APPROVAL_STATUSES,
    CRM_FOLLOWUP_REVIEW_STATUSES,
    CRM_PROJECT_STATUSES,
    CRM_TASK_STATUSES,
)
from app.schemas.external_api import (
    ExternalCapabilitiesData,
    ExternalCapability,
    ExternalApprovalItem,
    ExternalApprovalListData,
    ExternalDataScope,
    ExternalDictionariesData,
    ExternalDictionaryItem,
    ExternalEnvelope,
    ExternalFollowupItem,
    ExternalFollowupListData,
    ExternalKeyIdentity,
    ExternalMeData,
    ExternalOverviewData,
    ExternalOverviewStats,
    ExternalProgressMetrics,
    ExternalProjectDetailData,
    ExternalProjectItem,
    ExternalProjectListData,
    ExternalProjectProgressData,
    ExternalTaskItem,
    ExternalTaskListData,
    ExternalTimelineData,
    ExternalTimelineEvent,
    ExternalWorkItem,
    ExternalWorkItemListData,
)
from app.services.external_api_service import (
    EXTERNAL_PERMISSION_LABELS,
    apply_external_cursor,
    apply_external_followup_scope,
    apply_external_project_scope,
    apply_external_task_scope,
    apply_external_work_item_scope,
    allowed_customer_fields,
    audit_external_request,
    decode_external_cursor,
    external_key_dependency,
    external_limit,
    external_page,
    external_meta,
    external_permission_enabled,
    external_permission_scopes,
    external_permissions,
    get_external_project,
    get_external_task,
    require_external_permission,
    scope_project_ids,
)


router = APIRouter(prefix="/api/external/v2", tags=["external-agent-api-v2"])


PROJECT_STATUS_LABELS = {"draft": "草稿", "submitted": "已提交", "active": "进行中", "paused": "已暂停", "closed": "已关闭", "cancelled": "已取消"}
TASK_STATUS_LABELS = {"not_started": "未开始", "in_progress": "推进中", "need_supplement": "待补充", "need_support": "待支持", "paused": "已暂停", "closed": "已闭环"}
FOLLOWUP_REVIEW_STATUS_LABELS = {"pending": "待审核", "approved": "已通过", "rejected": "已驳回", "need_supplement": "待补充"}
APPROVAL_STATUS_LABELS = {"draft": "草稿", "submitted": "已提交", "under_review": "审核中", "need_supplement": "待补充", "approved": "已通过", "rejected": "已驳回", "cancelled": "已取消", "completed": "已完成"}


def _dictionary(values: tuple[str, ...], labels: dict[str, str]) -> list[ExternalDictionaryItem]:
    return [ExternalDictionaryItem(code=value, label=labels.get(value, value)) for value in values]


def _aware(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def _user_labels(db: Session, user_ids: set[int | None]) -> dict[int, str]:
    ids = {int(value) for value in user_ids if value is not None}
    if not ids:
        return {}
    rows = list(db.scalars(select(User).where(User.id.in_(ids))).all())
    return {row.id: row.real_name or row.username for row in rows}


def _task_overdue(task: CrmProjectCustomerTask, now: datetime) -> bool:
    due_at = _aware(task.feedback_due_at)
    return bool(due_at and due_at < now and not task.is_closed)


def _task_item(task: CrmProjectCustomerTask, project: CrmProject, now: datetime) -> ExternalTaskItem:
    return ExternalTaskItem(
        id=task.id,
        project_id=task.project_id,
        task_code=task.task_code,
        customer_code=task.customer_code,
        customer_name=task.customer_name_snapshot,
        executor=task.executor_name_snapshot,
        project_purpose=project.purpose,
        business_issue_point=task.business_issue_point,
        round_target=task.round_target,
        feedback_due_at=task.feedback_due_at,
        status=task.status,
        minimum_action_done=task.minimum_action_done,
        need_support=task.need_support,
        need_manager_support=task.need_manager_support,
        need_boss_decision=task.need_boss_decision,
        is_blocked=task.is_blocked,
        is_closed=task.is_closed,
        overdue=_task_overdue(task, now),
        blocker_reason=task.latest_blocker_reason,
        blocker_note=task.latest_blocker_note,
        next_status=task.latest_owner_next_status,
        next_action=task.latest_owner_next_action,
        next_followup_at=task.latest_owner_next_followup_at,
        last_followup_at=task.last_followup_at,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def _project_item(
    project: CrmProject,
    tasks: list[CrmProjectCustomerTask],
    latest_followup_at: datetime | None,
    user_labels: dict[int, str],
    now: datetime,
) -> ExternalProjectItem:
    task_closed = sum(1 for task in tasks if task.is_closed)
    return ExternalProjectItem(
        id=project.id,
        project_code=project.project_code,
        project_name=project.project_name,
        project_type=project.project_type,
        purpose=project.purpose,
        business_line=project.business_line,
        owner=user_labels.get(project.owner_user_id) if project.owner_user_id else None,
        project_manager=user_labels.get(project.project_manager_user_id) if project.project_manager_user_id else None,
        start_date=project.start_date,
        due_date=project.due_date,
        status=project.status,
        approval_status=project.approval_status,
        next_step_status=project.next_step_status,
        next_step_action=project.next_step_action,
        next_step_followup_at=project.next_step_followup_at,
        task_total=len(tasks),
        task_closed=task_closed,
        task_open=max(len(tasks) - task_closed, 0),
        task_overdue=sum(1 for task in tasks if _task_overdue(task, now)),
        task_need_support=sum(1 for task in tasks if task.need_support or task.need_manager_support or task.need_boss_decision),
        task_blocked=sum(1 for task in tasks if task.is_blocked),
        latest_approved_followup_at=latest_followup_at,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def _payload_int(payload: Any, *path: str) -> int | None:
    value = payload
    for part in path:
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _approval_project_id(approval: ApprovalInstance) -> int | None:
    if approval.resource_type == "crm_project":
        try:
            return int(approval.resource_id)
        except (TypeError, ValueError):
            pass
    payload = approval.payload_json
    for path in (("project_id",), ("project", "id"), ("task", "project_id"), ("followup", "project_id")):
        value = _payload_int(payload, *path)
        if value is not None:
            return value
    return None


def _project_approvals(db: Session, project: CrmProject) -> list[ApprovalInstance]:
    candidates = list(
        db.scalars(
            select(ApprovalInstance)
            .where(
                or_(
                    (ApprovalInstance.resource_type == "crm_project") & (ApprovalInstance.resource_id == str(project.id)),
                    ApprovalInstance.approval_type.in_(
                        [
                            "crm_project_create",
                            "crm_project_update",
                            "crm_followup_submit",
                            "customer_business_profile_update",
                            "customer_profile_update",
                            "crm_project_extension",
                            "crm_task_extension",
                            "crm_project_close",
                        ]
                    ),
                )
            )
            .order_by(ApprovalInstance.updated_at.desc(), ApprovalInstance.id.desc())
        ).all()
    )
    return [
        row
        for row in candidates
        if _approval_project_id(row) == project.id or (project.current_approval_id is not None and row.id == project.current_approval_id)
    ]


def _approval_item(row: ApprovalInstance) -> ExternalApprovalItem:
    return ExternalApprovalItem(
        id=row.id,
        approval_no=row.approval_no,
        approval_type=row.approval_type,
        resource_type=row.resource_type,
        resource_id=row.resource_id,
        title=row.title,
        status=row.status,
        priority=row.priority,
        submitted_at=row.submitted_at,
        reviewed_at=row.reviewed_at,
        closed_at=row.closed_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _followup_item(row: CrmFollowup, customer_name: str) -> ExternalFollowupItem:
    return ExternalFollowupItem(
        id=row.id,
        followup_no=row.followup_no,
        project_id=row.project_id,
        task_id=row.task_id,
        customer_code=row.customer_code,
        customer_name=customer_name,
        executor=row.executor_name_snapshot,
        followup_date=row.followup_date,
        method=row.method,
        frontline_action=row.frontline_action,
        customer_feedback=row.customer_feedback,
        current_need=row.current_need,
        blocker_reason=row.blocker_reason,
        blocker_note=row.blocker_note,
        next_action_type=row.next_action_type,
        next_action=row.next_action,
        next_followup_at=row.next_followup_at,
        minimum_action_done=row.minimum_action_done,
        need_support=row.need_support,
        need_manager_support=row.need_manager_support,
        need_boss_decision=row.need_boss_decision,
        is_closed=row.is_closed,
        valid_feedback=row.valid_feedback,
        review_status=row.review_status,
        reviewed_at=row.reviewed_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _work_item(row: WorkItem, labels: dict[int, str]) -> ExternalWorkItem:
    return ExternalWorkItem(
        id=row.id,
        item_no=row.item_no,
        project_id=row.project_id,
        customer_code=row.customer_code,
        item_type=row.item_type,
        title=row.title,
        detail=row.detail,
        priority=row.priority,
        status=row.status,
        assignee=labels.get(row.assignee_user_id) if row.assignee_user_id else None,
        due_at=row.due_at,
        resolved_at=row.resolved_at,
        resolution_note=row.resolution_note,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _project_progress(db: Session, project: CrmProject, api_key: ExternalApiKey) -> ExternalProjectProgressData:
    now = datetime.now(timezone.utc)
    tasks = list(
        db.scalars(
            apply_external_task_scope(
                select(CrmProjectCustomerTask).where(CrmProjectCustomerTask.project_id == project.id), api_key
            ).order_by(CrmProjectCustomerTask.id)
        ).all()
    )
    followups = list(
        db.scalars(
            apply_external_followup_scope(
                select(CrmFollowup).where(CrmFollowup.project_id == project.id, CrmFollowup.review_status == "approved"), api_key
            ).order_by(CrmFollowup.updated_at.desc(), CrmFollowup.id.desc())
        ).all()
    )
    work_items = list(
        db.scalars(
            apply_external_work_item_scope(select(WorkItem).where(WorkItem.project_id == project.id), api_key)
            .order_by(WorkItem.updated_at.desc(), WorkItem.id.desc())
        ).all()
    )
    approvals = _project_approvals(db, project)
    reviews = list(
        db.scalars(
            select(CrmProjectReview)
            .where(CrmProjectReview.project_id == project.id)
            .order_by(CrmProjectReview.review_date.desc().nullslast(), CrmProjectReview.id.desc())
        ).all()
    )
    feedback_task_ids = {row.task_id for row in followups}
    valid_feedback_task_ids = {row.task_id for row in followups if row.valid_feedback}
    task_total = len(tasks)
    task_closed = sum(1 for row in tasks if row.is_closed)
    task_open = max(task_total - task_closed, 0)
    task_overdue = sum(1 for row in tasks if _task_overdue(row, now))
    task_blocked = sum(1 for row in tasks if row.is_blocked)
    support_open = sum(1 for row in work_items if row.status in {"open", "processing"})
    support_closed = sum(1 for row in work_items if row.status in {"resolved", "closed"})
    pending_approvals = sum(1 for row in approvals if row.status in {"submitted", "under_review", "need_supplement"})
    review_confirmed = sum(1 for row in reviews if row.status == "confirmed")
    no_feedback = max(task_total - len(feedback_task_ids), 0)
    if task_total == 0:
        closure_state = "no_tasks"
    elif task_blocked > 0 or support_open > 0 or pending_approvals > 0:
        closure_state = "blocked"
    elif task_open > 0 or task_overdue > 0 or no_feedback > 0:
        closure_state = "in_progress"
    elif review_confirmed == 0:
        closure_state = "need_review"
    else:
        closure_state = "ready"
    blocker_labels: list[str] = []
    for count, label in (
        (task_total == 0, "项目尚未创建客户任务"),
        (task_blocked, f"{task_blocked} 个任务存在阻塞"),
        (support_open, f"{support_open} 个支持事项未解决"),
        (pending_approvals, f"{pending_approvals} 个审批仍在处理中"),
        (task_open, f"{task_open} 个任务尚未闭环"),
        (task_overdue, f"{task_overdue} 个任务已超期"),
        (no_feedback, f"{no_feedback} 个任务没有已审核跟进"),
        (task_total > 0 and task_open == 0 and review_confirmed == 0, "项目复盘尚未确认"),
    ):
        if count:
            blocker_labels.append(label)
    user_labels = _user_labels(db, {project.owner_user_id, project.project_manager_user_id})
    latest_followup_at = followups[0].reviewed_at or followups[0].updated_at if followups else None
    project_item = _project_item(project, tasks, latest_followup_at, user_labels, now)
    metrics = ExternalProgressMetrics(
        task_total=task_total,
        task_closed=task_closed,
        task_open=task_open,
        task_overdue=task_overdue,
        task_need_support=sum(1 for row in tasks if row.need_support),
        task_need_manager_support=sum(1 for row in tasks if row.need_manager_support),
        task_need_boss_decision=sum(1 for row in tasks if row.need_boss_decision),
        task_blocked=task_blocked,
        feedback_task_count=len(feedback_task_ids),
        valid_feedback_task_count=len(valid_feedback_task_ids),
        no_feedback_task_count=no_feedback,
        support_open_count=support_open,
        support_closed_count=support_closed,
        pending_approval_count=pending_approvals,
        review_total=len(reviews),
        review_confirmed=review_confirmed,
        task_closure_rate=round(task_closed * 100 / task_total, 2) if task_total else 0,
        valid_feedback_rate=round(len(valid_feedback_task_ids) * 100 / task_total, 2) if task_total else 0,
    )
    source_values = [project.updated_at]
    source_values.extend(row.updated_at for row in tasks)
    source_values.extend(row.updated_at for row in followups)
    source_values.extend(row.updated_at for row in work_items)
    source_values.extend(row.updated_at for row in approvals)
    source_values.extend(row.updated_at for row in reviews)
    source_updated_at = max((_aware(value) for value in source_values if value is not None), default=now)
    latest_review = reviews[0] if reviews else None
    return ExternalProjectProgressData(
        project=project_item,
        metrics=metrics,
        closure_ready=closure_state == "ready",
        closure_state=closure_state,
        closure_blockers=blocker_labels,
        latest_review_status=latest_review.status if latest_review else None,
        latest_review_conclusion=latest_review.conclusion if latest_review else None,
        calculated_at=now,
        source_updated_at=source_updated_at,
    )


@router.get("/me", response_model=ExternalEnvelope[ExternalMeData])
def external_v2_me(
    request: Request,
    api_key: ExternalApiKey = Depends(external_key_dependency),
    db: Session = Depends(get_db),
) -> ExternalEnvelope[ExternalMeData]:
    data = ExternalMeData(
        key=ExternalKeyIdentity(
            key_id=api_key.key_id,
            name=api_key.name,
            owner_name=api_key.owner_name,
            expires_at=api_key.expires_at,
            permissions=external_permissions(api_key),
            permission_scopes=external_permission_scopes(api_key),
            rate_limit_per_minute=api_key.rate_limit_per_minute,
            daily_request_limit=api_key.daily_request_limit,
            rotated_at=api_key.rotated_at,
            previous_key_expires_at=api_key.previous_key_expires_at,
            data_scope=ExternalDataScope(
                region=api_key.scope_region,
                project_ids=scope_project_ids(api_key),
                customer_fields=allowed_customer_fields(api_key),
            ),
        )
    )
    audit_external_request(db, request, api_key, "/me")
    return ExternalEnvelope(data=data, meta=external_meta(request))


@router.get("/capabilities", response_model=ExternalEnvelope[ExternalCapabilitiesData])
def external_v2_capabilities(
    request: Request,
    api_key: ExternalApiKey = Depends(external_key_dependency),
    db: Session = Depends(get_db),
) -> ExternalEnvelope[ExternalCapabilitiesData]:
    capabilities = [
        ExternalCapability(
            code=public_code,
            resource=resource,
            description=description,
            enabled=external_permission_enabled(api_key, model_field),
        )
        for model_field, (public_code, resource, description) in EXTERNAL_PERMISSION_LABELS.items()
    ]
    audit_external_request(db, request, api_key, "/capabilities")
    return ExternalEnvelope(data=ExternalCapabilitiesData(capabilities=capabilities), meta=external_meta(request))


@router.get("/dictionaries", response_model=ExternalEnvelope[ExternalDictionariesData])
def external_v2_dictionaries(
    request: Request,
    api_key: ExternalApiKey = Depends(external_key_dependency),
    db: Session = Depends(get_db),
) -> ExternalEnvelope[ExternalDictionariesData]:
    data = ExternalDictionariesData(
        project_statuses=_dictionary(CRM_PROJECT_STATUSES, PROJECT_STATUS_LABELS),
        task_statuses=_dictionary(CRM_TASK_STATUSES, TASK_STATUS_LABELS),
        followup_review_statuses=_dictionary(CRM_FOLLOWUP_REVIEW_STATUSES, FOLLOWUP_REVIEW_STATUS_LABELS),
        approval_statuses=_dictionary(CRM_APPROVAL_STATUSES, APPROVAL_STATUS_LABELS),
    )
    audit_external_request(db, request, api_key, "/dictionaries")
    return ExternalEnvelope(data=data, meta=external_meta(request))


@router.get("/overview", response_model=ExternalEnvelope[ExternalOverviewData])
def external_v2_overview(
    request: Request,
    api_key: ExternalApiKey = Depends(external_key_dependency),
    db: Session = Depends(get_db),
) -> ExternalEnvelope[ExternalOverviewData]:
    stats = ExternalOverviewStats()
    if api_key.can_read_projects:
        stats.projects = db.scalar(
            select(func.count()).select_from(apply_external_project_scope(select(CrmProject.id), api_key).order_by(None).subquery())
        ) or 0
    if api_key.can_read_tasks:
        task_stmt = apply_external_task_scope(select(CrmProjectCustomerTask), api_key)
        tasks = list(db.scalars(task_stmt).all())
        now = datetime.now(timezone.utc)
        stats.tasks = len(tasks)
        stats.open_tasks = sum(1 for row in tasks if not row.is_closed)
        stats.overdue_tasks = sum(1 for row in tasks if _task_overdue(row, now))
        stats.blocked_tasks = sum(1 for row in tasks if row.is_blocked)
        work_items = list(db.scalars(apply_external_work_item_scope(select(WorkItem), api_key)).all())
        stats.open_work_items = sum(1 for row in work_items if row.status in {"open", "processing"})
    if api_key.can_read_followups:
        stats.approved_followups = db.scalar(
            select(func.count()).select_from(
                apply_external_followup_scope(
                    select(CrmFollowup.id).where(CrmFollowup.review_status == "approved"), api_key
                ).order_by(None).subquery()
            )
        ) or 0
    if api_key.can_read_approvals:
        visible_ids = set(db.scalars(apply_external_project_scope(select(CrmProject.id), api_key)).all())
        stats.pending_approvals = sum(
            1
            for row in db.scalars(select(ApprovalInstance)).all()
            if _approval_project_id(row) in visible_ids and row.status in {"submitted", "under_review", "need_supplement"}
        )
    audit_external_request(db, request, api_key, "/overview")
    return ExternalEnvelope(data=ExternalOverviewData(stats=stats), meta=external_meta(request))


@router.get("/projects", response_model=ExternalEnvelope[ExternalProjectListData])
def external_v2_projects(
    request: Request,
    q: str | None = None,
    status: str | None = None,
    approval_status: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
    api_key: ExternalApiKey = Depends(require_external_permission("can_read_projects")),
    db: Session = Depends(get_db),
) -> ExternalEnvelope[ExternalProjectListData]:
    limit_value = external_limit(limit)
    stmt = apply_external_project_scope(select(CrmProject), api_key)
    if q:
        keyword = f"%{q.strip()}%"
        stmt = stmt.where(or_(CrmProject.project_code.ilike(keyword), CrmProject.project_name.ilike(keyword), CrmProject.purpose.ilike(keyword)))
    if status:
        stmt = stmt.where(CrmProject.status == status)
    if approval_status:
        stmt = stmt.where(CrmProject.approval_status == approval_status)
    stmt = apply_external_cursor(stmt, CrmProject, cursor, dialect_name=db.get_bind().dialect.name)
    rows = list(db.scalars(stmt.order_by(CrmProject.updated_at.desc(), CrmProject.id.desc()).limit(limit_value + 1)).all())
    projects, next_cursor, has_more = external_page(rows, limit_value)
    project_ids = [row.id for row in projects]
    task_rows = list(
        db.scalars(
            apply_external_task_scope(select(CrmProjectCustomerTask).where(CrmProjectCustomerTask.project_id.in_(project_ids)), api_key)
        ).all()
    ) if project_ids else []
    followup_rows = list(
        db.scalars(
            apply_external_followup_scope(
                select(CrmFollowup).where(CrmFollowup.project_id.in_(project_ids), CrmFollowup.review_status == "approved"), api_key
            ).order_by(CrmFollowup.updated_at.desc(), CrmFollowup.id.desc())
        ).all()
    ) if project_ids else []
    tasks_by_project: dict[int, list[CrmProjectCustomerTask]] = {project_id: [] for project_id in project_ids}
    for task in task_rows:
        tasks_by_project.setdefault(task.project_id, []).append(task)
    latest_by_project: dict[int, datetime] = {}
    for followup in followup_rows:
        latest_by_project.setdefault(followup.project_id, followup.reviewed_at or followup.updated_at)
    labels = _user_labels(db, {value for row in projects for value in (row.owner_user_id, row.project_manager_user_id)})
    now = datetime.now(timezone.utc)
    items = [_project_item(row, tasks_by_project.get(row.id, []), latest_by_project.get(row.id), labels, now) for row in projects]
    audit_external_request(db, request, api_key, "/projects", {"count": len(items)})
    return ExternalEnvelope(
        data=ExternalProjectListData(items=items, count=len(items)),
        meta=external_meta(request, next_cursor=next_cursor, has_more=has_more),
    )


@router.get("/projects/{project_id}", response_model=ExternalEnvelope[ExternalProjectDetailData])
def external_v2_project_detail(
    project_id: int,
    request: Request,
    api_key: ExternalApiKey = Depends(require_external_permission("can_read_projects")),
    db: Session = Depends(get_db),
) -> ExternalEnvelope[ExternalProjectDetailData]:
    project = get_external_project(db, project_id, api_key)
    progress = _project_progress(db, project, api_key)
    audit_external_request(db, request, api_key, f"/projects/{project_id}")
    return ExternalEnvelope(data=ExternalProjectDetailData(project=progress.project, progress=progress), meta=external_meta(request))


@router.get("/projects/{project_id}/progress", response_model=ExternalEnvelope[ExternalProjectProgressData])
def external_v2_project_progress(
    project_id: int,
    request: Request,
    api_key: ExternalApiKey = Depends(require_external_permission("can_read_projects")),
    db: Session = Depends(get_db),
) -> ExternalEnvelope[ExternalProjectProgressData]:
    project = get_external_project(db, project_id, api_key)
    progress = _project_progress(db, project, api_key)
    audit_external_request(db, request, api_key, f"/projects/{project_id}/progress")
    return ExternalEnvelope(data=progress, meta=external_meta(request))


def _task_page_response(
    *,
    request: Request,
    api_key: ExternalApiKey,
    db: Session,
    project_id: int | None,
    status: str | None,
    customer_code: str | None,
    overdue: bool | None,
    limit: int,
    cursor: str | None,
    endpoint: str,
) -> ExternalEnvelope[ExternalTaskListData]:
    if project_id is not None:
        get_external_project(db, project_id, api_key)
    limit_value = external_limit(limit)
    stmt = apply_external_task_scope(select(CrmProjectCustomerTask), api_key)
    if project_id is not None:
        stmt = stmt.where(CrmProjectCustomerTask.project_id == project_id)
    if status:
        stmt = stmt.where(CrmProjectCustomerTask.status == status)
    if customer_code:
        stmt = stmt.where(CrmProjectCustomerTask.customer_code == customer_code)
    if overdue is True:
        stmt = stmt.where(
            CrmProjectCustomerTask.is_closed.is_(False),
            CrmProjectCustomerTask.feedback_due_at.is_not(None),
            CrmProjectCustomerTask.feedback_due_at < datetime.now(timezone.utc),
        )
    elif overdue is False:
        stmt = stmt.where(
            or_(
                CrmProjectCustomerTask.is_closed.is_(True),
                CrmProjectCustomerTask.feedback_due_at.is_(None),
                CrmProjectCustomerTask.feedback_due_at >= datetime.now(timezone.utc),
            )
        )
    stmt = apply_external_cursor(stmt, CrmProjectCustomerTask, cursor, dialect_name=db.get_bind().dialect.name)
    rows = list(db.scalars(stmt.order_by(CrmProjectCustomerTask.updated_at.desc(), CrmProjectCustomerTask.id.desc()).limit(limit_value + 1)).all())
    tasks, next_cursor, has_more = external_page(rows, limit_value)
    project_ids = {row.project_id for row in tasks}
    projects = {row.id: row for row in db.scalars(select(CrmProject).where(CrmProject.id.in_(project_ids))).all()} if project_ids else {}
    now = datetime.now(timezone.utc)
    items = [_task_item(row, projects[row.project_id], now) for row in tasks]
    audit_external_request(db, request, api_key, endpoint, {"count": len(items)})
    return ExternalEnvelope(
        data=ExternalTaskListData(items=items, count=len(items)),
        meta=external_meta(request, next_cursor=next_cursor, has_more=has_more),
    )


@router.get("/tasks", response_model=ExternalEnvelope[ExternalTaskListData])
def external_v2_tasks(
    request: Request,
    project_id: int | None = None,
    status: str | None = None,
    customer_code: str | None = None,
    overdue: bool | None = None,
    limit: int = 50,
    cursor: str | None = None,
    api_key: ExternalApiKey = Depends(require_external_permission("can_read_tasks")),
    db: Session = Depends(get_db),
) -> ExternalEnvelope[ExternalTaskListData]:
    return _task_page_response(
        request=request, api_key=api_key, db=db, project_id=project_id, status=status, customer_code=customer_code,
        overdue=overdue, limit=limit, cursor=cursor, endpoint="/tasks"
    )


@router.get("/projects/{project_id}/tasks", response_model=ExternalEnvelope[ExternalTaskListData])
def external_v2_project_tasks(
    project_id: int,
    request: Request,
    status: str | None = None,
    overdue: bool | None = None,
    limit: int = 50,
    cursor: str | None = None,
    api_key: ExternalApiKey = Depends(require_external_permission("can_read_tasks")),
    db: Session = Depends(get_db),
) -> ExternalEnvelope[ExternalTaskListData]:
    return _task_page_response(
        request=request, api_key=api_key, db=db, project_id=project_id, status=status, customer_code=None,
        overdue=overdue, limit=limit, cursor=cursor, endpoint=f"/projects/{project_id}/tasks"
    )


@router.get("/tasks/{task_id}", response_model=ExternalEnvelope[ExternalTaskItem])
def external_v2_task_detail(
    task_id: int,
    request: Request,
    api_key: ExternalApiKey = Depends(require_external_permission("can_read_tasks")),
    db: Session = Depends(get_db),
) -> ExternalEnvelope[ExternalTaskItem]:
    task = get_external_task(db, task_id, api_key)
    project = get_external_project(db, task.project_id, api_key)
    item = _task_item(task, project, datetime.now(timezone.utc))
    audit_external_request(db, request, api_key, f"/tasks/{task_id}")
    return ExternalEnvelope(data=item, meta=external_meta(request))


@router.get("/followups", response_model=ExternalEnvelope[ExternalFollowupListData])
def external_v2_followups(
    request: Request,
    project_id: int | None = None,
    task_id: int | None = None,
    customer_code: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 50,
    cursor: str | None = None,
    api_key: ExternalApiKey = Depends(require_external_permission("can_read_followups")),
    db: Session = Depends(get_db),
) -> ExternalEnvelope[ExternalFollowupListData]:
    if project_id is not None:
        get_external_project(db, project_id, api_key)
    limit_value = external_limit(limit)
    stmt = apply_external_followup_scope(select(CrmFollowup).where(CrmFollowup.review_status == "approved"), api_key)
    if project_id is not None:
        stmt = stmt.where(CrmFollowup.project_id == project_id)
    if task_id is not None:
        stmt = stmt.where(CrmFollowup.task_id == task_id)
    if customer_code:
        stmt = stmt.where(CrmFollowup.customer_code == customer_code)
    if date_from:
        stmt = stmt.where(CrmFollowup.followup_date >= date_from)
    if date_to:
        stmt = stmt.where(CrmFollowup.followup_date <= date_to)
    stmt = apply_external_cursor(stmt, CrmFollowup, cursor, dialect_name=db.get_bind().dialect.name)
    rows = list(db.scalars(stmt.order_by(CrmFollowup.updated_at.desc(), CrmFollowup.id.desc()).limit(limit_value + 1)).all())
    followups, next_cursor, has_more = external_page(rows, limit_value)
    task_ids = {row.task_id for row in followups}
    customer_names = {
        row.customer_code: row.customer_name_snapshot
        for row in db.scalars(select(CrmProjectCustomerTask).where(CrmProjectCustomerTask.id.in_(task_ids))).all()
    } if task_ids else {}
    items = [_followup_item(row, customer_names.get(row.customer_code, row.customer_code)) for row in followups]
    audit_external_request(db, request, api_key, "/followups", {"count": len(items)})
    return ExternalEnvelope(
        data=ExternalFollowupListData(items=items, count=len(items)),
        meta=external_meta(request, next_cursor=next_cursor, has_more=has_more),
    )


@router.get("/work-items", response_model=ExternalEnvelope[ExternalWorkItemListData])
def external_v2_work_items(
    request: Request,
    project_id: int | None = None,
    status: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
    api_key: ExternalApiKey = Depends(require_external_permission("can_read_tasks")),
    db: Session = Depends(get_db),
) -> ExternalEnvelope[ExternalWorkItemListData]:
    if project_id is not None:
        get_external_project(db, project_id, api_key)
    limit_value = external_limit(limit)
    stmt = apply_external_work_item_scope(select(WorkItem), api_key)
    if project_id is not None:
        stmt = stmt.where(WorkItem.project_id == project_id)
    if status:
        stmt = stmt.where(WorkItem.status == status)
    stmt = apply_external_cursor(stmt, WorkItem, cursor, dialect_name=db.get_bind().dialect.name)
    rows = list(db.scalars(stmt.order_by(WorkItem.updated_at.desc(), WorkItem.id.desc()).limit(limit_value + 1)).all())
    work_items, next_cursor, has_more = external_page(rows, limit_value)
    labels = _user_labels(db, {row.assignee_user_id for row in work_items})
    items = [_work_item(row, labels) for row in work_items]
    audit_external_request(db, request, api_key, "/work-items", {"count": len(items)})
    return ExternalEnvelope(
        data=ExternalWorkItemListData(items=items, count=len(items)),
        meta=external_meta(request, next_cursor=next_cursor, has_more=has_more),
    )


@router.get("/approvals", response_model=ExternalEnvelope[ExternalApprovalListData])
def external_v2_approvals(
    request: Request,
    project_id: int | None = None,
    status: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
    api_key: ExternalApiKey = Depends(require_external_permission("can_read_approvals")),
    db: Session = Depends(get_db),
) -> ExternalEnvelope[ExternalApprovalListData]:
    limit_value = external_limit(limit)
    if project_id is not None:
        projects = [get_external_project(db, project_id, api_key)]
    else:
        projects = list(db.scalars(apply_external_project_scope(select(CrmProject), api_key)).all())
    rows: list[ApprovalInstance] = []
    for project in projects:
        rows.extend(_project_approvals(db, project))
    unique = {row.id: row for row in rows}
    filtered = [row for row in unique.values() if not status or row.status == status]
    filtered.sort(key=lambda row: (_aware(row.updated_at), row.id), reverse=True)
    parsed_cursor = decode_external_cursor(cursor)
    if parsed_cursor:
        cursor_at, cursor_id = parsed_cursor
        filtered = [row for row in filtered if (_aware(row.updated_at), row.id) < (cursor_at, cursor_id)]
    approvals, next_cursor, has_more = external_page(filtered[: limit_value + 1], limit_value)
    items = [_approval_item(row) for row in approvals]
    audit_external_request(db, request, api_key, "/approvals", {"count": len(items)})
    return ExternalEnvelope(
        data=ExternalApprovalListData(items=items, count=len(items)),
        meta=external_meta(request, next_cursor=next_cursor, has_more=has_more),
    )


@router.get("/projects/{project_id}/timeline", response_model=ExternalEnvelope[ExternalTimelineData])
def external_v2_project_timeline(
    project_id: int,
    request: Request,
    limit: int = 100,
    api_key: ExternalApiKey = Depends(require_external_permission("can_read_projects")),
    db: Session = Depends(get_db),
) -> ExternalEnvelope[ExternalTimelineData]:
    project = get_external_project(db, project_id, api_key)
    events: list[ExternalTimelineEvent] = []
    if api_key.can_read_followups:
        followups = list(
            db.scalars(
                apply_external_followup_scope(
                    select(CrmFollowup).where(CrmFollowup.project_id == project_id, CrmFollowup.review_status == "approved"), api_key
                ).order_by(CrmFollowup.updated_at.desc(), CrmFollowup.id.desc()).limit(external_limit(limit))
            ).all()
        )
        events.extend(
            ExternalTimelineEvent(
                event_id=f"followup:{row.id}", event_type="followup_approved", title="跟进记录已审核",
                summary=row.customer_feedback or row.frontline_action, status=row.review_status,
                occurred_at=row.reviewed_at or row.updated_at, project_id=project_id, task_id=row.task_id, customer_code=row.customer_code,
            )
            for row in followups
        )
    if api_key.can_read_tasks:
        work_items = list(
            db.scalars(
                apply_external_work_item_scope(select(WorkItem).where(WorkItem.project_id == project_id), api_key)
                .order_by(WorkItem.updated_at.desc(), WorkItem.id.desc()).limit(external_limit(limit))
            ).all()
        )
        events.extend(
            ExternalTimelineEvent(
                event_id=f"work_item:{row.id}", event_type="work_item", title=row.title, summary=row.detail,
                status=row.status, occurred_at=row.updated_at, project_id=project_id, customer_code=row.customer_code,
            )
            for row in work_items
        )
    if api_key.can_read_approvals:
        events.extend(
            ExternalTimelineEvent(
                event_id=f"approval:{row.id}", event_type="approval", title=row.title, status=row.status,
                occurred_at=row.reviewed_at or row.submitted_at or row.created_at, project_id=project_id,
            )
            for row in _project_approvals(db, project)
        )
    events.sort(key=lambda row: (_aware(row.occurred_at), row.event_id), reverse=True)
    items = events[: external_limit(limit)]
    audit_external_request(db, request, api_key, f"/projects/{project_id}/timeline", {"count": len(items)})
    return ExternalEnvelope(data=ExternalTimelineData(items=items, count=len(items)), meta=external_meta(request))

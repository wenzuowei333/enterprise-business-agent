from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.api.dependencies import require_crm_permission
from app.core.database import get_db
from app.models import CrmFollowup, CrmProject, CrmProjectCustomerTask, CustomerMaster, User, WorkItem
from app.schemas.crm import WorkItemActionRequest, WorkItemPage, WorkItemPublic, WorkItemUpdate
from app.services.audit_service import write_audit_log
from app.services.crm_project_service import ensure_project_operable
from app.services.work_item_service import (
    OPEN_WORK_ITEM_STATUSES,
    mark_work_item_closed,
    mark_work_item_resolved,
    validate_work_item_update,
    work_item_scope_filter,
)

router = APIRouter(prefix="/work-items", tags=["work-items"])


def _safe_limit(limit: int) -> int:
    return max(1, min(limit, 100))


def _safe_offset(offset: int) -> int:
    return max(0, offset)


def _count_stmt(db: Session, stmt: Select[tuple[Any, ...]]) -> int:
    return db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0


def _scoped_work_item(db: Session, current_user: User, item_id: int) -> WorkItem:
    stmt = work_item_scope_filter(select(WorkItem).where(WorkItem.id == item_id), db, current_user)
    item = db.scalar(stmt)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work item not found")
    return item


def _ensure_work_item_project_operable(db: Session, item: WorkItem) -> None:
    if item.project_id is None:
        return
    project = db.get(CrmProject, item.project_id)
    if project is not None:
        ensure_project_operable(project)


def _user_label(user: User | None) -> str | None:
    if user is None:
        return None
    return user.real_name or user.username


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _int_from_string(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _followup_summary(followup: CrmFollowup | None) -> str | None:
    if followup is None:
        return None
    parts: list[str] = []
    for label, value in (
        ("一线动作", followup.frontline_action),
        ("客户反馈", followup.customer_feedback),
        ("当前需求", followup.current_need),
        ("卡点说明", followup.blocker_note),
    ):
        cleaned = _clean_text(value)
        if cleaned:
            parts.append(f"{label}：{cleaned}")
    return "；".join(parts) or None


def _support_detail(followup: CrmFollowup | None) -> str | None:
    if followup is None:
        return None
    return (
        _clean_text(followup.current_need)
        or _clean_text(followup.blocker_note)
        or _clean_text(followup.customer_feedback)
        or _clean_text(followup.review_note)
    )


def _work_item_publics(db: Session, rows: list[WorkItem]) -> list[WorkItemPublic]:
    customer_codes = {row.customer_code for row in rows if row.customer_code}
    project_ids = {row.project_id for row in rows if row.project_id is not None}
    task_ids = {
        task_id
        for row in rows
        if row.resource_type == "crm_project_customer_task"
        for task_id in [_int_from_string(row.resource_id)]
        if task_id is not None
    }
    followup_ids = {
        followup_id
        for row in rows
        if row.source_type == "crm_followup"
        for followup_id in [_int_from_string(row.source_id)]
        if followup_id is not None
    }
    user_ids = {
        user_id
        for row in rows
        for user_id in (row.assignee_user_id, row.resolved_by_user_id)
        if user_id is not None
    }

    customers = {
        row.customer_code: row
        for row in db.scalars(select(CustomerMaster).where(CustomerMaster.customer_code.in_(customer_codes))).all()
    } if customer_codes else {}
    projects = {
        row.id: row
        for row in db.scalars(select(CrmProject).where(CrmProject.id.in_(project_ids))).all()
    } if project_ids else {}
    tasks = {
        row.id: row
        for row in db.scalars(select(CrmProjectCustomerTask).where(CrmProjectCustomerTask.id.in_(task_ids))).all()
    } if task_ids else {}
    followups = {
        row.id: row
        for row in db.scalars(select(CrmFollowup).where(CrmFollowup.id.in_(followup_ids))).all()
    } if followup_ids else {}
    users = {
        row.id: row
        for row in db.scalars(select(User).where(User.id.in_(user_ids))).all()
    } if user_ids else {}

    enriched: list[WorkItemPublic] = []
    for row in rows:
        public = WorkItemPublic.model_validate(row)
        task_id = _int_from_string(row.resource_id) if row.resource_type == "crm_project_customer_task" else None
        task = tasks.get(task_id) if task_id is not None else None
        followup_id = _int_from_string(row.source_id) if row.source_type == "crm_followup" else None
        followup = followups.get(followup_id) if followup_id is not None else None
        customer = customers.get(row.customer_code or "")
        project = projects.get(row.project_id) if row.project_id is not None else None
        support_detail = _support_detail(followup)
        support_type = _clean_text(followup.need_type if followup else None)
        has_support_flag = bool(
            followup and (followup.need_support or followup.need_manager_support or followup.need_boss_decision)
        )
        needs_next_action = bool(followup and not (followup.owner_next_action or followup.next_action))
        enriched.append(
            public.model_copy(
                update={
                    "customer_name": (customer.customer_name if customer else None) or (task.customer_name_snapshot if task else None),
                    "project_name": project.project_name if project else None,
                    "project_approval_frozen": bool(
                        project
                        and project.approval_status == "need_supplement"
                        and project.approval_withdrawn_at is not None
                    ),
                    "project_approval_withdrawn_reason": project.approval_withdrawn_reason if project else None,
                    "project_approval_withdrawn_at": project.approval_withdrawn_at if project else None,
                    "task_no": task.task_code if task else None,
                    "task_title": f"{task.task_code} · {task.customer_name_snapshot}" if task else None,
                    "assignee_name": _user_label(users.get(row.assignee_user_id)) if row.assignee_user_id else None,
                    "resolved_by_name": _user_label(users.get(row.resolved_by_user_id)) if row.resolved_by_user_id else None,
                    "support_type": support_type,
                    "support_detail": support_detail if has_support_flag or row.item_type == "crm_support_needed" else None,
                    "source_followup_summary": _followup_summary(followup),
                    "needs_next_action": needs_next_action,
                }
            )
        )
    return enriched


def _work_item_public(db: Session, row: WorkItem) -> WorkItemPublic:
    return _work_item_publics(db, [row])[0]


@router.get("/page", response_model=WorkItemPage)
def list_work_items_page(
    q: str | None = None,
    status_value: str | None = None,
    priority: str | None = None,
    item_type: str | None = None,
    project_id: int | None = None,
    customer_code: str | None = None,
    assignee_user_id: int | None = None,
    source_type: str | None = None,
    open_only: bool = False,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_issue.view")),
) -> WorkItemPage:
    safe_limit = _safe_limit(limit)
    safe_offset = _safe_offset(offset)
    stmt = work_item_scope_filter(select(WorkItem), db, current_user)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                WorkItem.item_no.ilike(like),
                WorkItem.title.ilike(like),
                WorkItem.detail.ilike(like),
                WorkItem.customer_code.ilike(like),
                WorkItem.resource_id.ilike(like),
                WorkItem.source_id.ilike(like),
            )
        )
    if status_value:
        stmt = stmt.where(WorkItem.status == status_value)
    elif open_only:
        stmt = stmt.where(WorkItem.status.in_(OPEN_WORK_ITEM_STATUSES))
        frozen_project_ids = select(CrmProject.id).where(
            CrmProject.approval_status == "need_supplement",
            CrmProject.approval_withdrawn_at.is_not(None),
        )
        stmt = stmt.where(or_(WorkItem.project_id.is_(None), WorkItem.project_id.not_in(frozen_project_ids)))
    if priority:
        stmt = stmt.where(WorkItem.priority == priority)
    if item_type:
        stmt = stmt.where(WorkItem.item_type == item_type)
    if project_id is not None:
        stmt = stmt.where(WorkItem.project_id == project_id)
    if customer_code:
        stmt = stmt.where(WorkItem.customer_code == customer_code)
    if assignee_user_id is not None:
        stmt = stmt.where(WorkItem.assignee_user_id == assignee_user_id)
    if source_type:
        stmt = stmt.where(WorkItem.source_type == source_type)
    total = _count_stmt(db, stmt)
    rows = list(
        db.scalars(
            stmt.order_by(WorkItem.status.asc(), WorkItem.due_at.asc().nullslast(), WorkItem.id.desc())
            .offset(safe_offset)
            .limit(safe_limit)
        ).all()
    )
    return WorkItemPage(
        items=_work_item_publics(db, rows),
        total=total,
        limit=safe_limit,
        offset=safe_offset,
    )


@router.get("/{item_id}", response_model=WorkItemPublic)
def get_work_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_issue.view")),
) -> WorkItemPublic:
    return _work_item_public(db, _scoped_work_item(db, current_user, item_id))


@router.patch("/{item_id}", response_model=WorkItemPublic)
def update_work_item(
    item_id: int,
    payload: WorkItemUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_issue.handle")),
) -> WorkItemPublic:
    item = _scoped_work_item(db, current_user, item_id)
    _ensure_work_item_project_operable(db, item)
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("status") == "closed":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Use close action to close a work item")
    validate_work_item_update(db, changes)
    before = jsonable_encoder(item)
    for key, value in changes.items():
        setattr(item, key, value)
    if changes.get("status") == "resolved":
        mark_work_item_resolved(item, current_user, item.resolution_note)
    write_audit_log(
        db,
        action_type="update_work_item",
        resource_type="work_item",
        resource_id=str(item.id),
        user=current_user,
        request=request,
        before_data=before,
        after_data=jsonable_encoder(item),
    )
    db.commit()
    db.refresh(item)
    return _work_item_public(db, item)


@router.post("/{item_id}/resolve", response_model=WorkItemPublic)
def resolve_work_item(
    item_id: int,
    payload: WorkItemActionRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_issue.handle")),
) -> WorkItemPublic:
    item = _scoped_work_item(db, current_user, item_id)
    _ensure_work_item_project_operable(db, item)
    before = jsonable_encoder(item)
    mark_work_item_resolved(item, current_user, payload.resolution_note)
    write_audit_log(
        db,
        action_type="resolve_work_item",
        resource_type="work_item",
        resource_id=str(item.id),
        user=current_user,
        request=request,
        before_data=before,
        after_data=jsonable_encoder(item),
    )
    db.commit()
    db.refresh(item)
    return _work_item_public(db, item)


@router.post("/{item_id}/close", response_model=WorkItemPublic)
def close_work_item(
    item_id: int,
    payload: WorkItemActionRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_issue.close")),
) -> WorkItemPublic:
    item = _scoped_work_item(db, current_user, item_id)
    _ensure_work_item_project_operable(db, item)
    before = jsonable_encoder(item)
    mark_work_item_closed(item, current_user, payload.resolution_note)
    write_audit_log(
        db,
        action_type="close_work_item",
        resource_type="work_item",
        resource_id=str(item.id),
        user=current_user,
        request=request,
        before_data=before,
        after_data=jsonable_encoder(item),
    )
    db.commit()
    db.refresh(item)
    return _work_item_public(db, item)

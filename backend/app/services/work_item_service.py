from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import Select
from sqlalchemy.orm import Session

from app.models import User, WorkItem
from app.models.crm import WORK_ITEM_PRIORITIES, WORK_ITEM_STATUSES
from app.services.crm_access_service import crm_work_item_scope_filter
from app.services.crm_project_service import require_user

OPEN_WORK_ITEM_STATUSES = ("open", "processing")


def validate_work_item_status(status_value: str) -> None:
    if status_value not in WORK_ITEM_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid work item status: {status_value}")


def validate_work_item_priority(priority: str) -> None:
    if priority not in WORK_ITEM_PRIORITIES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid work item priority: {priority}")


def work_item_scope_filter(stmt: Select[tuple[Any, ...]], db: Session, user: User) -> Select[tuple[Any, ...]]:
    return crm_work_item_scope_filter(stmt, db, user)


def validate_work_item_update(db: Session, changes: dict[str, Any]) -> None:
    if "status" in changes and changes["status"] is not None:
        validate_work_item_status(str(changes["status"]))
    if "priority" in changes and changes["priority"] is not None:
        validate_work_item_priority(str(changes["priority"]))
    if "assignee_user_id" in changes:
        require_user(db, changes["assignee_user_id"], "assignee_user_id")


def mark_work_item_resolved(item: WorkItem, operator: User, note: str | None) -> None:
    item.status = "resolved"
    item.resolved_by_user_id = operator.id
    item.resolved_at = datetime.now(timezone.utc)
    item.resolution_note = note


def mark_work_item_closed(item: WorkItem, operator: User, note: str | None) -> None:
    item.status = "closed"
    item.resolved_by_user_id = item.resolved_by_user_id or operator.id
    item.resolved_at = item.resolved_at or datetime.now(timezone.utc)
    item.resolution_note = note if note is not None else item.resolution_note

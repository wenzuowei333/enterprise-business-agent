from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CrmFollowup, CrmProject, CrmProjectCustomerTask, CrmProjectReview, WorkItem


def refresh_task_from_followups(db: Session, task_id: int) -> CrmProjectCustomerTask | None:
    task = db.get(CrmProjectCustomerTask, task_id)
    if task is None:
        return None
    latest = db.scalar(
        select(CrmFollowup)
        .where(CrmFollowup.task_id == task_id)
        .order_by(CrmFollowup.created_at.desc(), CrmFollowup.id.desc())
        .limit(1)
    )
    if latest is None:
        return task
    task.latest_followup_id = latest.id
    task.last_followup_at = latest.created_at
    task.minimum_action_done = latest.minimum_action_done
    task.need_support = latest.need_support
    task.need_manager_support = latest.need_manager_support
    task.need_boss_decision = latest.need_boss_decision
    task.is_blocked = bool(latest.blocker_reason or latest.blocker_note)
    task.is_closed = latest.is_closed
    task.latest_blocker_reason = latest.blocker_reason
    task.latest_blocker_note = latest.blocker_note
    task.latest_owner_next_status = latest.owner_next_status or latest.next_action_type
    task.latest_owner_next_action = latest.owner_next_action or latest.next_action
    task.latest_owner_next_followup_at = latest.owner_next_followup_at or latest.next_followup_at
    if latest.is_closed:
        task.status = "closed"
    elif latest.need_support or latest.need_manager_support or latest.need_boss_decision:
        task.status = "need_support"
    elif latest.review_status == "need_supplement":
        task.status = "need_supplement"
    elif task.status == "not_started":
        task.status = "in_progress"
    return task


def refresh_project_summary(db: Session, project_id: int) -> CrmProject | None:
    project = db.get(CrmProject, project_id)
    if project is None:
        return None
    latest = db.scalar(
        select(CrmFollowup)
        .where(CrmFollowup.project_id == project_id)
        .order_by(
            CrmFollowup.next_followup_at.is_(None),
            CrmFollowup.next_followup_at.asc(),
            CrmFollowup.created_at.desc(),
        )
        .limit(1)
    )
    if latest is not None:
        project.next_step_status = latest.owner_next_status or latest.next_action_type or latest.review_status
        project.next_step_action = latest.owner_next_action or latest.next_action
        project.next_step_followup_at = latest.owner_next_followup_at or latest.next_followup_at
    support_count = db.scalar(
        select(func.count())
        .select_from(CrmProjectCustomerTask)
        .where(
            CrmProjectCustomerTask.project_id == project_id,
            CrmProjectCustomerTask.need_support.is_(True),
        )
    ) or 0
    open_tasks = db.scalar(
        select(func.count())
        .select_from(CrmProjectCustomerTask)
        .where(
            CrmProjectCustomerTask.project_id == project_id,
            CrmProjectCustomerTask.is_closed.is_(False),
        )
    ) or 0
    if project.status not in {"draft", "submitted", "closed", "cancelled"}:
        if support_count:
            project.next_step_status = project.next_step_status or "need_support"
        elif open_tasks == 0:
            project.next_step_status = project.next_step_status or "ready_to_close"
    return project


def project_task_summary(db: Session, project_id: int) -> dict[str, int]:
    total = db.scalar(select(func.count()).select_from(CrmProjectCustomerTask).where(CrmProjectCustomerTask.project_id == project_id)) or 0
    closed = db.scalar(
        select(func.count()).select_from(CrmProjectCustomerTask).where(CrmProjectCustomerTask.project_id == project_id, CrmProjectCustomerTask.is_closed.is_(True))
    ) or 0
    support = db.scalar(
        select(func.count()).select_from(CrmProjectCustomerTask).where(CrmProjectCustomerTask.project_id == project_id, CrmProjectCustomerTask.need_support.is_(True))
    ) or 0
    blocked = db.scalar(
        select(func.count()).select_from(CrmProjectCustomerTask).where(CrmProjectCustomerTask.project_id == project_id, CrmProjectCustomerTask.is_blocked.is_(True))
    ) or 0
    return {"total": total, "closed": closed, "open": max(total - closed, 0), "need_support": support, "blocked": blocked}


def latest_project_followup(db: Session, project_id: int) -> CrmFollowup | None:
    return db.scalar(
        select(CrmFollowup)
        .where(CrmFollowup.project_id == project_id)
        .order_by(CrmFollowup.created_at.desc(), CrmFollowup.id.desc())
        .limit(1)
    )


def project_support_item_count(db: Session, project_id: int) -> int:
    return db.scalar(
        select(func.count())
        .select_from(WorkItem)
        .where(WorkItem.project_id == project_id, WorkItem.status.in_(["open", "processing"]))
    ) or 0


def project_review_summary(db: Session, project_id: int) -> dict[str, int]:
    rows = db.execute(
        select(CrmProjectReview.status, func.count())
        .where(CrmProjectReview.project_id == project_id)
        .group_by(CrmProjectReview.status)
    ).all()
    return {str(status): int(count) for status, count in rows}


def fill_review_counts(db: Session, review: CrmProjectReview) -> None:
    summary = project_task_summary(db, review.project_id)
    review.customer_total = summary["total"]
    review.closed_customer_count = summary["closed"]
    review.unclosed_customer_count = summary["open"]
    review.support_item_count = summary["need_support"]
    feedback_count = db.scalar(
        select(func.count(func.distinct(CrmFollowup.customer_code))).where(CrmFollowup.project_id == review.project_id)
    ) or 0
    valid_count = db.scalar(
        select(func.count(func.distinct(CrmFollowup.customer_code))).where(
            CrmFollowup.project_id == review.project_id,
            CrmFollowup.valid_feedback.is_(True),
        )
    ) or 0
    review.feedback_customer_count = feedback_count
    review.valid_feedback_customer_count = valid_count
    review.no_feedback_customer_count = max(summary["total"] - feedback_count, 0)


def mark_reviewed(followup: CrmFollowup, reviewed_by_user_id: int) -> None:
    followup.reviewed_by_user_id = reviewed_by_user_id
    followup.reviewed_at = datetime.now(timezone.utc)

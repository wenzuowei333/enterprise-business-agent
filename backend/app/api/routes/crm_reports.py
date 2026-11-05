from __future__ import annotations

import csv
import io
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response
from sqlalchemy import Select, case, false, func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_any_permission
from app.core.database import get_db
from app.models import ApprovalInstance, AuditLog, CrmFollowup, CrmProject, CrmProjectCustomerTask, User, WorkItem
from app.schemas.crm import (
    CrmReportNotificationCenter,
    CrmReportNotificationProcessRequest,
    CrmReportNotificationProcessResult,
    CrmReportNotificationPublic,
    CrmReportNotificationSummary,
)
from app.services.approval_access_service import visible_approvals_stmt
from app.services.approval_service import TERMINAL_APPROVAL_STATUSES
from app.services.audit_service import write_audit_log
from app.services.crm_access_service import crm_followup_scope_filter, crm_project_scope_filter, crm_task_scope_filter, crm_work_item_scope_filter
from app.services.permission_service import has_permission
from app.services.work_item_service import OPEN_WORK_ITEM_STATUSES

router = APIRouter(prefix="/crm/reports", tags=["crm-reports"])
BUSINESS_TZ = ZoneInfo("Asia/Shanghai")
MAX_EXPORT_ROWS = 5000


def _count_stmt(db: Session, stmt: Select[tuple[Any, ...]]) -> int:
    return db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0


def _csv_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.astimezone(BUSINESS_TZ).strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return "是" if value else "否"
    return str(value)


def _csv_response(file_name: str, fieldnames: list[str], rows: list[dict[str, Any]]) -> Response:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: _csv_cell(row.get(field)) for field in fieldnames})
    encoded_name = quote(file_name)
    return Response(
        content=("\ufeff" + buffer.getvalue()).encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}"},
    )


def _audit_export(
    db: Session,
    request: Request,
    current_user: User,
    *,
    action_type: str,
    report_name: str,
    row_count: int,
    params: dict[str, Any] | None = None,
) -> None:
    write_audit_log(
        db,
        action_type=action_type,
        resource_type="crm_report",
        resource_id=report_name,
        user=current_user,
        request=request,
        after_data=jsonable_encoder({"report_name": report_name, "row_count": row_count, "params": params or {}}),
    )
    db.commit()


def _period_bounds(period: str, date_from: date | None, date_to: date | None) -> tuple[date, date, datetime, datetime]:
    today = datetime.now(BUSINESS_TZ).date()
    if period == "monthly":
        default_start = today.replace(day=1)
        if default_start.month == 12:
            next_month = default_start.replace(year=default_start.year + 1, month=1)
        else:
            next_month = default_start.replace(month=default_start.month + 1)
        default_end = next_month - timedelta(days=1)
    else:
        default_start = today - timedelta(days=today.weekday())
        default_end = default_start + timedelta(days=6)
    start = date_from or default_start
    end = date_to or default_end
    start_at = datetime.combine(start, time.min, tzinfo=BUSINESS_TZ).astimezone(timezone.utc)
    end_at = datetime.combine(end + timedelta(days=1), time.min, tzinfo=BUSINESS_TZ).astimezone(timezone.utc)
    return start, end, start_at, end_at


def _project_stats(db: Session, project_ids: list[int]) -> dict[int, dict[str, int | datetime | None]]:
    if not project_ids:
        return {}
    task_rows = db.execute(
        select(
            CrmProjectCustomerTask.project_id,
            func.count().label("task_total"),
            func.sum(case((CrmProjectCustomerTask.is_closed.is_(True), 1), else_=0)).label("task_closed"),
            func.sum(case((CrmProjectCustomerTask.need_support.is_(True), 1), else_=0)).label("task_need_support"),
            func.sum(case((CrmProjectCustomerTask.is_blocked.is_(True), 1), else_=0)).label("task_blocked"),
        )
        .where(CrmProjectCustomerTask.project_id.in_(project_ids))
        .group_by(CrmProjectCustomerTask.project_id)
    ).all()
    stats: dict[int, dict[str, int | datetime | None]] = {
        project_id: {
            "task_total": 0,
            "task_closed": 0,
            "task_open": 0,
            "task_need_support": 0,
            "task_blocked": 0,
            "support_item_open": 0,
            "pending_approval_count": 0,
            "latest_followup_at": None,
        }
        for project_id in project_ids
    }
    for row in task_rows:
        item = stats[int(row.project_id)]
        task_total = int(row.task_total or 0)
        task_closed = int(row.task_closed or 0)
        item["task_total"] = task_total
        item["task_closed"] = task_closed
        item["task_open"] = max(task_total - task_closed, 0)
        item["task_need_support"] = int(row.task_need_support or 0)
        item["task_blocked"] = int(row.task_blocked or 0)

    work_item_rows = db.execute(
        select(WorkItem.project_id, func.count())
        .where(WorkItem.project_id.in_(project_ids), WorkItem.status.in_(OPEN_WORK_ITEM_STATUSES))
        .group_by(WorkItem.project_id)
    ).all()
    for project_id, count_value in work_item_rows:
        if project_id in stats:
            stats[int(project_id)]["support_item_open"] = int(count_value or 0)

    approval_rows = db.execute(
        select(ApprovalInstance.resource_id, func.count())
        .where(
            ApprovalInstance.resource_type == "crm_project",
            ApprovalInstance.resource_id.in_([str(project_id) for project_id in project_ids]),
            ApprovalInstance.status.not_in(TERMINAL_APPROVAL_STATUSES),
        )
        .group_by(ApprovalInstance.resource_id)
    ).all()
    for resource_id, count_value in approval_rows:
        if str(resource_id).isdigit() and int(resource_id) in stats:
            stats[int(resource_id)]["pending_approval_count"] = int(count_value or 0)

    followup_rows = db.execute(
        select(CrmFollowup.project_id, func.max(CrmFollowup.created_at))
        .where(CrmFollowup.project_id.in_(project_ids))
        .group_by(CrmFollowup.project_id)
    ).all()
    for project_id, latest_at in followup_rows:
        if project_id in stats:
            stats[int(project_id)]["latest_followup_at"] = latest_at
    return stats


def _project_progress_rows(db: Session, current_user: User, status_value: str | None = None) -> list[dict[str, Any]]:
    stmt = crm_project_scope_filter(select(CrmProject), db, current_user)
    if status_value:
        stmt = stmt.where(CrmProject.status == status_value)
    projects = list(db.scalars(stmt.order_by(CrmProject.updated_at.desc(), CrmProject.id.desc()).limit(MAX_EXPORT_ROWS)).all())
    stats = _project_stats(db, [project.id for project in projects])
    rows: list[dict[str, Any]] = []
    for project in projects:
        project_stats = stats.get(project.id, {})
        rows.append(
            {
                "项目编号": project.project_code,
                "项目名称": project.project_name,
                "项目类型": project.project_type,
                "业务线": project.business_line,
                "项目状态": project.status,
                "审批状态": project.approval_status,
                "开始日期": project.start_date,
                "截止日期": project.due_date,
                "任务总数": project_stats.get("task_total", 0),
                "未闭环任务": project_stats.get("task_open", 0),
                "已闭环任务": project_stats.get("task_closed", 0),
                "待支持任务": project_stats.get("task_need_support", 0),
                "阻塞任务": project_stats.get("task_blocked", 0),
                "未闭环支持项": project_stats.get("support_item_open", 0),
                "待处理审批": project_stats.get("pending_approval_count", 0),
                "最近跟进": project_stats.get("latest_followup_at"),
                "下一步状态": project.next_step_status,
                "下一步动作": project.next_step_action,
                "更新时间": project.updated_at,
            }
        )
    return rows


@router.get("/project-progress.csv")
def export_project_progress(
    request: Request,
    status_value: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("crm_project.view", "crm_task.view")),
) -> Response:
    fieldnames = ["项目编号", "项目名称", "项目类型", "业务线", "项目状态", "审批状态", "开始日期", "截止日期", "任务总数", "未闭环任务", "已闭环任务", "待支持任务", "阻塞任务", "未闭环支持项", "待处理审批", "最近跟进", "下一步状态", "下一步动作", "更新时间"]
    rows = _project_progress_rows(db, current_user, status_value)
    _audit_export(db, request, current_user, action_type="crm_report_export_project_progress", report_name="project-progress", row_count=len(rows), params={"status_value": status_value})
    return _csv_response("项目进度导出.csv", fieldnames, rows)


@router.get("/followups.csv")
def export_followups(
    request: Request,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("crm_followup.view")),
) -> Response:
    stmt = crm_followup_scope_filter(select(CrmFollowup), db, current_user)
    if date_from:
        stmt = stmt.where(CrmFollowup.followup_date >= date_from)
    if date_to:
        stmt = stmt.where(CrmFollowup.followup_date <= date_to)
    followups = list(db.scalars(stmt.order_by(CrmFollowup.created_at.desc(), CrmFollowup.id.desc()).limit(MAX_EXPORT_ROWS)).all())
    fieldnames = ["跟进编号", "项目ID", "任务ID", "客户编号", "跟进日期", "方式", "一线动作", "客户反馈", "当前诉求", "需求类型", "阻塞原因", "下一步类型", "下一步动作", "下次跟进", "需支持", "需主管支持", "需老板决策", "是否闭环", "有效反馈", "审核状态", "审核结果", "负责人下一步状态", "提交人", "创建时间"]
    rows = [
        {
            "跟进编号": item.followup_no,
            "项目ID": item.project_id,
            "任务ID": item.task_id,
            "客户编号": item.customer_code,
            "跟进日期": item.followup_date,
            "方式": item.method,
            "一线动作": item.frontline_action,
            "客户反馈": item.customer_feedback,
            "当前诉求": item.current_need,
            "需求类型": item.need_type,
            "阻塞原因": item.blocker_reason,
            "下一步类型": item.next_action_type,
            "下一步动作": item.next_action,
            "下次跟进": item.next_followup_at,
            "需支持": item.need_support,
            "需主管支持": item.need_manager_support,
            "需老板决策": item.need_boss_decision,
            "是否闭环": item.is_closed,
            "有效反馈": item.valid_feedback,
            "审核状态": item.review_status,
            "审核结果": item.review_result,
            "负责人下一步状态": item.owner_next_status,
            "提交人": item.executor_name_snapshot,
            "创建时间": item.created_at,
        }
        for item in followups
    ]
    _audit_export(db, request, current_user, action_type="crm_report_export_followups", report_name="followups", row_count=len(rows), params={"date_from": date_from, "date_to": date_to})
    return _csv_response("跟进事实导出.csv", fieldnames, rows)


@router.get("/support-items.csv")
def export_support_items(
    request: Request,
    open_only: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("crm_issue.view")),
) -> Response:
    stmt = crm_work_item_scope_filter(select(WorkItem), db, current_user)
    if open_only:
        stmt = stmt.where(WorkItem.status.in_(OPEN_WORK_ITEM_STATUSES))
    items = list(db.scalars(stmt.order_by(WorkItem.status.asc(), WorkItem.due_at.asc().nullslast(), WorkItem.id.desc()).limit(MAX_EXPORT_ROWS)).all())
    fieldnames = ["事项编号", "标题", "类型", "优先级", "状态", "项目ID", "客户编号", "来源类型", "来源ID", "资源类型", "资源ID", "处理人ID", "截止时间", "解决时间", "详情", "解决说明", "更新时间"]
    rows = [
        {
            "事项编号": item.item_no,
            "标题": item.title,
            "类型": item.item_type,
            "优先级": item.priority,
            "状态": item.status,
            "项目ID": item.project_id,
            "客户编号": item.customer_code,
            "来源类型": item.source_type,
            "来源ID": item.source_id,
            "资源类型": item.resource_type,
            "资源ID": item.resource_id,
            "处理人ID": item.assignee_user_id,
            "截止时间": item.due_at,
            "解决时间": item.resolved_at,
            "详情": item.detail,
            "解决说明": item.resolution_note,
            "更新时间": item.updated_at,
        }
        for item in items
    ]
    _audit_export(db, request, current_user, action_type="crm_report_export_support_items", report_name="support-items", row_count=len(rows), params={"open_only": open_only})
    return _csv_response("待支持事项导出.csv", fieldnames, rows)


def _summary_rows(db: Session, current_user: User, period: str, date_from: date | None, date_to: date | None) -> tuple[list[str], list[dict[str, Any]], dict[str, Any]]:
    start, end, start_at, end_at = _period_bounds(period, date_from, date_to)
    project_stmt = (
        crm_project_scope_filter(select(CrmProject), db, current_user)
        if has_permission(db, current_user, "crm_project.view")
        else select(CrmProject).where(false())
    )
    task_stmt = (
        crm_task_scope_filter(select(CrmProjectCustomerTask), db, current_user)
        if has_permission(db, current_user, "crm_task.view")
        else select(CrmProjectCustomerTask).where(false())
    )
    followup_stmt = (
        crm_followup_scope_filter(select(CrmFollowup), db, current_user)
        if has_permission(db, current_user, "crm_followup.view")
        else select(CrmFollowup).where(false())
    )
    work_item_stmt = (
        crm_work_item_scope_filter(select(WorkItem), db, current_user)
        if has_permission(db, current_user, "crm_issue.view")
        else select(WorkItem).where(false())
    )
    approval_stmt = visible_approvals_stmt(db, current_user)
    metrics = [
        ("新增项目", _count_stmt(db, project_stmt.where(CrmProject.created_at >= start_at, CrmProject.created_at < end_at)), "本期创建的 CRM 项目"),
        ("活跃项目", _count_stmt(db, project_stmt.where(CrmProject.status.not_in(["closed", "cancelled"]))), "当前未关闭、未取消项目"),
        ("到期客户任务", _count_stmt(db, task_stmt.where(CrmProjectCustomerTask.feedback_due_at >= start_at, CrmProjectCustomerTask.feedback_due_at < end_at)), "本期应反馈的客户任务"),
        ("已闭环客户任务", _count_stmt(db, task_stmt.where(CrmProjectCustomerTask.is_closed.is_(True), CrmProjectCustomerTask.updated_at >= start_at, CrmProjectCustomerTask.updated_at < end_at)), "本期更新为闭环的客户任务"),
        ("超期未闭环任务", _count_stmt(db, task_stmt.where(CrmProjectCustomerTask.is_closed.is_(False), CrmProjectCustomerTask.feedback_due_at < end_at)), "截至周期末仍未闭环且已过反馈时间"),
        ("跟进事实", _count_stmt(db, followup_stmt.where(CrmFollowup.created_at >= start_at, CrmFollowup.created_at < end_at)), "本期提交的跟进事实"),
        ("有效反馈", _count_stmt(db, followup_stmt.where(CrmFollowup.valid_feedback.is_(True), CrmFollowup.created_at >= start_at, CrmFollowup.created_at < end_at)), "本期有效反馈记录"),
        ("新增待支持", _count_stmt(db, work_item_stmt.where(WorkItem.created_at >= start_at, WorkItem.created_at < end_at)), "本期新增的待支持事项"),
        ("未闭环待支持", _count_stmt(db, work_item_stmt.where(WorkItem.status.in_(OPEN_WORK_ITEM_STATUSES))), "当前仍未闭环的待支持事项"),
        ("待补充审批", _count_stmt(db, approval_stmt.where(ApprovalInstance.status == "need_supplement")), "当前处于待补充状态的审批"),
    ]
    fieldnames = ["周期", "开始日期", "结束日期", "报表项", "数量", "说明"]
    rows = [{"周期": "月报" if period == "monthly" else "周报", "开始日期": start, "结束日期": end, "报表项": label, "数量": value, "说明": detail} for label, value, detail in metrics]
    return fieldnames, rows, {"date_from": start, "date_to": end, "period": period}


@router.get("/weekly.csv")
def export_weekly_report(
    request: Request,
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("crm_project.view", "crm_task.view", "crm_followup.view", "crm_issue.view", "approval.view", "approval.approve", "crm_lead.view", "crm_lead.approve", "customer_tag.review")),
) -> Response:
    fieldnames, rows, params = _summary_rows(db, current_user, "weekly", date_from, date_to)
    _audit_export(db, request, current_user, action_type="crm_report_export_weekly", report_name="weekly", row_count=len(rows), params=params)
    return _csv_response("CRM周报.csv", fieldnames, rows)


@router.get("/monthly.csv")
def export_monthly_report(
    request: Request,
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("crm_project.view", "crm_task.view", "crm_followup.view", "crm_issue.view", "approval.view", "approval.approve", "crm_lead.view", "crm_lead.approve", "customer_tag.review")),
) -> Response:
    fieldnames, rows, params = _summary_rows(db, current_user, "monthly", date_from, date_to)
    _audit_export(db, request, current_user, action_type="crm_report_export_monthly", report_name="monthly", row_count=len(rows), params=params)
    return _csv_response("CRM月报.csv", fieldnames, rows)


def _day_bounds(target_date: date) -> tuple[datetime, datetime]:
    day_start = datetime.combine(target_date, time.min, tzinfo=BUSINESS_TZ).astimezone(timezone.utc)
    day_end = datetime.combine(target_date + timedelta(days=1), time.min, tzinfo=BUSINESS_TZ).astimezone(timezone.utc)
    return day_start, day_end


def _processed_notification_ids(db: Session, notification_ids: list[str]) -> set[str]:
    if not notification_ids:
        return set()
    return set(
        db.scalars(
            select(AuditLog.resource_id).where(
                AuditLog.resource_type == "crm_notification",
                AuditLog.action_type == "crm_notification_process",
                AuditLog.resource_id.in_(notification_ids),
            )
        ).all()
    )


def _notification(
    *,
    notification_type: str,
    source_type: str,
    source_id: str,
    title: str,
    detail: str | None = None,
    priority: str = "normal",
    project_id: int | None = None,
    task_id: int | None = None,
    customer_code: str | None = None,
    action_path: str | None = None,
    created_at: datetime | None = None,
    due_at: datetime | None = None,
    is_mine: bool = False,
) -> CrmReportNotificationPublic:
    notification_id = f"{notification_type}:{source_type}:{source_id}"
    return CrmReportNotificationPublic(
        notification_id=notification_id,
        notification_type=notification_type,
        title=title,
        detail=detail,
        status="pending",
        priority=priority,
        source_type=source_type,
        source_id=source_id,
        project_id=project_id,
        task_id=task_id,
        customer_code=customer_code,
        action_path=action_path,
        created_at=created_at,
        due_at=due_at,
        is_mine=is_mine,
    )


@router.get("/notifications", response_model=CrmReportNotificationCenter)
def crm_report_notifications(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CrmReportNotificationCenter:
    now = datetime.now(timezone.utc)
    today = now.astimezone(BUSINESS_TZ).date()
    day_start, day_end = _day_bounds(today)
    items: list[CrmReportNotificationPublic] = []

    if has_permission(db, current_user, "crm_task.view"):
        today_tasks = list(
            db.scalars(
                crm_task_scope_filter(
                    select(CrmProjectCustomerTask).where(
                        CrmProjectCustomerTask.is_closed.is_(False),
                        CrmProjectCustomerTask.feedback_due_at >= day_start,
                        CrmProjectCustomerTask.feedback_due_at < day_end,
                    ),
                    db,
                    current_user,
                )
                .order_by(CrmProjectCustomerTask.feedback_due_at.asc(), CrmProjectCustomerTask.id.desc())
                .limit(80)
            ).all()
        )
        for task in today_tasks:
            items.append(
                _notification(
                    notification_type="today",
                    source_type="crm_task",
                    source_id=str(task.id),
                    title=f"今日应跟：{task.customer_name_snapshot}",
                    detail=task.round_target or task.business_issue_point,
                    priority="normal",
                    project_id=task.project_id,
                    task_id=task.id,
                    customer_code=task.customer_code,
                    action_path="/crm/tasks",
                    created_at=task.created_at,
                    due_at=task.feedback_due_at,
                    is_mine=task.executor_user_id == current_user.id,
                )
            )
        overdue_tasks = list(
            db.scalars(
                crm_task_scope_filter(
                    select(CrmProjectCustomerTask).where(
                        CrmProjectCustomerTask.is_closed.is_(False),
                        CrmProjectCustomerTask.feedback_due_at.is_not(None),
                        CrmProjectCustomerTask.feedback_due_at < now,
                    ),
                    db,
                    current_user,
                )
                .order_by(CrmProjectCustomerTask.feedback_due_at.asc(), CrmProjectCustomerTask.id.desc())
                .limit(80)
            ).all()
        )
        for task in overdue_tasks:
            items.append(
                _notification(
                    notification_type="overdue",
                    source_type="crm_task",
                    source_id=str(task.id),
                    title=f"超期未反馈：{task.customer_name_snapshot}",
                    detail=task.latest_blocker_note or task.business_issue_point,
                    priority="high",
                    project_id=task.project_id,
                    task_id=task.id,
                    customer_code=task.customer_code,
                    action_path="/crm/tasks",
                    created_at=task.created_at,
                    due_at=task.feedback_due_at,
                    is_mine=task.executor_user_id == current_user.id,
                )
            )

    supplement_approvals = list(
        db.scalars(
            visible_approvals_stmt(db, current_user).where(ApprovalInstance.status == "need_supplement")
            .order_by(ApprovalInstance.updated_at.desc(), ApprovalInstance.id.desc())
            .limit(80)
        ).all()
    )
    for approval in supplement_approvals:
        items.append(
            _notification(
                notification_type="supplement",
                source_type="approval",
                source_id=str(approval.id),
                title=f"待补充：{approval.title}",
                detail=approval.description,
                priority=approval.priority or "normal",
                project_id=int(approval.resource_id) if approval.resource_type == "crm_project" and str(approval.resource_id).isdigit() else None,
                action_path="/crm/submissions" if approval.applicant_user_id == current_user.id else "/crm/work",
                created_at=approval.created_at,
                due_at=approval.updated_at,
                is_mine=approval.applicant_user_id == current_user.id or approval.current_handler_user_id == current_user.id,
            )
        )

    if has_permission(db, current_user, "crm_issue.view"):
        support_items = list(
            db.scalars(
                crm_work_item_scope_filter(select(WorkItem).where(WorkItem.status.in_(OPEN_WORK_ITEM_STATUSES)), db, current_user)
                .order_by(WorkItem.due_at.asc().nullslast(), WorkItem.priority.desc(), WorkItem.id.desc())
                .limit(80)
            ).all()
        )
        for item in support_items:
            items.append(
                _notification(
                    notification_type="support",
                    source_type="work_item",
                    source_id=str(item.id),
                    title=f"待支持：{item.title}",
                    detail=item.detail,
                    priority=item.priority,
                    project_id=item.project_id,
                    customer_code=item.customer_code,
                    action_path="/crm/issues",
                    created_at=item.created_at,
                    due_at=item.due_at,
                    is_mine=item.assignee_user_id == current_user.id,
                )
            )

    processed_ids = _processed_notification_ids(db, [item.notification_id for item in items])
    for item in items:
        if item.notification_id in processed_ids:
            item.status = "processed"
    items.sort(key=lambda item: (item.status == "processed", {"high": 0, "urgent": 0, "normal": 1, "low": 2}.get(item.priority, 1), item.due_at or now))
    summary = CrmReportNotificationSummary(
        total=len(items),
        pending=sum(1 for item in items if item.status != "processed"),
        processed=sum(1 for item in items if item.status == "processed"),
        today=sum(1 for item in items if item.notification_type == "today"),
        overdue=sum(1 for item in items if item.notification_type == "overdue"),
        supplement=sum(1 for item in items if item.notification_type == "supplement"),
        support=sum(1 for item in items if item.notification_type == "support"),
    )
    return CrmReportNotificationCenter(summary=summary, items=items[:240], generated_at=now)


@router.post("/notifications/{notification_id:path}/process", response_model=CrmReportNotificationProcessResult)
def process_crm_report_notification(
    notification_id: str,
    payload: CrmReportNotificationProcessRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CrmReportNotificationProcessResult:
    action = payload.action.strip() or "handled"
    write_audit_log(
        db,
        action_type="crm_notification_process",
        resource_type="crm_notification",
        resource_id=notification_id,
        user=current_user,
        request=request,
        after_data=jsonable_encoder({"action": action, "note": payload.note, "processed_at": datetime.now(timezone.utc)}),
    )
    db.commit()
    return CrmReportNotificationProcessResult(status="processed", notification_id=notification_id, action=action, audit_logged=True)

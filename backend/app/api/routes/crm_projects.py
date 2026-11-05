from datetime import date, datetime, time, timezone
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import Integer, Select, case, cast, exists, func, or_, select, text
from sqlalchemy.orm import Session

from app.api.dependencies import require_any_permission, require_crm_permission
from app.core.database import get_db
from app.models import AuditLog, ApprovalInstance, CrmFollowup, CrmProject, CrmProjectCustomerTask, CrmProjectReview, CustomerBusinessProfile, CustomerMaster, User, WorkItem
from app.schemas.crm import (
    ApprovalInstancePublic,
    CrmBusinessProfileApprovalDraftCreate,
    CrmBusinessProfileUpdateResponse,
    CrmCustomerProfileApprovalDraftCreate,
    CrmFollowupCreate,
    CrmFollowupApprovalDraftCreate,
    CrmFollowupPage,
    CrmFollowupPublic,
    CrmFollowupUpdate,
    CrmDailySummary,
    CrmDailySummaryTask,
    CrmDataCenterBucket,
    CrmDataCenterDimensions,
    CrmDataCenterPage,
    CrmDataCenterSummary,
    CrmDataCenterTaskRow,
    CrmLinkedCustomerPage,
    CrmLinkedCustomerRow,
    CrmLinkedCustomerSummary,
    CrmProjectApprovalDraftCreate,
    CrmProjectClosureSummary,
    CrmProjectCreate,
    CrmProjectContext,
    CrmProjectCustomerDetailPage,
    CrmProjectCustomerDetailRow,
    CrmProjectCustomerDetailSummary,
    CrmProjectCustomerTaskPublic,
    CrmProjectDetail,
    CrmProjectPage,
    CrmProjectPublic,
    CrmProjectReviewCreate,
    CrmProjectReviewPublic,
    CrmProjectReviewUpdate,
    CrmTestProjectCandidate,
    CrmTestProjectCounts,
    CrmTestProjectPage,
    CrmProjectUpdate,
    CrmSummary,
    CrmTaskCreate,
    CrmTaskDetail,
    CrmTaskPage,
    CrmTaskSubmissionSummary,
    CrmTaskUpdate,
    CrmVoidTestProjectRequest,
    CrmVoidTestProjectResult,
    WorkItemPublic,
)
from app.schemas.master_data import CustomerBusinessProfileResponse, CustomerBusinessProfileUpsert, CustomerMasterUpdate
from app.services.access_control_service import serialize_with_field_rules
from app.services.approval_service import TERMINAL_APPROVAL_STATUSES, create_approval_instance, transition_approval
from app.services.audit_service import write_audit_log
from app.services.crm_access_service import crm_followup_scope_filter, crm_project_scope_filter, crm_task_scope_filter, crm_work_item_scope_filter
from app.services.customer_business_profile_service import apply_customer_business_profile_update, customer_business_profile_response, customer_business_products
from app.services.customer_master_service import apply_customer_master_update, build_customer_profile_patch, customer_audit_snapshot
from app.services.crm_project_service import (
    ensure_project_operable,
    ensure_unique_followup_no,
    ensure_unique_project_code,
    ensure_unique_review_no,
    ensure_unique_task_code,
    followup_audit_snapshot,
    generated_code,
    project_audit_snapshot,
    require_customer,
    require_user,
    review_audit_snapshot,
    task_audit_snapshot,
    task_executor_snapshot,
    validate_approval_status,
    validate_followup_review_status,
    validate_project_status,
    validate_review_status,
    validate_task_status,
)
from app.services.crm_rollup_service import (
    fill_review_counts,
    latest_project_followup,
    mark_reviewed,
    project_review_summary,
    project_support_item_count,
    project_task_summary,
    refresh_project_summary,
    refresh_task_from_followups,
)
from app.services.exception_center_service import enqueue_incremental_exception_scan_safely
from app.services.permission_service import has_permission

router = APIRouter(prefix="/crm", tags=["crm-projects"])
BUSINESS_TZ = ZoneInfo("Asia/Shanghai")
TEST_DATA_MARKERS = ("TEMP", "E2E", "temporary", "temp")
TEST_PROJECT_VOID_CONFIRMATION = "VOID_TEST_PROJECT"
PROJECT_APPROVER_USERNAME = "admin"
CRM_BUSINESS_PROFILE_ACTIVE_PROJECT_STATUSES = {"draft", "submitted", "active", "paused"}


def _frozen_project_ids() -> Any:
    return select(CrmProject.id).where(
        CrmProject.approval_status == "need_supplement",
        CrmProject.approval_withdrawn_at.is_not(None),
    )

FOLLOWUP_REVIEW_FIELDS = {
    "review_status",
    "review_result",
    "review_note",
    "owner_next_status",
    "owner_next_action",
    "owner_next_followup_at",
}

PROFILE_UPDATE_ACTIVE_APPROVAL_STATUSES = {"submitted", "under_review", "approved", "completed", "need_supplement"}
DATA_UPDATE_APPROVAL_TYPES = {"customer_profile_update", "customer_business_profile_update"}
TASK_APPROVAL_TYPES = {"crm_followup_submit", *DATA_UPDATE_APPROVAL_TYPES}
TASK_DATA_UPDATE_PENDING_STATUSES = {"submitted", "under_review", "need_supplement"}
FOLLOWUP_SUBMITTED_APPROVAL_STATUSES = {"submitted", "under_review", "approved", "completed"}
FOLLOWUP_NEEDS_ACTION_APPROVAL_STATUSES = {"need_supplement", "rejected", "cancelled"}
CRM_CUSTOMER_PROFILE_DIRECT_ACTION = "crm_customer_profile_update_direct"
CRM_BUSINESS_PROFILE_DIRECT_ACTION = "crm_business_profile_update_direct"


def _safe_limit(limit: int) -> int:
    return max(1, min(limit, 100))


def _safe_offset(offset: int) -> int:
    return max(0, offset)


def _count_stmt(db: Session, stmt: Select[tuple[Any, ...]]) -> int:
    return db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0


def _is_sqlite(db: Session) -> bool:
    bind = db.get_bind()
    return bool(bind is not None and bind.dialect.name == "sqlite")


def _approval_payload_dict(approval: ApprovalInstance) -> dict[str, Any]:
    return approval.payload_json if isinstance(approval.payload_json, dict) else {}


def _payload_path(payload: dict[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _payload_path_int(payload: dict[str, Any], *keys: str) -> int | None:
    raw_value = _payload_path(payload, *keys)
    if raw_value in {"", None}:
        return None
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return None


def _approval_task_id(approval: ApprovalInstance) -> int | None:
    payload = _approval_payload_dict(approval)
    if approval.approval_type == "crm_followup_submit":
        return _payload_path_int(payload, "followup", "task_id")
    return _payload_path_int(payload, "task_id")


def _approval_project_id(approval: ApprovalInstance) -> int | None:
    payload = _approval_payload_dict(approval)
    if approval.approval_type == "crm_followup_submit":
        return _payload_path_int(payload, "followup", "project_id")
    return _payload_path_int(payload, "project_id")


def _approval_activity_at(approval: ApprovalInstance) -> datetime:
    return approval.submitted_at or approval.reviewed_at or approval.closed_at or approval.created_at


def _audit_after_data_dict(audit: AuditLog) -> dict[str, Any]:
    return audit.after_data if isinstance(audit.after_data, dict) else {}


def _audit_context_data(audit: AuditLog) -> dict[str, Any]:
    after_data = _audit_after_data_dict(audit)
    nested = after_data.get("audit_extra")
    return nested if isinstance(nested, dict) else after_data


def _direct_profile_update_task_id(audit: AuditLog) -> int | None:
    return _payload_path_int(_audit_context_data(audit), "task_id")


def _latest_direct_update_audit(
    db: Session,
    tasks: list[CrmProjectCustomerTask],
    action_type: str,
) -> AuditLog | None:
    task_ids = {task.id for task in tasks}
    customer_codes = {task.customer_code for task in tasks if task.customer_code}
    if not task_ids or not customer_codes:
        return None
    rows = list(
        db.scalars(
            select(AuditLog)
            .where(
                AuditLog.action_type == action_type,
                AuditLog.resource_id.in_(sorted(customer_codes)),
            )
            .order_by(AuditLog.id.desc())
        ).all()
    )
    matched = [row for row in rows if _direct_profile_update_task_id(row) in task_ids]
    return max(matched, key=lambda item: (item.created_at, item.id)) if matched else None


def _task_data_update_defaults(task: CrmProjectCustomerTask) -> None:
    task.data_update_total = 0
    task.data_update_pending = 0
    task.latest_data_update_at = None
    task.customer_profile_approval_id = None
    task.customer_profile_approval_status = None
    task.business_profile_approval_id = None
    task.business_profile_approval_status = None


def _fill_task_project_purpose(db: Session, tasks: list[CrmProjectCustomerTask]) -> None:
    project_ids = {task.project_id for task in tasks}
    purpose_by_project_id = dict(
        db.execute(
            select(CrmProject.id, CrmProject.purpose).where(CrmProject.id.in_(project_ids))
        ).all()
    ) if project_ids else {}
    for task in tasks:
        task.project_purpose = purpose_by_project_id.get(task.project_id)


def _task_search_conditions(like: str):
    return (
        CrmProjectCustomerTask.task_code.ilike(like),
        CrmProjectCustomerTask.customer_code.ilike(like),
        CrmProjectCustomerTask.customer_name_snapshot.ilike(like),
        CrmProjectCustomerTask.executor_name_snapshot.ilike(like),
        CrmProjectCustomerTask.business_issue_point.ilike(like),
        CrmProjectCustomerTask.round_target.ilike(like),
        CrmProjectCustomerTask.project_id.in_(
            select(CrmProject.id).where(CrmProject.purpose.ilike(like))
        ),
    )


def _followup_approval_task_id_expression() -> Any:
    return cast(ApprovalInstance.payload_json["followup"]["task_id"].as_string(), Integer)


def _latest_followup_submission_subquery() -> Any:
    task_id = _followup_approval_task_id_expression()
    ranked = (
        select(
            task_id.label("task_id"),
            ApprovalInstance.status.label("approval_status"),
            ApprovalInstance.submitted_at.label("submitted_at"),
            ApprovalInstance.created_at.label("created_at"),
            func.row_number()
            .over(
                partition_by=task_id,
                order_by=(ApprovalInstance.created_at.desc(), ApprovalInstance.id.desc()),
            )
            .label("row_number"),
        )
        .where(
            ApprovalInstance.approval_type == "crm_followup_submit",
            ApprovalInstance.status != "draft",
            task_id.is_not(None),
        )
        .subquery()
    )
    return (
        select(
            ranked.c.task_id,
            ranked.c.approval_status,
            ranked.c.submitted_at,
            ranked.c.created_at,
        )
        .where(ranked.c.row_number == 1)
        .subquery()
    )


def _followup_submission_state_expression(latest_submission: Any) -> Any:
    has_formal_followup = or_(
        CrmProjectCustomerTask.latest_followup_id.is_not(None),
        CrmProjectCustomerTask.last_followup_at.is_not(None),
        exists().where(CrmFollowup.task_id == CrmProjectCustomerTask.id),
    )
    return case(
        (latest_submission.c.approval_status.in_(sorted(FOLLOWUP_NEEDS_ACTION_APPROVAL_STATUSES)), "needs_action"),
        (latest_submission.c.approval_status.in_(sorted(FOLLOWUP_SUBMITTED_APPROVAL_STATUSES)), "submitted"),
        (latest_submission.c.approval_status.is_not(None), "needs_action"),
        (has_formal_followup, "submitted"),
        else_="unsubmitted",
    )


def _task_submission_page_query(
    db: Session,
    stmt: Select[tuple[CrmProjectCustomerTask]],
    selected_state: Literal["unsubmitted", "submitted", "needs_action"] | None,
) -> tuple[Select[tuple[CrmProjectCustomerTask]], CrmTaskSubmissionSummary]:
    latest_submission = _latest_followup_submission_subquery()
    state_expression = _followup_submission_state_expression(latest_submission)
    scoped_task_ids = stmt.with_only_columns(CrmProjectCustomerTask.id).order_by(None).subquery()
    summary_rows = db.execute(
        select(state_expression.label("submission_state"), func.count(CrmProjectCustomerTask.id))
        .select_from(CrmProjectCustomerTask)
        .join(scoped_task_ids, scoped_task_ids.c.id == CrmProjectCustomerTask.id)
        .outerjoin(latest_submission, latest_submission.c.task_id == CrmProjectCustomerTask.id)
        .group_by(state_expression)
    ).all()
    counts = {str(state): int(count) for state, count in summary_rows}
    summary = CrmTaskSubmissionSummary(
        total=sum(counts.values()),
        submitted=counts.get("submitted", 0),
        unsubmitted=counts.get("unsubmitted", 0),
        needs_action=counts.get("needs_action", 0),
    )
    result_stmt = stmt.outerjoin(latest_submission, latest_submission.c.task_id == CrmProjectCustomerTask.id)
    if selected_state is not None:
        result_stmt = result_stmt.where(state_expression == selected_state)
    return result_stmt, summary


def _fill_task_followup_submission(db: Session, tasks: list[CrmProjectCustomerTask]) -> None:
    if not tasks:
        return
    task_by_id = {task.id: task for task in tasks}
    task_ids = sorted(task_by_id)
    approval_rows = list(
        db.scalars(
            select(ApprovalInstance)
            .where(
                ApprovalInstance.approval_type == "crm_followup_submit",
                ApprovalInstance.status != "draft",
                _followup_approval_task_id_expression().in_(task_ids),
            )
            .order_by(ApprovalInstance.created_at.desc(), ApprovalInstance.id.desc())
        ).all()
    )
    latest_by_task_id: dict[int, ApprovalInstance] = {}
    for approval in approval_rows:
        task_id = _approval_task_id(approval)
        if task_id in task_by_id and task_id not in latest_by_task_id:
            latest_by_task_id[task_id] = approval
    formal_task_ids = set(
        db.scalars(select(CrmFollowup.task_id).where(CrmFollowup.task_id.in_(task_ids)).distinct()).all()
    )
    for task in tasks:
        approval = latest_by_task_id.get(task.id)
        task.latest_followup_approval_status = approval.status if approval else None
        task.latest_followup_submitted_at = (approval.submitted_at or approval.created_at) if approval else None
        if approval and approval.status in FOLLOWUP_NEEDS_ACTION_APPROVAL_STATUSES:
            task.followup_submission_state = "needs_action"
        elif approval and approval.status in FOLLOWUP_SUBMITTED_APPROVAL_STATUSES:
            task.followup_submission_state = "submitted"
        elif approval:
            task.followup_submission_state = "needs_action"
        elif task.latest_followup_id is not None or task.last_followup_at is not None or task.id in formal_task_ids:
            task.followup_submission_state = "submitted"
            task.latest_followup_submitted_at = task.last_followup_at
        else:
            task.followup_submission_state = "unsubmitted"


def _fill_task_data_update_summary(db: Session, tasks: list[CrmProjectCustomerTask]) -> None:
    if not tasks:
        return
    task_by_id = {task.id: task for task in tasks}
    customer_codes = {task.customer_code for task in tasks if task.customer_code}
    for task in tasks:
        _task_data_update_defaults(task)
    if not customer_codes:
        return
    approval_rows = list(
        db.scalars(
            select(ApprovalInstance)
            .where(
                ApprovalInstance.approval_type.in_(sorted(DATA_UPDATE_APPROVAL_TYPES)),
                ApprovalInstance.resource_id.in_(sorted(customer_codes)),
            )
            .order_by(ApprovalInstance.id.desc())
        ).all()
    )
    grouped: dict[int, list[ApprovalInstance]] = {task_id: [] for task_id in task_by_id}
    for approval in approval_rows:
        task_id = _approval_task_id(approval)
        if task_id in grouped:
            grouped[task_id].append(approval)
    for task_id, approvals in grouped.items():
        task = task_by_id[task_id]
        approvals.sort(key=lambda item: (_approval_activity_at(item), item.id), reverse=True)
        task.data_update_total = len(approvals)
        task.data_update_pending = sum(1 for item in approvals if item.status in TASK_DATA_UPDATE_PENDING_STATUSES)
        task.latest_data_update_at = _approval_activity_at(approvals[0]) if approvals else None
        for approval in approvals:
            if approval.approval_type == "customer_profile_update" and task.customer_profile_approval_id is None:
                task.customer_profile_approval_id = approval.id
                task.customer_profile_approval_status = approval.status
            if approval.approval_type == "customer_business_profile_update" and task.business_profile_approval_id is None:
                task.business_profile_approval_id = approval.id
                task.business_profile_approval_status = approval.status
    direct_update_rows = list(
        db.scalars(
            select(AuditLog)
            .where(
                AuditLog.action_type.in_([CRM_CUSTOMER_PROFILE_DIRECT_ACTION, CRM_BUSINESS_PROFILE_DIRECT_ACTION]),
                AuditLog.resource_id.in_(sorted(customer_codes)),
            )
            .order_by(AuditLog.id.desc())
        ).all()
    )
    direct_grouped: dict[int, list[AuditLog]] = {task_id: [] for task_id in task_by_id}
    for audit in direct_update_rows:
        task_id = _direct_profile_update_task_id(audit)
        if task_id in direct_grouped:
            direct_grouped[task_id].append(audit)
    for task_id, audits in direct_grouped.items():
        if not audits:
            continue
        task = task_by_id[task_id]
        audits.sort(key=lambda item: (item.created_at, item.id), reverse=True)
        task.data_update_total += len(audits)
        latest_audit = audits[0]
        if task.latest_data_update_at is None or latest_audit.created_at > task.latest_data_update_at:
            task.latest_data_update_at = latest_audit.created_at
        latest_customer_audit = next((audit for audit in audits if audit.action_type == CRM_CUSTOMER_PROFILE_DIRECT_ACTION), None)
        latest_business_audit = next((audit for audit in audits if audit.action_type == CRM_BUSINESS_PROFILE_DIRECT_ACTION), None)
        if latest_customer_audit and task.customer_profile_approval_status is None:
            task.customer_profile_approval_status = "synced"
        if latest_business_audit and task.business_profile_approval_status is None:
            task.business_profile_approval_status = "synced"


def _mark_task_started_by_data_update(db: Session, task: CrmProjectCustomerTask) -> None:
    if task.is_closed or task.status == "closed":
        return
    if task.status == "not_started":
        task.status = "in_progress"
    task.minimum_action_done = True
    task.latest_owner_next_status = "资料更新已提交"
    task.latest_owner_next_action = task.latest_owner_next_action or "等待资料更新审批"
    refresh_project_summary(db, task.project_id)


def _task_approval_rows(db: Session, task: CrmProjectCustomerTask, limit: int = 8) -> list[ApprovalInstance]:
    if _is_sqlite(db):
        candidates = list(
            db.scalars(
                select(ApprovalInstance)
                .where(ApprovalInstance.approval_type.in_(sorted(TASK_APPROVAL_TYPES)))
                .order_by(ApprovalInstance.id.desc())
            ).all()
        )
        rows = [approval for approval in candidates if _approval_task_id(approval) == task.id]
        return rows[:limit]
    rows = list(
        db.scalars(
            select(ApprovalInstance)
            .where(
                or_(
                    (ApprovalInstance.approval_type == "crm_followup_submit")
                    & text("(approval_instance.payload_json #>> '{followup,task_id}') = :crm_task_approval_task_id").bindparams(
                        crm_task_approval_task_id=str(task.id)
                    ),
                    ApprovalInstance.approval_type.in_(sorted(DATA_UPDATE_APPROVAL_TYPES))
                    & text("(approval_instance.payload_json #>> '{task_id}') = :crm_task_data_update_task_id").bindparams(
                        crm_task_data_update_task_id=str(task.id)
                    ),
                )
            )
            .order_by(ApprovalInstance.id.desc())
            .limit(limit)
        ).all()
    )
    return rows


def _approval_node_status(approval: ApprovalInstance | None) -> str:
    if approval is None:
        return "none"
    if approval.status in TERMINAL_APPROVAL_STATUSES:
        return "done" if approval.status == "completed" else "rejected"
    if approval.status == "need_supplement":
        return "need_supplement"
    return "pending"


def _latest_approval_by_type(approvals: list[ApprovalInstance], approval_type: str) -> ApprovalInstance | None:
    matches = [approval for approval in approvals if approval.approval_type == approval_type]
    if not matches:
        return None
    return max(matches, key=lambda item: (_approval_activity_at(item), item.id))


def _crm_flow_nodes_for_context(
    db: Session,
    *,
    task_rows: list[CrmProjectCustomerTask],
    project_rows: list[CrmProject],
    approval_rows: list[ApprovalInstance],
    work_item_rows: list[WorkItem],
    current_user: User,
) -> list[dict[str, Any]]:
    latest_task = max(
        task_rows,
        key=lambda task: _latest_datetime(task.last_followup_at, task.updated_at) or task.created_at,
    ) if task_rows else None
    latest_project = max(project_rows, key=lambda project: project.updated_at or project.created_at) if project_rows else None
    project_approval = _latest_approval_by_type(approval_rows, "crm_project_application")
    followup_approval = _latest_approval_by_type(approval_rows, "crm_followup_submit")
    profile_approval = _latest_approval_by_type(approval_rows, "customer_profile_update")
    business_approval = _latest_approval_by_type(approval_rows, "customer_business_profile_update")
    direct_profile_update = _latest_direct_update_audit(db, task_rows, CRM_CUSTOMER_PROFILE_DIRECT_ACTION)
    direct_business_update = _latest_direct_update_audit(db, task_rows, CRM_BUSINESS_PROFILE_DIRECT_ACTION)
    open_work_items = [item for item in work_item_rows if item.status in ["open", "processing"]]
    nodes = [
        {
            "key": "project_submitted",
            "label": "项目申请已提交",
            "status": "done" if latest_project or latest_task else "none",
            "handler_label": _format_user_label(db.get(User, latest_project.created_by_user_id)) if latest_project and latest_project.created_by_user_id else None,
            "at": latest_project.created_at if latest_project else (latest_task.created_at if latest_task else None),
            "waiting_for_current_user": False,
        },
        {
            "key": "landing_approval",
            "label": "项目落地审批",
            "status": _approval_node_status(project_approval) if project_approval else ("done" if latest_project and latest_project.approval_status in ["approved", "completed"] else "none"),
            "handler_label": _format_user_label(db.get(User, project_approval.current_handler_user_id)) if project_approval and project_approval.current_handler_user_id else None,
            "at": _approval_activity_at(project_approval) if project_approval else (latest_project.updated_at if latest_project else None),
            "waiting_for_current_user": bool(project_approval and project_approval.current_handler_user_id == current_user.id and project_approval.status not in TERMINAL_APPROVAL_STATUSES),
        },
        {
            "key": "task_assigned",
            "label": "任务已分配",
            "status": "done" if latest_task and latest_task.executor_user_id else ("pending" if latest_task else "none"),
            "handler_label": latest_task.executor_name_snapshot if latest_task else None,
            "at": latest_task.updated_at if latest_task else None,
            "waiting_for_current_user": bool(latest_task and latest_task.executor_user_id == current_user.id and not latest_task.is_closed),
        },
        {
            "key": "followup_submitted",
            "label": "一线已提交跟进",
            "status": _approval_node_status(followup_approval) if followup_approval else ("done" if latest_task and latest_task.last_followup_at else "pending" if latest_task else "none"),
            "handler_label": _format_user_label(db.get(User, followup_approval.current_handler_user_id)) if followup_approval and followup_approval.current_handler_user_id else None,
            "at": _approval_activity_at(followup_approval) if followup_approval else (latest_task.last_followup_at if latest_task else None),
            "waiting_for_current_user": bool(followup_approval and followup_approval.current_handler_user_id == current_user.id and followup_approval.status not in TERMINAL_APPROVAL_STATUSES),
        },
        {
            "key": "customer_profile_approval",
            "label": "基本资料已保存",
            "status": "done" if direct_profile_update else _approval_node_status(profile_approval),
            "handler_label": _format_user_label(db.get(User, direct_profile_update.user_id)) if direct_profile_update and direct_profile_update.user_id else (_format_user_label(db.get(User, profile_approval.current_handler_user_id)) if profile_approval and profile_approval.current_handler_user_id else None),
            "at": direct_profile_update.created_at if direct_profile_update else (_approval_activity_at(profile_approval) if profile_approval else None),
            "waiting_for_current_user": bool(not direct_profile_update and profile_approval and profile_approval.current_handler_user_id == current_user.id and profile_approval.status not in TERMINAL_APPROVAL_STATUSES),
            "approval_id": profile_approval.id if profile_approval else None,
        },
        {
            "key": "business_profile_approval",
            "label": "经营资料已保存",
            "status": "done" if direct_business_update else _approval_node_status(business_approval),
            "handler_label": _format_user_label(db.get(User, direct_business_update.user_id)) if direct_business_update and direct_business_update.user_id else (_format_user_label(db.get(User, business_approval.current_handler_user_id)) if business_approval and business_approval.current_handler_user_id else None),
            "at": direct_business_update.created_at if direct_business_update else (_approval_activity_at(business_approval) if business_approval else None),
            "waiting_for_current_user": bool(not direct_business_update and business_approval and business_approval.current_handler_user_id == current_user.id and business_approval.status not in TERMINAL_APPROVAL_STATUSES),
            "approval_id": business_approval.id if business_approval else None,
        },
        {
            "key": "support_handling",
            "label": "待支持处理",
            "status": "pending" if open_work_items else "none",
            "handler_label": _format_user_label(db.get(User, open_work_items[0].assignee_user_id)) if open_work_items and open_work_items[0].assignee_user_id else None,
            "at": open_work_items[0].updated_at if open_work_items else None,
            "waiting_for_current_user": bool(open_work_items and open_work_items[0].assignee_user_id == current_user.id),
            "count": len(open_work_items),
        },
        {
            "key": "task_closed",
            "label": "任务闭环",
            "status": "done" if latest_task and latest_task.is_closed else ("pending" if latest_task else "none"),
            "handler_label": latest_task.executor_name_snapshot if latest_task else None,
            "at": latest_task.updated_at if latest_task and latest_task.is_closed else None,
            "waiting_for_current_user": bool(latest_task and latest_task.executor_user_id == current_user.id and not latest_task.is_closed),
        },
    ]
    return jsonable_encoder(nodes)


def _clean_update(payload: Any) -> dict[str, Any]:
    return payload.model_dump(exclude_unset=True)


def _apply_changes(row: Any, changes: dict[str, Any]) -> None:
    for key, value in changes.items():
        setattr(row, key, value)


def _normalize_user_ids(db: Session, user_ids: list[int] | None, field_name: str) -> list[int] | None:
    if user_ids is None:
        return None
    normalized = list(dict.fromkeys(int(user_id) for user_id in user_ids))
    for user_id in normalized:
        require_user(db, user_id, field_name)
    return normalized


def _normalize_participants(db: Session, participant_user_ids: list[int] | None) -> list[int] | None:
    return _normalize_user_ids(db, participant_user_ids, "participant_user_ids")


def _project_or_404(db: Session, project_id: int) -> CrmProject:
    project = db.get(CrmProject, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CRM project not found")
    return project


def _fixed_active_handler(db: Session, username: str, label: str) -> User:
    user = db.scalar(
        select(User).where(
            User.username == username,
            User.status == "active",
            User.is_active.is_(True),
        )
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{label}账号不存在或未启用：{username}",
        )
    return user


def _format_user_label(user: User | None) -> str | None:
    if user is None:
        return None
    name = user.real_name or user.username
    return f"{name} / {user.username}"


def _project_user_label_payload(db: Session, project: CrmProject) -> dict[str, Any]:
    user_ids: set[int] = set()
    for user_id in [
        project.applicant_user_id,
        project.landing_approver_user_id,
        project.owner_user_id,
        project.project_manager_user_id,
        project.approval_withdrawn_by_user_id,
    ]:
        if user_id:
            user_ids.add(user_id)
    for user_id in project.participant_user_ids or []:
        if user_id:
            user_ids.add(int(user_id))
    for user_id in project.progress_cc_user_ids or []:
        if user_id:
            user_ids.add(int(user_id))
    users = {user.id: user for user in db.scalars(select(User).where(User.id.in_(list(user_ids)))).all()} if user_ids else {}
    return {
        "applicant_user_label": _format_user_label(users.get(project.applicant_user_id)) if project.applicant_user_id else None,
        "landing_approver_user_label": _format_user_label(users.get(project.landing_approver_user_id)) if project.landing_approver_user_id else None,
        "owner_user_label": _format_user_label(users.get(project.owner_user_id)) if project.owner_user_id else None,
        "project_manager_user_label": _format_user_label(users.get(project.project_manager_user_id)) if project.project_manager_user_id else None,
        "approval_withdrawn_by_user_label": _format_user_label(users.get(project.approval_withdrawn_by_user_id)) if project.approval_withdrawn_by_user_id else None,
        "participant_user_labels": [
            label for label in (_format_user_label(users.get(int(user_id))) for user_id in project.participant_user_ids or []) if label
        ],
        "progress_cc_user_labels": [
            label for label in (_format_user_label(users.get(int(user_id))) for user_id in project.progress_cc_user_ids or []) if label
        ],
    }


def _project_owner_handler(db: Session, project: CrmProject, label: str) -> User:
    if not project.owner_user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"细节审批人缺失，无法提交{label}")
    user = db.scalar(
        select(User).where(
            User.id == project.owner_user_id,
            User.status == "active",
            User.is_active.is_(True),
        )
    )
    if user is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"细节审批人账号不存在或未启用，无法提交{label}")
    return user


def _is_progress_cc_only(project: CrmProject, user: User) -> bool:
    progress_cc_ids = {int(user_id) for user_id in project.progress_cc_user_ids or [] if user_id}
    if user.id not in progress_cc_ids:
        return False
    action_role_ids = {
        project.applicant_user_id,
        project.landing_approver_user_id,
        project.owner_user_id,
        project.project_manager_user_id,
        project.created_by_user_id,
    }
    action_role_ids.update(int(user_id) for user_id in project.participant_user_ids or [] if user_id)
    return user.id not in action_role_ids


def _scoped_project(db: Session, current_user: User, project_id: int) -> CrmProject:
    stmt = crm_project_scope_filter(select(CrmProject).where(CrmProject.id == project_id), db, current_user)
    project = db.scalar(stmt)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CRM project not found")
    return project


def _scoped_task(db: Session, current_user: User, task_id: int) -> CrmProjectCustomerTask:
    stmt = crm_task_scope_filter(select(CrmProjectCustomerTask).where(CrmProjectCustomerTask.id == task_id), db, current_user)
    task = db.scalar(stmt)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CRM project task not found")
    return task


def _scoped_active_customer_task(
    db: Session,
    current_user: User,
    customer_code: str,
) -> tuple[CrmProjectCustomerTask, CrmProject]:
    stmt = crm_task_scope_filter(
        select(CrmProjectCustomerTask, CrmProject)
        .join(CrmProject, CrmProject.id == CrmProjectCustomerTask.project_id)
        .where(
            CrmProjectCustomerTask.customer_code == customer_code,
            CrmProject.status.in_(CRM_BUSINESS_PROFILE_ACTIVE_PROJECT_STATUSES),
        ),
        db,
        current_user,
    )
    row = db.execute(stmt.order_by(CrmProjectCustomerTask.updated_at.desc(), CrmProjectCustomerTask.id.desc())).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CRM linked customer not found or project already ended")
    task, project = row
    return task, project


def _customer_base_info_completeness(customer: CustomerMaster) -> str:
    missing = []
    if not customer.contact_phone:
        missing.append("缺电话")
    if not customer.address:
        missing.append("缺地址")
    if not customer.contact_name:
        missing.append("缺联系人")
    return "完整" if not missing else "、".join(missing)


def _crm_customer_profile_detail_payload(db: Session, current_user: User, customer: CustomerMaster) -> dict[str, Any]:
    data = serialize_with_field_rules(db, current_user, "customer", customer)
    data["base_info_completeness"] = _customer_base_info_completeness(customer)
    return data


CUSTOMER_PROFILE_FIELD_LABELS = {
    "customer_name": "客户名称",
    "customer_short_name": "客户简称",
    "customer_type": "客户类型",
    "region": "所属区域",
    "salesperson_employee_code": "业务员工号",
    "salesperson_name": "当前业务员",
    "contact_name": "联系人",
    "contact_phone": "联系电话",
    "contact_channel": "微信/对接方式",
    "customer_group_name": "客户群名称",
    "customer_tags": "客户标签",
    "address": "详细地址",
    "status": "客户状态",
    "profile_updated_at": "资料更新时间",
    "base_remark": "基础备注",
}

BUSINESS_PROFILE_FIELD_LABELS = {
    "business_customer_type": "经营客户类型",
    "confirmed_at": "确认日期",
    "filled_by": "填写人",
    "update_source": "更新来源",
    "update_type": "更新类型",
    "current_salesperson": "当前业务员",
    "sales_channels": "销售渠道",
    "business_status_tags": "经营状态标签",
    "business_status_label": "经营状态",
    "business_status_note": "经营状态说明",
    "other_status_label": "其他状态",
    "other_status_note": "其他状态说明",
    "latest_update_note": "最近更新说明",
    "confirmed_by": "确认人",
    "products": "经营产品清单",
    "recommended_products": "拜访推荐产品",
}


def _business_profile_snapshot(profile: CustomerBusinessProfile | None) -> dict[str, Any] | None:
    if profile is None:
        return None
    return jsonable_encoder({
        "business_customer_type": profile.business_customer_type,
        "confirmed_at": profile.confirmed_at,
        "filled_by": profile.filled_by,
        "update_source": profile.update_source,
        "update_type": profile.update_type,
        "current_salesperson": profile.current_salesperson,
        "sales_channels": profile.sales_channels or [],
        "business_status_tags": profile.business_status_tags or [],
        "business_status_label": profile.business_status_label,
        "business_status_note": profile.business_status_note,
        "other_status_label": profile.other_status_label,
        "other_status_note": profile.other_status_note,
        "latest_update_note": profile.latest_update_note,
        "confirmed_by": profile.confirmed_by,
    })


def _business_products_snapshot(db: Session, customer_code: str) -> list[dict[str, Any]]:
    return jsonable_encoder([
        {
            "product_category": product.product_category,
            "spec": product.spec,
            "common_brand": product.common_brand,
            "monthly_usage": product.monthly_usage,
            "price_sensitivity": product.price_sensitivity,
            "cooperation_status": product.cooperation_status,
            "change_type": product.change_type,
            "opportunity_note": product.opportunity_note,
            "last_confirmed_at": product.last_confirmed_at,
            "sort_order": product.sort_order,
            "is_active": product.is_active,
        }
        for product in customer_business_products(db, customer_code)
    ])


def _recommended_products_payload(rows: list[Any] | None) -> list[dict[str, Any]]:
    if not rows:
        return []
    cleaned: list[dict[str, Any]] = []
    for row in rows:
        data = row.model_dump(exclude_unset=True) if hasattr(row, "model_dump") else dict(row or {})
        item = {
            "product_name": _clean_text(data.get("product_name")),
            "spec": _clean_text(data.get("spec")),
            "recommended_quote": _clean_text(data.get("recommended_quote")),
            "recommend_reason": _clean_text(data.get("recommend_reason")),
            "customer_feedback": _clean_text(data.get("customer_feedback")),
            "next_action": _clean_text(data.get("next_action")),
        }
        if any(item.values()):
            cleaned.append(item)
    return cleaned[:50]


def _approval_change_items(before_data: dict[str, Any] | None, after_data: dict[str, Any], labels: dict[str, str]) -> list[dict[str, Any]]:
    before = before_data or {}
    items: list[dict[str, Any]] = []
    for field, after_value in after_data.items():
        before_value = before.get(field)
        encoded_before = jsonable_encoder(before_value)
        encoded_after = jsonable_encoder(after_value)
        if encoded_before != encoded_after:
            items.append({
                "field": field,
                "label": labels.get(field, field),
                "before": encoded_before,
                "after": encoded_after,
            })
    return items


def _is_blank_customer_profile_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return len(value) == 0
    return False


def _direct_customer_profile_patch(before_profile: dict[str, Any], incoming_profile: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    # CRM 基本资料保存常来自大表单。旧前端可能把未填写字段以空值一起提交；
    # 多字段提交时保护已有值不被这些空值误清空。单字段空值仍视为有意清空。
    explicit_single_field_clear = len(incoming_profile) == 1
    guarded_profile: dict[str, Any] = {}
    for field, value in incoming_profile.items():
        before_value = before_profile.get(field)
        if (
            not explicit_single_field_clear
            and _is_blank_customer_profile_value(value)
            and not _is_blank_customer_profile_value(before_value)
        ):
            continue
        guarded_profile[field] = value
    return build_customer_profile_patch(before_profile, guarded_profile, CUSTOMER_PROFILE_FIELD_LABELS)


def _validate_customer_profile_followup_link(db: Session, *, data: dict[str, Any], task: CrmProjectCustomerTask) -> None:
    if not data.get("customer_profile_updated"):
        return
    approval_id = data.get("customer_profile_approval_id")
    if not approval_id:
        direct_updates = list(
            db.scalars(
                select(AuditLog).where(
                    AuditLog.action_type == CRM_CUSTOMER_PROFILE_DIRECT_ACTION,
                    AuditLog.resource_type == "customer",
                    AuditLog.resource_id == task.customer_code,
                )
            ).all()
        )
        for audit in direct_updates:
            try:
                if int(_audit_context_data(audit).get("task_id")) == task.id:
                    return
            except (TypeError, ValueError):
                continue
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请先保存客户基本资料，或取消该勾选。")
    approval = db.get(ApprovalInstance, int(approval_id))
    if approval is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="客户基本资料更新审批单不存在。")
    payload = approval.payload_json if isinstance(approval.payload_json, dict) else {}
    if approval.approval_type != "customer_profile_update":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="关联的审批单不是客户基本资料更新审批。")
    if approval.status not in PROFILE_UPDATE_ACTIVE_APPROVAL_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="客户基本资料更新审批单状态不可用于跟进闭环。")
    if str(payload.get("customer_code") or approval.resource_id or "") != str(task.customer_code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="客户基本资料更新审批单与当前客户不一致。")
    payload_project_id = payload.get("project_id")
    if payload_project_id not in {None, ""}:
        try:
            if int(payload_project_id) != task.project_id:
                raise ValueError
        except (TypeError, ValueError):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="客户基本资料更新审批单与当前项目不一致。")


def _validate_business_profile_followup_link(db: Session, *, data: dict[str, Any], task: CrmProjectCustomerTask) -> None:
    if not data.get("business_profile_updated"):
        return
    approval_id = data.get("business_profile_approval_id")
    if not approval_id:
        direct_updates = list(
            db.scalars(
                select(AuditLog).where(
                    AuditLog.action_type == CRM_BUSINESS_PROFILE_DIRECT_ACTION,
                    AuditLog.resource_type == "customer_business_profile",
                    AuditLog.resource_id == task.customer_code,
                )
            ).all()
        )
        for audit in direct_updates:
            try:
                if int(_audit_context_data(audit).get("task_id")) == task.id:
                    return
            except (TypeError, ValueError):
                continue
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请先保存客户经营资料，或取消该勾选。")
    approval = db.get(ApprovalInstance, int(approval_id))
    if approval is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="客户经营资料更新审批单不存在。")
    payload = approval.payload_json if isinstance(approval.payload_json, dict) else {}
    if approval.approval_type != "customer_business_profile_update":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="关联的审批单不是客户经营资料更新审批。")
    if approval.status not in PROFILE_UPDATE_ACTIVE_APPROVAL_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="客户经营资料更新审批单状态不可用于跟进闭环。")
    if str(payload.get("customer_code") or approval.resource_id or "") != str(task.customer_code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="客户经营资料更新审批单与当前客户不一致。")
    payload_project_id = payload.get("project_id")
    if payload_project_id not in {None, ""}:
        try:
            if int(payload_project_id) != task.project_id:
                raise ValueError
        except (TypeError, ValueError):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="客户经营资料更新审批单与当前项目不一致。")


def _crm_task_is_overdue(task: CrmProjectCustomerTask, now: datetime) -> bool:
    return bool(task.feedback_due_at and not task.is_closed and task.feedback_due_at < now)


def _compact_options(values: list[str | None], limit: int = 80) -> list[str]:
    seen: dict[str, None] = {}
    for value in values:
        text_value = str(value or "").strip()
        if text_value and text_value not in seen:
            seen[text_value] = None
        if len(seen) >= limit:
            break
    return list(seen.keys())


def _crm_project_customer_detail_row(
    task: CrmProjectCustomerTask,
    customer: CustomerMaster | None,
    now: datetime,
) -> CrmProjectCustomerDetailRow:
    return CrmProjectCustomerDetailRow(
        id=task.id,
        project_id=task.project_id,
        task_code=task.task_code,
        customer_code=task.customer_code,
        customer_name_snapshot=task.customer_name_snapshot,
        customer_name=customer.customer_name if customer else task.customer_name_snapshot,
        customer_short_name=customer.customer_short_name if customer else None,
        customer_type=customer.customer_type if customer else None,
        customer_status=customer.status if customer else None,
        customer_group_name=customer.customer_group_name if customer else None,
        region=customer.region if customer else None,
        salesperson_employee_code=customer.salesperson_employee_code if customer else None,
        salesperson_name=customer.salesperson_name if customer else None,
        contact_name=customer.contact_name if customer else None,
        contact_phone=customer.contact_phone if customer else None,
        executor_user_id=task.executor_user_id,
        executor_employee_code=task.executor_employee_code,
        executor_name_snapshot=task.executor_name_snapshot,
        business_issue_point=task.business_issue_point,
        round_target=task.round_target,
        feedback_due_at=task.feedback_due_at,
        status=task.status,
        task_status=task.status,
        minimum_action_done=task.minimum_action_done,
        need_support=task.need_support,
        need_manager_support=task.need_manager_support,
        need_boss_decision=task.need_boss_decision,
        is_blocked=task.is_blocked,
        is_closed=task.is_closed,
        overdue=_crm_task_is_overdue(task, now),
        latest_followup_id=task.latest_followup_id,
        latest_blocker_reason=task.latest_blocker_reason,
        latest_blocker_note=task.latest_blocker_note,
        latest_owner_next_status=task.latest_owner_next_status,
        latest_owner_next_action=task.latest_owner_next_action,
        latest_owner_next_followup_at=task.latest_owner_next_followup_at,
        last_followup_at=task.last_followup_at,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def _crm_project_customer_detail_summary(rows: list[tuple[CrmProjectCustomerTask, CustomerMaster | None]], now: datetime) -> CrmProjectCustomerDetailSummary:
    tasks = [task for task, _customer in rows]
    customers = [customer for _task, customer in rows]
    return CrmProjectCustomerDetailSummary(
        total=len(tasks),
        open=sum(1 for task in tasks if not task.is_closed),
        closed=sum(1 for task in tasks if task.is_closed),
        overdue=sum(1 for task in tasks if _crm_task_is_overdue(task, now)),
        need_support=sum(1 for task in tasks if task.need_support or task.need_manager_support or task.need_boss_decision),
        need_manager_support=sum(1 for task in tasks if task.need_manager_support),
        need_boss_decision=sum(1 for task in tasks if task.need_boss_decision),
        blocked=sum(1 for task in tasks if task.is_blocked),
        customer_groups=_compact_options([customer.customer_group_name if customer else None for customer in customers]),
        salespersons=_compact_options([
            customer.salesperson_name if customer and customer.salesperson_name else task.executor_name_snapshot
            for task, customer in rows
        ]),
        regions=_compact_options([customer.region if customer else None for customer in customers]),
        customer_types=_compact_options([customer.customer_type if customer else None for customer in customers]),
        customer_statuses=_compact_options([customer.status if customer else None for customer in customers]),
        task_statuses=_compact_options([task.status for task in tasks]),
        blocker_reasons=_compact_options([task.latest_blocker_reason for task in tasks]),
    )


def _latest_datetime(*values: datetime | None) -> datetime | None:
    candidates = [value for value in values if value is not None]
    return max(candidates) if candidates else None


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text_value = str(value).strip()
    return text_value or None


def _crm_linked_customer_risk(task_overdue: int, task_blocked: int, task_need_support: int, task_open: int) -> str:
    if task_blocked > 0 or task_overdue > 0:
        return "high"
    if task_need_support > 0:
        return "medium"
    if task_open > 0:
        return "watch"
    return "normal"


def _crm_linked_customer_flow_summary(
    task: CrmProjectCustomerTask,
    *,
    latest_followup_at: datetime | None,
    work_item_open: int,
) -> dict[str, str | None]:
    handler = task.executor_name_snapshot or (f"用户 #{task.executor_user_id}" if task.executor_user_id else None)
    blocker = _clean_text(task.latest_blocker_reason) or _clean_text(task.latest_blocker_note)
    next_action = _clean_text(task.latest_owner_next_action)
    next_status = _clean_text(task.latest_owner_next_status)
    if task.is_closed or task.status == "closed":
        return {
            "current_flow_node": "任务闭环",
            "current_handler_label": handler,
            "blocked_reason_summary": next_action or blocker,
            "flow_status": "done",
        }
    if work_item_open > 0 or task.need_support or task.need_manager_support or task.need_boss_decision:
        return {
            "current_flow_node": "待支持处理",
            "current_handler_label": handler,
            "blocked_reason_summary": blocker or next_action or "等待支持事项处理",
            "flow_status": "blocked" if task.is_blocked else "pending",
        }
    if task.is_blocked:
        return {
            "current_flow_node": "待支持处理",
            "current_handler_label": handler,
            "blocked_reason_summary": blocker or next_action or "任务已标记阻塞",
            "flow_status": "blocked",
        }
    if latest_followup_at or task.last_followup_at or next_action or next_status:
        return {
            "current_flow_node": "一线已提交跟进",
            "current_handler_label": handler,
            "blocked_reason_summary": next_action or next_status or blocker,
            "flow_status": "in_progress",
        }
    if task.executor_user_id:
        return {
            "current_flow_node": "任务已分配",
            "current_handler_label": handler,
            "blocked_reason_summary": task.business_issue_point or task.round_target,
            "flow_status": "pending",
        }
    return {
        "current_flow_node": "任务已分配",
        "current_handler_label": None,
        "blocked_reason_summary": "客户任务暂未分配一线业务员",
        "flow_status": "pending",
    }


def _crm_customer_tags(customer: CustomerMaster | None) -> list[str]:
    if customer is None or not isinstance(customer.customer_tags, list):
        return []
    return [str(item).strip() for item in customer.customer_tags if str(item).strip()]


def _crm_customer_completeness(customer: CustomerMaster | None) -> str | None:
    if customer is None:
        return None
    missing: list[str] = []
    if not _clean_text(customer.contact_phone):
        missing.append("缺电话")
    if not _clean_text(customer.address):
        missing.append("缺地址")
    if not _clean_text(customer.contact_name):
        missing.append("缺联系人")
    if not _clean_text(customer.customer_group_name):
        missing.append("缺客户群")
    return "完整" if not missing else " / ".join(missing)


def _crm_customer_profile_payload(customer: CustomerMaster | None, *, include_details: bool) -> dict[str, Any]:
    if customer is None:
        return {}
    payload: dict[str, Any] = {
        "customer_short_name": customer.customer_short_name,
        "customer_updated_at": customer.updated_at,
    }
    if include_details:
        payload.update(
            {
                "customer_type": customer.customer_type,
                "customer_status": customer.status,
                "status": customer.status,
                "region": customer.region,
                "salesperson_employee_code": customer.salesperson_employee_code,
                "salesperson_name": customer.salesperson_name,
                "contact_name": customer.contact_name,
                "contact_phone": customer.contact_phone,
                "contact_channel": customer.contact_channel,
                "customer_group_name": customer.customer_group_name,
                "customer_tags": _crm_customer_tags(customer),
                "address": customer.address,
                "base_info_completeness": _crm_customer_completeness(customer),
                "profile_updated_at": customer.profile_updated_at,
                "base_remark": customer.base_remark,
            }
        )
    return payload


def _crm_linked_customer_row(
    customer_code: str,
    rows: list[tuple[CrmProjectCustomerTask, CustomerMaster | None, CrmProject]],
    now: datetime,
    followup_total: int,
    latest_followup_at: datetime | None,
    work_item_open: int,
    *,
    include_customer_profile: bool,
) -> CrmLinkedCustomerRow:
    tasks = [task for task, _customer, _project in rows]
    projects = [project for _task, _customer, project in rows]
    project_by_id = {project.id: project for project in projects}
    latest_pair = max(
        rows,
        key=lambda item: _latest_datetime(item[0].last_followup_at, item[0].updated_at, item[2].updated_at) or item[0].created_at,
    )
    latest_task, latest_customer, latest_project = latest_pair
    task_open = sum(1 for task in tasks if not task.is_closed)
    task_closed = sum(1 for task in tasks if task.is_closed)
    task_overdue = sum(1 for task in tasks if _crm_task_is_overdue(task, now))
    task_need_support = sum(1 for task in tasks if task.need_support or task.need_manager_support or task.need_boss_decision)
    task_blocked = sum(1 for task in tasks if task.is_blocked)
    task_status_counts: dict[str, int] = {}
    for task in tasks:
        status_key = "closed" if task.is_closed else (task.status or "not_started")
        task_status_counts[status_key] = task_status_counts.get(status_key, 0) + 1
    executor_names = _compact_options([task.executor_name_snapshot for task in tasks], limit=6)
    best_followup_at = _latest_datetime(latest_followup_at, *[task.last_followup_at for task in tasks])
    customer_name = latest_customer.customer_name if latest_customer else latest_task.customer_name_snapshot
    flow_summary = _crm_linked_customer_flow_summary(
        latest_task,
        latest_followup_at=best_followup_at,
        work_item_open=work_item_open,
    )
    return CrmLinkedCustomerRow(
        customer_code=customer_code,
        customer_name=customer_name or latest_task.customer_name_snapshot or customer_code,
        customer_name_snapshot=latest_task.customer_name_snapshot,
        **_crm_customer_profile_payload(latest_customer, include_details=include_customer_profile),
        project_total=len(project_by_id),
        latest_project_id=latest_project.id,
        latest_project_name=latest_project.project_name,
        latest_project_status=latest_project.status,
        task_total=len(tasks),
        task_open=task_open,
        task_closed=task_closed,
        task_overdue=task_overdue,
        task_need_support=task_need_support,
        task_blocked=task_blocked,
        task_status_counts=task_status_counts,
        followup_total=followup_total,
        latest_followup_at=best_followup_at,
        work_item_open=work_item_open,
        executor_names=executor_names,
        latest_task_id=latest_task.id,
        latest_task_code=latest_task.task_code,
        latest_task_status=latest_task.status,
        latest_owner_next_status=latest_task.latest_owner_next_status,
        latest_owner_next_action=latest_task.latest_owner_next_action,
        latest_owner_next_followup_at=latest_task.latest_owner_next_followup_at,
        latest_blocker_reason=latest_task.latest_blocker_reason,
        current_flow_node=flow_summary["current_flow_node"],
        current_handler_label=flow_summary["current_handler_label"],
        blocked_reason_summary=flow_summary["blocked_reason_summary"],
        flow_status=flow_summary["flow_status"],
        last_activity_at=_latest_datetime(best_followup_at, latest_task.updated_at, latest_project.updated_at),
        risk_level=_crm_linked_customer_risk(task_overdue, task_blocked, task_need_support, task_open),
    )


def _crm_linked_customer_summary(rows: list[CrmLinkedCustomerRow], generated_at: datetime) -> CrmLinkedCustomerSummary:
    return CrmLinkedCustomerSummary(
        total_customers=len(rows),
        project_total=sum(row.project_total for row in rows),
        task_total=sum(row.task_total for row in rows),
        task_open=sum(row.task_open for row in rows),
        task_closed=sum(row.task_closed for row in rows),
        task_overdue=sum(row.task_overdue for row in rows),
        task_need_support=sum(row.task_need_support for row in rows),
        task_blocked=sum(row.task_blocked for row in rows),
        followup_total=sum(row.followup_total for row in rows),
        work_item_open=sum(row.work_item_open for row in rows),
        profile_incomplete=sum(1 for row in rows if row.base_info_completeness and row.base_info_completeness != "完整"),
        pending_action_customers=sum(1 for row in rows if row.latest_owner_next_action or row.blocked_reason_summary or row.work_item_open > 0),
        risk_customers=sum(1 for row in rows if row.risk_level in {"high", "medium"} or row.task_blocked > 0 or row.task_overdue > 0 or row.task_need_support > 0 or row.work_item_open > 0),
        generated_at=generated_at,
    )


def _crm_data_center_followup_status(task: CrmProjectCustomerTask, now: datetime) -> str:
    if task.is_closed:
        return "closed"
    if _crm_task_is_overdue(task, now):
        return "overdue"
    if task.is_blocked:
        return "blocked"
    if task.need_boss_decision:
        return "need_boss_decision"
    if task.need_manager_support:
        return "need_manager_support"
    if task.need_support:
        return "need_support"
    if not task.last_followup_at:
        return "not_followed"
    return task.latest_owner_next_status or "followed"


def _crm_data_center_risk_level(task: CrmProjectCustomerTask, now: datetime) -> str:
    if task.is_blocked or task.need_boss_decision or _crm_task_is_overdue(task, now):
        return "high"
    if task.need_support or task.need_manager_support or not task.last_followup_at:
        return "medium"
    return "closed" if task.is_closed else "normal"


def _crm_data_center_task_row(
    task: CrmProjectCustomerTask,
    customer: CustomerMaster | None,
    project: CrmProject | None,
    now: datetime,
) -> CrmDataCenterTaskRow:
    base = _crm_project_customer_detail_row(task, customer, now).model_dump()
    return CrmDataCenterTaskRow(
        **base,
        project_name=project.project_name if project else None,
        project_code=project.project_code if project else None,
        project_status=project.status if project else None,
        project_owner_user_id=project.owner_user_id if project else None,
        project_manager_user_id=project.project_manager_user_id if project else None,
        followup_status=_crm_data_center_followup_status(task, now),
        risk_level=_crm_data_center_risk_level(task, now),
    )


def _crm_data_center_is_risky(row: CrmDataCenterTaskRow) -> bool:
    return row.risk_level in {"high", "medium"}


def _crm_data_center_bucket(
    rows: list[CrmDataCenterTaskRow],
    build_value: Any,
    build_label: Any,
    limit: int = 12,
) -> list[CrmDataCenterBucket]:
    bucket_map: dict[str, dict[str, Any]] = {}
    for row in rows:
        value = str(build_value(row) or "").strip()
        if not value:
            value = "__empty__"
        label = str(build_label(row) or "").strip() or "未填写"
        current = bucket_map.setdefault(value, {"value": value, "label": label, "count": 0, "risk_count": 0})
        current["count"] += 1
        if _crm_data_center_is_risky(row):
            current["risk_count"] += 1
    return [
        CrmDataCenterBucket(**item)
        for item in sorted(bucket_map.values(), key=lambda bucket: (-bucket["count"], bucket["label"]))[:limit]
    ]


def _crm_data_center_dimensions(rows: list[CrmDataCenterTaskRow]) -> CrmDataCenterDimensions:
    return CrmDataCenterDimensions(
        projects=_crm_data_center_bucket(rows, lambda row: row.project_id, lambda row: row.project_name or f"项目 {row.project_id}"),
        owners=_crm_data_center_bucket(
            rows,
            lambda row: row.executor_user_id or row.executor_name_snapshot or row.executor_employee_code,
            lambda row: row.executor_name_snapshot or row.executor_employee_code or (f"用户 {row.executor_user_id}" if row.executor_user_id else "未分配"),
        ),
        regions=_crm_data_center_bucket(rows, lambda row: row.region, lambda row: row.region),
        customer_types=_crm_data_center_bucket(rows, lambda row: row.customer_type, lambda row: row.customer_type),
        blocker_reasons=_crm_data_center_bucket(rows, lambda row: row.latest_blocker_reason, lambda row: row.latest_blocker_reason),
        followup_statuses=_crm_data_center_bucket(rows, lambda row: row.followup_status, lambda row: row.followup_status),
    )


def _crm_data_center_summary(
    rows: list[CrmDataCenterTaskRow],
    project_total: int,
    open_work_items: int,
    pending_approvals: int,
    valid_feedback_tasks: int,
    now: datetime,
) -> CrmDataCenterSummary:
    return CrmDataCenterSummary(
        project_total=project_total,
        task_total=len(rows),
        open_tasks=sum(1 for row in rows if not row.is_closed),
        closed_tasks=sum(1 for row in rows if row.is_closed),
        overdue_tasks=sum(1 for row in rows if row.overdue),
        need_support_tasks=sum(1 for row in rows if row.need_support or row.need_manager_support or row.need_boss_decision),
        blocked_tasks=sum(1 for row in rows if row.is_blocked),
        no_followup_tasks=sum(1 for row in rows if not row.last_followup_at),
        valid_feedback_tasks=valid_feedback_tasks,
        open_work_items=open_work_items,
        pending_approvals=pending_approvals,
        generated_at=now,
    )


def _crm_data_center_scope_filter(rows: list[CrmDataCenterTaskRow], scope: str | None) -> list[CrmDataCenterTaskRow]:
    if not scope or scope == "all":
        return rows
    if scope == "open":
        return [row for row in rows if not row.is_closed]
    if scope == "closed":
        return [row for row in rows if row.is_closed]
    if scope == "overdue":
        return [row for row in rows if row.overdue]
    if scope == "support":
        return [row for row in rows if row.need_support or row.need_manager_support or row.need_boss_decision]
    if scope == "blocked":
        return [row for row in rows if row.is_blocked]
    if scope == "no_followup":
        return [row for row in rows if not row.last_followup_at]
    return rows


def _scoped_followup(db: Session, current_user: User, followup_id: int) -> CrmFollowup:
    stmt = crm_followup_scope_filter(select(CrmFollowup).where(CrmFollowup.id == followup_id), db, current_user)
    followup = db.scalar(stmt)
    if followup is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CRM followup not found")
    return followup


def _followup_public_rows(db: Session, followups: list[CrmFollowup]) -> list[CrmFollowupPublic]:
    if not followups:
        return []
    customer_codes = {followup.customer_code for followup in followups if followup.customer_code}
    customer_names = {
        customer_code: customer_name
        for customer_code, customer_name in db.execute(
            select(CustomerMaster.customer_code, CustomerMaster.customer_name).where(CustomerMaster.customer_code.in_(customer_codes))
        ).all()
    } if customer_codes else {}
    task_ids = {followup.task_id for followup in followups if followup.task_id}
    task_customer_names = {
        task_id: customer_name
        for task_id, customer_name in db.execute(
            select(CrmProjectCustomerTask.id, CrmProjectCustomerTask.customer_name_snapshot).where(CrmProjectCustomerTask.id.in_(task_ids))
        ).all()
    } if task_ids else {}
    project_ids = {followup.project_id for followup in followups if followup.project_id}
    project_names = {
        project_id: project_name
        for project_id, project_name in db.execute(
            select(CrmProject.id, CrmProject.project_name).where(CrmProject.id.in_(project_ids))
        ).all()
    } if project_ids else {}
    return [
        CrmFollowupPublic.model_validate(followup).model_copy(update={
            "customer_name": customer_names.get(followup.customer_code) or task_customer_names.get(followup.task_id) or followup.customer_code,
            "project_name": project_names.get(followup.project_id),
        })
        for followup in followups
    ]


def _approval_summary(db: Session, project: CrmProject) -> dict[str, int]:
    if _is_sqlite(db):
        summary: dict[str, int] = {}
        for approval in _project_approval_rows(db, project):
            summary[approval.status] = summary.get(approval.status, 0) + 1
        return summary
    rows = db.execute(
        select(ApprovalInstance.status, func.count())
        .where(
            or_(*_project_approval_filters(project)),
        )
        .group_by(ApprovalInstance.status)
    ).all()
    return {str(status_value): int(count) for status_value, count in rows}


def _pending_approval_count(db: Session, project: CrmProject) -> int:
    if _is_sqlite(db):
        return sum(1 for approval in _project_approval_rows(db, project) if approval.status in TASK_DATA_UPDATE_PENDING_STATUSES)
    return db.scalar(
        select(func.count())
        .select_from(ApprovalInstance)
        .where(
            or_(*_project_approval_filters(project)),
            ApprovalInstance.status.in_(["submitted", "under_review", "need_supplement"]),
        )
    ) or 0


def _project_approval_rows(db: Session, project: CrmProject) -> list[ApprovalInstance]:
    candidates = list(
        db.scalars(
            select(ApprovalInstance)
            .where(
                or_(
                    (ApprovalInstance.resource_type == "crm_project") & (ApprovalInstance.resource_id == str(project.id)),
                    ApprovalInstance.approval_type.in_(sorted(TASK_APPROVAL_TYPES)),
                )
            )
            .order_by(ApprovalInstance.id.desc())
        ).all()
    )
    rows: list[ApprovalInstance] = []
    for approval in candidates:
        if approval.resource_type == "crm_project" and approval.resource_id == str(project.id):
            rows.append(approval)
            continue
        if _approval_project_id(approval) == project.id:
            rows.append(approval)
            continue
        if project.current_approval_id and approval.id == project.current_approval_id:
            rows.append(approval)
    return rows


def _project_approval_filters(project: CrmProject) -> list[Any]:
    filters: list[Any] = [
        (ApprovalInstance.resource_type == "crm_project") & (ApprovalInstance.resource_id == str(project.id)),
        (ApprovalInstance.approval_type == "crm_followup_submit")
        & text("(approval_instance.payload_json #>> '{followup,project_id}') = :crm_project_approval_project_id").bindparams(
            crm_project_approval_project_id=str(project.id)
        ),
        (ApprovalInstance.approval_type.in_(sorted(DATA_UPDATE_APPROVAL_TYPES)))
        & text("(approval_instance.payload_json #>> '{project_id}') = :crm_project_data_update_project_id").bindparams(
            crm_project_data_update_project_id=str(project.id)
        ),
    ]
    if project.current_approval_id:
        filters.append(ApprovalInstance.id == project.current_approval_id)
    return filters


def _project_closure_summary(db: Session, project: CrmProject) -> CrmProjectClosureSummary:
    task_summary = project_task_summary(db, project.id)
    now = datetime.now(timezone.utc)
    task_total = task_summary.get("total", 0)
    feedback_task_count = db.scalar(
        select(func.count(func.distinct(CrmFollowup.task_id))).where(CrmFollowup.project_id == project.id)
    ) or 0
    valid_feedback_task_count = db.scalar(
        select(func.count(func.distinct(CrmFollowup.task_id))).where(
            CrmFollowup.project_id == project.id,
            CrmFollowup.valid_feedback.is_(True),
        )
    ) or 0
    task_overdue = db.scalar(
        select(func.count())
        .select_from(CrmProjectCustomerTask)
        .where(
            CrmProjectCustomerTask.project_id == project.id,
            CrmProjectCustomerTask.is_closed.is_(False),
            CrmProjectCustomerTask.feedback_due_at.is_not(None),
            CrmProjectCustomerTask.feedback_due_at < now,
        )
    ) or 0
    support_open_count = db.scalar(
        select(func.count())
        .select_from(WorkItem)
        .where(WorkItem.project_id == project.id, WorkItem.status.in_(["open", "processing"]))
    ) or 0
    support_closed_count = db.scalar(
        select(func.count())
        .select_from(WorkItem)
        .where(WorkItem.project_id == project.id, WorkItem.status.in_(["resolved", "closed"]))
    ) or 0
    pending_approval_count = db.scalar(
        select(func.count())
        .select_from(ApprovalInstance)
        .where(
            or_(*_project_approval_filters(project)),
            ApprovalInstance.status.in_(["submitted", "under_review", "need_supplement"]),
        )
    ) or 0
    review_total = db.scalar(
        select(func.count()).select_from(CrmProjectReview).where(CrmProjectReview.project_id == project.id)
    ) or 0
    review_confirmed = db.scalar(
        select(func.count())
        .select_from(CrmProjectReview)
        .where(CrmProjectReview.project_id == project.id, CrmProjectReview.status == "confirmed")
    ) or 0
    latest_review = db.scalar(
        select(CrmProjectReview)
        .where(CrmProjectReview.project_id == project.id)
        .order_by(CrmProjectReview.review_date.desc().nullslast(), CrmProjectReview.id.desc())
        .limit(1)
    )
    task_open = task_summary.get("open", 0)
    task_blocked = task_summary.get("blocked", 0)
    no_feedback_task_count = max(task_total - feedback_task_count, 0)
    if task_total == 0:
        closure_state = "no_tasks"
    elif task_blocked > 0 or support_open_count > 0 or pending_approval_count > 0:
        closure_state = "blocked"
    elif task_open > 0 or task_overdue > 0 or no_feedback_task_count > 0:
        closure_state = "in_progress"
    elif review_confirmed == 0:
        closure_state = "need_review"
    else:
        closure_state = "ready"
    return CrmProjectClosureSummary(
        task_total=task_total,
        task_closed=task_summary.get("closed", 0),
        task_open=task_open,
        task_need_support=task_summary.get("need_support", 0),
        task_blocked=task_blocked,
        task_overdue=task_overdue,
        feedback_task_count=feedback_task_count,
        valid_feedback_task_count=valid_feedback_task_count,
        no_feedback_task_count=no_feedback_task_count,
        support_open_count=support_open_count,
        support_closed_count=support_closed_count,
        pending_approval_count=pending_approval_count,
        review_total=review_total,
        review_confirmed=review_confirmed,
        latest_review_status=latest_review.status if latest_review else None,
        latest_review_conclusion=latest_review.conclusion if latest_review else None,
        closure_ready=closure_state == "ready",
        closure_state=closure_state,
    )


def _active_test_markers(marker: str | None) -> tuple[str, ...]:
    normalized = (marker or "").strip()
    return (normalized,) if normalized else TEST_DATA_MARKERS


def _contains_test_marker(value: Any, markers: tuple[str, ...]) -> str | None:
    if value is None:
        return None
    text_value = str(value).strip()
    if not text_value:
        return None
    lower_value = text_value.lower()
    for marker in markers:
        if marker.lower() in lower_value:
            return marker
    return None


def _append_test_reason(reasons: list[str], field_label: str, value: Any, markers: tuple[str, ...]) -> None:
    marker = _contains_test_marker(value, markers)
    if marker is None:
        return
    reason = f"{field_label}包含“{marker}”"
    if reason not in reasons:
        reasons.append(reason)


def _test_marker_filter(markers: tuple[str, ...]) -> Any:
    filters: list[Any] = []
    for marker in markers:
        like = f"%{marker}%"
        filters.extend(
            [
                CrmProject.project_code.ilike(like),
                CrmProject.project_name.ilike(like),
                CrmProject.project_type.ilike(like),
                CrmProject.purpose.ilike(like),
                CrmProject.customer_scope_note.ilike(like),
                CrmProject.business_line.ilike(like),
                CrmProject.minimum_action.ilike(like),
                CrmProject.closure_standard.ilike(like),
                exists()
                .where(CrmProjectCustomerTask.project_id == CrmProject.id)
                .where(
                    or_(
                        CrmProjectCustomerTask.task_code.ilike(like),
                        CrmProjectCustomerTask.customer_name_snapshot.ilike(like),
                        CrmProjectCustomerTask.business_issue_point.ilike(like),
                        CrmProjectCustomerTask.round_target.ilike(like),
                    )
                ),
                exists()
                .where(CrmFollowup.project_id == CrmProject.id)
                .where(
                    or_(
                        CrmFollowup.followup_no.ilike(like),
                        CrmFollowup.customer_feedback.ilike(like),
                        CrmFollowup.current_need.ilike(like),
                        CrmFollowup.frontline_action.ilike(like),
                        CrmFollowup.review_note.ilike(like),
                    )
                ),
                exists()
                .where(CrmProjectReview.project_id == CrmProject.id)
                .where(
                    or_(
                        CrmProjectReview.data_summary.ilike(like),
                        CrmProjectReview.business_judgement.ilike(like),
                        CrmProjectReview.main_problem.ilike(like),
                        CrmProjectReview.next_suggestion.ilike(like),
                        CrmProjectReview.conclusion.ilike(like),
                    )
                ),
            ]
        )
    return or_(*filters)


def _project_test_reasons(db: Session, project: CrmProject, marker: str | None = None) -> list[str]:
    markers = _active_test_markers(marker)
    reasons: list[str] = []
    project_fields = [
        ("项目编号", project.project_code),
        ("项目名称", project.project_name),
        ("项目类型", project.project_type),
        ("项目目的", project.purpose),
        ("客户范围", project.customer_scope_note),
        ("业务线", project.business_line),
        ("最小动作", project.minimum_action),
        ("闭环标准", project.closure_standard),
    ]
    for label, value in project_fields:
        _append_test_reason(reasons, label, value, markers)

    task_rows = list(
        db.scalars(
            select(CrmProjectCustomerTask)
            .where(CrmProjectCustomerTask.project_id == project.id)
            .order_by(CrmProjectCustomerTask.id.desc())
            .limit(5)
        ).all()
    )
    for task in task_rows:
        _append_test_reason(reasons, "客户任务", task.task_code, markers)
        _append_test_reason(reasons, "任务客户", task.customer_name_snapshot, markers)
        _append_test_reason(reasons, "业务问题点", task.business_issue_point, markers)
        _append_test_reason(reasons, "轮次目标", task.round_target, markers)

    followup_rows = list(
        db.scalars(
            select(CrmFollowup)
            .where(CrmFollowup.project_id == project.id)
            .order_by(CrmFollowup.id.desc())
            .limit(5)
        ).all()
    )
    for followup in followup_rows:
        _append_test_reason(reasons, "跟进编号", followup.followup_no, markers)
        _append_test_reason(reasons, "客户反馈", followup.customer_feedback, markers)
        _append_test_reason(reasons, "当前需求", followup.current_need, markers)
        _append_test_reason(reasons, "审核备注", followup.review_note, markers)

    review_rows = list(
        db.scalars(
            select(CrmProjectReview)
            .where(CrmProjectReview.project_id == project.id)
            .order_by(CrmProjectReview.id.desc())
            .limit(5)
        ).all()
    )
    for review in review_rows:
        _append_test_reason(reasons, "复盘摘要", review.data_summary, markers)
        _append_test_reason(reasons, "业务判断", review.business_judgement, markers)
        _append_test_reason(reasons, "主要问题", review.main_problem, markers)
        _append_test_reason(reasons, "复盘结论", review.conclusion, markers)

    return reasons[:12]


def _project_test_counts(db: Session, project: CrmProject) -> CrmTestProjectCounts:
    approval_filters = _project_approval_filters(project)
    task_total = db.scalar(select(func.count()).select_from(CrmProjectCustomerTask).where(CrmProjectCustomerTask.project_id == project.id)) or 0
    followup_total = db.scalar(select(func.count()).select_from(CrmFollowup).where(CrmFollowup.project_id == project.id)) or 0
    review_total = db.scalar(select(func.count()).select_from(CrmProjectReview).where(CrmProjectReview.project_id == project.id)) or 0
    approval_total = db.scalar(select(func.count()).select_from(ApprovalInstance).where(or_(*approval_filters))) or 0
    work_item_total = db.scalar(select(func.count()).select_from(WorkItem).where(WorkItem.project_id == project.id)) or 0
    open_work_item_total = (
        db.scalar(select(func.count()).select_from(WorkItem).where(WorkItem.project_id == project.id, WorkItem.status.in_(["open", "processing"])))
        or 0
    )
    pending_approval_total = (
        db.scalar(
            select(func.count())
            .select_from(ApprovalInstance)
            .where(or_(*approval_filters), ApprovalInstance.status.in_(["draft", "submitted", "under_review", "need_supplement"]))
        )
        or 0
    )
    latest_candidates = [
        project.updated_at,
        db.scalar(select(func.max(CrmProjectCustomerTask.updated_at)).where(CrmProjectCustomerTask.project_id == project.id)),
        db.scalar(select(func.max(CrmFollowup.updated_at)).where(CrmFollowup.project_id == project.id)),
        db.scalar(select(func.max(CrmProjectReview.updated_at)).where(CrmProjectReview.project_id == project.id)),
        db.scalar(select(func.max(WorkItem.updated_at)).where(WorkItem.project_id == project.id)),
        db.scalar(select(func.max(ApprovalInstance.updated_at)).where(or_(*approval_filters))),
    ]
    latest_activity_at = max([item for item in latest_candidates if item is not None], default=None)
    return CrmTestProjectCounts(
        task_total=task_total,
        followup_total=followup_total,
        review_total=review_total,
        approval_total=approval_total,
        work_item_total=work_item_total,
        open_work_item_total=open_work_item_total,
        pending_approval_total=pending_approval_total,
        latest_activity_at=latest_activity_at,
    )


def _test_project_candidate(db: Session, project: CrmProject, marker: str | None = None) -> CrmTestProjectCandidate:
    reasons = _project_test_reasons(db, project, marker)
    return CrmTestProjectCandidate(
        project=_project_public(db, project),
        test_reasons=reasons,
        counts=_project_test_counts(db, project),
        can_void=bool(reasons) and project.status != "cancelled",
    )


def _void_test_project(db: Session, project: CrmProject, current_user: User, request: Request, reason: str, marker: str | None = None) -> CrmVoidTestProjectResult:
    reasons = _project_test_reasons(db, project, marker)
    if not reasons:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only projects with temporary-data markers can be voided")

    before_data = jsonable_encoder(
        {
            "project": project_audit_snapshot(project),
            "counts": _project_test_counts(db, project).model_dump(),
            "test_reasons": reasons,
        }
    )
    now = datetime.now(timezone.utc)
    close_note = f"临时数据作废：{reason}"

    tasks = list(db.scalars(select(CrmProjectCustomerTask).where(CrmProjectCustomerTask.project_id == project.id)).all())
    for task in tasks:
        task.is_closed = True
        task.status = "closed"
        task.need_support = False
        task.need_manager_support = False
        task.need_boss_decision = False
        task.is_blocked = False
        task.latest_blocker_reason = None
        task.latest_blocker_note = None
        task.latest_owner_next_status = "cancelled"
        task.latest_owner_next_action = close_note
        task.latest_owner_next_followup_at = None

    work_items = list(db.scalars(select(WorkItem).where(WorkItem.project_id == project.id)).all())
    for item in work_items:
        if item.status in {"open", "processing"}:
            item.status = "closed"
            item.resolved_by_user_id = current_user.id
            item.resolved_at = now
            item.resolution_note = close_note if not item.resolution_note else f"{item.resolution_note}\n{close_note}"

    approvals = list(db.scalars(select(ApprovalInstance).where(or_(*_project_approval_filters(project)))).all())
    for approval in approvals:
        if approval.status not in TERMINAL_APPROVAL_STATUSES:
            transition_approval(
                db,
                approval=approval,
                operator=current_user,
                event_type="cancel",
                to_status="cancelled",
                comment=close_note,
                result_json={"voided_by": current_user.id, "void_reason": reason, "project_id": project.id},
            )

    project.status = "cancelled"
    if project.approval_status in {"draft", "submitted", "under_review", "need_supplement"}:
        project.approval_status = "cancelled"
    project.next_step_status = "cancelled"
    project.next_step_action = close_note
    project.next_step_followup_at = None
    project.updated_by_user_id = current_user.id
    db.flush()

    after_counts = _project_test_counts(db, project)
    write_audit_log(
        db,
        action_type="void_crm_test_project",
        resource_type="crm_project",
        resource_id=str(project.id),
        user=current_user,
        request=request,
        before_data=before_data,
        after_data=jsonable_encoder(
            {
                "project": project_audit_snapshot(project),
                "counts": after_counts.model_dump(),
                "void_reason": reason,
                "test_reasons": reasons,
            }
        ),
    )
    return CrmVoidTestProjectResult(
        project=_project_public(db, project),
        test_reasons=reasons,
        counts=after_counts,
        message="临时项目已作废，关联未闭环任务、未处理事项和未终态审批已收口。",
    )


def _day_bounds(target_date: date) -> tuple[datetime, datetime]:
    start_at = datetime.combine(target_date, time.min, tzinfo=BUSINESS_TZ)
    end_at = datetime.combine(target_date, time.max, tzinfo=BUSINESS_TZ)
    return start_at.astimezone(timezone.utc), end_at.astimezone(timezone.utc)


def _valid_feedback_exists() -> Any:
    return exists().where(
        CrmFollowup.task_id == CrmProjectCustomerTask.id,
        CrmFollowup.valid_feedback.is_(True),
    )


def _daily_summary_task(task: CrmProjectCustomerTask, valid_task_ids: set[int], now: datetime) -> CrmDailySummaryTask:
    has_valid_followup = task.id in valid_task_ids
    overdue = bool(task.feedback_due_at and task.feedback_due_at < now and not task.is_closed and not has_valid_followup)
    return CrmDailySummaryTask(
        id=task.id,
        project_id=task.project_id,
        task_code=task.task_code,
        customer_code=task.customer_code,
        customer_name_snapshot=task.customer_name_snapshot,
        executor_user_id=task.executor_user_id,
        executor_employee_code=task.executor_employee_code,
        executor_name_snapshot=task.executor_name_snapshot,
        feedback_due_at=task.feedback_due_at,
        status=task.status,
        is_closed=task.is_closed,
        last_followup_at=task.last_followup_at,
        latest_followup_id=task.latest_followup_id,
        has_valid_followup=has_valid_followup,
        overdue=overdue,
    )


def _project_public(db: Session, project: CrmProject) -> CrmProjectPublic:
    task_summary = project_task_summary(db, project.id)
    latest_followup = latest_project_followup(db, project.id)
    return CrmProjectPublic.model_validate(project).model_copy(
        update={
            "task_total": task_summary.get("total", 0),
            "task_closed": task_summary.get("closed", 0),
            "task_open": task_summary.get("open", 0),
            "task_need_support": task_summary.get("need_support", 0),
            "task_blocked": task_summary.get("blocked", 0),
            "support_item_open": project_support_item_count(db, project.id),
            "pending_approval_count": _pending_approval_count(db, project),
            "latest_followup_at": latest_followup.created_at if latest_followup else None,
            **_project_user_label_payload(db, project),
        }
    )


def _project_detail(db: Session, project: CrmProject) -> CrmProjectDetail:
    return CrmProjectDetail(
        project=_project_public(db, project),
        task_summary=project_task_summary(db, project.id),
        latest_followup=CrmFollowupPublic.model_validate(latest) if (latest := latest_project_followup(db, project.id)) else None,
        support_item_count=project_support_item_count(db, project.id),
        approval_summary=_approval_summary(db, project),
        review_summary=project_review_summary(db, project.id),
        closure_summary=_project_closure_summary(db, project),
    )


def _task_detail(db: Session, current_user: User, task: CrmProjectCustomerTask) -> CrmTaskDetail:
    project = _scoped_project(db, current_user, task.project_id)
    followups: list[CrmFollowupPublic] = []
    approvals: list[ApprovalInstancePublic] = []
    work_items: list[WorkItemPublic] = []

    if has_permission(db, current_user, "crm_followup.view"):
        followup_stmt = crm_followup_scope_filter(
            select(CrmFollowup).where(CrmFollowup.task_id == task.id),
            db,
            current_user,
        )
        followup_rows = list(
            db.scalars(
                followup_stmt.order_by(CrmFollowup.created_at.desc(), CrmFollowup.id.desc()).limit(8)
            ).all()
        )
        followups = [CrmFollowupPublic.model_validate(followup) for followup in followup_rows]

    if has_permission(db, current_user, "approval.view"):
        approval_by_id: dict[int, ApprovalInstance] = {}
        for approval in _project_approval_rows(db, project)[:6]:
            approval_by_id[approval.id] = approval
        for approval in _task_approval_rows(db, task, limit=12):
            approval_by_id[approval.id] = approval
        approval_rows = sorted(
            approval_by_id.values(),
            key=lambda item: (_approval_activity_at(item), item.id),
            reverse=True,
        )[:12]
        approvals = [ApprovalInstancePublic.model_validate(approval) for approval in approval_rows]

    if has_permission(db, current_user, "crm_issue.view"):
        item_stmt = crm_work_item_scope_filter(
            select(WorkItem).where(
                or_(
                    (WorkItem.resource_type == "crm_project_customer_task") & (WorkItem.resource_id == str(task.id)),
                    (WorkItem.project_id == task.project_id) & (WorkItem.customer_code == task.customer_code),
                )
            ),
            db,
            current_user,
        )
        item_rows = list(
            db.scalars(
                item_stmt.order_by(WorkItem.status.asc(), WorkItem.id.desc()).limit(8)
            ).all()
        )
        work_items = [WorkItemPublic.model_validate(item) for item in item_rows]

    _fill_task_data_update_summary(db, [task])
    _fill_task_followup_submission(db, [task])
    return CrmTaskDetail(
        task=CrmProjectCustomerTaskPublic.model_validate(task),
        project=_project_public(db, project),
        followups=followups,
        approvals=approvals,
        work_items=work_items,
    )


def _validate_project_payload(db: Session, changes: dict[str, Any]) -> None:
    if "status" in changes and changes["status"] is not None:
        validate_project_status(changes["status"])
    if "approval_status" in changes and changes["approval_status"] is not None:
        validate_approval_status(changes["approval_status"])
    if "applicant_user_id" in changes:
        require_user(db, changes["applicant_user_id"], "applicant_user_id")
    if "landing_approver_user_id" in changes:
        require_user(db, changes["landing_approver_user_id"], "landing_approver_user_id")
    if "owner_user_id" in changes:
        require_user(db, changes["owner_user_id"], "owner_user_id")
    if "project_manager_user_id" in changes:
        require_user(db, changes["project_manager_user_id"], "project_manager_user_id")
    if "participant_user_ids" in changes:
        changes["participant_user_ids"] = _normalize_participants(db, changes["participant_user_ids"])
    if "progress_cc_user_ids" in changes:
        changes["progress_cc_user_ids"] = _normalize_user_ids(db, changes["progress_cc_user_ids"], "progress_cc_user_ids")


@router.get("/summary", response_model=CrmSummary)
def get_crm_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("crm_project.view", "crm_task.view", "crm_issue.view", "approval.view")),
) -> CrmSummary:
    now = datetime.now(timezone.utc)
    _, today_end = _day_bounds(now.astimezone(BUSINESS_TZ).date())
    active_projects = 0
    pending_project_approvals = 0
    task_total = 0
    due_today_tasks = 0
    overdue_no_feedback_tasks = 0
    open_work_items = 0
    closed_tasks = 0
    valid_feedback_tasks = 0
    latest_followup_at = None

    if has_permission(db, current_user, "crm_project.view"):
        project_stmt = crm_project_scope_filter(
            select(CrmProject).where(CrmProject.status == "active"),
            db,
            current_user,
        )
        active_projects = _count_stmt(db, project_stmt)

    if has_permission(db, current_user, "approval.view"):
        pending_project_approvals = (
            db.scalar(
                select(func.count())
                .select_from(ApprovalInstance)
                .where(
                    ApprovalInstance.approval_type == "crm_project_create",
                    ApprovalInstance.status.in_(["submitted", "under_review"]),
                )
            )
            or 0
        )

    if has_permission(db, current_user, "crm_task.view"):
        base_task_stmt = crm_task_scope_filter(
            select(CrmProjectCustomerTask).where(CrmProjectCustomerTask.project_id.not_in(_frozen_project_ids())),
            db,
            current_user,
        )
        task_total = _count_stmt(db, base_task_stmt)
        closed_tasks = _count_stmt(db, base_task_stmt.where(CrmProjectCustomerTask.is_closed.is_(True)))
        due_today_tasks = _count_stmt(
            db,
            base_task_stmt.where(
                CrmProjectCustomerTask.is_closed.is_(False),
                CrmProjectCustomerTask.feedback_due_at.is_not(None),
                CrmProjectCustomerTask.feedback_due_at <= today_end,
            ),
        )
        overdue_no_feedback_tasks = _count_stmt(
            db,
            base_task_stmt.where(
                CrmProjectCustomerTask.is_closed.is_(False),
                CrmProjectCustomerTask.feedback_due_at.is_not(None),
                CrmProjectCustomerTask.feedback_due_at < now,
                ~_valid_feedback_exists(),
            ),
        )
        valid_feedback_tasks = _count_stmt(db, base_task_stmt.where(_valid_feedback_exists()))

    if has_permission(db, current_user, "crm_issue.view"):
        item_stmt = crm_work_item_scope_filter(
            select(WorkItem).where(WorkItem.status.in_(["open", "processing"])),
            db,
            current_user,
        )
        open_work_items = _count_stmt(db, item_stmt)

    if has_permission(db, current_user, "crm_followup.view"):
        latest_followup_at = db.scalar(
            crm_followup_scope_filter(select(CrmFollowup.created_at), db, current_user)
            .order_by(CrmFollowup.created_at.desc(), CrmFollowup.id.desc())
            .limit(1)
        )

    return CrmSummary(
        active_projects=active_projects,
        pending_project_approvals=pending_project_approvals,
        task_total=task_total,
        due_today_tasks=due_today_tasks,
        overdue_no_feedback_tasks=overdue_no_feedback_tasks,
        open_work_items=open_work_items,
        closed_tasks=closed_tasks,
        valid_feedback_tasks=valid_feedback_tasks,
        valid_feedback_rate=round(valid_feedback_tasks / task_total, 4) if task_total else 0,
        latest_followup_at=latest_followup_at,
        generated_at=now,
    )


@router.get("/data-center", response_model=CrmDataCenterPage)
def get_crm_data_center(
    q: str | None = None,
    scope: str | None = None,
    project_id: int | None = None,
    owner_user_id: int | None = None,
    owner_key: str | None = None,
    region: str | None = None,
    customer_type: str | None = None,
    latest_blocker_reason: str | None = None,
    followup_status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("crm_project.view", "crm_task.view", "crm_followup.view", "crm_issue.view", "approval.view")),
) -> CrmDataCenterPage:
    safe_limit = _safe_limit(limit)
    safe_offset = _safe_offset(offset)
    now = datetime.now(timezone.utc)
    all_rows: list[CrmDataCenterTaskRow] = []
    if has_permission(db, current_user, "crm_task.view"):
        stmt = crm_task_scope_filter(
            select(CrmProjectCustomerTask, CustomerMaster, CrmProject)
            .join(CrmProject, CrmProject.id == CrmProjectCustomerTask.project_id)
            .outerjoin(CustomerMaster, CustomerMaster.customer_code == CrmProjectCustomerTask.customer_code),
            db,
            current_user,
        )
        raw_rows = list(db.execute(stmt.order_by(CrmProjectCustomerTask.id.desc())).all())
        all_rows = [_crm_data_center_task_row(task, customer, project, now) for task, customer, project in raw_rows]

    dimensions = _crm_data_center_dimensions(all_rows)

    def text_matches(row: CrmDataCenterTaskRow, keyword: str) -> bool:
        normalized = keyword.strip().lower()
        if not normalized:
            return True
        values = [
            row.project_name,
            row.project_code,
            row.task_code,
            row.customer_code,
            row.customer_name,
            row.customer_name_snapshot,
            row.customer_group_name,
            row.region,
            row.customer_type,
            row.salesperson_name,
            row.executor_name_snapshot,
            row.latest_blocker_reason,
            row.business_issue_point,
            row.round_target,
        ]
        return any(normalized in str(value or "").lower() for value in values)

    def dim_matches(value: str | int | None, selected: str | None) -> bool:
        if not selected:
            return True
        if selected == "__empty__":
            return not str(value or "").strip()
        return str(value or "").strip() == selected

    base_rows = all_rows
    if q:
        base_rows = [row for row in base_rows if text_matches(row, q)]
    if project_id:
        base_rows = [row for row in base_rows if row.project_id == project_id]
    if owner_user_id:
        base_rows = [row for row in base_rows if row.executor_user_id == owner_user_id or row.project_owner_user_id == owner_user_id or row.project_manager_user_id == owner_user_id]
    if owner_key:
        base_rows = [
            row for row in base_rows
            if dim_matches(row.executor_user_id or row.executor_name_snapshot or row.executor_employee_code, owner_key)
        ]
    if region:
        base_rows = [row for row in base_rows if dim_matches(row.region, region)]
    if customer_type:
        base_rows = [row for row in base_rows if dim_matches(row.customer_type, customer_type)]
    if latest_blocker_reason:
        base_rows = [row for row in base_rows if dim_matches(row.latest_blocker_reason, latest_blocker_reason)]
    if followup_status:
        base_rows = [row for row in base_rows if dim_matches(row.followup_status, followup_status)]

    valid_task_ids: set[int] = set()
    if base_rows and has_permission(db, current_user, "crm_followup.view"):
        valid_task_ids = set(
            db.scalars(
                crm_followup_scope_filter(
                    select(CrmFollowup.task_id).where(
                        CrmFollowup.task_id.in_([row.id for row in base_rows]),
                        CrmFollowup.valid_feedback.is_(True),
                    ),
                    db,
                    current_user,
                )
            ).all()
        )

    open_work_items = 0
    if has_permission(db, current_user, "crm_issue.view"):
        open_work_items = _count_stmt(
            db,
            crm_work_item_scope_filter(
                select(WorkItem).where(WorkItem.status.in_(["open", "processing"])),
                db,
                current_user,
            ),
        )

    pending_approvals = 0
    if has_permission(db, current_user, "approval.view"):
        pending_approvals = db.scalar(
            select(func.count()).select_from(ApprovalInstance).where(ApprovalInstance.status.in_(["submitted", "under_review", "need_supplement"]))
        ) or 0

    summary = _crm_data_center_summary(
        base_rows,
        project_total=len({row.project_id for row in base_rows}),
        open_work_items=open_work_items,
        pending_approvals=pending_approvals,
        valid_feedback_tasks=sum(1 for row in base_rows if row.id in valid_task_ids),
        now=now,
    )

    filtered_rows = _crm_data_center_scope_filter(base_rows, scope)
    risk_order = {"high": 0, "medium": 1, "normal": 2, "closed": 3}
    filtered_rows = sorted(
        filtered_rows,
        key=lambda row: (
            risk_order.get(row.risk_level, 4),
            row.feedback_due_at is None,
            row.feedback_due_at or datetime.max.replace(tzinfo=timezone.utc),
            -row.id,
        ),
    )
    total = len(filtered_rows)
    items = filtered_rows[safe_offset:safe_offset + safe_limit]
    return CrmDataCenterPage(
        items=items,
        total=total,
        limit=safe_limit,
        offset=safe_offset,
        scope=scope,
        summary=summary,
        dimensions=dimensions,
    )


@router.get("/linked-customers/page", response_model=CrmLinkedCustomerPage)
def list_crm_linked_customers_page(
    q: str | None = None,
    scope: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("crm_project.view", "crm_task.view", "crm_followup.view", "crm_issue.view", "approval.view", "crm_business_profile.view", "crm_customer_profile.view")),
) -> CrmLinkedCustomerPage:
    safe_limit = _safe_limit(limit)
    safe_offset = _safe_offset(offset)
    now = datetime.now(timezone.utc)
    can_list_linked_customers = (
        has_permission(db, current_user, "crm_task.view")
        or has_permission(db, current_user, "crm_business_profile.view")
        or has_permission(db, current_user, "crm_customer_profile.view")
    )
    if not can_list_linked_customers:
        return CrmLinkedCustomerPage(
            items=[],
            total=0,
            limit=safe_limit,
            offset=safe_offset,
            summary=CrmLinkedCustomerSummary(generated_at=now),
        )

    stmt = crm_task_scope_filter(
        select(CrmProjectCustomerTask, CustomerMaster, CrmProject)
        .join(CrmProject, CrmProject.id == CrmProjectCustomerTask.project_id)
        .outerjoin(CustomerMaster, CustomerMaster.customer_code == CrmProjectCustomerTask.customer_code),
        db,
        current_user,
    )
    if scope == "active_project":
        stmt = stmt.where(CrmProject.status.in_(CRM_BUSINESS_PROFILE_ACTIVE_PROJECT_STATUSES))
    if q:
        like = f"%{q}%"
        search_terms = [
            CrmProjectCustomerTask.task_code.ilike(like),
            CrmProjectCustomerTask.customer_code.ilike(like),
            CrmProjectCustomerTask.customer_name_snapshot.ilike(like),
            CrmProjectCustomerTask.executor_name_snapshot.ilike(like),
            CrmProjectCustomerTask.business_issue_point.ilike(like),
            CrmProjectCustomerTask.round_target.ilike(like),
            CrmProjectCustomerTask.latest_owner_next_action.ilike(like),
            CrmProjectCustomerTask.latest_owner_next_status.ilike(like),
            CrmProjectCustomerTask.latest_blocker_reason.ilike(like),
            CrmProjectCustomerTask.latest_blocker_note.ilike(like),
            CrmProject.project_name.ilike(like),
            CrmProject.project_code.ilike(like),
            CustomerMaster.customer_name.ilike(like),
            CustomerMaster.customer_short_name.ilike(like),
            CustomerMaster.contact_name.ilike(like),
            CustomerMaster.contact_phone.ilike(like),
        ]
        if has_permission(db, current_user, "crm_followup.view"):
            search_terms.append(
                exists()
                .where(CrmFollowup.task_id == CrmProjectCustomerTask.id)
                .where(
                    or_(
                        CrmFollowup.customer_feedback.ilike(like),
                        CrmFollowup.current_need.ilike(like),
                        CrmFollowup.blocker_reason.ilike(like),
                        CrmFollowup.blocker_note.ilike(like),
                        CrmFollowup.next_action.ilike(like),
                        CrmFollowup.owner_next_action.ilike(like),
                        CrmFollowup.owner_next_status.ilike(like),
                    )
                )
            )
        stmt = stmt.where(
            or_(*search_terms)
        )

    grouped: dict[str, list[tuple[CrmProjectCustomerTask, CustomerMaster | None, CrmProject]]] = {}
    for task, customer, project in db.execute(stmt.order_by(CrmProjectCustomerTask.updated_at.desc(), CrmProjectCustomerTask.id.desc())).all():
        grouped.setdefault(task.customer_code, []).append((task, customer, project))

    customer_codes = list(grouped)
    followup_totals: dict[str, tuple[int, datetime | None]] = {}
    if customer_codes and has_permission(db, current_user, "crm_followup.view"):
        followup_stmt = crm_followup_scope_filter(
            select(CrmFollowup.customer_code, func.count(CrmFollowup.id), func.max(CrmFollowup.created_at))
            .where(CrmFollowup.customer_code.in_(customer_codes))
            .group_by(CrmFollowup.customer_code),
            db,
            current_user,
        )
        followup_totals = {
            str(customer_code): (int(total), latest_at)
            for customer_code, total, latest_at in db.execute(followup_stmt).all()
        }

    work_item_totals: dict[str, int] = {}
    if customer_codes and has_permission(db, current_user, "crm_issue.view"):
        item_stmt = crm_work_item_scope_filter(
            select(WorkItem.customer_code, func.count(WorkItem.id))
            .where(
                WorkItem.customer_code.in_(customer_codes),
                WorkItem.status.in_(["open", "processing"]),
            )
            .group_by(WorkItem.customer_code),
            db,
            current_user,
        )
        work_item_totals = {
            str(customer_code): int(total)
            for customer_code, total in db.execute(item_stmt).all()
            if customer_code
        }

    all_rows = [
        _crm_linked_customer_row(
            customer_code,
            rows,
            now,
            followup_totals.get(customer_code, (0, None))[0],
            followup_totals.get(customer_code, (0, None))[1],
            work_item_totals.get(customer_code, 0),
            include_customer_profile=has_permission(db, current_user, "crm_customer_profile.view"),
        )
        for customer_code, rows in grouped.items()
    ]

    if scope == "open":
        all_rows = [row for row in all_rows if row.task_open > 0]
    elif scope == "profile_incomplete":
        all_rows = [row for row in all_rows if row.base_info_completeness and row.base_info_completeness != "完整"]
    elif scope == "pending_action":
        all_rows = [row for row in all_rows if row.latest_owner_next_action or row.blocked_reason_summary or row.work_item_open > 0]
    elif scope == "overdue":
        all_rows = [row for row in all_rows if row.task_overdue > 0]
    elif scope == "support":
        all_rows = [row for row in all_rows if row.task_need_support > 0 or row.work_item_open > 0]
    elif scope == "blocked":
        all_rows = [row for row in all_rows if row.task_blocked > 0]
    elif scope == "risk":
        all_rows = [row for row in all_rows if row.risk_level in {"high", "medium"} or row.work_item_open > 0]
    elif scope == "closed":
        all_rows = [row for row in all_rows if row.task_total > 0 and row.task_open == 0]

    risk_rank = {"high": 0, "medium": 1, "watch": 2, "normal": 3}
    all_rows.sort(
        key=lambda row: (
            risk_rank.get(row.risk_level, 9),
            -(row.last_activity_at.timestamp() if row.last_activity_at else 0),
            row.customer_name,
        )
    )
    summary = _crm_linked_customer_summary(all_rows, now)
    return CrmLinkedCustomerPage(
        items=all_rows[safe_offset:safe_offset + safe_limit],
        total=len(all_rows),
        limit=safe_limit,
        offset=safe_offset,
        summary=summary,
    )


@router.get("/linked-customers/{customer_code}/context")
def get_crm_linked_customer_context(
    customer_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("crm_project.view", "crm_task.view", "crm_followup.view", "crm_issue.view", "approval.view", "crm_business_profile.view", "crm_customer_profile.view")),
) -> dict[str, Any]:
    customer = db.scalar(select(CustomerMaster).where(CustomerMaster.customer_code == customer_code))
    task_rows: list[CrmProjectCustomerTask] = []
    project_rows: list[CrmProject] = []
    followup_rows: list[CrmFollowup] = []
    work_item_rows: list[WorkItem] = []
    approval_rows: list[ApprovalInstance] = []
    business_profile = None

    if customer is not None and has_permission(db, current_user, "crm_business_profile.view"):
        try:
            _scoped_active_customer_task(db, current_user, customer_code)
            profile_result = customer_business_profile_response(db, current_user, customer, include_history=False)
            business_profile = {
                "profile": jsonable_encoder(profile_result["profile"]) if profile_result["profile"] else None,
                "products": jsonable_encoder(profile_result["products"]),
            }
        except HTTPException:
            business_profile = None

    if has_permission(db, current_user, "crm_task.view"):
        task_stmt = crm_task_scope_filter(
            select(CrmProjectCustomerTask).where(CrmProjectCustomerTask.customer_code == customer_code),
            db,
            current_user,
        )
        task_rows = list(db.scalars(task_stmt.order_by(CrmProjectCustomerTask.id.desc()).limit(50)).all())

    if has_permission(db, current_user, "crm_project.view"):
        project_stmt = crm_project_scope_filter(
            select(CrmProject)
            .join(CrmProjectCustomerTask, CrmProjectCustomerTask.project_id == CrmProject.id)
            .where(CrmProjectCustomerTask.customer_code == customer_code),
            db,
            current_user,
        )
        project_rows = list(db.scalars(project_stmt.distinct().order_by(CrmProject.id.desc()).limit(20)).all())

    project_ids = [row.id for row in project_rows]

    if has_permission(db, current_user, "crm_followup.view"):
        followup_stmt = crm_followup_scope_filter(
            select(CrmFollowup).where(CrmFollowup.customer_code == customer_code),
            db,
            current_user,
        )
        followup_rows = list(db.scalars(followup_stmt.order_by(CrmFollowup.created_at.desc(), CrmFollowup.id.desc()).limit(50)).all())

    if has_permission(db, current_user, "crm_issue.view"):
        item_stmt = crm_work_item_scope_filter(
            select(WorkItem).where(WorkItem.customer_code == customer_code),
            db,
            current_user,
        )
        work_item_rows = list(db.scalars(item_stmt.order_by(WorkItem.id.desc()).limit(20)).all())

    if has_permission(db, current_user, "approval.view"):
        approval_by_id: dict[int, ApprovalInstance] = {}
        if project_ids:
            for approval in db.scalars(
                select(ApprovalInstance)
                .where(
                    (ApprovalInstance.resource_type == "crm_project")
                    & ApprovalInstance.resource_id.in_([str(project_id) for project_id in project_ids])
                )
                .order_by(ApprovalInstance.id.desc())
                .limit(20)
            ).all():
                approval_by_id[approval.id] = approval
        for task in task_rows[:20]:
            for approval in _task_approval_rows(db, task, limit=12):
                approval_by_id[approval.id] = approval
        if not approval_by_id and customer_code:
            for approval in db.scalars(
                select(ApprovalInstance)
                .where(
                    ApprovalInstance.approval_type.in_(sorted(DATA_UPDATE_APPROVAL_TYPES)),
                    ApprovalInstance.resource_id == customer_code,
                )
                .order_by(ApprovalInstance.id.desc())
                .limit(20)
            ).all():
                approval_by_id[approval.id] = approval
        approval_rows = sorted(
            approval_by_id.values(),
            key=lambda item: (_approval_activity_at(item), item.id),
            reverse=True,
        )[:30]

    projects = [_project_public(db, project) for project in project_rows]
    tasks = [CrmProjectCustomerTaskPublic.model_validate(task) for task in task_rows]
    followups = [CrmFollowupPublic.model_validate(followup) for followup in followup_rows]
    work_items = [WorkItemPublic.model_validate(item) for item in work_item_rows]
    approvals = [ApprovalInstancePublic.model_validate(approval) for approval in approval_rows]
    flow_nodes = _crm_flow_nodes_for_context(
        db,
        task_rows=task_rows,
        project_rows=project_rows,
        approval_rows=approval_rows,
        work_item_rows=work_item_rows,
        current_user=current_user,
    )
    task_open = sum(1 for task in task_rows if not task.is_closed)
    task_need_support = sum(1 for task in task_rows if task.need_support or task.need_manager_support or task.need_boss_decision)
    task_blocked = sum(1 for task in task_rows if task.is_blocked)
    approval_pending = sum(1 for approval in approval_rows if approval.status in ["submitted", "under_review", "need_supplement"])
    fallback_name = next((task.customer_name_snapshot for task in task_rows if task.customer_name_snapshot), customer_code)
    customer_payload = {
        "customer_code": customer_code,
        "customer_name": customer.customer_name if customer else fallback_name,
        "customer_short_name": customer.customer_short_name if customer else None,
        "updated_at": customer.updated_at if customer else None,
    }
    if has_permission(db, current_user, "crm_customer_profile.view"):
        customer_payload.update(_crm_customer_profile_payload(customer, include_details=True))
    return {
        "customer": customer_payload,
        "business_profile": business_profile,
        "portrait": None,
        "crm": {
            "available": True,
            "projects": jsonable_encoder(projects),
            "tasks": jsonable_encoder(tasks),
            "followups": jsonable_encoder(followups),
            "work_items": jsonable_encoder(work_items),
            "approvals": jsonable_encoder(approvals),
            "flow_nodes": flow_nodes,
            "stats": {
                "project_total": len(projects),
                "task_total": len(tasks),
                "task_open": task_open,
                "task_closed": len(tasks) - task_open,
                "task_need_support": task_need_support,
                "task_blocked": task_blocked,
                "followup_total": len(followups),
                "work_item_open": sum(1 for item in work_item_rows if item.status in ["open", "processing"]),
                "approval_pending": approval_pending,
            },
        },
        "audit": [],
    }


@router.get("/linked-customers/{customer_code}/profile")
def get_crm_linked_customer_profile(
    customer_code: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_customer_profile.view")),
) -> dict[str, Any]:
    _scoped_active_customer_task(db, current_user, customer_code)
    customer = db.scalar(select(CustomerMaster).where(CustomerMaster.customer_code == customer_code))
    if customer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    result = _crm_customer_profile_detail_payload(db, current_user, customer)
    write_audit_log(
        db,
        action_type="view_crm_customer_profile",
        resource_type="crm_customer_profile",
        resource_id=customer.customer_code,
        user=current_user,
        request=request,
        after_data={
            "scope": "crm_linked_customer",
            "customer_code": customer.customer_code,
            "project_scope": "active",
        },
    )
    db.commit()
    return result


@router.post("/linked-customers/{customer_code}/profile/update")
def update_crm_linked_customer_profile(
    customer_code: str,
    payload: CustomerMasterUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_customer_profile.submit")),
) -> dict[str, Any]:
    task, project = _scoped_active_customer_task(db, current_user, customer_code)
    customer = db.scalar(select(CustomerMaster).where(CustomerMaster.customer_code == customer_code))
    if customer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    incoming_profile_payload = payload.model_dump(exclude_unset=True)
    if not incoming_profile_payload:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Customer profile update payload is empty")
    before_profile = customer_audit_snapshot(customer)
    profile_payload, change_items = _direct_customer_profile_patch(before_profile, incoming_profile_payload)
    if not profile_payload:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请至少修改一项客户基本资料")

    update_result = apply_customer_master_update(
        db,
        customer=customer,
        payload=CustomerMasterUpdate.model_validate(profile_payload),
        operator=current_user,
        audit_action_type=CRM_CUSTOMER_PROFILE_DIRECT_ACTION,
        audit_extra={
            "scope": "crm_linked_customer",
            "project_id": project.id,
            "project_name": project.project_name,
            "task_id": task.id,
            "task_code": task.task_code,
            "customer_code": customer.customer_code,
            "change_items": change_items,
            "synced_to_master": True,
        },
        request=request,
    )
    _mark_task_started_by_data_update(db, task)
    if task.latest_owner_next_action == "等待资料更新审批":
        task.latest_owner_next_action = "客户基本资料已保存，继续跟进客户需求"
    db.flush()
    audit_log = update_result.get("audit_log")
    audit_log_id = audit_log.id if audit_log is not None else None
    db.commit()
    db.refresh(customer)
    return {
        "customer": _crm_customer_profile_detail_payload(db, current_user, customer),
        "changed_fields": update_result.get("changed_fields") or [],
        "audit_log_id": audit_log_id,
        "task_id": task.id,
        "project_id": project.id,
        "synced_to_master": True,
        "change_items": change_items,
    }


@router.post("/linked-customers/{customer_code}/profile/approval-draft", response_model=ApprovalInstancePublic, status_code=status.HTTP_201_CREATED)
def create_crm_customer_profile_approval_draft(
    customer_code: str,
    payload: CrmCustomerProfileApprovalDraftCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_customer_profile.submit")),
) -> ApprovalInstance:
    task, project = _scoped_active_customer_task(db, current_user, customer_code)
    customer = db.scalar(select(CustomerMaster).where(CustomerMaster.customer_code == customer_code))
    if customer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    handler_user = _project_owner_handler(db, project, "资料更新审批")
    incoming_profile_payload = payload.profile.model_dump(exclude_unset=True)
    if not incoming_profile_payload:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Customer profile update payload is empty")
    before_profile = customer_audit_snapshot(customer)
    profile_payload, change_items = build_customer_profile_patch(before_profile, incoming_profile_payload, CUSTOMER_PROFILE_FIELD_LABELS)
    if not profile_payload:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请至少修改一项客户基本资料")
    approval = create_approval_instance(
        db,
        approval_type="customer_profile_update",
        resource_type="crm_customer_profile",
        resource_id=customer.customer_code,
        title=payload.title or f"客户基本资料更新：{customer.customer_name}",
        description=payload.description,
        applicant=current_user,
        current_handler_user_id=handler_user.id,
        priority=payload.priority,
        payload_json={
            "customer_code": customer.customer_code,
            "customer_name": customer.customer_name,
            "project_id": project.id,
            "project_name": project.project_name,
            "task_id": task.id,
            "task_code": task.task_code,
            "before_profile": before_profile,
            "profile": profile_payload,
            "change_items": change_items,
        },
        status_value="draft",
        submit=payload.submit,
    )
    if approval.status != "draft":
        _mark_task_started_by_data_update(db, task)
    write_audit_log(
        db,
        action_type="create_crm_customer_profile_approval_draft",
        resource_type="approval_instance",
        resource_id=str(approval.id),
        user=current_user,
        request=request,
        after_data=jsonable_encoder({
            "approval_no": approval.approval_no,
            "approval_type": approval.approval_type,
            "status": approval.status,
            "customer_code": customer.customer_code,
            "current_handler_user_id": approval.current_handler_user_id,
        }),
    )
    db.commit()
    db.refresh(approval)
    return approval


@router.get("/linked-customers/{customer_code}/business-profile", response_model=CustomerBusinessProfileResponse)
def get_crm_linked_customer_business_profile(
    customer_code: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_business_profile.view")),
) -> dict[str, Any]:
    _scoped_active_customer_task(db, current_user, customer_code)
    customer = db.scalar(select(CustomerMaster).where(CustomerMaster.customer_code == customer_code))
    if customer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    result = customer_business_profile_response(db, current_user, customer, include_history=False)
    write_audit_log(
        db,
        action_type="view_crm_customer_business_profile",
        resource_type="customer_business_profile",
        resource_id=customer.customer_code,
        user=current_user,
        request=request,
        after_data={
            "scope": "crm_linked_customer",
            "has_profile": result["profile"] is not None,
            "product_count": len(result["products"]),
        },
    )
    db.commit()
    return result


@router.post(
    "/linked-customers/{customer_code}/business-profile/update",
    response_model=CrmBusinessProfileUpdateResponse,
)
def update_crm_linked_customer_business_profile(
    customer_code: str,
    payload: CustomerBusinessProfileUpsert,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_business_profile.submit")),
) -> dict[str, Any]:
    task, project = _scoped_active_customer_task(db, current_user, customer_code)
    customer = db.scalar(select(CustomerMaster).where(CustomerMaster.customer_code == customer_code))
    if customer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    raw_payload = payload.model_dump(exclude_unset=True)
    if not raw_payload:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请至少填写一项客户经营资料")
    recommended_products = raw_payload.pop("recommended_products", [])
    profile_payload = CustomerBusinessProfileUpsert.model_validate(raw_payload)
    result = apply_customer_business_profile_update(
        db,
        customer=customer,
        payload=profile_payload,
        operator=current_user,
        request=request,
        audit_action_type=CRM_BUSINESS_PROFILE_DIRECT_ACTION,
        recommended_products=[item.model_dump(exclude_unset=True) for item in payload.recommended_products] if payload.recommended_products else recommended_products,
        audit_extra={
            "scope": "crm_linked_customer",
            "project_id": project.id,
            "project_name": project.project_name,
            "task_id": task.id,
            "task_code": task.task_code,
            "synced_to_master": True,
        },
    )
    _mark_task_started_by_data_update(db, task)
    task.latest_owner_next_status = "经营资料已保存"
    if not task.latest_owner_next_action or task.latest_owner_next_action == "等待资料更新审批":
        task.latest_owner_next_action = "经营资料已同步，继续推进客户跟进"
    response = CrmBusinessProfileUpdateResponse.model_validate(
        {
            **result,
            "task_id": task.id,
            "project_id": project.id,
            "synced_to_master": True,
        }
    ).model_dump(mode="python")
    db.commit()
    db.refresh(task)
    return response


@router.post("/linked-customers/{customer_code}/business-profile/approval-draft", response_model=ApprovalInstancePublic, status_code=status.HTTP_201_CREATED)
def create_crm_business_profile_approval_draft(
    customer_code: str,
    payload: CrmBusinessProfileApprovalDraftCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_business_profile.submit")),
) -> ApprovalInstance:
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="客户经营资料已改为直接保存，请使用 /business-profile/update 接口。",
    )


@router.get("/daily-summary", response_model=CrmDailySummary)
def get_crm_daily_summary(
    target_date: date | None = Query(None, alias="date"),
    limit: int = 200,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_task.view")),
) -> CrmDailySummary:
    safe_limit = max(1, min(limit, 500))
    now = datetime.now(timezone.utc)
    calendar_date = target_date or now.astimezone(BUSINESS_TZ).date()
    day_start, day_end = _day_bounds(calendar_date)
    stmt = crm_task_scope_filter(
        select(CrmProjectCustomerTask).where(
            CrmProjectCustomerTask.is_closed.is_(False),
            CrmProjectCustomerTask.project_id.not_in(_frozen_project_ids()),
            CrmProjectCustomerTask.feedback_due_at.is_not(None),
            CrmProjectCustomerTask.feedback_due_at >= day_start,
            CrmProjectCustomerTask.feedback_due_at <= day_end,
        ),
        db,
        current_user,
    )
    task_total = _count_stmt(db, stmt)
    task_rows = list(
        db.scalars(
            stmt.order_by(CrmProjectCustomerTask.feedback_due_at.asc(), CrmProjectCustomerTask.id.desc())
            .limit(safe_limit)
        ).all()
    )
    task_ids = [task.id for task in task_rows]
    valid_task_ids: set[int] = set()
    if task_ids:
        valid_task_ids = set(
            db.scalars(
                select(CrmFollowup.task_id)
                .where(
                    CrmFollowup.task_id.in_(task_ids),
                    CrmFollowup.valid_feedback.is_(True),
                )
            ).all()
        )
    due_tasks = [_daily_summary_task(task, valid_task_ids, now) for task in task_rows]
    overdue_tasks = [task for task in due_tasks if task.overdue]
    responsible_user_ids = sorted({task.executor_user_id for task in task_rows if task.executor_user_id})
    missing_responsible_user_ids = sorted({task.executor_user_id for task in task_rows if task.executor_user_id and task.id not in valid_task_ids and task.feedback_due_at and task.feedback_due_at < now})
    return CrmDailySummary(
        date=calendar_date,
        due_tasks=due_tasks,
        overdue_tasks=overdue_tasks,
        task_total=task_total,
        due_count=len(due_tasks),
        overdue_count=len(overdue_tasks),
        responsible_user_ids=responsible_user_ids,
        missing_responsible_user_ids=missing_responsible_user_ids,
        generated_at=now,
    )


@router.get("/projects/page", response_model=CrmProjectPage)
def list_crm_projects_page(
    q: str | None = None,
    status_value: str | None = None,
    approval_status: str | None = None,
    project_type: str | None = None,
    owner_user_id: int | None = None,
    participant_user_id: int | None = None,
    executor_user_id: int | None = None,
    start_from: date | None = None,
    start_to: date | None = None,
    due_from: date | None = None,
    due_to: date | None = None,
    overdue: bool | None = None,
    has_support: bool | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_project.view")),
) -> CrmProjectPage:
    safe_limit = _safe_limit(limit)
    safe_offset = _safe_offset(offset)
    stmt = crm_project_scope_filter(select(CrmProject), db, current_user)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                CrmProject.project_code.ilike(like),
                CrmProject.project_name.ilike(like),
                CrmProject.project_type.ilike(like),
                CrmProject.business_line.ilike(like),
            )
        )
    if status_value:
        stmt = stmt.where(CrmProject.status == status_value)
    if approval_status:
        stmt = stmt.where(CrmProject.approval_status == approval_status)
    if project_type:
        stmt = stmt.where(CrmProject.project_type == project_type)
    if owner_user_id:
        stmt = stmt.where(CrmProject.owner_user_id == owner_user_id)
    if participant_user_id:
        stmt = stmt.where(CrmProject.participant_user_ids.contains([participant_user_id]))
    if executor_user_id:
        stmt = stmt.where(
            exists()
            .where(CrmProjectCustomerTask.project_id == CrmProject.id)
            .where(CrmProjectCustomerTask.executor_user_id == executor_user_id)
        )
    if start_from:
        stmt = stmt.where(CrmProject.start_date >= start_from)
    if start_to:
        stmt = stmt.where(CrmProject.start_date <= start_to)
    if due_from:
        stmt = stmt.where(CrmProject.due_date >= due_from)
    if due_to:
        stmt = stmt.where(CrmProject.due_date <= due_to)
    if overdue is not None:
        overdue_filter = (
            CrmProject.due_date < date.today(),
            CrmProject.status.not_in(["closed", "cancelled"]),
        )
        stmt = stmt.where(*overdue_filter) if overdue else stmt.where(or_(CrmProject.due_date.is_(None), CrmProject.due_date >= date.today()))
    if has_support is not None:
        support_exists = exists().where(CrmProjectCustomerTask.project_id == CrmProject.id).where(CrmProjectCustomerTask.need_support.is_(True))
        work_item_exists = exists().where(WorkItem.project_id == CrmProject.id).where(WorkItem.status.in_(["open", "processing"]))
        stmt = stmt.where(or_(support_exists, work_item_exists)) if has_support else stmt.where(~or_(support_exists, work_item_exists))

    total = _count_stmt(db, stmt)
    projects = list(db.scalars(stmt.order_by(CrmProject.id.desc()).offset(safe_offset).limit(safe_limit)).all())
    items = [_project_public(db, project) for project in projects]
    return CrmProjectPage(items=items, total=total, limit=safe_limit, offset=safe_offset)


@router.post("/projects/approval-draft", response_model=ApprovalInstancePublic, status_code=status.HTTP_201_CREATED)
def create_crm_project_approval_draft(
    payload: CrmProjectApprovalDraftCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_project.create")),
) -> ApprovalInstance:
    project_data = payload.project.model_dump()
    project_data["applicant_user_id"] = current_user.id
    landing_approver_id = project_data.get("landing_approver_user_id")
    if landing_approver_id:
        handler_user = require_user(db, landing_approver_id, "landing_approver_user_id")
    else:
        handler_user = _fixed_active_handler(db, PROJECT_APPROVER_USERNAME, "项目落地审批人")
        project_data["landing_approver_user_id"] = handler_user.id
    if not project_data.get("owner_user_id"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请选择细节审批人")
    _validate_project_payload(db, project_data)
    if not payload.project.project_name.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="项目名称不能为空")
    if not payload.tasks:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="项目申请至少需要选择 1 个客户任务")
    seen_customers: set[str] = set()
    task_payloads = []
    for task_payload in payload.tasks:
        task_data = task_payload.model_dump()
        if task_data["customer_code"] in seen_customers:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"客户任务底盘存在重复客户：{task_data['customer_code']}")
        seen_customers.add(task_data["customer_code"])
        require_customer(db, task_data["customer_code"])
        validate_task_status(task_data["status"])
        task_executor_snapshot(db, task_data.get("executor_user_id"), task_data.get("executor_employee_code"))
        task_payloads.append(task_data)
    approval = create_approval_instance(
        db,
        approval_type="crm_project_create",
        resource_type="crm_project",
        resource_id="pending",
        title=payload.title or f"客户项目立项：{payload.project.project_name}",
        description=payload.description,
        applicant=current_user,
        current_handler_user_id=handler_user.id,
        priority=payload.priority,
        payload_json={"project": project_data, "tasks": task_payloads},
        status_value="draft",
        submit=payload.submit,
    )
    write_audit_log(
        db,
        action_type="create_crm_project_approval_draft",
        resource_type="approval_instance",
        resource_id=str(approval.id),
        user=current_user,
        request=request,
        after_data=jsonable_encoder({
            "approval_no": approval.approval_no,
            "approval_type": approval.approval_type,
            "status": approval.status,
            "current_handler_user_id": approval.current_handler_user_id,
        }),
    )
    db.commit()
    db.refresh(approval)
    return approval


@router.get("/governance/test-projects", response_model=CrmTestProjectPage)
def list_crm_test_projects(
    marker: str | None = Query("E2E"),
    include_cancelled: bool = True,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_project.view")),
) -> CrmTestProjectPage:
    safe_limit = _safe_limit(limit)
    safe_offset = _safe_offset(offset)
    normalized_marker = (marker or "").strip() or None
    markers = _active_test_markers(normalized_marker)
    stmt = crm_project_scope_filter(select(CrmProject), db, current_user).where(_test_marker_filter(markers))
    if not include_cancelled:
        stmt = stmt.where(CrmProject.status != "cancelled")
    total = _count_stmt(db, stmt)
    projects = list(db.scalars(stmt.order_by(CrmProject.updated_at.desc(), CrmProject.id.desc()).offset(safe_offset).limit(safe_limit)).all())
    return CrmTestProjectPage(
        items=[_test_project_candidate(db, project, normalized_marker) for project in projects],
        total=total,
        limit=safe_limit,
        offset=safe_offset,
        marker=normalized_marker,
    )


@router.post("/governance/test-projects/{project_id}/void", response_model=CrmVoidTestProjectResult)
def void_crm_test_project(
    project_id: int,
    payload: CrmVoidTestProjectRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_project.edit")),
) -> CrmVoidTestProjectResult:
    if payload.confirmation != TEST_PROJECT_VOID_CONFIRMATION:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid confirmation for voiding temporary project")
    project = _scoped_project(db, current_user, project_id)
    result = _void_test_project(db, project, current_user, request, payload.reason)
    db.commit()
    return result


@router.get("/projects/{project_id}", response_model=CrmProjectDetail)
def get_crm_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_project.view")),
) -> CrmProjectDetail:
    project = _scoped_project(db, current_user, project_id)
    return _project_detail(db, project)


@router.get("/projects/{project_id}/context", response_model=CrmProjectContext)
def get_crm_project_context(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_project.view")),
) -> CrmProjectContext:
    project = _scoped_project(db, current_user, project_id)
    tasks: list[CrmProjectCustomerTaskPublic] = []
    followups: list[CrmFollowupPublic] = []
    approvals: list[ApprovalInstancePublic] = []
    work_items: list[WorkItemPublic] = []
    reviews: list[CrmProjectReviewPublic] = []

    if has_permission(db, current_user, "crm_task.view"):
        task_stmt = crm_task_scope_filter(
            select(CrmProjectCustomerTask).where(CrmProjectCustomerTask.project_id == project_id),
            db,
            current_user,
        )
        task_rows = list(db.scalars(task_stmt.order_by(CrmProjectCustomerTask.id.desc()).limit(50)).all())
        tasks = [CrmProjectCustomerTaskPublic.model_validate(task) for task in task_rows]

    if has_permission(db, current_user, "crm_followup.view"):
        followup_stmt = crm_followup_scope_filter(
            select(CrmFollowup).where(CrmFollowup.project_id == project_id),
            db,
            current_user,
        )
        followup_rows = list(db.scalars(followup_stmt.order_by(CrmFollowup.created_at.desc(), CrmFollowup.id.desc()).limit(50)).all())
        followups = [CrmFollowupPublic.model_validate(followup) for followup in followup_rows]

    if has_permission(db, current_user, "approval.view"):
        approval_filters = [
            (ApprovalInstance.resource_type == "crm_project") & (ApprovalInstance.resource_id == str(project_id)),
            (ApprovalInstance.approval_type == "crm_followup_submit")
            & text("(approval_instance.payload_json #>> '{followup,project_id}') = :crm_context_project_id").bindparams(crm_context_project_id=str(project_id)),
        ]
        if project.current_approval_id:
            approval_filters.append(ApprovalInstance.id == project.current_approval_id)
        approval_rows = list(
            db.scalars(
                select(ApprovalInstance)
                .where(or_(*approval_filters))
                .order_by(ApprovalInstance.id.desc())
                .limit(20)
            ).all()
        )
        approvals = [ApprovalInstancePublic.model_validate(approval) for approval in approval_rows]

    if has_permission(db, current_user, "crm_issue.view"):
        item_stmt = crm_work_item_scope_filter(
            select(WorkItem).where(WorkItem.project_id == project_id),
            db,
            current_user,
        )
        item_rows = list(
            db.scalars(
                item_stmt.order_by(WorkItem.id.desc()).limit(50)
            ).all()
        )
        work_items = [WorkItemPublic.model_validate(item) for item in item_rows]

    if has_permission(db, current_user, "crm_project.review"):
        review_rows = list(
            db.scalars(
                select(CrmProjectReview)
                .where(CrmProjectReview.project_id == project_id)
                .order_by(CrmProjectReview.id.desc())
                .limit(20)
            ).all()
        )
        reviews = [CrmProjectReviewPublic.model_validate(review) for review in review_rows]

    return CrmProjectContext(
        project_detail=_project_detail(db, project),
        tasks=tasks,
        followups=followups,
        approvals=approvals,
        work_items=work_items,
        reviews=reviews,
    )


@router.post("/projects", response_model=CrmProjectPublic, status_code=status.HTTP_201_CREATED)
def create_crm_project(
    payload: CrmProjectCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_project.create")),
) -> CrmProject:
    data = payload.model_dump()
    project_code = data.pop("project_code") or generated_code("CRMP")
    ensure_unique_project_code(db, project_code)
    data["applicant_user_id"] = data.get("applicant_user_id") or current_user.id
    data["landing_approver_user_id"] = data.get("landing_approver_user_id") or _fixed_active_handler(db, PROJECT_APPROVER_USERNAME, "项目落地审批人").id
    data["owner_user_id"] = data.get("owner_user_id") or current_user.id
    _validate_project_payload(db, data)
    project = CrmProject(
        project_code=project_code,
        **data,
        created_by_user_id=current_user.id,
        updated_by_user_id=current_user.id,
    )
    db.add(project)
    db.flush()
    write_audit_log(
        db,
        action_type="create_crm_project",
        resource_type="crm_project",
        resource_id=str(project.id),
        user=current_user,
        request=request,
        after_data=jsonable_encoder(project_audit_snapshot(project)),
    )
    db.commit()
    db.refresh(project)
    return project


@router.patch("/projects/{project_id}", response_model=CrmProjectPublic)
def update_crm_project(
    project_id: int,
    payload: CrmProjectUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_project.edit")),
) -> CrmProject:
    project = _scoped_project(db, current_user, project_id)
    ensure_project_operable(project)
    if _is_progress_cc_only(project, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="项目进展抄送人只能查看项目进展，不能修改项目",
        )
    changes = _clean_update(payload)
    _validate_project_payload(db, changes)
    before_data = jsonable_encoder(project_audit_snapshot(project))
    _apply_changes(project, changes)
    project.updated_by_user_id = current_user.id
    write_audit_log(
        db,
        action_type="update_crm_project",
        resource_type="crm_project",
        resource_id=str(project.id),
        user=current_user,
        request=request,
        before_data=before_data,
        after_data=jsonable_encoder(project_audit_snapshot(project)),
    )
    db.commit()
    db.refresh(project)
    return project


@router.get("/projects/{project_id}/customer-details/page", response_model=CrmProjectCustomerDetailPage)
def list_crm_project_customer_details_page(
    project_id: int,
    q: str | None = None,
    customer_group_name: str | None = None,
    salesperson_name: str | None = None,
    region: str | None = None,
    customer_type: str | None = None,
    customer_status: str | None = None,
    status_value: str | None = None,
    latest_blocker_reason: str | None = None,
    overdue: bool | None = None,
    need_support: bool | None = None,
    is_blocked: bool | None = None,
    is_closed: bool | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_task.view")),
) -> CrmProjectCustomerDetailPage:
    _scoped_project(db, current_user, project_id)
    safe_limit = _safe_limit(limit)
    safe_offset = _safe_offset(offset)
    now = datetime.now(timezone.utc)
    scoped_stmt = crm_task_scope_filter(
        select(CrmProjectCustomerTask, CustomerMaster)
        .outerjoin(CustomerMaster, CustomerMaster.customer_code == CrmProjectCustomerTask.customer_code)
        .where(CrmProjectCustomerTask.project_id == project_id),
        db,
        current_user,
    )
    summary_rows = list(db.execute(scoped_stmt.order_by(CrmProjectCustomerTask.id.desc())).all())
    summary = _crm_project_customer_detail_summary(summary_rows, now)

    stmt = scoped_stmt
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                CrmProjectCustomerTask.task_code.ilike(like),
                CrmProjectCustomerTask.customer_code.ilike(like),
                CrmProjectCustomerTask.customer_name_snapshot.ilike(like),
                CrmProjectCustomerTask.executor_name_snapshot.ilike(like),
                CrmProjectCustomerTask.business_issue_point.ilike(like),
                CrmProjectCustomerTask.round_target.ilike(like),
                CustomerMaster.customer_name.ilike(like),
                CustomerMaster.customer_short_name.ilike(like),
                CustomerMaster.customer_group_name.ilike(like),
                CustomerMaster.region.ilike(like),
                CustomerMaster.salesperson_name.ilike(like),
                CustomerMaster.contact_name.ilike(like),
                CustomerMaster.contact_phone.ilike(like),
            )
        )
    if customer_group_name:
        stmt = stmt.where(CustomerMaster.customer_group_name == customer_group_name)
    if salesperson_name:
        stmt = stmt.where(
            or_(
                CustomerMaster.salesperson_name == salesperson_name,
                CrmProjectCustomerTask.executor_name_snapshot == salesperson_name,
            )
        )
    if region:
        stmt = stmt.where(CustomerMaster.region == region)
    if customer_type:
        stmt = stmt.where(CustomerMaster.customer_type == customer_type)
    if customer_status:
        stmt = stmt.where(CustomerMaster.status == customer_status)
    if status_value:
        stmt = stmt.where(CrmProjectCustomerTask.status == status_value)
    if latest_blocker_reason:
        stmt = stmt.where(CrmProjectCustomerTask.latest_blocker_reason == latest_blocker_reason)
    if overdue is not None:
        if overdue:
            stmt = stmt.where(
                CrmProjectCustomerTask.is_closed.is_(False),
                CrmProjectCustomerTask.feedback_due_at.is_not(None),
                CrmProjectCustomerTask.feedback_due_at < now,
            )
        else:
            stmt = stmt.where(
                or_(
                    CrmProjectCustomerTask.is_closed.is_(True),
                    CrmProjectCustomerTask.feedback_due_at.is_(None),
                    CrmProjectCustomerTask.feedback_due_at >= now,
                )
            )
    if need_support is not None:
        if need_support:
            stmt = stmt.where(
                or_(
                    CrmProjectCustomerTask.need_support.is_(True),
                    CrmProjectCustomerTask.need_manager_support.is_(True),
                    CrmProjectCustomerTask.need_boss_decision.is_(True),
                )
            )
        else:
            stmt = stmt.where(
                CrmProjectCustomerTask.need_support.is_(False),
                CrmProjectCustomerTask.need_manager_support.is_(False),
                CrmProjectCustomerTask.need_boss_decision.is_(False),
            )
    if is_blocked is not None:
        stmt = stmt.where(CrmProjectCustomerTask.is_blocked.is_(is_blocked))
    if is_closed is not None:
        stmt = stmt.where(CrmProjectCustomerTask.is_closed.is_(is_closed))

    total = _count_stmt(db, stmt.with_only_columns(CrmProjectCustomerTask.id))
    rows = list(
        db.execute(
            stmt.order_by(
                CrmProjectCustomerTask.is_closed.asc(),
                CrmProjectCustomerTask.feedback_due_at.asc().nullslast(),
                CrmProjectCustomerTask.id.desc(),
            )
            .offset(safe_offset)
            .limit(safe_limit)
        ).all()
    )
    items = [_crm_project_customer_detail_row(task, customer, now) for task, customer in rows]
    return CrmProjectCustomerDetailPage(items=items, total=total, limit=safe_limit, offset=safe_offset, summary=summary)


@router.get("/projects/{project_id}/tasks/page", response_model=CrmTaskPage)
def list_crm_project_tasks_page(
    project_id: int,
    q: str | None = None,
    customer_code: str | None = None,
    customer_name: str | None = None,
    executor_user_id: int | None = None,
    status_value: str | None = None,
    minimum_action_done: bool | None = None,
    need_support: bool | None = None,
    is_blocked: bool | None = None,
    is_closed: bool | None = None,
    followup_submission_state: Literal["unsubmitted", "submitted", "needs_action"] | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_task.view")),
) -> CrmTaskPage:
    _project_or_404(db, project_id)
    safe_limit = _safe_limit(limit)
    safe_offset = _safe_offset(offset)
    stmt = crm_task_scope_filter(select(CrmProjectCustomerTask).where(CrmProjectCustomerTask.project_id == project_id), db, current_user)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(*_task_search_conditions(like)))
    if customer_code:
        stmt = stmt.where(CrmProjectCustomerTask.customer_code == customer_code)
    if customer_name:
        stmt = stmt.where(CrmProjectCustomerTask.customer_name_snapshot.ilike(f"%{customer_name}%"))
    if executor_user_id:
        stmt = stmt.where(CrmProjectCustomerTask.executor_user_id == executor_user_id)
    if status_value:
        stmt = stmt.where(CrmProjectCustomerTask.status == status_value)
    if minimum_action_done is not None:
        stmt = stmt.where(CrmProjectCustomerTask.minimum_action_done.is_(minimum_action_done))
    if need_support is not None:
        stmt = stmt.where(CrmProjectCustomerTask.need_support.is_(need_support))
    if is_blocked is not None:
        stmt = stmt.where(CrmProjectCustomerTask.is_blocked.is_(is_blocked))
    if is_closed is not None:
        stmt = stmt.where(CrmProjectCustomerTask.is_closed.is_(is_closed))
    stmt, submission_summary = _task_submission_page_query(db, stmt, followup_submission_state)
    total = _count_stmt(db, stmt)
    items = list(db.scalars(stmt.order_by(CrmProjectCustomerTask.id.desc()).offset(safe_offset).limit(safe_limit)).all())
    _fill_task_project_purpose(db, items)
    _fill_task_data_update_summary(db, items)
    _fill_task_followup_submission(db, items)
    return CrmTaskPage(
        items=items,
        total=total,
        limit=safe_limit,
        offset=safe_offset,
        submission_summary=submission_summary,
    )


@router.get("/tasks/page", response_model=CrmTaskPage)
def list_crm_tasks_page(
    q: str | None = None,
    project_id: int | None = None,
    customer_code: str | None = None,
    customer_name: str | None = None,
    executor_user_id: int | None = None,
    status_value: str | None = None,
    minimum_action_done: bool | None = None,
    need_support: bool | None = None,
    need_manager_support: bool | None = None,
    need_boss_decision: bool | None = None,
    is_blocked: bool | None = None,
    is_closed: bool | None = None,
    overdue: bool | None = None,
    due_from: datetime | None = None,
    due_to: datetime | None = None,
    followup_submission_state: Literal["unsubmitted", "submitted", "needs_action"] | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_task.view")),
) -> CrmTaskPage:
    safe_limit = _safe_limit(limit)
    safe_offset = _safe_offset(offset)
    stmt = crm_task_scope_filter(select(CrmProjectCustomerTask), db, current_user)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(*_task_search_conditions(like)))
    if project_id:
        stmt = stmt.where(CrmProjectCustomerTask.project_id == project_id)
    if customer_code:
        stmt = stmt.where(CrmProjectCustomerTask.customer_code == customer_code)
    if customer_name:
        stmt = stmt.where(CrmProjectCustomerTask.customer_name_snapshot.ilike(f"%{customer_name}%"))
    if executor_user_id:
        stmt = stmt.where(CrmProjectCustomerTask.executor_user_id == executor_user_id)
    if status_value:
        stmt = stmt.where(CrmProjectCustomerTask.status == status_value)
    if minimum_action_done is not None:
        stmt = stmt.where(CrmProjectCustomerTask.minimum_action_done.is_(minimum_action_done))
    if need_support is not None:
        stmt = stmt.where(CrmProjectCustomerTask.need_support.is_(need_support))
    if need_manager_support is not None:
        stmt = stmt.where(CrmProjectCustomerTask.need_manager_support.is_(need_manager_support))
    if need_boss_decision is not None:
        stmt = stmt.where(CrmProjectCustomerTask.need_boss_decision.is_(need_boss_decision))
    if is_blocked is not None:
        stmt = stmt.where(CrmProjectCustomerTask.is_blocked.is_(is_blocked))
    if is_closed is not None:
        stmt = stmt.where(CrmProjectCustomerTask.is_closed.is_(is_closed))
    now = datetime.now(timezone.utc)
    if overdue is not None:
        if overdue:
            stmt = stmt.where(
                CrmProjectCustomerTask.is_closed.is_(False),
                CrmProjectCustomerTask.feedback_due_at.is_not(None),
                CrmProjectCustomerTask.feedback_due_at < now,
            )
        else:
            stmt = stmt.where(
                or_(
                    CrmProjectCustomerTask.is_closed.is_(True),
                    CrmProjectCustomerTask.feedback_due_at.is_(None),
                    CrmProjectCustomerTask.feedback_due_at >= now,
                )
            )
    if due_from:
        stmt = stmt.where(CrmProjectCustomerTask.feedback_due_at >= due_from)
    if due_to:
        stmt = stmt.where(CrmProjectCustomerTask.feedback_due_at <= due_to)
    stmt, submission_summary = _task_submission_page_query(db, stmt, followup_submission_state)
    total = _count_stmt(db, stmt)
    items = list(db.scalars(stmt.order_by(CrmProjectCustomerTask.feedback_due_at.asc().nullslast(), CrmProjectCustomerTask.id.desc()).offset(safe_offset).limit(safe_limit)).all())
    _fill_task_project_purpose(db, items)
    _fill_task_data_update_summary(db, items)
    _fill_task_followup_submission(db, items)
    return CrmTaskPage(
        items=items,
        total=total,
        limit=safe_limit,
        offset=safe_offset,
        submission_summary=submission_summary,
    )


@router.post("/projects/{project_id}/tasks", response_model=CrmProjectCustomerTaskPublic, status_code=status.HTTP_201_CREATED)
def create_crm_project_task(
    project_id: int,
    payload: CrmTaskCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_task.assign")),
) -> CrmProjectCustomerTask:
    project = _scoped_project(db, current_user, project_id)
    ensure_project_operable(project)
    data = payload.model_dump()
    task_code = data.pop("task_code") or generated_code("CRMT")
    ensure_unique_task_code(db, task_code)
    validate_task_status(data["status"])
    customer = require_customer(db, data["customer_code"])
    if db.scalar(
        select(CrmProjectCustomerTask).where(
            CrmProjectCustomerTask.project_id == project_id,
            CrmProjectCustomerTask.customer_code == customer.customer_code,
        )
    ):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Customer task already exists in this project")
    employee_code, executor_name = task_executor_snapshot(db, data.get("executor_user_id"), data.get("executor_employee_code"))
    task = CrmProjectCustomerTask(
        project_id=project_id,
        task_code=task_code,
        customer_code=customer.customer_code,
        customer_name_snapshot=customer.customer_name,
        executor_user_id=data.get("executor_user_id"),
        executor_employee_code=employee_code,
        executor_name_snapshot=executor_name,
        business_issue_point=data.get("business_issue_point"),
        round_target=data.get("round_target"),
        feedback_due_at=data.get("feedback_due_at"),
        status=data["status"],
    )
    db.add(task)
    db.flush()
    refresh_project_summary(db, project_id)
    write_audit_log(
        db,
        action_type="create_crm_project_task",
        resource_type="crm_project_task",
        resource_id=str(task.id),
        user=current_user,
        request=request,
        after_data=jsonable_encoder(task_audit_snapshot(task)),
    )
    enqueue_incremental_exception_scan_safely(
        db,
        domains=["crm"],
        target_resource_type="crm_project_task",
        target_resource_id=task.id,
    )
    db.commit()
    db.refresh(task)
    return task


@router.get("/tasks/{task_id}", response_model=CrmTaskDetail)
def get_crm_task_detail(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_task.view")),
) -> CrmTaskDetail:
    task = _scoped_task(db, current_user, task_id)
    return _task_detail(db, current_user, task)


@router.patch("/tasks/{task_id}", response_model=CrmProjectCustomerTaskPublic)
def update_crm_task(
    task_id: int,
    payload: CrmTaskUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_task.edit")),
) -> CrmProjectCustomerTask:
    task = _scoped_task(db, current_user, task_id)
    ensure_project_operable(_project_or_404(db, task.project_id))
    changes = _clean_update(payload)
    if "status" in changes and changes["status"] is not None:
        validate_task_status(changes["status"])
    if "executor_user_id" in changes or "executor_employee_code" in changes:
        employee_code, executor_name = task_executor_snapshot(
            db,
            changes.get("executor_user_id", task.executor_user_id),
            changes.get("executor_employee_code", task.executor_employee_code),
        )
        changes["executor_employee_code"] = employee_code
        changes["executor_name_snapshot"] = executor_name
    before_data = jsonable_encoder(task_audit_snapshot(task))
    _apply_changes(task, changes)
    if task.is_closed and task.status != "closed":
        task.status = "closed"
    refresh_project_summary(db, task.project_id)
    write_audit_log(
        db,
        action_type="update_crm_project_task",
        resource_type="crm_project_task",
        resource_id=str(task.id),
        user=current_user,
        request=request,
        before_data=before_data,
        after_data=jsonable_encoder(task_audit_snapshot(task)),
    )
    enqueue_incremental_exception_scan_safely(
        db,
        domains=["crm"],
        target_resource_type="crm_project_task",
        target_resource_id=task.id,
    )
    db.commit()
    db.refresh(task)
    return task


@router.get("/followups/page", response_model=CrmFollowupPage)
def list_crm_followups_page(
    q: str | None = None,
    project_id: int | None = None,
    task_id: int | None = None,
    customer_code: str | None = None,
    executor_user_id: int | None = None,
    review_status: str | None = None,
    review_scope: str | None = None,
    need_support: bool | None = None,
    valid_feedback: bool | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_followup.view")),
) -> CrmFollowupPage:
    safe_limit = _safe_limit(limit)
    safe_offset = _safe_offset(offset)
    stmt = crm_followup_scope_filter(select(CrmFollowup), db, current_user)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                CrmFollowup.followup_no.ilike(like),
                CrmFollowup.customer_code.ilike(like),
                CrmFollowup.executor_name_snapshot.ilike(like),
                CrmFollowup.customer_feedback.ilike(like),
                CrmFollowup.current_need.ilike(like),
                exists().where(
                    CustomerMaster.customer_code == CrmFollowup.customer_code,
                    CustomerMaster.customer_name.ilike(like),
                ),
            )
        )
    if project_id:
        stmt = stmt.where(CrmFollowup.project_id == project_id)
    if task_id:
        stmt = stmt.where(CrmFollowup.task_id == task_id)
    if customer_code:
        stmt = stmt.where(CrmFollowup.customer_code == customer_code)
    if executor_user_id:
        stmt = stmt.where(CrmFollowup.executor_user_id == executor_user_id)
    if review_scope == "pending":
        stmt = stmt.where(CrmFollowup.review_status.in_(["pending", "need_supplement"]))
    elif review_status:
        stmt = stmt.where(CrmFollowup.review_status == review_status)
    if need_support is not None:
        stmt = stmt.where(CrmFollowup.need_support.is_(need_support))
    if valid_feedback is not None:
        stmt = stmt.where(CrmFollowup.valid_feedback.is_(valid_feedback))
    if date_from:
        stmt = stmt.where(CrmFollowup.followup_date >= date_from)
    if date_to:
        stmt = stmt.where(CrmFollowup.followup_date <= date_to)
    total = _count_stmt(db, stmt)
    items = list(db.scalars(stmt.order_by(CrmFollowup.created_at.desc(), CrmFollowup.id.desc()).offset(safe_offset).limit(safe_limit)).all())
    return CrmFollowupPage(items=_followup_public_rows(db, items), total=total, limit=safe_limit, offset=safe_offset)


@router.post("/followups/approval-draft", response_model=ApprovalInstancePublic, status_code=status.HTTP_201_CREATED)
def create_crm_followup_approval_draft(
    payload: CrmFollowupApprovalDraftCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_followup.submit")),
) -> ApprovalInstance:
    followup_data = payload.followup.model_dump()
    task = _scoped_task(db, current_user, followup_data["task_id"])
    if task.project_id != followup_data["project_id"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Task does not belong to the project")
    project = _project_or_404(db, task.project_id)
    ensure_project_operable(project)
    followup_data["review_status"] = "pending"
    _validate_customer_profile_followup_link(db, data=followup_data, task=task)
    _validate_business_profile_followup_link(db, data=followup_data, task=task)
    handler_user = _project_owner_handler(db, project, "跟进审批")
    approval = create_approval_instance(
        db,
        approval_type="crm_followup_submit",
        resource_type="crm_followup",
        resource_id="pending",
        title=payload.title or f"跟进事实审核：{task.customer_name_snapshot}",
        description=payload.description,
        applicant=current_user,
        current_handler_user_id=handler_user.id,
        priority=payload.priority,
        payload_json={"followup": followup_data},
        status_value="draft",
        submit=payload.submit,
    )
    write_audit_log(
        db,
        action_type="create_crm_followup_approval_draft",
        resource_type="approval_instance",
        resource_id=str(approval.id),
        user=current_user,
        request=request,
        after_data=jsonable_encoder({
            "approval_no": approval.approval_no,
            "approval_type": approval.approval_type,
            "status": approval.status,
            "current_handler_user_id": approval.current_handler_user_id,
        }),
    )
    db.commit()
    db.refresh(approval)
    return approval


@router.get("/followups/{followup_id}", response_model=CrmFollowupPublic)
def get_crm_followup(
    followup_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_followup.view")),
) -> CrmFollowupPublic:
    followup = _scoped_followup(db, current_user, followup_id)
    return _followup_public_rows(db, [followup])[0]


@router.post("/followups", response_model=CrmFollowupPublic, status_code=status.HTTP_201_CREATED)
def create_crm_followup(
    payload: CrmFollowupCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_followup.submit")),
) -> CrmFollowup:
    data = payload.model_dump()
    task = _scoped_task(db, current_user, data["task_id"])
    if task.project_id != data["project_id"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Task does not belong to the project")
    ensure_project_operable(_project_or_404(db, task.project_id))
    validate_followup_review_status(data["review_status"])
    _validate_customer_profile_followup_link(db, data=data, task=task)
    _validate_business_profile_followup_link(db, data=data, task=task)
    if data["review_status"] != "pending" and not has_permission(db, current_user, "crm_followup.review"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing CRM permission: crm_followup.review")
    followup_no = data.pop("followup_no") or generated_code("CRMF")
    ensure_unique_followup_no(db, followup_no)
    followup = CrmFollowup(
        followup_no=followup_no,
        project_id=task.project_id,
        task_id=task.id,
        customer_code=task.customer_code,
        executor_user_id=current_user.id,
        executor_name_snapshot=current_user.real_name or current_user.username,
        **{key: value for key, value in data.items() if key not in {"project_id", "task_id"}},
    )
    db.add(followup)
    db.flush()
    refresh_task_from_followups(db, task.id)
    refresh_project_summary(db, task.project_id)
    write_audit_log(
        db,
        action_type="create_crm_followup",
        resource_type="crm_followup",
        resource_id=str(followup.id),
        user=current_user,
        request=request,
        after_data=jsonable_encoder(followup_audit_snapshot(followup)),
    )
    enqueue_incremental_exception_scan_safely(
        db,
        domains=["crm"],
        target_resource_type="crm_followup",
        target_resource_id=followup.id,
    )
    enqueue_incremental_exception_scan_safely(
        db,
        domains=["crm"],
        target_resource_type="crm_project_task",
        target_resource_id=task.id,
    )
    db.commit()
    db.refresh(followup)
    return followup


@router.patch("/followups/{followup_id}", response_model=CrmFollowupPublic)
def update_crm_followup(
    followup_id: int,
    payload: CrmFollowupUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("crm_followup.edit", "crm_followup.review")),
) -> CrmFollowup:
    followup = _scoped_followup(db, current_user, followup_id)
    ensure_project_operable(_project_or_404(db, followup.project_id))
    changes = _clean_update(payload)
    needs_review_permission = bool(FOLLOWUP_REVIEW_FIELDS.intersection(changes))
    required_permission = "crm_followup.review" if needs_review_permission else "crm_followup.edit"
    if not has_permission(db, current_user, required_permission):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Missing CRM permission: {required_permission}")
    if "review_status" in changes and changes["review_status"] is not None:
        validate_followup_review_status(changes["review_status"])
    if "customer_profile_updated" in changes or "customer_profile_approval_id" in changes or "business_profile_updated" in changes or "business_profile_approval_id" in changes:
        task = db.get(CrmProjectCustomerTask, followup.task_id)
        if task is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CRM project task not found")
        candidate = {
            "customer_profile_updated": followup.customer_profile_updated,
            "customer_profile_approval_id": followup.customer_profile_approval_id,
            "business_profile_updated": followup.business_profile_updated,
            "business_profile_approval_id": followup.business_profile_approval_id,
        }
        candidate.update({key: value for key, value in changes.items() if key in candidate})
        _validate_customer_profile_followup_link(db, data=candidate, task=task)
        _validate_business_profile_followup_link(db, data=candidate, task=task)
    before_data = jsonable_encoder(followup_audit_snapshot(followup))
    _apply_changes(followup, changes)
    if needs_review_permission:
        mark_reviewed(followup, current_user.id)
    refresh_task_from_followups(db, followup.task_id)
    refresh_project_summary(db, followup.project_id)
    write_audit_log(
        db,
        action_type="review_crm_followup" if needs_review_permission else "update_crm_followup",
        resource_type="crm_followup",
        resource_id=str(followup.id),
        user=current_user,
        request=request,
        before_data=before_data,
        after_data=jsonable_encoder(followup_audit_snapshot(followup)),
    )
    enqueue_incremental_exception_scan_safely(
        db,
        domains=["crm"],
        target_resource_type="crm_followup",
        target_resource_id=followup.id,
    )
    enqueue_incremental_exception_scan_safely(
        db,
        domains=["crm"],
        target_resource_type="crm_project_task",
        target_resource_id=followup.task_id,
    )
    db.commit()
    db.refresh(followup)
    return followup


@router.get("/projects/{project_id}/reviews", response_model=list[CrmProjectReviewPublic])
def list_crm_project_reviews(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("crm_project.view", "crm_project.review")),
) -> list[CrmProjectReview]:
    _scoped_project(db, current_user, project_id)
    return list(db.scalars(select(CrmProjectReview).where(CrmProjectReview.project_id == project_id).order_by(CrmProjectReview.id.desc())).all())


@router.post("/projects/{project_id}/reviews", response_model=CrmProjectReviewPublic, status_code=status.HTTP_201_CREATED)
def create_crm_project_review(
    project_id: int,
    payload: CrmProjectReviewCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_project.review")),
) -> CrmProjectReview:
    project = _scoped_project(db, current_user, project_id)
    ensure_project_operable(project)
    data = payload.model_dump()
    review_no = data.pop("review_no") or generated_code("CRMR")
    ensure_unique_review_no(db, review_no)
    validate_review_status(data["status"])
    require_user(db, data.get("decision_maker_user_id"), "decision_maker_user_id")
    review = CrmProjectReview(review_no=review_no, project_id=project_id, **data)
    fill_review_counts(db, review)
    db.add(review)
    db.flush()
    write_audit_log(
        db,
        action_type="create_crm_project_review",
        resource_type="crm_project_review",
        resource_id=str(review.id),
        user=current_user,
        request=request,
        after_data=jsonable_encoder(review_audit_snapshot(review)),
    )
    db.commit()
    db.refresh(review)
    return review


@router.patch("/reviews/{review_id}", response_model=CrmProjectReviewPublic)
def update_crm_project_review(
    review_id: int,
    payload: CrmProjectReviewUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("crm_project.review")),
) -> CrmProjectReview:
    review = db.get(CrmProjectReview, review_id)
    if review is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CRM project review not found")
    project = _scoped_project(db, current_user, review.project_id)
    ensure_project_operable(project)
    changes = _clean_update(payload)
    if "status" in changes and changes["status"] is not None:
        validate_review_status(changes["status"])
    if "decision_maker_user_id" in changes:
        require_user(db, changes["decision_maker_user_id"], "decision_maker_user_id")
    before_data = jsonable_encoder(review_audit_snapshot(review))
    _apply_changes(review, changes)
    fill_review_counts(db, review)
    write_audit_log(
        db,
        action_type="update_crm_project_review",
        resource_type="crm_project_review",
        resource_id=str(review.id),
        user=current_user,
        request=request,
        before_data=before_data,
        after_data=jsonable_encoder(review_audit_snapshot(review)),
    )
    db.commit()
    db.refresh(review)
    return review

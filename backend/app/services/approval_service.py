from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import AuditLog, ApprovalEvent, ApprovalInstance, CrmFollowup, CrmLead, CrmLeadCampaign, CrmProject, CrmProjectCustomerTask, CustomerMaster, User, WorkItem
from app.models.crm import CRM_APPROVAL_STATUSES, CRM_APPROVAL_TYPES, WORK_ITEM_PRIORITIES
from app.schemas.crm import CrmFollowupCreate, CrmProjectCreate, CrmTaskCreate
from app.schemas.master_data import CustomerBusinessProfileUpsert, CustomerMasterUpdate
from app.services.audit_service import write_audit_log
from app.services.customer_identity_service import assert_customer_identity_available
from app.services.customer_master_service import apply_customer_master_update, customer_audit_snapshot, customer_profile_patch_from_change_items
from app.services.customer_business_profile_service import apply_customer_business_profile_update
from app.services.exception_center_service import enqueue_incremental_exception_scan_safely
from app.services.crm_lead_service import (
    acquire_lead_duplicate_locks,
    changed_lead_conversion_guard_fields,
    find_lead_duplicate_candidates,
    lead_audit_snapshot,
)
from app.services.crm_project_service import (
    ensure_unique_followup_no,
    ensure_unique_project_code,
    ensure_unique_task_code,
    followup_audit_snapshot,
    generated_code,
    project_audit_snapshot,
    require_customer,
    require_user,
    task_audit_snapshot,
    task_executor_snapshot,
    validate_followup_review_status,
    validate_project_status,
    validate_task_status,
)
from app.services.crm_rollup_service import mark_reviewed, refresh_project_summary, refresh_task_from_followups

TERMINAL_APPROVAL_STATUSES = {"completed", "approved", "rejected", "cancelled"}
ACTIONABLE_APPROVAL_STATUSES = {"submitted", "under_review"}
PROFILE_UPDATE_ACTIVE_APPROVAL_STATUSES = {"submitted", "under_review", "approved", "completed", "need_supplement"}
CRM_CUSTOMER_PROFILE_DIRECT_ACTION = "crm_customer_profile_update_direct"
CRM_BUSINESS_PROFILE_DIRECT_ACTION = "crm_business_profile_update_direct"
PROJECT_REAPPROVAL_MUTABLE_FIELDS = (
    "project_name",
    "project_type",
    "purpose",
    "customer_scope_note",
    "business_line",
    "owner_user_id",
    "project_manager_user_id",
    "participant_user_ids",
    "progress_cc_user_ids",
    "start_date",
    "due_date",
    "minimum_action",
    "closure_standard",
)


def _withdrawn_project_for_approval(db: Session, approval: ApprovalInstance) -> CrmProject | None:
    if approval.approval_type != "crm_project_create":
        return None
    result = approval.result_json if isinstance(approval.result_json, dict) else {}
    try:
        project_id = int(result.get("project_id") or (approval.resource_id if approval.resource_type == "crm_project" else 0))
    except (TypeError, ValueError):
        return None
    project = db.get(CrmProject, project_id) if project_id else None
    if project is None or project.current_approval_id != approval.id or project.approval_withdrawn_at is None:
        return None
    return project


def _approval_references_task(row: ApprovalInstance, task_id: int) -> bool:
    payload = row.payload_json if isinstance(row.payload_json, dict) else {}
    nested_task = payload.get("task") if isinstance(payload.get("task"), dict) else {}
    nested_followup = payload.get("followup") if isinstance(payload.get("followup"), dict) else {}
    values = (payload.get("task_id"), nested_task.get("id"), nested_followup.get("task_id"))
    for value in values:
        try:
            if value not in {None, ""} and int(value) == task_id:
                return True
        except (TypeError, ValueError):
            continue
    return row.resource_type == "crm_project_customer_task" and row.resource_id == str(task_id)


def _task_has_business_history(db: Session, task: CrmProjectCustomerTask, approval_id: int) -> bool:
    if any(
        (
            task.latest_followup_id is not None,
            task.last_followup_at is not None,
            task.minimum_action_done,
            task.need_support,
            task.need_manager_support,
            task.need_boss_decision,
            task.is_blocked,
            task.status not in {"not_started", "cancelled"},
        )
    ):
        return True
    if db.scalar(select(CrmFollowup.id).where(CrmFollowup.task_id == task.id).limit(1)) is not None:
        return True
    if db.scalar(select(WorkItem.id).where(WorkItem.project_id == task.project_id, WorkItem.resource_id == str(task.id)).limit(1)) is not None:
        return True
    related_approvals = db.scalars(select(ApprovalInstance).where(ApprovalInstance.id != approval_id)).all()
    return any(_approval_references_task(row, task.id) for row in related_approvals)


def validate_withdrawn_project_reapproval_payload(
    db: Session,
    approval: ApprovalInstance,
    payload_json: dict | list | None,
) -> CrmProject | None:
    project = _withdrawn_project_for_approval(db, approval)
    if project is None:
        return None
    if not isinstance(payload_json, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Project approval payload is missing or invalid")
    project_payload = payload_json.get("project")
    task_payloads = payload_json.get("tasks") or []
    if not isinstance(project_payload, dict) or not isinstance(task_payloads, list):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Project approval payload is missing project or tasks")
    project_model = CrmProjectCreate.model_validate(project_payload)
    if project_model.project_code not in {None, "", project.project_code}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": "PROJECT_REAPPROVAL_CONFLICT", "message": "重新审批不能修改项目编号。"},
        )
    if project_model.applicant_user_id not in {None, approval.applicant_user_id, project.applicant_user_id}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": "PROJECT_REAPPROVAL_CONFLICT", "message": "重新审批不能修改项目申请人。"},
        )
    if project_model.landing_approver_user_id not in {None, approval.current_handler_user_id, project.landing_approver_user_id}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": "PROJECT_REAPPROVAL_CONFLICT", "message": "重新审批不能修改原落地审批人。"},
        )

    task_models = [CrmTaskCreate.model_validate(item) for item in task_payloads]
    customer_codes = [item.customer_code for item in task_models]
    if len(customer_codes) != len(set(customer_codes)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": "PROJECT_REAPPROVAL_CONFLICT", "message": "重新提交的客户任务存在重复客户。"},
        )
    existing_tasks = list(db.scalars(select(CrmProjectCustomerTask).where(CrmProjectCustomerTask.project_id == project.id)).all())
    requested_codes = set(customer_codes)
    protected = [
        task
        for task in existing_tasks
        if task.customer_code not in requested_codes and _task_has_business_history(db, task, approval.id)
    ]
    if protected:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "PROJECT_REAPPROVAL_CONFLICT",
                "message": "存在已有业务历史的客户任务，不能从项目申请中删除。",
                "field_errors": [
                    {"field": "tasks", "message": f"{task.task_code} / {task.customer_name_snapshot} 已有业务记录"}
                    for task in protected
                ],
            },
        )
    return project


def _reconcile_withdrawn_project(
    db: Session,
    approval: ApprovalInstance,
    operator: User,
) -> dict[str, Any]:
    payload = approval_payload_dict(approval)
    project = validate_withdrawn_project_reapproval_payload(db, approval, payload)
    if project is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Withdrawn project binding is invalid")
    project_model = CrmProjectCreate.model_validate(payload["project"])
    project_data = project_model.model_dump()
    project_before = project_audit_snapshot(project)
    for field in PROJECT_REAPPROVAL_MUTABLE_FIELDS:
        setattr(project, field, project_data.get(field))
    require_user(db, project.owner_user_id, "owner_user_id")
    require_user(db, project.project_manager_user_id, "project_manager_user_id")
    for user_id in project.participant_user_ids or []:
        require_user(db, user_id, "participant_user_ids")
    for user_id in project.progress_cc_user_ids or []:
        require_user(db, user_id, "progress_cc_user_ids")

    existing_tasks = {
        task.customer_code: task
        for task in db.scalars(select(CrmProjectCustomerTask).where(CrmProjectCustomerTask.project_id == project.id)).all()
    }
    requested_codes: set[str] = set()
    active_task_ids: list[int] = []
    added_task_ids: list[int] = []
    updated_task_ids: list[int] = []
    cancelled_task_ids: list[int] = []
    for raw_task in payload.get("tasks") or []:
        task_model = CrmTaskCreate.model_validate(raw_task)
        requested_codes.add(task_model.customer_code)
        validate_task_status(task_model.status)
        customer = require_customer(db, task_model.customer_code)
        employee_code, executor_name = task_executor_snapshot(db, task_model.executor_user_id, task_model.executor_employee_code)
        task = existing_tasks.get(task_model.customer_code)
        if task is None:
            task_code = task_model.task_code or generated_code("CRMT")
            ensure_unique_task_code(db, task_code)
            task = CrmProjectCustomerTask(
                project_id=project.id,
                task_code=task_code,
                customer_code=customer.customer_code,
                customer_name_snapshot=customer.customer_name,
                executor_user_id=task_model.executor_user_id,
                executor_employee_code=employee_code,
                executor_name_snapshot=executor_name,
                business_issue_point=task_model.business_issue_point,
                round_target=task_model.round_target,
                feedback_due_at=task_model.feedback_due_at,
                status="not_started" if task_model.status == "cancelled" else task_model.status,
            )
            db.add(task)
            db.flush()
            added_task_ids.append(task.id)
            action_type = "reapproval_add_crm_project_task"
            before_data = None
        else:
            before_data = jsonable_encoder(task_audit_snapshot(task))
            task.executor_user_id = task_model.executor_user_id
            task.executor_employee_code = employee_code
            task.executor_name_snapshot = executor_name
            task.business_issue_point = task_model.business_issue_point
            task.round_target = task_model.round_target
            task.feedback_due_at = task_model.feedback_due_at
            if task.status == "cancelled":
                task.status = "not_started" if task_model.status == "cancelled" else task_model.status
                task.is_closed = False
            updated_task_ids.append(task.id)
            action_type = "reapproval_update_crm_project_task"
        active_task_ids.append(task.id)
        write_audit_log(
            db,
            action_type=action_type,
            resource_type="crm_project_task",
            resource_id=str(task.id),
            user=operator,
            before_data=before_data,
            after_data=jsonable_encoder(task_audit_snapshot(task)),
        )

    for task in existing_tasks.values():
        if task.customer_code in requested_codes or task.status == "cancelled":
            continue
        before_data = jsonable_encoder(task_audit_snapshot(task))
        task.status = "cancelled"
        task.is_closed = True
        task.need_support = False
        task.need_manager_support = False
        task.need_boss_decision = False
        task.is_blocked = False
        cancelled_task_ids.append(task.id)
        write_audit_log(
            db,
            action_type="reapproval_cancel_unused_crm_project_task",
            resource_type="crm_project_task",
            resource_id=str(task.id),
            user=operator,
            before_data=before_data,
            after_data=jsonable_encoder(task_audit_snapshot(task)),
        )

    project.status = project.pre_withdraw_status if project.pre_withdraw_status in {"active", "paused"} else "active"
    project.approval_status = "approved"
    project.approval_withdrawn_at = None
    project.approval_withdrawn_by_user_id = None
    project.approval_withdrawn_reason = None
    project.pre_withdraw_status = None
    project.updated_by_user_id = operator.id
    refresh_project_summary(db, project.id)
    result = {
        **(approval.result_json if isinstance(approval.result_json, dict) else {}),
        "project_id": project.id,
        "project_code": project.project_code,
        "task_ids": active_task_ids,
        "reapproval_sync": {
            "added_task_ids": added_task_ids,
            "updated_task_ids": updated_task_ids,
            "cancelled_task_ids": cancelled_task_ids,
        },
    }
    approval.resource_type = "crm_project"
    approval.resource_id = str(project.id)
    approval.result_json = jsonable_encoder(result)
    write_audit_log(
        db,
        action_type="reapproval_sync_crm_project",
        resource_type="crm_project",
        resource_id=str(project.id),
        user=operator,
        before_data=jsonable_encoder(project_before),
        after_data=jsonable_encoder(project_audit_snapshot(project)),
    )
    return result


def _direct_update_matches_task(audit: AuditLog, task: CrmProjectCustomerTask) -> bool:
    after_data = audit.after_data if isinstance(audit.after_data, dict) else {}
    nested = after_data.get("audit_extra")
    audit_context = nested if isinstance(nested, dict) else after_data
    try:
        return int(audit_context.get("task_id")) == task.id
    except (TypeError, ValueError):
        return False


def generated_approval_no() -> str:
    return generated_code("APPR")


def validate_approval_type(approval_type: str) -> None:
    if approval_type not in CRM_APPROVAL_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid approval type: {approval_type}")


def validate_approval_status(status_value: str) -> None:
    if status_value not in CRM_APPROVAL_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid approval status: {status_value}")


def validate_priority(priority: str) -> None:
    if priority not in WORK_ITEM_PRIORITIES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid approval priority: {priority}")


def validate_customer_profile_followup_link(db: Session, *, data: dict[str, Any], task: CrmProjectCustomerTask) -> None:
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
            after_data = audit.after_data if isinstance(audit.after_data, dict) else {}
            audit_extra = after_data.get("audit_extra") if isinstance(after_data.get("audit_extra"), dict) else {}
            try:
                if int(audit_extra.get("task_id")) == task.id:
                    return
            except (TypeError, ValueError):
                continue
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请先保存客户基本资料，或取消该勾选。")
    linked_approval = db.get(ApprovalInstance, int(approval_id))
    if linked_approval is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="客户基本资料更新审批单不存在。")
    payload = linked_approval.payload_json if isinstance(linked_approval.payload_json, dict) else {}
    if linked_approval.approval_type != "customer_profile_update":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="关联的审批单不是客户基本资料更新审批。")
    if linked_approval.status not in PROFILE_UPDATE_ACTIVE_APPROVAL_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="客户基本资料更新审批单状态不可用于跟进闭环。")
    if str(payload.get("customer_code") or linked_approval.resource_id or "") != str(task.customer_code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="客户基本资料更新审批单与当前客户不一致。")
    payload_project_id = payload.get("project_id")
    if payload_project_id not in {None, ""}:
        try:
            if int(payload_project_id) != task.project_id:
                raise ValueError
        except (TypeError, ValueError):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="客户基本资料更新审批单与当前项目不一致。")


def validate_business_profile_followup_link(db: Session, *, data: dict[str, Any], task: CrmProjectCustomerTask) -> None:
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
        if any(_direct_update_matches_task(audit, task) for audit in direct_updates):
            return
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请先保存客户经营资料，或取消该勾选。")
    linked_approval = db.get(ApprovalInstance, int(approval_id))
    if linked_approval is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="客户经营资料更新审批单不存在。")
    payload = linked_approval.payload_json if isinstance(linked_approval.payload_json, dict) else {}
    if linked_approval.approval_type != "customer_business_profile_update":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="关联的审批单不是客户经营资料更新审批。")
    if linked_approval.status not in PROFILE_UPDATE_ACTIVE_APPROVAL_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="客户经营资料更新审批单状态不可用于跟进闭环。")
    if str(payload.get("customer_code") or linked_approval.resource_id or "") != str(task.customer_code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="客户经营资料更新审批单与当前客户不一致。")
    payload_project_id = payload.get("project_id")
    if payload_project_id not in {None, ""}:
        try:
            if int(payload_project_id) != task.project_id:
                raise ValueError
        except (TypeError, ValueError):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="客户经营资料更新审批单与当前项目不一致。")


def add_approval_event(
    db: Session,
    *,
    approval: ApprovalInstance,
    event_type: str,
    operator: User | None,
    from_status: str | None,
    to_status: str | None,
    comment: str | None = None,
    snapshot_json: dict | list | None = None,
) -> ApprovalEvent:
    event = ApprovalEvent(
        approval_id=approval.id,
        event_type=event_type,
        operator_user_id=operator.id if operator else None,
        from_status=from_status,
        to_status=to_status,
        comment=comment,
        snapshot_json=jsonable_encoder(snapshot_json) if snapshot_json is not None else None,
    )
    db.add(event)
    return event


def create_approval_instance(
    db: Session,
    *,
    approval_type: str,
    resource_type: str,
    resource_id: str,
    title: str,
    description: str | None,
    applicant: User,
    current_handler_user_id: int | None,
    priority: str,
    payload_json: dict | list | None,
    status_value: str = "draft",
    submit: bool = False,
) -> ApprovalInstance:
    validate_approval_type(approval_type)
    validate_approval_status(status_value)
    validate_priority(priority)
    require_user(db, current_handler_user_id, "current_handler_user_id")
    final_status = "submitted" if submit else status_value
    submitted_at = datetime.now(timezone.utc) if final_status == "submitted" else None
    approval = ApprovalInstance(
        approval_no=generated_approval_no(),
        approval_type=approval_type,
        resource_type=resource_type,
        resource_id=resource_id,
        title=title,
        description=description,
        applicant_user_id=applicant.id,
        current_handler_user_id=current_handler_user_id,
        status=final_status,
        priority=priority,
        payload_json=jsonable_encoder(payload_json) if payload_json is not None else None,
        submitted_at=submitted_at,
    )
    db.add(approval)
    db.flush()
    add_approval_event(
        db,
        approval=approval,
        event_type="submit" if submit else "create",
        operator=applicant,
        from_status=None,
        to_status=final_status,
        snapshot_json={"approval_type": approval_type, "resource_type": resource_type, "resource_id": resource_id},
    )
    enqueue_incremental_exception_scan_safely(
        db,
        domains=["approval"],
        target_resource_type="approval_instance",
        target_resource_id=approval.id,
    )
    return approval


def transition_approval(
    db: Session,
    *,
    approval: ApprovalInstance,
    operator: User,
    event_type: str,
    to_status: str,
    comment: str | None = None,
    payload_json: dict | list | None = None,
    result_json: dict | None = None,
    event_snapshot_json: dict | list | None = None,
) -> None:
    validate_approval_status(to_status)
    from_status = approval.status
    approval.status = to_status
    if payload_json is not None:
        approval.payload_json = jsonable_encoder(payload_json)
    if result_json is not None:
        approval.result_json = jsonable_encoder(result_json)
    if to_status in {"submitted", "under_review"} and approval.submitted_at is None:
        approval.submitted_at = datetime.now(timezone.utc)
    if to_status in TERMINAL_APPROVAL_STATUSES:
        approval.reviewed_at = approval.reviewed_at or datetime.now(timezone.utc)
        approval.closed_at = approval.closed_at or datetime.now(timezone.utc)
    add_approval_event(
        db,
        approval=approval,
        event_type=event_type,
        operator=operator,
        from_status=from_status,
        to_status=to_status,
        comment=comment,
        snapshot_json=event_snapshot_json if event_snapshot_json is not None else {"payload_json": payload_json, "result_json": result_json},
    )
    enqueue_incremental_exception_scan_safely(
        db,
        domains=["approval"],
        target_resource_type="approval_instance",
        target_resource_id=approval.id,
    )


def ensure_actionable(approval: ApprovalInstance) -> None:
    if approval.status in TERMINAL_APPROVAL_STATUSES:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Approval already closed: {approval.status}")
    if approval.status not in ACTIONABLE_APPROVAL_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Approval is not actionable: {approval.status}")


def ensure_handler(approval: ApprovalInstance, user: User) -> None:
    if approval.current_handler_user_id is not None and approval.current_handler_user_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only current handler can operate this approval")


def approval_payload_dict(approval: ApprovalInstance) -> dict[str, Any]:
    if not isinstance(approval.payload_json, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Approval payload is missing or invalid")
    return approval.payload_json


def execute_crm_project_create(db: Session, approval: ApprovalInstance, operator: User, result_json: dict[str, Any] | None = None) -> dict[str, Any]:
    if _withdrawn_project_for_approval(db, approval) is not None:
        return _reconcile_withdrawn_project(db, approval, operator)
    payload = approval_payload_dict(approval)
    project_payload = payload.get("project")
    task_payloads = payload.get("tasks") or []
    if not isinstance(project_payload, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Project approval payload missing project")
    if not isinstance(task_payloads, list):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Project approval tasks must be a list")

    project_model = CrmProjectCreate.model_validate(project_payload)
    project_data = project_model.model_dump()
    project_data.pop("assignment_mode", None)
    project_data.pop("allow_unassigned_tasks", None)
    project_code = project_data.pop("project_code") or generated_code("CRMP")
    ensure_unique_project_code(db, project_code)
    project_data["applicant_user_id"] = project_data.get("applicant_user_id") or approval.applicant_user_id
    project_data["landing_approver_user_id"] = project_data.get("landing_approver_user_id") or approval.current_handler_user_id
    project_data["owner_user_id"] = project_data.get("owner_user_id") or approval.applicant_user_id
    if project_data.get("status") in {None, "draft", "submitted"}:
        project_data["status"] = "active"
    project_data["approval_status"] = "approved"
    validate_project_status(project_data["status"])
    require_user(db, project_data.get("applicant_user_id"), "applicant_user_id")
    require_user(db, project_data.get("landing_approver_user_id"), "landing_approver_user_id")
    require_user(db, project_data.get("owner_user_id"), "owner_user_id")
    require_user(db, project_data.get("project_manager_user_id"), "project_manager_user_id")
    participant_ids = project_data.get("participant_user_ids") or []
    for participant_user_id in participant_ids:
        require_user(db, participant_user_id, "participant_user_ids")
    for cc_user_id in project_data.get("progress_cc_user_ids") or []:
        require_user(db, cc_user_id, "progress_cc_user_ids")

    seen_customers: set[str] = set()
    task_models: list[CrmTaskCreate] = []
    for raw_task in task_payloads:
        task_model = CrmTaskCreate.model_validate(raw_task)
        if task_model.customer_code in seen_customers:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"客户任务底盘存在重复客户：{task_model.customer_code}")
        seen_customers.add(task_model.customer_code)
        require_customer(db, task_model.customer_code)
        validate_task_status(task_model.status)
        task_executor_snapshot(db, task_model.executor_user_id, task_model.executor_employee_code)
        task_models.append(task_model)

    project = CrmProject(
        project_code=project_code,
        **project_data,
        current_approval_id=approval.id,
        created_by_user_id=approval.applicant_user_id,
        updated_by_user_id=operator.id,
    )
    db.add(project)
    db.flush()
    task_ids: list[int] = []
    for task_model in task_models:
        task_data = task_model.model_dump()
        task_code = task_data.pop("task_code") or generated_code("CRMT")
        ensure_unique_task_code(db, task_code)
        customer = require_customer(db, task_data["customer_code"])
        employee_code, executor_name = task_executor_snapshot(db, task_data.get("executor_user_id"), task_data.get("executor_employee_code"))
        task = CrmProjectCustomerTask(
            project_id=project.id,
            task_code=task_code,
            customer_code=customer.customer_code,
            customer_name_snapshot=customer.customer_name,
            executor_user_id=task_data.get("executor_user_id"),
            executor_employee_code=employee_code,
            executor_name_snapshot=executor_name,
            business_issue_point=task_data.get("business_issue_point"),
            round_target=task_data.get("round_target"),
            feedback_due_at=task_data.get("feedback_due_at"),
            status=task_data["status"],
        )
        db.add(task)
        db.flush()
        task_ids.append(task.id)
        write_audit_log(
            db,
            action_type="approval_create_crm_project_task",
            resource_type="crm_project_task",
            resource_id=str(task.id),
            user=operator,
            after_data=jsonable_encoder(task_audit_snapshot(task)),
        )
        enqueue_incremental_exception_scan_safely(
            db,
            domains=["crm"],
            target_resource_type="crm_project_task",
            target_resource_id=task.id,
        )
    refresh_project_summary(db, project.id)
    approval.resource_type = "crm_project"
    approval.resource_id = str(project.id)
    result = {"project_id": project.id, "project_code": project.project_code, "task_ids": task_ids, **(result_json or {})}
    approval.result_json = jsonable_encoder(result)
    write_audit_log(
        db,
        action_type="approval_create_crm_project",
        resource_type="crm_project",
        resource_id=str(project.id),
        user=operator,
        after_data=jsonable_encoder(project_audit_snapshot(project)),
    )
    return result


def _project_for_task(db: Session, task: CrmProjectCustomerTask) -> CrmProject:
    project = db.get(CrmProject, task.project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Task project not found")
    return project


def _make_work_item(
    db: Session,
    *,
    followup: CrmFollowup,
    item_type: str,
    title: str,
    detail: str | None,
    priority: str = "normal",
    assignee_user_id: int | None = None,
) -> WorkItem:
    existing = db.scalar(
        select(WorkItem)
        .where(
            WorkItem.project_id == followup.project_id,
            WorkItem.customer_code == followup.customer_code,
            WorkItem.item_type == item_type,
            WorkItem.resource_type == "crm_project_customer_task",
            WorkItem.resource_id == str(followup.task_id),
            WorkItem.status.in_(["open", "processing"]),
        )
        .order_by(WorkItem.id.desc())
    )
    if existing is not None:
        existing.source_type = "crm_followup"
        existing.source_id = str(followup.id)
        existing.title = title
        existing.detail = detail
        existing.priority = priority
        existing.assignee_user_id = assignee_user_id
        existing.due_at = followup.owner_next_followup_at or followup.next_followup_at
        return existing

    item = WorkItem(
        item_no=generated_code("WI"),
        source_type="crm_followup",
        source_id=str(followup.id),
        resource_type="crm_project_customer_task",
        resource_id=str(followup.task_id),
        project_id=followup.project_id,
        customer_code=followup.customer_code,
        item_type=item_type,
        title=title,
        detail=detail,
        priority=priority,
        status="open",
        assignee_user_id=assignee_user_id,
        due_at=followup.owner_next_followup_at or followup.next_followup_at,
    )
    db.add(item)
    return item


def execute_crm_followup_submit(db: Session, approval: ApprovalInstance, operator: User, result_json: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = approval_payload_dict(approval)
    followup_payload = payload.get("followup")
    if not isinstance(followup_payload, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Followup approval payload missing followup")
    followup_model = CrmFollowupCreate.model_validate(followup_payload)
    data = followup_model.model_dump()
    task = db.get(CrmProjectCustomerTask, data["task_id"])
    if task is None or task.project_id != data["project_id"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Task does not belong to the project")
    validate_customer_profile_followup_link(db, data=data, task=task)
    validate_business_profile_followup_link(db, data=data, task=task)
    project = _project_for_task(db, task)
    applicant = require_user(db, approval.applicant_user_id, "applicant_user_id")

    review_data = result_json or {}
    review_status = str(review_data.get("review_status") or "approved")
    validate_followup_review_status(review_status)
    followup_no = data.pop("followup_no") or generated_code("CRMF")
    ensure_unique_followup_no(db, followup_no)
    followup = CrmFollowup(
        followup_no=followup_no,
        project_id=task.project_id,
        task_id=task.id,
        customer_code=task.customer_code,
        executor_user_id=applicant.id if applicant else approval.applicant_user_id,
        executor_name_snapshot=(applicant.real_name or applicant.username) if applicant else None,
        **{key: value for key, value in data.items() if key not in {"project_id", "task_id", "review_status"}},
        review_status=review_status,
        review_result=review_data.get("review_result"),
        review_note=review_data.get("review_note"),
        owner_next_status=review_data.get("owner_next_status"),
        owner_next_action=review_data.get("owner_next_action"),
        owner_next_followup_at=review_data.get("owner_next_followup_at"),
        approval_id=approval.id,
    )
    if "valid_feedback" in review_data:
        followup.valid_feedback = bool(review_data["valid_feedback"])
    db.add(followup)
    db.flush()
    mark_reviewed(followup, operator.id)
    refresh_task_from_followups(db, task.id)
    refresh_project_summary(db, task.project_id)

    assignee_id = project.project_manager_user_id or project.owner_user_id or operator.id
    work_item_ids: list[int] = []
    support_requested = bool(followup.need_support or followup.need_manager_support or followup.need_boss_decision)
    if support_requested:
        support_type = (followup.need_type or "").strip()
        support_detail = followup.current_need or followup.blocker_note or followup.customer_feedback or followup.review_note
        item = _make_work_item(
            db,
            followup=followup,
            item_type="crm_support_needed",
            title=f"跟进需要支持：{support_type}" if support_type else "跟进需要支持",
            detail=support_detail,
            priority="high" if followup.need_boss_decision else "normal",
            assignee_user_id=assignee_id,
        )
        db.flush()
        work_item_ids.append(item.id)
    if not followup.valid_feedback:
        item = _make_work_item(db, followup=followup, item_type="invalid_feedback", title="跟进反馈无效", detail=followup.review_note, assignee_user_id=assignee_id)
        db.flush()
        work_item_ids.append(item.id)
    if not support_requested and not (followup.owner_next_action or followup.next_action):
        item = _make_work_item(db, followup=followup, item_type="missing_next_action", title="缺少下一步动作", detail=followup.review_note, assignee_user_id=assignee_id)
        db.flush()
        work_item_ids.append(item.id)
    if not (followup.owner_next_followup_at or followup.next_followup_at) and not followup.is_closed:
        item = _make_work_item(db, followup=followup, item_type="missing_next_followup_time", title="缺少下次跟进时间", detail=followup.review_note, assignee_user_id=assignee_id)
        db.flush()
        work_item_ids.append(item.id)

    approval.resource_type = "crm_followup"
    approval.resource_id = str(followup.id)
    result = {"followup_id": followup.id, "task_id": task.id, "project_id": task.project_id, "work_item_ids": work_item_ids, **review_data}
    approval.result_json = jsonable_encoder(result)
    write_audit_log(
        db,
        action_type="approval_create_crm_followup",
        resource_type="crm_followup",
        resource_id=str(followup.id),
        user=operator,
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
    return result


def _payload_int(payload: dict[str, Any], approval: ApprovalInstance, *keys: str) -> int:
    raw_value: Any = None
    for key in keys:
        if payload.get(key) not in {None, ""}:
            raw_value = payload[key]
            break
    if (raw_value is None or raw_value == "") and approval.resource_id not in {"", "pending", None}:
        raw_value = approval.resource_id
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Approval payload missing integer field: {keys[0]}") from None


def _payload_date(value: Any, field_name: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            pass
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Approval payload missing valid date field: {field_name}")


def _payload_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time())
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Approval payload missing valid datetime field: {field_name}") from None
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Approval payload missing valid datetime field: {field_name}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def execute_crm_project_extension(db: Session, approval: ApprovalInstance, operator: User, result_json: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = approval_payload_dict(approval)
    project_id = _payload_int(payload, approval, "project_id")
    project = db.get(CrmProject, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Project not found for extension approval")
    requested_due_date = _payload_date(payload.get("requested_due_date") or payload.get("due_date"), "requested_due_date")
    before = project_audit_snapshot(project)
    old_due_date = project.due_date

    project.due_date = requested_due_date
    project.current_approval_id = approval.id
    project.updated_by_user_id = operator.id
    next_step_status = payload.get("next_step_status")
    next_step_action = payload.get("next_step_action")
    next_step_followup_at = payload.get("next_step_followup_at")
    if isinstance(next_step_status, str):
        project.next_step_status = next_step_status
    if isinstance(next_step_action, str):
        project.next_step_action = next_step_action
    if next_step_followup_at:
        project.next_step_followup_at = _payload_datetime(next_step_followup_at, "next_step_followup_at")
    refresh_project_summary(db, project.id)

    result = {
        "project_id": project.id,
        "project_code": project.project_code,
        "old_due_date": old_due_date.isoformat() if old_due_date else None,
        "new_due_date": requested_due_date.isoformat(),
        "reason": payload.get("reason"),
        "progress_summary": payload.get("progress_summary"),
        **(result_json or {}),
    }
    approval.resource_type = "crm_project"
    approval.resource_id = str(project.id)
    approval.result_json = jsonable_encoder(result)
    write_audit_log(
        db,
        action_type="approval_extend_crm_project",
        resource_type="crm_project",
        resource_id=str(project.id),
        user=operator,
        before_data=jsonable_encoder(before),
        after_data=jsonable_encoder(project_audit_snapshot(project)),
    )
    return result


def execute_crm_task_extension(db: Session, approval: ApprovalInstance, operator: User, result_json: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = approval_payload_dict(approval)
    task_id = _payload_int(payload, approval, "task_id")
    task = db.get(CrmProjectCustomerTask, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Task not found for extension approval")
    requested_feedback_due_at = _payload_datetime(payload.get("requested_feedback_due_at") or payload.get("feedback_due_at"), "requested_feedback_due_at")
    before = task_audit_snapshot(task)
    old_feedback_due_at = task.feedback_due_at

    task.feedback_due_at = requested_feedback_due_at
    if task.status in {"not_started", "need_supplement"}:
        task.status = "in_progress"
    refresh_project_summary(db, task.project_id)

    result = {
        "task_id": task.id,
        "task_code": task.task_code,
        "project_id": task.project_id,
        "customer_code": task.customer_code,
        "old_feedback_due_at": old_feedback_due_at.isoformat() if old_feedback_due_at else None,
        "new_feedback_due_at": requested_feedback_due_at.isoformat(),
        "reason": payload.get("reason"),
        "progress_summary": payload.get("progress_summary"),
        **(result_json or {}),
    }
    approval.resource_type = "crm_project_customer_task"
    approval.resource_id = str(task.id)
    approval.result_json = jsonable_encoder(result)
    write_audit_log(
        db,
        action_type="approval_extend_crm_task",
        resource_type="crm_project_customer_task",
        resource_id=str(task.id),
        user=operator,
        before_data=jsonable_encoder(before),
        after_data=jsonable_encoder(task_audit_snapshot(task)),
    )
    return result


def execute_customer_business_profile_update(db: Session, approval: ApprovalInstance, operator: User, result_json: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = approval_payload_dict(approval)
    customer_code = str(payload.get("customer_code") or approval.resource_id or "").strip()
    if not customer_code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Business profile approval payload missing customer_code")
    customer = db.scalar(select(CustomerMaster).where(CustomerMaster.customer_code == customer_code))
    if customer is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Customer not found for business profile approval")
    profile_payload = payload.get("profile")
    if not isinstance(profile_payload, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Business profile approval payload missing profile")
    recommended_products = payload.get("recommended_products")
    if not isinstance(recommended_products, list):
        recommended_products = []
    profile_model = CustomerBusinessProfileUpsert.model_validate(profile_payload)
    response = apply_customer_business_profile_update(
        db,
        customer=customer,
        payload=profile_model,
        operator=operator,
        audit_action_type="approval_update_customer_business_profile",
        recommended_products=recommended_products,
        audit_extra={
            "approval_id": approval.id,
            "approval_no": approval.approval_no,
            "project_id": payload.get("project_id"),
            "task_id": payload.get("task_id"),
        },
    )
    approval.resource_type = "customer_business_profile"
    approval.resource_id = customer.customer_code
    profile = response.get("profile")
    products = response.get("products") or []
    saved_recommended_products = response.get("recommended_products") or []
    result = {
        "customer_code": customer.customer_code,
        "customer_name": customer.customer_name,
        "profile_version": getattr(profile, "version_no", None),
        "product_count": len(products),
        "recommended_product_count": len(saved_recommended_products),
        "recommended_products": saved_recommended_products,
        "changed_fields": response.get("changed_fields") or [],
        "synced_to_master": True,
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "master_resource_type": "customer_business_profile",
        "master_resource_id": customer.customer_code,
        "project_id": payload.get("project_id"),
        "task_id": payload.get("task_id"),
        **(result_json or {}),
    }
    approval.result_json = jsonable_encoder(result)
    return result


def execute_customer_profile_update(db: Session, approval: ApprovalInstance, operator: User, result_json: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = approval_payload_dict(approval)
    customer_code = str(payload.get("customer_code") or approval.resource_id or "").strip()
    if not customer_code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Customer profile approval payload missing customer_code")
    customer = db.scalar(select(CustomerMaster).where(CustomerMaster.customer_code == customer_code))
    if customer is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Customer not found for profile approval")
    change_patch = customer_profile_patch_from_change_items(payload.get("change_items"))
    profile_payload = change_patch if isinstance(payload.get("change_items"), list) else payload.get("profile")
    if not isinstance(profile_payload, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Customer profile approval payload missing profile")
    if not profile_payload:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Customer profile approval payload has no effective changes")
    profile_model = CustomerMasterUpdate.model_validate(profile_payload)
    update_result = apply_customer_master_update(
        db,
        customer=customer,
        payload=profile_model,
        operator=operator,
        audit_action_type="approval_update_customer_profile",
        audit_extra={
            "approval_id": approval.id,
            "approval_no": approval.approval_no,
            "project_id": payload.get("project_id"),
            "task_id": payload.get("task_id"),
        },
    )
    approval.resource_type = "crm_customer_profile"
    approval.resource_id = customer.customer_code
    result = {
        "customer_code": customer.customer_code,
        "customer_name": customer.customer_name,
        "changed_fields": update_result.get("changed_fields") or [],
        "synced_to_master": True,
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "master_resource_type": "customer",
        "master_resource_id": customer.customer_code,
        "project_id": payload.get("project_id"),
        "task_id": payload.get("task_id"),
        **(result_json or {}),
    }
    approval.result_json = jsonable_encoder(result)
    return result


def _crm_lead_customer_code(lead_id: int, attempt: int = 0) -> str:
    base_code = f"KHCRM{datetime.now(timezone.utc):%Y%m%d}{lead_id:06d}"
    return base_code if attempt == 0 else f"{base_code}-{attempt}"


def _assert_no_conversion_lead_duplicates(db: Session, lead: CrmLead) -> None:
    lead_candidates = find_lead_duplicate_candidates(
        db,
        lead_name=lead.lead_name,
        contact_phone=lead.contact_phone,
        exclude_lead_id=lead.id,
    )
    lead_blockers = [candidate for candidate in lead_candidates if candidate["blocking"]]
    if lead_blockers:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Blocking CRM lead duplicate prevents conversion",
                "blocking_duplicate_count": len(lead_blockers),
                "blocking_reasons": sorted({reason for candidate in lead_blockers for reason in candidate["reasons"] if reason.startswith("exact_")}),
            },
        )

def _conversion_customer_name(lead: CrmLead) -> str:
    return (lead.company_name or lead.lead_name).strip()


def _lead_user_attribution(db: Session, user_id: int | None) -> dict[str, Any] | None:
    if user_id is None:
        return None
    user = db.get(User, user_id)
    return {
        "user_id": user_id,
        "label": (user.real_name or user.username) if user is not None else "已删除账号",
    }


def _lead_conversion_attribution(db: Session, lead: CrmLead) -> dict[str, Any]:
    campaign = db.get(CrmLeadCampaign, lead.campaign_id) if lead.campaign_id is not None else None
    return {
        "source": lead.source,
        "campaign": None
        if campaign is None
        else {
            "campaign_id": campaign.id,
            "campaign_code": campaign.campaign_code,
            "campaign_name": campaign.campaign_name,
            "channel": campaign.channel,
        },
        "owner_user_id": lead.owner_user_id,
        "owner": _lead_user_attribution(db, lead.owner_user_id),
        "assigned_user_id": lead.assigned_user_id,
        "assigned_user": _lead_user_attribution(db, lead.assigned_user_id),
    }


def _create_conversion_customer(db: Session, lead: CrmLead, customer_name: str) -> CustomerMaster:
    salesperson = db.get(User, lead.assigned_user_id or lead.owner_user_id)
    for attempt in range(100):
        customer_code = _crm_lead_customer_code(lead.id, attempt)
        if db.scalar(select(CustomerMaster.id).where(CustomerMaster.customer_code == customer_code)) is not None:
            continue
        customer = CustomerMaster(
            customer_code=customer_code,
            customer_name=customer_name,
            customer_short_name=lead.lead_name if lead.company_name and lead.company_name != lead.lead_name else None,
            region=lead.region,
            address=lead.address,
            customer_group_name=lead.customer_group_name,
            salesperson_employee_code=salesperson.employee_code if salesperson else None,
            salesperson_name=(salesperson.real_name or salesperson.username) if salesperson else None,
            contact_name=lead.contact_name,
            contact_phone=lead.contact_phone,
            status="active",
            source="crm_lead_convert",
            base_remark=f"由CRM线索 {lead.lead_no} 转正。",
        )
        try:
            with db.begin_nested():
                db.add(customer)
                db.flush()
        except IntegrityError:
            continue
        return customer
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Unable to reserve a unique CRM customer code")


def conversion_payload_lead_id(approval: ApprovalInstance, payload: dict[str, Any] | None = None) -> int:
    payload = payload if payload is not None else approval_payload_dict(approval)
    if not isinstance(payload, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Conversion approval payload must be an object")
    try:
        lead_id = int(payload.get("lead_id"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Conversion approval payload missing integer lead_id") from None
    if approval.resource_type != "crm_lead" or approval.resource_id != str(lead_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Conversion approval resource binding does not match payload lead_id")
    for snapshot_key in ("lead", "before"):
        lead_snapshot = payload.get(snapshot_key)
        if not isinstance(lead_snapshot, dict):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Conversion approval payload missing {snapshot_key} lead snapshot")
        try:
            snapshot_lead_id = int(lead_snapshot.get("id"))
        except (TypeError, ValueError):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Conversion approval {snapshot_key} lead snapshot missing integer id") from None
        if snapshot_lead_id != lead_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Conversion approval {snapshot_key} lead snapshot does not match payload lead_id")
    return lead_id


def execute_crm_lead_convert(db: Session, approval: ApprovalInstance, operator: User, result_json: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = approval_payload_dict(approval)
    lead_id = conversion_payload_lead_id(approval, payload)
    lead = db.scalar(
        select(CrmLead)
        .where(CrmLead.id == lead_id)
        .execution_options(populate_existing=True)
    )
    if lead is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CRM lead not found for conversion approval")

    acquire_lead_duplicate_locks(db, lead_name=lead.lead_name, contact_phone=lead.contact_phone)
    lead = db.scalar(
        select(CrmLead)
        .where(CrmLead.id == lead_id)
        .execution_options(populate_existing=True)
    )
    if lead is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CRM lead not found for conversion approval")
    if lead.status == "converted":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="CRM lead has already been converted")
    if lead.status != "conversion_pending":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"CRM lead is not pending conversion: {lead.status}")

    conversion_guard = payload.get("conversion_guard")
    if isinstance(conversion_guard, dict):
        changed_fields = changed_lead_conversion_guard_fields(lead, conversion_guard)
        if changed_fields:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": "线索资料在审批期间发生变化，请退回申请人重新提交转正审批",
                    "changed_fields": changed_fields,
                },
            )

    _assert_no_conversion_lead_duplicates(db, lead)
    customer_name = _conversion_customer_name(lead)
    assert_customer_identity_available(
        db,
        customer_name=customer_name,
        contact_phone=lead.contact_phone,
        conflict_message="Blocking customer master duplicate prevents conversion",
    )
    before = lead_audit_snapshot(db, lead)
    customer = _create_conversion_customer(db, lead, customer_name)
    synced_at = datetime.now(timezone.utc)
    lead.status = "converted"
    lead.converted_customer_code = customer.customer_code
    lead.converted_at = synced_at
    lead.converted_by_user_id = operator.id
    lead.current_approval_id = approval.id
    lead.updated_by_user_id = operator.id
    db.flush()

    attribution = _lead_conversion_attribution(db, lead)
    project_prefill = {
        "customer_code": customer.customer_code,
        "customer_name": customer.customer_name,
        "project_name": f"{customer.customer_name}客户开发项目",
        "project_type": "客户开发",
        "customer_scope_note": f"由CRM线索 {lead.lead_no} 转正后预填，需人工确认创建项目。",
        "business_line": lead.business_line,
        "owner_user_id": lead.assigned_user_id or lead.owner_user_id,
        "source_lead_id": lead.id,
        "source_lead_no": lead.lead_no,
        "source": attribution["source"],
        "campaign": attribution["campaign"],
        "attribution": attribution,
    }
    result = {
        **(result_json or {}),
        "lead_id": lead.id,
        "lead_no": lead.lead_no,
        "customer_code": customer.customer_code,
        "customer_name": customer.customer_name,
        "master_resource_type": "customer",
        "master_resource_id": customer.customer_code,
        "synced_at": synced_at.isoformat(),
        "attribution": attribution,
        "project_prefill": project_prefill,
    }
    # Keep the approval bound to the lead for scope checks and history. The
    # created customer is linked through the explicit master/result fields.
    approval.result_json = jsonable_encoder(result)
    write_audit_log(
        db,
        action_type="approve_crm_lead_convert",
        resource_type="crm_lead",
        resource_id=str(lead.id),
        user=operator,
        before_data=jsonable_encoder({"lead": before}),
        after_data=jsonable_encoder(
            {
                "lead": lead_audit_snapshot(db, lead),
                "customer": customer_audit_snapshot(customer),
                "attribution": attribution,
                "project_prefill": project_prefill,
            }
        ),
    )
    return result


def execute_customer_tag_change(
    db: Session,
    approval: ApprovalInstance,
    operator: User,
    result_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from app.models import CustomerTagChangeItem, CustomerTagChangeRequest
    from app.services.customer_tagging_service import review_change_request

    try:
        request_id = int(approval.resource_id)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Customer tag request ID is invalid") from exc
    request_row = db.get(CustomerTagChangeRequest, request_id)
    if request_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer tag request not found")
    pending_items = list(
        db.scalars(
            select(CustomerTagChangeItem).where(
                CustomerTagChangeItem.request_id == request_row.id,
                CustomerTagChangeItem.status.in_(["pending", "need_supplement"]),
            )
        ).all()
    )
    decisions = [
        {"item_id": item.id, "decision": "approved", "comment": (result_json or {}).get("review_comment")}
        for item in pending_items
    ]
    if not decisions:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Customer tag request has no pending items")
    review_change_request(
        db,
        request_row=request_row,
        decisions=decisions,
        reviewer=operator,
        comment=(result_json or {}).get("review_comment"),
        manage_approval=False,
    )
    return {"request_id": request_row.id, "request_status": request_row.status, "decisions": decisions}


ApprovalExecutor = Callable[[Session, ApprovalInstance, User, dict[str, Any] | None], dict[str, Any]]

APPROVAL_EXECUTORS: dict[str, ApprovalExecutor] = {
    "crm_project_create": execute_crm_project_create,
    "crm_followup_submit": execute_crm_followup_submit,
    "customer_business_profile_update": execute_customer_business_profile_update,
    "customer_profile_update": execute_customer_profile_update,
    "crm_project_extension": execute_crm_project_extension,
    "crm_task_extension": execute_crm_task_extension,
    "crm_lead_convert": execute_crm_lead_convert,
    "customer_tag_change": execute_customer_tag_change,
}


def execute_approval(db: Session, approval: ApprovalInstance, operator: User, result_json: dict[str, Any] | None = None) -> dict[str, Any]:
    executor = APPROVAL_EXECUTORS.get(approval.approval_type)
    if executor is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"No executor for approval type: {approval.approval_type}")
    return executor(db, approval, operator, result_json)

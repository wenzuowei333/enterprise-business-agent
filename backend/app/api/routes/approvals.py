import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_crm_permission
from app.core.config import settings
from app.core.database import get_db
from app.models import ApprovalAttachment, ApprovalEvent, ApprovalInstance, CrmFollowup, CrmLead, CrmProject, CrmProjectCustomerTask, CustomerBusinessProfile, CustomerMaster, User, WorkItem
from app.schemas.crm import ApprovalActionRequest, ApprovalAttachmentPublic, ApprovalCreate, ApprovalDetail, ApprovalDraftUpdate, ApprovalEventPublic, ApprovalInstancePublic, ApprovalPage, ApprovalReturnFeedback, ApprovalWithdrawalPreview, ApprovalWithdrawalRequest
from app.services.access_control_service import serialize_with_field_rules
from app.services.approval_access_service import (
    LEAD_CONVERSION_APPROVAL_TYPE,
    lead_conversion_visibility_clause,
    visible_approval_or_404,
    visible_approvals_stmt,
)
from app.services.approval_service import (
    add_approval_event,
    conversion_payload_lead_id,
    create_approval_instance,
    ensure_actionable,
    ensure_handler,
    execute_approval,
    transition_approval,
    validate_withdrawn_project_reapproval_payload,
    validate_priority,
)
from app.services.audit_service import write_audit_log
from app.services.customer_business_profile_service import customer_business_products
from app.services.customer_master_service import customer_audit_snapshot
from app.services.crm_access_service import crm_lead_scope_filter
from app.services.crm_project_service import ensure_project_operable, project_audit_snapshot, require_user
from app.services.exception_center_service import enqueue_incremental_exception_scan_safely
from app.services.permission_service import has_permission

router = APIRouter(prefix="/approvals", tags=["approvals"])
MAX_APPROVAL_ATTACHMENT_BYTES = 20 * 1024 * 1024
FIXED_CRM_APPROVAL_HANDLERS = {
    "crm_project_create": ("admin", "项目申请审批人"),
    "crm_lead_convert": ("admin", "线索转正审批人"),
}
RETURN_EVENT_BY_STATUS = {
    "need_supplement": "supplement_request",
    "rejected": "reject",
}
PROJECT_WITHDRAWAL_WINDOW = timedelta(hours=24)
PROJECT_RELATED_APPROVAL_TYPES = {
    "crm_followup_submit",
    "customer_business_profile_update",
    "customer_profile_update",
    "crm_project_extension",
    "crm_task_extension",
    "crm_project_close",
}


def _api_conflict(error_code: str, message: str, *, resource_type: str = "approval_instance", resource_id: str | None = None) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "error_code": error_code,
            "message": message,
            "module": "crm",
            "resource_type": resource_type,
            "resource_id": resource_id,
            "retryable": False,
        },
    )


def _safe_limit(limit: int) -> int:
    return max(1, min(limit, 100))


def _safe_offset(offset: int) -> int:
    return max(0, offset)


def _count_stmt(db: Session, stmt: Select[tuple[Any, ...]]) -> int:
    return db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0


def _int_value(value: Any) -> int | None:
    try:
        return int(value) if value not in {None, ""} else None
    except (TypeError, ValueError):
        return None


def _approval_bound_project(db: Session, approval: ApprovalInstance) -> CrmProject | None:
    payload = approval.payload_json if isinstance(approval.payload_json, dict) else {}
    result = approval.result_json if isinstance(approval.result_json, dict) else {}
    nested_project = payload.get("project") if isinstance(payload.get("project"), dict) else {}
    nested_task = payload.get("task") if isinstance(payload.get("task"), dict) else {}
    nested_followup = payload.get("followup") if isinstance(payload.get("followup"), dict) else {}
    project_id = next(
        (
            value
            for value in (
                _int_value(result.get("project_id")),
                _int_value(payload.get("project_id")),
                _int_value(nested_project.get("id")),
                _int_value(nested_task.get("project_id")),
                _int_value(nested_followup.get("project_id")),
                _int_value(approval.resource_id) if approval.resource_type == "crm_project" else None,
            )
            if value is not None
        ),
        None,
    )
    if project_id is not None:
        return db.get(CrmProject, project_id)
    task_id = next(
        (
            value
            for value in (
                _int_value(payload.get("task_id")),
                _int_value(nested_task.get("id")),
                _int_value(nested_followup.get("task_id")),
                _int_value(approval.resource_id) if approval.resource_type == "crm_project_customer_task" else None,
            )
            if value is not None
        ),
        None,
    )
    task = db.get(CrmProjectCustomerTask, task_id) if task_id is not None else None
    return db.get(CrmProject, task.project_id) if task is not None else None


def _ensure_bound_project_operable(db: Session, approval: ApprovalInstance) -> None:
    if approval.approval_type not in PROJECT_RELATED_APPROVAL_TYPES:
        return
    project = _approval_bound_project(db, approval)
    if project is not None:
        ensure_project_operable(project)


def _project_withdrawal_impact(db: Session, project: CrmProject) -> dict[str, int]:
    task_ids = list(db.scalars(select(CrmProjectCustomerTask.id).where(CrmProjectCustomerTask.project_id == project.id)).all())
    approvals = list(
        db.scalars(
            select(ApprovalInstance).where(
                ApprovalInstance.status.in_(["draft", "submitted", "under_review", "need_supplement"]),
                ApprovalInstance.id != project.current_approval_id,
            )
        ).all()
    )
    pending_approval_count = sum(
        1
        for row in approvals
        if (bound_project := _approval_bound_project(db, row)) is not None and bound_project.id == project.id
    )
    return {
        "tasks": len(task_ids),
        "followups": _count_stmt(db, select(CrmFollowup.id).where(CrmFollowup.project_id == project.id)),
        "work_items": _count_stmt(db, select(WorkItem.id).where(WorkItem.project_id == project.id)),
        "pending_approvals": pending_approval_count,
    }


def _withdrawal_preview(
    db: Session,
    approval: ApprovalInstance,
    current_user: User,
    *,
    now: datetime | None = None,
) -> ApprovalWithdrawalPreview:
    current_time = now or datetime.now(timezone.utc)
    blockers: list[str] = []
    project = _approval_bound_project(db, approval)
    is_override = has_permission(db, current_user, "crm_project.approval_withdraw_override")
    has_regular_permission = has_permission(db, current_user, "crm_project.approval_withdraw")
    completed_at = approval.closed_at or approval.reviewed_at
    if completed_at is not None and completed_at.tzinfo is None:
        completed_at = completed_at.replace(tzinfo=timezone.utc)
    deadline = completed_at + PROJECT_WITHDRAWAL_WINDOW if completed_at else None

    if not settings.crm_project_approval_withdraw_enabled:
        blockers.append("撤回审核功能尚未启用")
    if approval.approval_type != "crm_project_create":
        blockers.append("仅项目申请审批支持撤回审核")
    if approval.status != "completed":
        blockers.append("审批单不是已通过状态")
    if project is None:
        blockers.append("审批单未绑定有效项目")
    elif project.current_approval_id != approval.id:
        blockers.append("项目当前审批单与本审批单不一致")
    elif project.approval_withdrawn_at is not None:
        blockers.append("项目审批已经撤回")
    elif project.approval_status != "approved":
        blockers.append("项目审批状态不是已通过")
    elif project.status in {"closed", "cancelled"}:
        blockers.append("已关闭或已取消项目不能撤回审核")

    if not is_override:
        if not has_regular_permission or approval.current_handler_user_id != current_user.id:
            blockers.append("只有原审批人或管理员可以撤回审核")
        elif deadline is None:
            blockers.append("审批完成时间缺失，不能计算撤回时限")
        elif current_time > deadline:
            blockers.append("原审批人的24小时撤回时限已过")

    state = "withdrawn" if project is not None and project.approval_withdrawn_at is not None else "available" if not blockers else "unavailable"
    return ApprovalWithdrawalPreview(
        approval_id=approval.id,
        project_id=project.id if project else None,
        state=state,
        can_withdraw=not blockers,
        deadline=deadline,
        is_override=is_override,
        blockers=blockers,
        impact_counts=_project_withdrawal_impact(db, project) if project else {},
        project_status=project.status if project else None,
    )


def _approval_or_404(db: Session, approval_id: int) -> ApprovalInstance:
    approval = db.get(ApprovalInstance, approval_id)
    if approval is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found")
    return approval


def _fixed_crm_handler_id(db: Session, approval_type: str) -> int | None:
    handler_config = FIXED_CRM_APPROVAL_HANDLERS.get(approval_type)
    if handler_config is None:
        return None
    username, label = handler_config
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
    return user.id


def _active_project_owner_id(db: Session, project: CrmProject, label: str) -> int:
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
    return user.id


def _project_owner_handler_id_from_payload(db: Session, approval_type: str, payload_json: Any) -> int | None:
    if approval_type not in {"crm_followup_submit", "customer_business_profile_update", "customer_profile_update"}:
        return None
    if not isinstance(payload_json, dict):
        return None
    payload = payload_json.get("followup") if approval_type == "crm_followup_submit" else payload_json
    if not isinstance(payload, dict):
        return None
    project_id = payload.get("project_id")
    task_id = payload.get("task_id")
    project: CrmProject | None = None
    if project_id:
        project = db.get(CrmProject, int(project_id))
    elif task_id:
        task = db.get(CrmProjectCustomerTask, int(task_id))
        if task is not None:
            project = db.get(CrmProject, task.project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="项目不存在，无法提交审批")
    label = "跟进审批" if approval_type == "crm_followup_submit" else "资料更新审批"
    return _active_project_owner_id(db, project, label)


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
        "version_no": profile.version_no,
    })


def _approval_payload_change_items(payload: dict[str, Any], *, profile_key: str, before_key: str) -> list[dict[str, Any]]:
    raw_items = payload.get("change_items")
    if isinstance(raw_items, list) and raw_items:
        return [item for item in raw_items if isinstance(item, dict)]
    profile = payload.get(profile_key)
    if not isinstance(profile, dict):
        return []
    before = payload.get(before_key) if isinstance(payload.get(before_key), dict) else {}
    items: list[dict[str, Any]] = []
    for field, after_value in profile.items():
        items.append({
            "field": str(field),
            "label": str(field),
            "before": before.get(field) if isinstance(before, dict) else None,
            "after": after_value,
        })
    return items


def _approval_user_labels(db: Session, user_ids: list[Any]) -> dict[int, str]:
    normalized_ids: set[int] = set()
    for value in user_ids:
        try:
            if value is not None:
                normalized_ids.add(int(value))
        except (TypeError, ValueError):
            continue
    if not normalized_ids:
        return {}
    return {
        user.id: _format_user_label(user) or user.username
        for user in db.scalars(select(User).where(User.id.in_(normalized_ids))).all()
    }


def _project_approval_business_summary(
    db: Session,
    approval: ApprovalInstance,
    payload: dict[str, Any],
    result: dict[str, Any],
    current_user: User | None = None,
) -> dict[str, Any]:
    project_payload = payload.get("project") if isinstance(payload.get("project"), dict) else payload
    task_payloads = payload.get("tasks") if isinstance(payload.get("tasks"), list) else []
    project_id = result.get("project_id")
    if project_id is None and approval.resource_type == "crm_project" and approval.resource_id not in {"", "pending"}:
        try:
            project_id = int(approval.resource_id)
        except (TypeError, ValueError):
            project_id = None
    project = db.get(CrmProject, int(project_id)) if project_id else None

    applicant_id = project_payload.get("applicant_user_id") or approval.applicant_user_id
    landing_approver_id = project_payload.get("landing_approver_user_id") or approval.current_handler_user_id
    detail_approver_id = project_payload.get("owner_user_id")
    manager_id = project_payload.get("project_manager_user_id")
    participant_ids = project_payload.get("participant_user_ids") if isinstance(project_payload.get("participant_user_ids"), list) else []
    cc_ids = project_payload.get("progress_cc_user_ids") if isinstance(project_payload.get("progress_cc_user_ids"), list) else []
    executor_ids = [item.get("executor_user_id") for item in task_payloads if isinstance(item, dict)]
    user_labels = _approval_user_labels(
        db,
        [applicant_id, landing_approver_id, detail_approver_id, manager_id, *participant_ids, *cc_ids, *executor_ids],
    )
    customer_codes = {
        str(item.get("customer_code")).strip()
        for item in task_payloads
        if isinstance(item, dict) and item.get("customer_code")
    }
    customer_names = {
        code: name
        for code, name in db.execute(
            select(CustomerMaster.customer_code, CustomerMaster.customer_name).where(CustomerMaster.customer_code.in_(customer_codes))
        ).all()
    } if customer_codes else {}
    tasks: list[dict[str, Any]] = []
    for item in task_payloads:
        if not isinstance(item, dict):
            continue
        customer_code = str(item.get("customer_code") or "").strip()
        executor_id = item.get("executor_user_id")
        tasks.append({
            "customer_code": customer_code or None,
            "customer_name": customer_names.get(customer_code) or item.get("customer_name_snapshot") or customer_code or None,
            "executor": user_labels.get(int(executor_id)) if executor_id else item.get("executor_name_snapshot"),
            "business_issue_point": item.get("business_issue_point"),
            "round_target": item.get("round_target"),
            "feedback_due_at": item.get("feedback_due_at"),
            "status": item.get("status"),
        })
    project_data = {
        "project_id": getattr(project, "id", None) or project_id,
        "project_code": getattr(project, "project_code", None) or result.get("project_code") or project_payload.get("project_code"),
        "project_name": getattr(project, "project_name", None) or project_payload.get("project_name"),
        "project_type": getattr(project, "project_type", None) or project_payload.get("project_type"),
        "purpose": getattr(project, "purpose", None) or project_payload.get("purpose"),
        "business_line": getattr(project, "business_line", None) or project_payload.get("business_line"),
        "start_date": getattr(project, "start_date", None) or project_payload.get("start_date"),
        "due_date": getattr(project, "due_date", None) or project_payload.get("due_date"),
        "minimum_action": getattr(project, "minimum_action", None) or project_payload.get("minimum_action"),
        "closure_standard": getattr(project, "closure_standard", None) or project_payload.get("closure_standard"),
        "status": getattr(project, "status", None) or project_payload.get("status"),
    }
    withdrawal_preview = _withdrawal_preview(db, approval, current_user) if current_user is not None else None
    return {
        "kind": approval.approval_type,
        "project": jsonable_encoder(project_data),
        "people": {
            "applicant": user_labels.get(int(applicant_id)) if applicant_id else None,
            "landing_approver": user_labels.get(int(landing_approver_id)) if landing_approver_id else None,
            "detail_approver": user_labels.get(int(detail_approver_id)) if detail_approver_id else None,
            "project_manager": user_labels.get(int(manager_id)) if manager_id else None,
            "frontline": [user_labels[user_id] for user_id in participant_ids if user_id in user_labels],
            "progress_cc": [user_labels[user_id] for user_id in cc_ids if user_id in user_labels],
        },
        "tasks": tasks,
        "task_count": len(tasks),
        "review_withdrawal": (
            {
                **withdrawal_preview.model_dump(),
                "reason": project.approval_withdrawn_reason if project else None,
                "withdrawn_at": project.approval_withdrawn_at if project else None,
                "withdrawn_by_user_id": project.approval_withdrawn_by_user_id if project else None,
                "withdrawn_by_user_label": (
                    _approval_user_labels(db, [project.approval_withdrawn_by_user_id]).get(project.approval_withdrawn_by_user_id)
                    if project and project.approval_withdrawn_by_user_id
                    else None
                ),
            }
            if withdrawal_preview is not None
            else None
        ),
    }


def _followup_approval_business_summary(db: Session, approval: ApprovalInstance, payload: dict[str, Any]) -> dict[str, Any]:
    followup = payload.get("followup") if isinstance(payload.get("followup"), dict) else payload
    task_id = followup.get("task_id")
    project_id = followup.get("project_id")
    task = db.get(CrmProjectCustomerTask, int(task_id)) if task_id else None
    if task is not None:
        project_id = task.project_id
    project = db.get(CrmProject, int(project_id)) if project_id else None
    customer_code = str(followup.get("customer_code") or getattr(task, "customer_code", None) or "").strip()
    customer = db.scalar(select(CustomerMaster).where(CustomerMaster.customer_code == customer_code)) if customer_code else None
    user_labels = _approval_user_labels(db, [approval.applicant_user_id, approval.current_handler_user_id])
    return {
        "kind": approval.approval_type,
        "customer_code": customer_code or None,
        "customer_name": getattr(customer, "customer_name", None) or getattr(task, "customer_name_snapshot", None) or customer_code or None,
        "project_id": getattr(project, "id", None) or project_id,
        "project_code": getattr(project, "project_code", None),
        "project_name": getattr(project, "project_name", None),
        "task_id": getattr(task, "id", None) or task_id,
        "task_code": getattr(task, "task_code", None),
        "applicant": user_labels.get(approval.applicant_user_id),
        "handler": user_labels.get(approval.current_handler_user_id),
        "followup": jsonable_encoder(followup),
    }


def _generic_crm_approval_business_summary(db: Session, approval: ApprovalInstance, payload: dict[str, Any]) -> dict[str, Any]:
    project_id = payload.get("project_id")
    task_id = payload.get("task_id")
    task = db.get(CrmProjectCustomerTask, int(task_id)) if task_id else None
    if task is not None:
        project_id = task.project_id
    project = db.get(CrmProject, int(project_id)) if project_id else None
    return {
        "kind": approval.approval_type,
        "project_id": getattr(project, "id", None) or project_id,
        "project_code": getattr(project, "project_code", None),
        "project_name": getattr(project, "project_name", None),
        "task_id": getattr(task, "id", None) or task_id,
        "task_code": getattr(task, "task_code", None),
        "customer_code": getattr(task, "customer_code", None) or payload.get("customer_code"),
        "customer_name": getattr(task, "customer_name_snapshot", None),
        "requested_due_date": payload.get("requested_due_date") or payload.get("requested_feedback_due_at"),
        "reason": payload.get("reason") or approval.description,
        "progress_summary": payload.get("progress_summary"),
    }


def _mask_phone(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    if text == "******":
        return text
    if len(text) >= 7:
        return f"{text[:3]}****{text[-4:]}"
    return "******"


def _mask_contact_name(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return f"{text[0]}***"


def _lead_conversion_public_payload(db: Session, approval: ApprovalInstance, current_user: User | None) -> dict[str, Any]:
    payload = approval.payload_json if isinstance(approval.payload_json, dict) else {}
    snapshot = payload.get("lead") if isinstance(payload.get("lead"), dict) else {}
    lead_id = payload.get("lead_id") or snapshot.get("id") or approval.resource_id
    try:
        lead = db.get(CrmLead, int(lead_id))
    except (TypeError, ValueError):
        lead = None
    lead_data = serialize_with_field_rules(db, current_user, "crm_lead", lead) if lead is not None and current_user is not None else snapshot
    before = payload.get("before") if isinstance(payload.get("before"), dict) else {}
    after = payload.get("after") if isinstance(payload.get("after"), dict) else {}
    return {
        "kind": LEAD_CONVERSION_APPROVAL_TYPE,
        "lead_id": lead_id,
        "lead": {
            "lead_no": lead_data.get("lead_no"),
            "lead_name": lead_data.get("lead_name"),
            "company_name": lead_data.get("company_name"),
            "contact_name": _mask_contact_name(lead_data.get("contact_name")),
            "contact_phone": _mask_phone(lead_data.get("contact_phone")),
            "source": lead_data.get("source"),
            "region": lead_data.get("region"),
            "address": lead_data.get("address"),
            "customer_group_name": lead_data.get("customer_group_name"),
            "business_line": lead_data.get("business_line"),
            "status": lead_data.get("status") or before.get("status"),
        },
        "conversion": {
            "from_status": before.get("status"),
            "to_status": after.get("status"),
        },
    }


def _lead_conversion_public_result(approval: ApprovalInstance) -> dict[str, Any] | None:
    result = approval.result_json if isinstance(approval.result_json, dict) else None
    if result is None:
        return None
    public_result = {
        key: result.get(key)
        for key in ("customer_code", "customer_name", "master_resource_type", "master_resource_id", "synced_at")
        if key in result
    }
    project_prefill = result.get("project_prefill")
    if isinstance(project_prefill, dict):
        public_result["project_prefill"] = {
            key: project_prefill.get(key)
            for key in (
                "customer_code",
                "customer_name",
                "project_name",
                "project_type",
                "customer_scope_note",
                "business_line",
                "source_lead_no",
                "source",
            )
            if key in project_prefill
        }
        campaign = project_prefill.get("campaign")
        if isinstance(campaign, dict):
            public_result["project_prefill"]["campaign"] = {
                key: campaign.get(key)
                for key in ("campaign_code", "campaign_name", "channel")
                if key in campaign
            }
    attribution = result.get("attribution")
    if isinstance(attribution, dict):
        public_result["attribution"] = {
            "source": attribution.get("source"),
            "campaign": None,
            "owner_label": (attribution.get("owner") or {}).get("label") if isinstance(attribution.get("owner"), dict) else None,
            "assigned_user_label": (attribution.get("assigned_user") or {}).get("label") if isinstance(attribution.get("assigned_user"), dict) else None,
        }
        campaign = attribution.get("campaign")
        if isinstance(campaign, dict):
            public_result["attribution"]["campaign"] = {
                key: campaign.get(key)
                for key in ("campaign_code", "campaign_name", "channel")
                if key in campaign
            }
    return public_result


def _approval_business_summary(db: Session, approval: ApprovalInstance, current_user: User | None = None) -> dict[str, Any] | None:
    if approval.approval_type == LEAD_CONVERSION_APPROVAL_TYPE:
        payload = _lead_conversion_public_payload(db, approval, current_user)
        result = _lead_conversion_public_result(approval) or {}
        lead = payload["lead"]
        return {
            "kind": LEAD_CONVERSION_APPROVAL_TYPE,
            "lead_id": payload.get("lead_id"),
            "lead_no": lead.get("lead_no"),
            "lead_name": lead.get("lead_name"),
            "company_name": lead.get("company_name"),
            "contact_name": lead.get("contact_name"),
            "contact_phone": lead.get("contact_phone"),
            "conversion": payload.get("conversion"),
            "customer_code": result.get("customer_code"),
            "customer_name": result.get("customer_name"),
            "master_resource_type": result.get("master_resource_type"),
            "master_resource_id": result.get("master_resource_id"),
            "synced_at": result.get("synced_at"),
            "sync_status": "synced" if result.get("customer_code") else "not_synced" if approval.status in {"rejected", "cancelled"} else "pending",
        }
    payload = approval.payload_json if isinstance(approval.payload_json, dict) else {}
    result = approval.result_json if isinstance(approval.result_json, dict) else {}
    if approval.approval_type == "customer_tag_change":
        customer_code = str(payload.get("customer_code") or "").strip()
        customer_name = db.scalar(select(CustomerMaster.customer_name).where(CustomerMaster.customer_code == customer_code)) if customer_code else None
        return {
            "kind": approval.approval_type,
            "request_id": payload.get("request_id"),
            "request_no": payload.get("request_no"),
            "customer_code": customer_code or None,
            "customer_name": customer_name,
            "items": payload.get("items") if isinstance(payload.get("items"), list) else [],
            "request_status": result.get("request_status") or approval.status,
        }
    if approval.approval_type == "crm_project_create":
        return _project_approval_business_summary(db, approval, payload, result, current_user)
    if approval.approval_type == "crm_followup_submit":
        return _followup_approval_business_summary(db, approval, payload)
    if approval.approval_type not in {"customer_profile_update", "customer_business_profile_update"}:
        return _generic_crm_approval_business_summary(db, approval, payload)
    customer_code = str(payload.get("customer_code") or approval.resource_id or "").strip()
    customer = db.scalar(select(CustomerMaster).where(CustomerMaster.customer_code == customer_code)) if customer_code else None
    current_master: dict[str, Any] | None = None
    if approval.approval_type == "customer_profile_update" and customer is not None:
        current_master = customer_audit_snapshot(customer)
    elif approval.approval_type == "customer_business_profile_update" and customer is not None:
        profile = db.scalar(select(CustomerBusinessProfile).where(CustomerBusinessProfile.customer_code == customer.customer_code))
        current_master = {
            "profile": _business_profile_snapshot(profile),
            "products": jsonable_encoder([
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
                for product in customer_business_products(db, customer.customer_code)
            ]),
        }
    synced = bool(result.get("synced_to_master"))
    if synced:
        sync_status = "synced"
    elif approval.status in {"rejected", "cancelled"}:
        sync_status = "not_synced"
    else:
        sync_status = "pending"
    profile_key = "profile"
    before_key = "before_business_profile" if approval.approval_type == "customer_business_profile_update" else "before_profile"
    change_items = _approval_payload_change_items(payload, profile_key=profile_key, before_key=before_key)
    return {
        "kind": approval.approval_type,
        "customer_code": customer_code or None,
        "customer_name": payload.get("customer_name") or getattr(customer, "customer_name", None),
        "project_id": payload.get("project_id"),
        "project_name": payload.get("project_name"),
        "task_id": payload.get("task_id"),
        "task_code": payload.get("task_code"),
        "change_items": change_items,
        "changed_fields": result.get("changed_fields") if isinstance(result.get("changed_fields"), list) else [],
        "sync_status": sync_status,
        "synced_to_master": synced,
        "synced_at": result.get("synced_at"),
        "master_resource_type": result.get("master_resource_type"),
        "master_resource_id": result.get("master_resource_id"),
        "current_master": current_master,
        "has_before_snapshot": "before_profile" in payload or "before_business_profile" in payload,
    }


def _crm_handler_id(db: Session, approval_type: str, payload_json: Any) -> int | None:
    fixed_handler_id = _fixed_crm_handler_id(db, approval_type)
    if fixed_handler_id is not None:
        return fixed_handler_id
    return _project_owner_handler_id_from_payload(db, approval_type, payload_json)


def _format_user_label(user: User | None) -> str | None:
    if user is None:
        return None
    display_name = (user.real_name or "").strip() or user.username
    return f"{display_name} / {user.username}"


def _return_feedback_from_events(
    approval: ApprovalInstance,
    events: list[ApprovalEvent],
    user_labels: dict[int, str],
) -> ApprovalReturnFeedback | None:
    expected_event_type = RETURN_EVENT_BY_STATUS.get(approval.status)
    if expected_event_type is None:
        return None
    event = next((item for item in reversed(events) if item.event_type == expected_event_type), None)
    if event is None:
        return None
    return ApprovalReturnFeedback(
        event_type=expected_event_type,
        comment=event.comment,
        operator_user_id=event.operator_user_id,
        operator_user_label=user_labels.get(event.operator_user_id) if event.operator_user_id else None,
        created_at=event.created_at,
    )


def _approval_return_feedback_by_id(
    db: Session,
    approvals: list[ApprovalInstance],
) -> dict[int, ApprovalReturnFeedback]:
    eligible = {approval.id: approval for approval in approvals if approval.status in RETURN_EVENT_BY_STATUS}
    if not eligible:
        return {}
    events = list(
        db.scalars(
            select(ApprovalEvent)
            .where(
                ApprovalEvent.approval_id.in_(eligible),
                ApprovalEvent.event_type.in_(RETURN_EVENT_BY_STATUS.values()),
            )
            .order_by(ApprovalEvent.id.desc())
        ).all()
    )
    latest_events: dict[int, ApprovalEvent] = {}
    for event in events:
        approval = eligible.get(event.approval_id)
        if (
            approval is not None
            and event.event_type == RETURN_EVENT_BY_STATUS[approval.status]
            and event.approval_id not in latest_events
        ):
            latest_events[event.approval_id] = event
    user_labels = _approval_user_labels(
        db,
        [event.operator_user_id for event in latest_events.values()],
    )
    return {
        approval_id: ApprovalReturnFeedback(
            event_type=event.event_type,
            comment=event.comment,
            operator_user_id=event.operator_user_id,
            operator_user_label=user_labels.get(event.operator_user_id) if event.operator_user_id else None,
            created_at=event.created_at,
        )
        for approval_id, event in latest_events.items()
    }


def _approval_public(
    db: Session,
    approval: ApprovalInstance,
    current_user: User | None = None,
    latest_return_feedback: ApprovalReturnFeedback | None = None,
) -> ApprovalInstancePublic:
    user_ids = [user_id for user_id in [approval.applicant_user_id, approval.current_handler_user_id] if user_id is not None]
    users_by_id = {
        user.id: user
        for user in db.scalars(select(User).where(User.id.in_(user_ids))).all()
    } if user_ids else {}
    updates: dict[str, Any] = {
        "applicant_user_label": _format_user_label(users_by_id.get(approval.applicant_user_id)),
        "current_handler_user_label": _format_user_label(users_by_id.get(approval.current_handler_user_id)),
        "business_summary": _approval_business_summary(db, approval, current_user),
        "latest_return_feedback": latest_return_feedback,
    }
    if approval.approval_type == LEAD_CONVERSION_APPROVAL_TYPE:
        updates["payload_json"] = _lead_conversion_public_payload(db, approval, current_user)
        updates["result_json"] = _lead_conversion_public_result(approval)
    return ApprovalInstancePublic.model_validate(approval).model_copy(
        update={
            **updates,
        }
    )


def _approval_public_page(
    db: Session,
    approvals: list[ApprovalInstance],
    current_user: User | None = None,
) -> list[ApprovalInstancePublic]:
    feedback_by_id = _approval_return_feedback_by_id(db, approvals)
    return [
        _approval_public(db, approval, current_user, feedback_by_id.get(approval.id))
        for approval in approvals
    ]


def _approval_detail(db: Session, approval: ApprovalInstance, current_user: User | None = None) -> ApprovalDetail:
    events = list(db.scalars(select(ApprovalEvent).where(ApprovalEvent.approval_id == approval.id).order_by(ApprovalEvent.id)).all())
    attachments = list(db.scalars(select(ApprovalAttachment).where(ApprovalAttachment.approval_id == approval.id).order_by(ApprovalAttachment.id.desc())).all())
    user_labels = _approval_user_labels(
        db,
        [
            *[event.operator_user_id for event in events],
            *[attachment.created_by_user_id for attachment in attachments],
        ],
    )
    return ApprovalDetail(
        approval=_approval_public(
            db,
            approval,
            current_user,
            _return_feedback_from_events(approval, events, user_labels),
        ),
        events=[
            ApprovalEventPublic.model_validate(event).model_copy(
                update={
                    "snapshot_json": None,
                    "operator_user_label": user_labels.get(event.operator_user_id),
                }
            ) if approval.approval_type == LEAD_CONVERSION_APPROVAL_TYPE else ApprovalEventPublic.model_validate(event)
            .model_copy(update={"operator_user_label": user_labels.get(event.operator_user_id)})
            for event in events
        ],
        attachments=[
            ApprovalAttachmentPublic.model_validate(attachment).model_copy(
                update={"created_by_user_label": user_labels.get(attachment.created_by_user_id)}
            )
            for attachment in attachments
        ],
    )


def _require_actor_or_approver(db: Session, approval: ApprovalInstance, user: User) -> None:
    if approval.applicant_user_id == user.id or has_permission(db, user, "approval.approve"):
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only applicant or approver can operate this approval")


def _require_any_approval_action_permission(db: Session, user: User) -> None:
    if has_permission(db, user, "approval.approve") or has_permission(db, user, "crm_lead.approve") or has_permission(db, user, "customer_tag.review"):
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing approval action permission")


def _lead_conversion_in_scope(db: Session, approval: ApprovalInstance, user: User) -> bool:
    if not has_permission(db, user, "crm_lead.view"):
        return False
    try:
        lead_id = int(approval.resource_id)
    except (TypeError, ValueError):
        return False
    return db.scalar(
        crm_lead_scope_filter(select(CrmLead.id).where(CrmLead.id == lead_id), db, user)
    ) is not None


def _require_approval_action_permission(db: Session, approval: ApprovalInstance, user: User) -> None:
    if approval.approval_type == LEAD_CONVERSION_APPROVAL_TYPE:
        if approval.current_handler_user_id == user.id and has_permission(db, user, "crm_lead.approve"):
            return
        if has_permission(db, user, "approval.approve") and _lead_conversion_in_scope(db, approval, user):
            return
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing approval action permission")
    if approval.approval_type == "customer_tag_change":
        if approval.current_handler_user_id == user.id and has_permission(db, user, "customer_tag.review"):
            return
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing customer-tag review permission")
    if has_permission(db, user, "approval.approve"):
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing approval action permission")


def _approval_for_action(db: Session, approval_id: int, user: User) -> ApprovalInstance:
    if has_permission(db, user, "approval.approve"):
        return _approval_or_404(db, approval_id)
    allowed_types: list[str] = []
    if has_permission(db, user, "crm_lead.approve"):
        allowed_types.append(LEAD_CONVERSION_APPROVAL_TYPE)
    if has_permission(db, user, "customer_tag.review"):
        allowed_types.append("customer_tag_change")
    approval = (
        db.scalar(
            select(ApprovalInstance).where(
                ApprovalInstance.id == approval_id,
                ApprovalInstance.current_handler_user_id == user.id,
                ApprovalInstance.approval_type.in_(allowed_types),
            )
        )
        if allowed_types
        else None
    )
    if approval is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing approval action permission")
    return approval


def _upload_root() -> Path:
    root = Path(settings.upload_root)
    if not root.is_absolute():
        root = (Path(__file__).resolve().parents[3] / root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_file_name(file_name: str | None) -> str:
    raw_name = Path(file_name or "attachment").name.strip()
    safe_name = "".join(char if char.isalnum() or char in ".-_ ()（）[]" else "_" for char in raw_name)
    return (safe_name[:180] or "attachment").strip(". ") or "attachment"


def _approval_attachment_path(storage_path: str) -> Path:
    root = _upload_root()
    path = (root / storage_path).resolve()
    if path != root and root not in path.parents:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid attachment storage path")
    return path


def _approval_attachment_or_404(db: Session, approval: ApprovalInstance, attachment_id: int) -> ApprovalAttachment:
    attachment = db.get(ApprovalAttachment, attachment_id)
    if attachment is None or attachment.approval_id != approval.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval attachment not found")
    return attachment


@router.get("/page", response_model=ApprovalPage)
def list_approvals_page(
    q: str | None = None,
    status_value: str | None = None,
    approval_type: str | None = None,
    resource_type: str | None = None,
    applicant_user_id: int | None = None,
    current_handler_user_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApprovalPage:
    safe_limit = _safe_limit(limit)
    safe_offset = _safe_offset(offset)
    stmt = visible_approvals_stmt(db, current_user)
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
    if status_value:
        stmt = stmt.where(ApprovalInstance.status == status_value)
    if approval_type:
        stmt = stmt.where(ApprovalInstance.approval_type == approval_type)
    if resource_type:
        stmt = stmt.where(ApprovalInstance.resource_type == resource_type)
    if applicant_user_id:
        stmt = stmt.where(ApprovalInstance.applicant_user_id == applicant_user_id)
    if current_handler_user_id:
        stmt = stmt.where(ApprovalInstance.current_handler_user_id == current_handler_user_id)
    total = _count_stmt(db, stmt)
    items = list(db.scalars(stmt.order_by(ApprovalInstance.id.desc()).offset(safe_offset).limit(safe_limit)).all())
    return ApprovalPage(items=_approval_public_page(db, items, current_user), total=total, limit=safe_limit, offset=safe_offset)


@router.get("/my-submissions", response_model=ApprovalPage)
def list_my_approval_submissions(
    q: str | None = None,
    scope: str | None = None,
    status_value: str | None = None,
    approval_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApprovalPage:
    safe_limit = _safe_limit(limit)
    safe_offset = _safe_offset(offset)
    stmt = select(ApprovalInstance).where(
        or_(
            ApprovalInstance.applicant_user_id == current_user.id,
            ApprovalInstance.current_handler_user_id == current_user.id,
        )
    ).where(lead_conversion_visibility_clause(db, current_user))
    if status_value:
        stmt = stmt.where(ApprovalInstance.status == status_value)
    normalized_scope = (scope or "").strip()
    if normalized_scope:
        scope_statuses = {
            "drafts": ["draft"],
            "need_supplement": ["need_supplement"],
            "pending": ["submitted", "under_review"],
            "completed": ["completed", "approved"],
            "rejected": ["rejected"],
            "cancelled": ["cancelled"],
            "active": ["draft", "submitted", "under_review", "need_supplement"],
        }
        if normalized_scope not in scope_statuses:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid submission scope: {normalized_scope}")
        stmt = stmt.where(ApprovalInstance.status.in_(scope_statuses[normalized_scope]))
    if approval_type:
        stmt = stmt.where(ApprovalInstance.approval_type == approval_type)
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
    total = _count_stmt(db, stmt)
    items = list(
        db.scalars(
            stmt.order_by(ApprovalInstance.updated_at.desc(), ApprovalInstance.id.desc())
            .offset(safe_offset)
            .limit(safe_limit)
        ).all()
    )
    return ApprovalPage(items=_approval_public_page(db, items, current_user), total=total, limit=safe_limit, offset=safe_offset)


@router.patch("/{approval_id}/draft", response_model=ApprovalDetail)
def update_approval_draft(
    approval_id: int,
    payload: ApprovalDraftUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApprovalDetail:
    approval = visible_approval_or_404(db, current_user, approval_id)
    _require_actor_or_approver(db, approval, current_user)
    _ensure_bound_project_operable(db, approval)
    if approval.status not in {"draft", "need_supplement"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Approval draft cannot be edited from status: {approval.status}")

    changes = payload.model_dump(exclude_unset=True)
    if "title" in changes:
        next_title = (changes["title"] or "").strip()
        if not next_title:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Approval title is required")
        approval.title = next_title
    if "description" in changes:
        approval.description = changes["description"]
    next_payload_json = changes.get("payload_json", approval.payload_json)
    crm_handler_id = _crm_handler_id(db, approval.approval_type, next_payload_json)
    if crm_handler_id is not None:
        approval.current_handler_user_id = crm_handler_id
    elif "current_handler_user_id" in changes:
        require_user(db, changes["current_handler_user_id"], "current_handler_user_id")
        approval.current_handler_user_id = changes["current_handler_user_id"]
    if "priority" in changes and changes["priority"] is not None:
        validate_priority(str(changes["priority"]))
        approval.priority = str(changes["priority"])
    if "payload_json" in changes:
        if approval.approval_type == "crm_lead_convert":
            conversion_payload_lead_id(approval, changes["payload_json"])
        approval.payload_json = jsonable_encoder(changes["payload_json"])

    add_approval_event(
        db,
        approval=approval,
        event_type="draft_update",
        operator=current_user,
        from_status=approval.status,
        to_status=approval.status,
        comment=payload.comment,
        snapshot_json={
            "updated_fields": sorted(changes.keys()),
            "approval_type": approval.approval_type,
        },
    )
    write_audit_log(
        db,
        action_type="update_approval_draft",
        resource_type="approval_instance",
        resource_id=str(approval.id),
        user=current_user,
        request=request,
        after_data=jsonable_encoder({"approval_no": approval.approval_no, "status": approval.status, "updated_fields": sorted(changes.keys())}),
    )
    db.commit()
    db.refresh(approval)
    return _approval_detail(db, approval, current_user)


@router.get("/{approval_id}", response_model=ApprovalDetail)
def get_approval(
    approval_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApprovalDetail:
    approval = visible_approval_or_404(db, current_user, approval_id)
    return _approval_detail(db, approval, current_user)


@router.post("/{approval_id}/attachments", response_model=ApprovalAttachmentPublic, status_code=status.HTTP_201_CREATED)
def upload_approval_attachment(
    approval_id: int,
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApprovalAttachment:
    approval = visible_approval_or_404(db, current_user, approval_id)
    _require_actor_or_approver(db, approval, current_user)
    _ensure_bound_project_operable(db, approval)
    if approval.status in {"completed", "approved", "rejected", "cancelled"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Approval already closed: {approval.status}")

    original_name = _safe_file_name(file.filename)
    relative_dir = Path("approval_attachments") / str(approval.id)
    target_dir = _upload_root() / relative_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    target_name = f"{uuid4().hex}_{original_name}"
    target_path = target_dir / target_name

    digest = hashlib.sha256()
    size_bytes = 0
    with target_path.open("wb") as output:
        while chunk := file.file.read(1024 * 1024):
            size_bytes += len(chunk)
            if size_bytes > MAX_APPROVAL_ATTACHMENT_BYTES:
                output.close()
                target_path.unlink(missing_ok=True)
                raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Attachment exceeds 20MB")
            digest.update(chunk)
            output.write(chunk)

    file_digest = digest.hexdigest()
    existing_attachment = db.scalar(
        select(ApprovalAttachment).where(
            ApprovalAttachment.approval_id == approval.id,
            ApprovalAttachment.file_digest == file_digest,
        )
    )
    if existing_attachment is not None:
        target_path.unlink(missing_ok=True)
        return existing_attachment

    attachment = ApprovalAttachment(
        approval_id=approval.id,
        file_name=original_name,
        content_type=file.content_type,
        size_bytes=size_bytes,
        storage_path=str(relative_dir / target_name),
        file_digest=file_digest,
        created_by_user_id=current_user.id,
    )
    db.add(attachment)
    db.flush()
    add_approval_event(
        db,
        approval=approval,
        event_type="attachment_upload",
        operator=current_user,
        from_status=approval.status,
        to_status=approval.status,
        comment=f"上传附件：{original_name}",
        snapshot_json={"attachment_id": attachment.id, "file_name": original_name, "size_bytes": size_bytes},
    )
    write_audit_log(
        db,
        action_type="upload_approval_attachment",
        resource_type="approval_attachment",
        resource_id=str(attachment.id),
        user=current_user,
        request=request,
        after_data=jsonable_encoder({"approval_id": approval.id, "file_name": original_name, "size_bytes": size_bytes}),
    )
    db.commit()
    db.refresh(attachment)
    return attachment


@router.get("/{approval_id}/attachments/{attachment_id}/download")
def download_approval_attachment(
    approval_id: int,
    attachment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    approval = visible_approval_or_404(db, current_user, approval_id)
    attachment = _approval_attachment_or_404(db, approval, attachment_id)
    path = _approval_attachment_path(attachment.storage_path)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment file not found")
    return FileResponse(path=path, filename=attachment.file_name, media_type=attachment.content_type or "application/octet-stream")


@router.delete("/{approval_id}/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_approval_attachment(
    approval_id: int,
    attachment_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    approval = visible_approval_or_404(db, current_user, approval_id)
    _require_actor_or_approver(db, approval, current_user)
    if approval.status in {"completed", "approved", "rejected", "cancelled"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Approval already closed: {approval.status}")
    attachment = _approval_attachment_or_404(db, approval, attachment_id)
    file_name = attachment.file_name
    path = _approval_attachment_path(attachment.storage_path)
    path.unlink(missing_ok=True)
    db.delete(attachment)
    add_approval_event(
        db,
        approval=approval,
        event_type="attachment_delete",
        operator=current_user,
        from_status=approval.status,
        to_status=approval.status,
        comment=f"删除附件：{file_name}",
        snapshot_json={"attachment_id": attachment_id, "file_name": file_name},
    )
    write_audit_log(
        db,
        action_type="delete_approval_attachment",
        resource_type="approval_attachment",
        resource_id=str(attachment_id),
        user=current_user,
        request=request,
        after_data=jsonable_encoder({"approval_id": approval.id, "file_name": file_name}),
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("", response_model=ApprovalInstancePublic, status_code=status.HTTP_201_CREATED)
def create_approval(
    payload: ApprovalCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_crm_permission("approval.view")),
) -> ApprovalInstancePublic:
    if payload.approval_type == "crm_lead_convert":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CRM lead conversion approvals must be created through /crm-leads/{lead_id}/conversion-approval-draft",
        )
    crm_handler_id = _crm_handler_id(db, payload.approval_type, payload.payload_json)
    approval = create_approval_instance(
        db,
        approval_type=payload.approval_type,
        resource_type=payload.resource_type,
        resource_id=payload.resource_id,
        title=payload.title,
        description=payload.description,
        applicant=current_user,
        current_handler_user_id=crm_handler_id if crm_handler_id is not None else payload.current_handler_user_id,
        priority=payload.priority,
        payload_json=payload.payload_json,
        status_value=payload.status,
        submit=payload.submit,
    )
    _ensure_bound_project_operable(db, approval)
    write_audit_log(
        db,
        action_type="create_approval",
        resource_type="approval_instance",
        resource_id=str(approval.id),
        user=current_user,
        request=request,
        after_data=jsonable_encoder({"approval_no": approval.approval_no, "approval_type": approval.approval_type, "status": approval.status}),
    )
    db.commit()
    db.refresh(approval)
    return _approval_public(db, approval, current_user)


@router.post("/{approval_id}/submit", response_model=ApprovalDetail)
def submit_approval(
    approval_id: int,
    request: Request,
    payload: ApprovalActionRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApprovalDetail:
    approval = visible_approval_or_404(db, current_user, approval_id)
    _require_actor_or_approver(db, approval, current_user)
    _ensure_bound_project_operable(db, approval)
    if approval.status not in {"draft", "need_supplement"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Approval cannot be submitted from status: {approval.status}")
    action = payload or ApprovalActionRequest()
    next_payload_json = action.payload_json or approval.payload_json
    if approval.approval_type == "crm_lead_convert":
        conversion_payload_lead_id(approval, next_payload_json)
    crm_handler_id = _crm_handler_id(db, approval.approval_type, next_payload_json)
    if crm_handler_id is not None:
        approval.current_handler_user_id = crm_handler_id
    transition_approval(
        db,
        approval=approval,
        operator=current_user,
        event_type="submit",
        to_status="submitted",
        comment=action.comment,
        payload_json=next_payload_json,
    )
    write_audit_log(
        db,
        action_type="submit_approval",
        resource_type="approval_instance",
        resource_id=str(approval.id),
        user=current_user,
        request=request,
        after_data=jsonable_encoder({"status": approval.status}),
    )
    db.commit()
    db.refresh(approval)
    return _approval_detail(db, approval, current_user)


@router.post("/{approval_id}/approve", response_model=ApprovalDetail)
def approve_approval(
    approval_id: int,
    request: Request,
    payload: ApprovalActionRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApprovalDetail:
    _require_any_approval_action_permission(db, current_user)
    approval = _approval_for_action(db, approval_id, current_user)
    _require_approval_action_permission(db, approval, current_user)
    _ensure_bound_project_operable(db, approval)
    ensure_actionable(approval)
    ensure_handler(approval, current_user)
    action = payload or ApprovalActionRequest()
    result = execute_approval(db, approval, current_user, action.result_json)
    transition_approval(
        db,
        approval=approval,
        operator=current_user,
        event_type="approve",
        to_status="completed",
        comment=action.comment,
        result_json=result,
    )
    write_audit_log(
        db,
        action_type="approve_approval",
        resource_type="approval_instance",
        resource_id=str(approval.id),
        user=current_user,
        request=request,
        after_data=jsonable_encoder({"status": approval.status, "result_json": approval.result_json}),
    )
    db.commit()
    db.refresh(approval)
    return _approval_detail(db, approval, current_user)


@router.get("/{approval_id}/withdrawal-preview", response_model=ApprovalWithdrawalPreview)
def get_approved_project_withdrawal_preview(
    approval_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApprovalWithdrawalPreview:
    approval = visible_approval_or_404(db, current_user, approval_id)
    return _withdrawal_preview(db, approval, current_user)


@router.post("/{approval_id}/withdraw-approved", response_model=ApprovalDetail)
def withdraw_approved_project(
    approval_id: int,
    payload: ApprovalWithdrawalRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApprovalDetail:
    visible_approval_or_404(db, current_user, approval_id)
    approval = db.scalar(
        select(ApprovalInstance).where(ApprovalInstance.id == approval_id).with_for_update()
    )
    if approval is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found")
    project = _approval_bound_project(db, approval)
    if project is not None:
        project = db.scalar(select(CrmProject).where(CrmProject.id == project.id).with_for_update())
    preview = _withdrawal_preview(db, approval, current_user)
    if not preview.can_withdraw:
        if project is not None and project.approval_withdrawn_at is not None:
            raise _api_conflict("PROJECT_ALREADY_WITHDRAWN", "项目审批已经撤回。", resource_type="crm_project", resource_id=str(project.id))
        if project is not None and project.status in {"closed", "cancelled"}:
            raise _api_conflict("PROJECT_TERMINAL", "已关闭或已取消项目不能撤回审核。", resource_type="crm_project", resource_id=str(project.id))
        if preview.deadline is not None and datetime.now(timezone.utc) > preview.deadline and not preview.is_override:
            raise _api_conflict("APPROVAL_WITHDRAW_WINDOW_EXPIRED", "原审批人的24小时撤回时限已过。", resource_id=str(approval.id))
        if not has_permission(db, current_user, "crm_project.approval_withdraw") and not preview.is_override:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error_code": "APPROVAL_WITHDRAW_NOT_ALLOWED",
                    "message": "当前账号没有撤回已通过项目审批的权限。",
                    "module": "crm",
                    "resource_type": "approval_instance",
                    "resource_id": str(approval.id),
                    "retryable": False,
                },
            )
        raise _api_conflict(
            "APPROVAL_WITHDRAW_NOT_ALLOWED",
            preview.blockers[0] if preview.blockers else "当前项目审批不能撤回。",
            resource_id=str(approval.id),
        )
    if project is None:
        raise _api_conflict("APPROVAL_WITHDRAW_NOT_ALLOWED", "审批单未绑定有效项目。", resource_id=str(approval.id))

    reason = payload.reason.strip()
    if len(reason) < 5:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="撤回原因至少需要5个字符")
    now = datetime.now(timezone.utc)
    approval_before = {
        "status": approval.status,
        "reviewed_at": approval.reviewed_at,
        "closed_at": approval.closed_at,
        "result_json": approval.result_json,
    }
    project_before = project_audit_snapshot(project)
    impact_counts = _project_withdrawal_impact(db, project)
    transition_approval(
        db,
        approval=approval,
        operator=current_user,
        event_type="withdraw_approved_project",
        to_status="need_supplement",
        comment=reason,
        event_snapshot_json={
            "approval_before": approval_before,
            "project_before": project_before,
            "impact_counts": impact_counts,
            "override": preview.is_override,
        },
    )
    approval.reviewed_at = None
    approval.closed_at = None
    project.pre_withdraw_status = project.status
    if project.status == "active":
        project.status = "paused"
    project.approval_status = "need_supplement"
    project.approval_withdrawn_at = now
    project.approval_withdrawn_by_user_id = current_user.id
    project.approval_withdrawn_reason = reason
    project.updated_by_user_id = current_user.id
    db.flush()

    audit_after = {
        "approval": {
            "status": approval.status,
            "reviewed_at": approval.reviewed_at,
            "closed_at": approval.closed_at,
        },
        "project": project_audit_snapshot(project),
        "withdrawal_reason": reason,
        "impact_counts": impact_counts,
        "override": preview.is_override,
    }
    write_audit_log(
        db,
        action_type="withdraw_approved_project",
        resource_type="approval_instance",
        resource_id=str(approval.id),
        user=current_user,
        request=request,
        before_data=jsonable_encoder({"approval": approval_before, "project": project_before}),
        after_data=jsonable_encoder(audit_after),
    )
    write_audit_log(
        db,
        action_type="freeze_project_after_approval_withdrawal",
        resource_type="crm_project",
        resource_id=str(project.id),
        user=current_user,
        request=request,
        before_data=jsonable_encoder(project_before),
        after_data=jsonable_encoder(project_audit_snapshot(project)),
    )
    enqueue_incremental_exception_scan_safely(
        db,
        domains=["crm", "approval"],
        target_resource_type="crm_project",
        target_resource_id=project.id,
    )
    db.commit()
    db.refresh(approval)
    return _approval_detail(db, approval, current_user)


@router.post("/{approval_id}/reject", response_model=ApprovalDetail)
def reject_approval(
    approval_id: int,
    request: Request,
    payload: ApprovalActionRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApprovalDetail:
    _require_any_approval_action_permission(db, current_user)
    approval = _approval_for_action(db, approval_id, current_user)
    _require_approval_action_permission(db, approval, current_user)
    _ensure_bound_project_operable(db, approval)
    ensure_actionable(approval)
    ensure_handler(approval, current_user)
    action = payload or ApprovalActionRequest()
    transition_approval(db, approval=approval, operator=current_user, event_type="reject", to_status="rejected", comment=action.comment, result_json=action.result_json)
    write_audit_log(
        db,
        action_type="reject_approval",
        resource_type="approval_instance",
        resource_id=str(approval.id),
        user=current_user,
        request=request,
        after_data=jsonable_encoder({"status": approval.status, "result_json": approval.result_json}),
    )
    db.commit()
    db.refresh(approval)
    return _approval_detail(db, approval, current_user)


@router.post("/{approval_id}/supplement-request", response_model=ApprovalDetail)
def request_approval_supplement(
    approval_id: int,
    request: Request,
    payload: ApprovalActionRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApprovalDetail:
    _require_any_approval_action_permission(db, current_user)
    approval = _approval_for_action(db, approval_id, current_user)
    _require_approval_action_permission(db, approval, current_user)
    _ensure_bound_project_operable(db, approval)
    ensure_actionable(approval)
    ensure_handler(approval, current_user)
    action = payload or ApprovalActionRequest()
    transition_approval(
        db,
        approval=approval,
        operator=current_user,
        event_type="supplement_request",
        to_status="need_supplement",
        comment=action.comment,
        result_json=action.result_json,
    )
    write_audit_log(
        db,
        action_type="request_approval_supplement",
        resource_type="approval_instance",
        resource_id=str(approval.id),
        user=current_user,
        request=request,
        after_data=jsonable_encoder({"status": approval.status}),
    )
    db.commit()
    db.refresh(approval)
    return _approval_detail(db, approval, current_user)


@router.post("/{approval_id}/supplement", response_model=ApprovalDetail)
def supplement_approval(
    approval_id: int,
    request: Request,
    payload: ApprovalActionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApprovalDetail:
    approval = visible_approval_or_404(db, current_user, approval_id)
    _require_actor_or_approver(db, approval, current_user)
    _ensure_bound_project_operable(db, approval)
    if approval.status != "need_supplement":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Approval cannot be supplemented from status: {approval.status}")
    next_payload_json = payload.payload_json or approval.payload_json
    if approval.approval_type == "crm_lead_convert":
        conversion_payload_lead_id(approval, next_payload_json)
    if approval.approval_type == "crm_project_create":
        validate_withdrawn_project_reapproval_payload(db, approval, next_payload_json)
    transition_approval(
        db,
        approval=approval,
        operator=current_user,
        event_type="supplement",
        to_status="submitted",
        comment=payload.comment,
        payload_json=next_payload_json,
    )
    write_audit_log(
        db,
        action_type="supplement_approval",
        resource_type="approval_instance",
        resource_id=str(approval.id),
        user=current_user,
        request=request,
        after_data=jsonable_encoder({"status": approval.status}),
    )
    db.commit()
    db.refresh(approval)
    return _approval_detail(db, approval, current_user)


@router.post("/{approval_id}/cancel", response_model=ApprovalDetail)
def cancel_approval(
    approval_id: int,
    request: Request,
    payload: ApprovalActionRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApprovalDetail:
    approval = visible_approval_or_404(db, current_user, approval_id)
    _require_actor_or_approver(db, approval, current_user)
    project = _approval_bound_project(db, approval)
    if approval.approval_type == "crm_project_create" and project is not None and project.approval_withdrawn_at is not None:
        raise _api_conflict(
            "PROJECT_FROZEN",
            "已撤回审核的项目申请必须补充后重新提交，不能直接取消。",
            resource_type="crm_project",
            resource_id=str(project.id),
        )
    _ensure_bound_project_operable(db, approval)
    if approval.status in {"completed", "approved", "rejected", "cancelled"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Approval already closed: {approval.status}")
    action = payload or ApprovalActionRequest()
    transition_approval(db, approval=approval, operator=current_user, event_type="cancel", to_status="cancelled", comment=action.comment, result_json=action.result_json)
    write_audit_log(
        db,
        action_type="cancel_approval",
        resource_type="approval_instance",
        resource_id=str(approval.id),
        user=current_user,
        request=request,
        after_data=jsonable_encoder({"status": approval.status}),
    )
    db.commit()
    db.refresh(approval)
    return _approval_detail(db, approval, current_user)

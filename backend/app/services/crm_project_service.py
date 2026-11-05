from datetime import datetime
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CustomerMaster, EmployeeProfile, User
from app.models.crm import (
    CRM_APPROVAL_STATUSES,
    CRM_FOLLOWUP_REVIEW_STATUSES,
    CRM_PROJECT_REVIEW_STATUSES,
    CRM_PROJECT_STATUSES,
    CRM_TASK_STATUSES,
    CrmFollowup,
    CrmProject,
    CrmProjectCustomerTask,
    CrmProjectReview,
)


def generated_code(prefix: str) -> str:
    return f"{prefix}{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}"


def validate_project_status(status_value: str) -> None:
    if status_value not in CRM_PROJECT_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid project status: {status_value}")


def validate_approval_status(status_value: str) -> None:
    if status_value not in CRM_APPROVAL_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid approval status: {status_value}")


def validate_task_status(status_value: str) -> None:
    if status_value not in CRM_TASK_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid task status: {status_value}")


def validate_followup_review_status(status_value: str) -> None:
    if status_value not in CRM_FOLLOWUP_REVIEW_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid followup review status: {status_value}")


def validate_review_status(status_value: str) -> None:
    if status_value not in CRM_PROJECT_REVIEW_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid review status: {status_value}")


def project_is_approval_frozen(project: CrmProject) -> bool:
    return project.approval_status == "need_supplement" and project.approval_withdrawn_at is not None


def ensure_project_operable(project: CrmProject) -> None:
    if project_is_approval_frozen(project):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "PROJECT_FROZEN",
                "message": "项目审批已撤回，当前项目已冻结；请等待申请人补充并重新审批。",
                "module": "crm",
                "resource_type": "crm_project",
                "resource_id": str(project.id),
                "retryable": False,
                "action_path": f"/crm/work?approval_id={project.current_approval_id}" if project.current_approval_id else "/crm/work",
            },
        )


def require_customer(db: Session, customer_code: str) -> CustomerMaster:
    customer = db.scalar(select(CustomerMaster).where(CustomerMaster.customer_code == customer_code))
    if customer is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"客户不存在：{customer_code}")
    return customer


def require_user(db: Session, user_id: int | None, field_name: str) -> User | None:
    if user_id is None:
        return None
    user = db.get(User, user_id)
    if user is None or user.status != "active" or not user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{field_name} 指向的账号不存在或未启用：{user_id}")
    return user


def require_employee(db: Session, employee_code: str | None) -> EmployeeProfile | None:
    if not employee_code:
        return None
    employee = db.scalar(select(EmployeeProfile).where(EmployeeProfile.employee_code == employee_code))
    if employee is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"员工档案不存在：{employee_code}")
    return employee


def ensure_unique_project_code(db: Session, project_code: str) -> None:
    if db.scalar(select(CrmProject).where(CrmProject.project_code == project_code)) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Project code already exists")


def ensure_unique_task_code(db: Session, task_code: str) -> None:
    if db.scalar(select(CrmProjectCustomerTask).where(CrmProjectCustomerTask.task_code == task_code)) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Task code already exists")


def ensure_unique_followup_no(db: Session, followup_no: str) -> None:
    if db.scalar(select(CrmFollowup).where(CrmFollowup.followup_no == followup_no)) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Followup number already exists")


def ensure_unique_review_no(db: Session, review_no: str) -> None:
    if db.scalar(select(CrmProjectReview).where(CrmProjectReview.review_no == review_no)) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Review number already exists")


def task_executor_snapshot(db: Session, executor_user_id: int | None, executor_employee_code: str | None) -> tuple[str | None, str | None]:
    user = require_user(db, executor_user_id, "executor_user_id")
    employee = require_employee(db, executor_employee_code)
    employee_code = executor_employee_code or (user.employee_code if user else None)
    name = None
    if employee:
        name = employee.employee_name
    elif user:
        name = user.real_name
    if employee_code and employee is None:
        employee = require_employee(db, employee_code)
        name = employee.employee_name
    return employee_code, name


def project_audit_snapshot(project: CrmProject) -> dict:
    return {
        "id": project.id,
        "project_code": project.project_code,
        "project_name": project.project_name,
        "project_type": project.project_type,
        "business_line": project.business_line,
        "applicant_user_id": project.applicant_user_id,
        "landing_approver_user_id": project.landing_approver_user_id,
        "owner_user_id": project.owner_user_id,
        "project_manager_user_id": project.project_manager_user_id,
        "participant_user_ids": project.participant_user_ids,
        "progress_cc_user_ids": project.progress_cc_user_ids,
        "status": project.status,
        "approval_status": project.approval_status,
        "approval_withdrawn_at": project.approval_withdrawn_at,
        "approval_withdrawn_by_user_id": project.approval_withdrawn_by_user_id,
        "approval_withdrawn_reason": project.approval_withdrawn_reason,
        "pre_withdraw_status": project.pre_withdraw_status,
    }


def task_audit_snapshot(task: CrmProjectCustomerTask) -> dict:
    return {
        "id": task.id,
        "project_id": task.project_id,
        "task_code": task.task_code,
        "customer_code": task.customer_code,
        "executor_user_id": task.executor_user_id,
        "executor_employee_code": task.executor_employee_code,
        "status": task.status,
        "need_support": task.need_support,
        "is_blocked": task.is_blocked,
        "is_closed": task.is_closed,
    }


def followup_audit_snapshot(followup: CrmFollowup) -> dict:
    return {
        "id": followup.id,
        "followup_no": followup.followup_no,
        "project_id": followup.project_id,
        "task_id": followup.task_id,
        "customer_code": followup.customer_code,
        "executor_user_id": followup.executor_user_id,
        "business_profile_updated": followup.business_profile_updated,
        "business_profile_approval_id": followup.business_profile_approval_id,
        "customer_profile_updated": followup.customer_profile_updated,
        "customer_profile_approval_id": followup.customer_profile_approval_id,
        "need_support": followup.need_support,
        "review_status": followup.review_status,
        "valid_feedback": followup.valid_feedback,
        "is_closed": followup.is_closed,
    }


def review_audit_snapshot(review: CrmProjectReview) -> dict:
    return {
        "id": review.id,
        "review_no": review.review_no,
        "project_id": review.project_id,
        "review_date": review.review_date.isoformat() if review.review_date else None,
        "status": review.status,
        "conclusion": review.conclusion,
        "decision_maker_user_id": review.decision_maker_user_id,
    }

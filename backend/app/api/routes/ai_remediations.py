from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.database import get_db
from app.models import User
from app.schemas.ai_remediation import (
    RemediationAnswersRequest,
    RemediationCancelRequest,
    RemediationConfirmRequest,
    RemediationCreateRequest,
    RemediationPlanRequest,
    RemediationWorkflowPublic,
)
from app.services.ai_remediation_service import (
    RemediationGenerationError,
    _workflow_or_404,
    attachment_path,
    business_reference_options,
    cancel_workflow,
    confirm_and_execute,
    create_remediation,
    delete_attachment,
    generate_plan,
    require_remediation_enabled,
    save_answers,
    serialize_workflow,
    upload_attachment,
)
from app.services.audit_service import write_audit_log
from app.services.permission_service import has_permission


router = APIRouter(prefix="/ai/remediations", tags=["ai-remediations"])


def _require_access(db: Session, user: User) -> None:
    require_remediation_enabled()
    if not has_permission(db, user, "exception_center.view") or not has_permission(db, user, "crm_insight.view"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="当前账号没有 AI 异常修复权限")


def _public(db: Session, user: User, workflow: Any) -> RemediationWorkflowPublic:
    return RemediationWorkflowPublic.model_validate(serialize_workflow(db, user, workflow))


def _audit(db: Session, request: Request, user: User, action: str, workflow_no: str, status_value: str) -> None:
    write_audit_log(
        db,
        action_type=action,
        resource_type="ai_case_remediation",
        resource_id=workflow_no,
        user=user,
        request=request,
        after_data={"status": status_value},
    )


@router.post("", response_model=RemediationWorkflowPublic, status_code=status.HTTP_201_CREATED)
def create_workflow(
    payload: RemediationCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RemediationWorkflowPublic:
    _require_access(db, current_user)
    try:
        workflow = create_remediation(
            db,
            current_user,
            source_message_no=payload.source_message_no,
            client_request_id=payload.client_request_id,
        )
    except RemediationGenerationError as exc:
        db.commit()
        raise HTTPException(status_code=502, detail="补充信息表单生成失败，请稍后重试") from exc
    _audit(db, request, current_user, "create_ai_case_remediation", workflow.workflow_no, workflow.status)
    db.commit()
    db.refresh(workflow)
    return _public(db, current_user, workflow)


@router.get("/{workflow_no}", response_model=RemediationWorkflowPublic)
def get_workflow(
    workflow_no: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RemediationWorkflowPublic:
    _require_access(db, current_user)
    workflow = _workflow_or_404(db, current_user, workflow_no)
    if db.dirty:
        db.commit()
        db.refresh(workflow)
    return _public(db, current_user, workflow)


@router.get("/{workflow_no}/events")
def workflow_events(
    workflow_no: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    _require_access(db, current_user)
    workflow = _workflow_or_404(db, current_user, workflow_no)
    snapshot = jsonable_encoder(serialize_workflow(db, current_user, workflow))
    status_value = workflow.status
    event_name = {
        "schema_generating": "schema_started",
        "form_ready": "schema_ready",
        "collecting": "schema_ready",
        "plan_generating": "plan_started",
        "plan_ready": "plan_ready",
        "execution_queued": "execution_queued",
        "executing": "executing",
        "completed": "completed",
        "failed": "failed",
        "stale": "blocked",
        "cancelled": "blocked",
    }.get(status_value, "failed")

    def stream():
        data = {"workflow_no": workflow_no, "status": status_value, "lock_version": workflow.lock_version}
        if event_name in {"schema_ready", "plan_ready", "completed"}:
            data["workflow"] = snapshot
        yield f"event: {event_name}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
        yield f"event: done\ndata: {json.dumps({'workflow_no': workflow_no}, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/{workflow_no}/references/{reference_type}")
def list_business_references(
    workflow_no: str,
    reference_type: str,
    q: str = Query(default="", max_length=100),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict[str, str]]:
    _require_access(db, current_user)
    return business_reference_options(db, current_user, workflow_no, reference_type, q, limit)


@router.post("/{workflow_no}/attachments", response_model=RemediationWorkflowPublic)
async def add_attachment(
    workflow_no: str,
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RemediationWorkflowPublic:
    _require_access(db, current_user)
    await upload_attachment(db, current_user, workflow_no, file)
    workflow = _workflow_or_404(db, current_user, workflow_no)
    _audit(db, request, current_user, "upload_ai_remediation_attachment", workflow_no, workflow.status)
    db.commit()
    db.refresh(workflow)
    return _public(db, current_user, workflow)


@router.delete("/{workflow_no}/attachments/{attachment_no}", response_model=RemediationWorkflowPublic)
def remove_attachment(
    workflow_no: str,
    attachment_no: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RemediationWorkflowPublic:
    _require_access(db, current_user)
    workflow = delete_attachment(db, current_user, workflow_no, attachment_no)
    _audit(db, request, current_user, "delete_ai_remediation_attachment", workflow_no, workflow.status)
    db.commit()
    db.refresh(workflow)
    return _public(db, current_user, workflow)


@router.get("/{workflow_no}/attachments/{attachment_no}")
def download_attachment(
    workflow_no: str,
    attachment_no: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    _require_access(db, current_user)
    row, path = attachment_path(db, current_user, workflow_no, attachment_no)
    return FileResponse(path, media_type=row.content_type, filename=row.original_name)


@router.put("/{workflow_no}/answers", response_model=RemediationWorkflowPublic)
def update_answers(
    workflow_no: str,
    payload: RemediationAnswersRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RemediationWorkflowPublic:
    _require_access(db, current_user)
    workflow = save_answers(db, current_user, workflow_no, expected_lock_version=payload.expected_lock_version, answers=payload.answers)
    _audit(db, request, current_user, "save_ai_remediation_answers", workflow_no, workflow.status)
    db.commit()
    db.refresh(workflow)
    return _public(db, current_user, workflow)


@router.post("/{workflow_no}/plan", response_model=RemediationWorkflowPublic)
def create_plan(
    workflow_no: str,
    payload: RemediationPlanRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RemediationWorkflowPublic:
    _require_access(db, current_user)
    try:
        workflow = generate_plan(db, current_user, workflow_no, expected_lock_version=payload.expected_lock_version, client_request_id=payload.client_request_id)
    except RemediationGenerationError as exc:
        db.commit()
        raise HTTPException(status_code=502, detail="修复方案生成失败，请稍后重试") from exc
    _audit(db, request, current_user, "generate_ai_remediation_plan", workflow_no, workflow.status)
    db.commit()
    db.refresh(workflow)
    return _public(db, current_user, workflow)


@router.post("/{workflow_no}/confirm-execute", response_model=RemediationWorkflowPublic)
def execute_plan(
    workflow_no: str,
    payload: RemediationConfirmRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RemediationWorkflowPublic:
    _require_access(db, current_user)
    workflow = confirm_and_execute(db, current_user, workflow_no, expected_lock_version=payload.expected_lock_version, idempotency_key=payload.idempotency_key)
    _audit(db, request, current_user, "confirm_execute_ai_remediation", workflow_no, workflow.status)
    db.commit()
    db.refresh(workflow)
    return _public(db, current_user, workflow)


@router.post("/{workflow_no}/cancel", response_model=RemediationWorkflowPublic)
def cancel(
    workflow_no: str,
    payload: RemediationCancelRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RemediationWorkflowPublic:
    _require_access(db, current_user)
    workflow = cancel_workflow(db, current_user, workflow_no, expected_lock_version=payload.expected_lock_version)
    _audit(db, request, current_user, "cancel_ai_remediation", workflow_no, workflow.status)
    db.commit()
    db.refresh(workflow)
    return _public(db, current_user, workflow)

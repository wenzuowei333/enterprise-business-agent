from __future__ import annotations

import json
import shutil
import statistics
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import false, func, or_, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.models import (
    ApprovalInstance,
    AssistantConversation,
    CrmProject,
    CrmProjectCustomerTask,
    MobileFeedback,
    MobileSession,
    MobileTelemetryRecord,
    User,
)
from app.schemas.mobile import (
    MobileAssistantDraftRequest,
    MobileAssistantDraftResponse,
    MobileFeedbackCreate,
    MobileFeedbackPage,
    MobileFeedbackPublic,
    MobileFeedbackUpdate,
)
from app.services.audit_service import write_audit_log
from app.services.access_control_service import ALL_SCOPE, ASSIGNED_SCOPE, CUSTOM_SCOPE, OWN_SCOPE, get_data_scope_rule
from app.services.crm_access_service import crm_project_scope_filter, crm_task_scope_filter
from app.services.hermes_ai_service import call_hermes_chat, hermes_configured
from app.services.permission_service import has_permission

router = APIRouter(prefix="/mobile", tags=["mobile-round5"])

FEEDBACK_STATUSES = {"open", "processing", "resolved", "closed"}
FEEDBACK_CONTENT_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
AI_DRAFT_TYPES = {"followup", "approval_opinion", "project_summary"}


def _safe_route(value: str | None) -> str | None:
    if not value:
        return None
    return value.split("?", 1)[0].split("#", 1)[0][:240]


def _feedback_public(row: MobileFeedback, db: Session) -> MobileFeedbackPublic:
    owner = db.get(User, row.user_id)
    handler = db.get(User, row.handler_user_id) if row.handler_user_id else None
    return MobileFeedbackPublic(
        id=row.id,
        user_id=row.user_id,
        user_label=(owner.real_name or owner.username) if owner else None,
        category=row.category,
        description=row.description,
        current_route=row.current_route,
        request_id=row.request_id,
        app_version=row.app_version,
        android_version=row.android_version,
        device_model=row.device_model,
        screenshot_path=f"/api/v1/mobile/feedback/{row.id}/attachment" if row.screenshot_path else None,
        status=row.status,
        handler_user_id=row.handler_user_id,
        handler_label=(handler.real_name or handler.username) if handler else None,
        resolution=row.resolution,
        resolved_at=row.resolved_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _require_feedback_admin(db: Session, user: User) -> None:
    if user.role == "admin" or has_permission(db, user, "settings.view"):
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权处理移动端反馈")


@router.post("/feedback", response_model=MobileFeedbackPublic)
def mobile_create_feedback(
    payload: MobileFeedbackCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MobileFeedbackPublic:
    screenshot_path = payload.screenshot_path
    moved_target: Path | None = None
    if screenshot_path and not screenshot_path.startswith(f"mobile-feedback://{current_user.id}/"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="反馈截图路径无效")
    if screenshot_path:
        filename = screenshot_path.removeprefix(f"mobile-feedback://{current_user.id}/")
        if Path(filename).name != filename:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="反馈截图路径无效")
        source = _feedback_pending_root() / str(current_user.id) / filename
        if not source.is_file():
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="反馈截图已失效，请重新选择")
        target = _feedback_storage_root() / str(current_user.id) / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
        moved_target = target
    try:
        row = MobileFeedback(
            user_id=current_user.id,
            category=payload.category,
            description=payload.description.strip(),
            current_route=_safe_route(payload.current_route),
            request_id=payload.request_id,
            app_version=payload.app_version,
            android_version=payload.android_version,
            device_model=payload.device_model,
            screenshot_path=screenshot_path,
            status="open",
        )
        db.add(row)
        db.flush()
        write_audit_log(
            db,
            action_type="mobile_feedback_create",
            resource_type="mobile_feedback",
            resource_id=str(row.id),
            user=current_user,
            request=request,
            after_data={"category": row.category, "route": row.current_route, "request_id": row.request_id},
        )
        db.commit()
    except Exception:
        db.rollback()
        if moved_target is not None:
            moved_target.unlink(missing_ok=True)
        raise
    db.refresh(row)
    return _feedback_public(row, db)


@router.get("/feedback/mine", response_model=MobileFeedbackPage)
def mobile_list_my_feedback(
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MobileFeedbackPage:
    stmt = select(MobileFeedback).where(MobileFeedback.user_id == current_user.id)
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = list(db.scalars(stmt.order_by(MobileFeedback.id.desc()).offset(offset).limit(limit)).all())
    return MobileFeedbackPage(items=[_feedback_public(row, db) for row in rows], total=total, limit=limit, offset=offset)


@router.post("/feedback/attachments")
async def mobile_upload_feedback_attachment(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    extension = FEEDBACK_CONTENT_TYPES.get(file.content_type or "")
    if extension is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="反馈截图仅支持 JPG、PNG 或 WebP")
    content = await file.read(5 * 1024 * 1024 + 1)
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="反馈截图不能超过 5MB")
    if not _feedback_image_matches(file.content_type or "", content):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="反馈截图内容与图片格式不一致")
    _cleanup_pending_feedback()
    filename = f"{uuid4().hex}{extension}"
    target = _feedback_pending_root() / str(current_user.id) / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return {"screenshot_path": f"mobile-feedback://{current_user.id}/{filename}", "size_bytes": len(content)}


def _feedback_storage_root() -> Path:
    upload_root = Path(settings.upload_root)
    if not upload_root.is_absolute():
        upload_root = (Path(__file__).resolve().parents[3] / upload_root).resolve()
    return upload_root.parent / "mobile_feedback_private"


def _feedback_pending_root() -> Path:
    return _feedback_storage_root().parent / "mobile_feedback_pending"


def _feedback_image_matches(content_type: str, content: bytes) -> bool:
    if content_type == "image/jpeg":
        return content.startswith(b"\xff\xd8\xff")
    if content_type == "image/png":
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/webp":
        return len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP"
    return False


def _cleanup_pending_feedback(max_age_seconds: int = 24 * 60 * 60) -> None:
    root = _feedback_pending_root()
    if not root.exists():
        return
    cutoff = time.time() - max_age_seconds
    for target in root.rglob("*"):
        if target.is_file() and target.stat().st_mtime < cutoff:
            target.unlink(missing_ok=True)


@router.get("/feedback/{feedback_id}/attachment")
def mobile_feedback_attachment(
    feedback_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    row = db.get(MobileFeedback, feedback_id)
    if row is None or not row.screenshot_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="反馈截图不存在")
    if row.user_id != current_user.id:
        _require_feedback_admin(db, current_user)
    prefix = f"mobile-feedback://{row.user_id}/"
    if not row.screenshot_path.startswith(prefix):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="反馈截图路径无效")
    filename = row.screenshot_path.removeprefix(prefix)
    if Path(filename).name != filename:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="反馈截图路径无效")
    target = _feedback_storage_root() / str(row.user_id) / filename
    if not target.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="反馈截图文件不存在")
    return FileResponse(target, filename=f"mobile-feedback-{feedback_id}{target.suffix}")


@router.get("/admin/feedback", response_model=MobileFeedbackPage)
def mobile_admin_feedback(
    status_value: str | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MobileFeedbackPage:
    _require_feedback_admin(db, current_user)
    stmt = select(MobileFeedback)
    if status_value:
        if status_value not in FEEDBACK_STATUSES:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="反馈状态无效")
        stmt = stmt.where(MobileFeedback.status == status_value)
    if q and q.strip():
        keyword = f"%{q.strip()}%"
        stmt = stmt.where(or_(MobileFeedback.description.ilike(keyword), MobileFeedback.request_id.ilike(keyword)))
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = list(db.scalars(stmt.order_by(MobileFeedback.id.desc()).offset(offset).limit(limit)).all())
    return MobileFeedbackPage(items=[_feedback_public(row, db) for row in rows], total=total, limit=limit, offset=offset)


@router.patch("/admin/feedback/{feedback_id}", response_model=MobileFeedbackPublic)
def mobile_admin_update_feedback(
    feedback_id: int,
    payload: MobileFeedbackUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MobileFeedbackPublic:
    _require_feedback_admin(db, current_user)
    row = db.get(MobileFeedback, feedback_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="移动端反馈不存在")
    if payload.status == "resolved" and not (payload.resolution or "").strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="标记已解决时请填写处理结果")
    before = {"status": row.status, "resolution": row.resolution}
    row.status = payload.status
    row.resolution = payload.resolution.strip() if payload.resolution else None
    row.handler_user_id = current_user.id
    row.resolved_at = datetime.now(timezone.utc) if payload.status in {"resolved", "closed"} else None
    write_audit_log(
        db,
        action_type="mobile_feedback_update",
        resource_type="mobile_feedback",
        resource_id=str(row.id),
        user=current_user,
        request=request,
        before_data=before,
        after_data={"status": row.status, "resolution": row.resolution},
    )
    db.commit()
    db.refresh(row)
    return _feedback_public(row, db)


def parse_mobile_ai_draft(raw: str, draft_type: str) -> dict[str, Any]:
    if draft_type not in AI_DRAFT_TYPES:
        raise ValueError("unsupported draft type")
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    data = json.loads(text)
    if not isinstance(data, dict) or not isinstance(data.get("fields"), dict):
        raise ValueError("AI draft fields must be an object")
    warnings = data.get("warnings") or []
    source_refs = data.get("source_refs") or []
    if not isinstance(warnings, list) or not all(isinstance(item, str) for item in warnings):
        raise ValueError("AI draft warnings must be strings")
    if not isinstance(source_refs, list) or not all(isinstance(item, str) for item in source_refs):
        raise ValueError("AI draft source refs must be strings")
    return {"fields": data["fields"], "warnings": warnings, "source_refs": source_refs}


def _require_ai_drafts(current_user: User) -> None:
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="AI 草稿仅管理员可用")
    if not settings.mobile_feature_ai_drafts:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI 草稿功能尚未开放")
    if not hermes_configured():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="AI 服务尚未配置")


def _scoped_ai_approval(db: Session, current_user: User, approval_id: int) -> ApprovalInstance | None:
    if not has_permission(db, current_user, "approval.view"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权查看审批内容")
    stmt = select(ApprovalInstance).where(ApprovalInstance.id == approval_id)
    rule = get_data_scope_rule(db, current_user, "approval")
    if rule is not None and rule.scope_mode != ALL_SCOPE:
        if rule.scope_mode in {OWN_SCOPE, ASSIGNED_SCOPE}:
            stmt = stmt.where(
                or_(
                    ApprovalInstance.applicant_user_id == current_user.id,
                    ApprovalInstance.current_handler_user_id == current_user.id,
                )
            )
        elif rule.scope_mode == CUSTOM_SCOPE:
            value = rule.scope_value if isinstance(rule.scope_value, dict) else {}
            approval_types = value.get("approval_types")
            if value.get("mode") == "none":
                stmt = stmt.where(false())
            elif isinstance(approval_types, list) and approval_types:
                stmt = stmt.where(ApprovalInstance.approval_type.in_([str(item) for item in approval_types]))
            else:
                stmt = stmt.where(false())
        else:
            stmt = stmt.where(false())
    return db.scalar(stmt)


def _draft_context(
    draft_type: str,
    payload: MobileAssistantDraftRequest,
    db: Session,
    current_user: User,
) -> tuple[dict[str, Any], list[str]]:
    context: dict[str, Any] = {"text": payload.text, "context_revision": payload.context_revision}
    refs: list[str] = ["input:text"] if payload.text else []
    if payload.task_id:
        if not has_permission(db, current_user, "crm_task.view"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权查看任务内容")
        row = db.scalar(crm_task_scope_filter(select(CrmProjectCustomerTask).where(CrmProjectCustomerTask.id == payload.task_id), db, current_user))
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
        context["task"] = {
            "id": row.id,
            "task_code": row.task_code,
            "project_id": row.project_id,
            "customer_code": row.customer_code,
            "customer_name": row.customer_name_snapshot,
            "status": row.status,
            "business_issue_point": row.business_issue_point,
            "round_target": row.round_target,
            "latest_blocker_reason": row.latest_blocker_reason,
            "latest_blocker_note": row.latest_blocker_note,
            "latest_owner_next_status": row.latest_owner_next_status,
            "latest_owner_next_action": row.latest_owner_next_action,
        }
        refs.append(f"task:{row.id}")
    if payload.approval_id:
        row = _scoped_ai_approval(db, current_user, payload.approval_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="审批不存在")
        context["approval"] = {
            "id": row.id,
            "approval_no": row.approval_no,
            "approval_type": row.approval_type,
            "title": row.title,
            "description": row.description,
            "status": row.status,
            "priority": row.priority,
            "submitted_at": row.submitted_at,
        }
        refs.append(f"approval:{row.id}")
    if payload.project_id:
        if not has_permission(db, current_user, "crm_project.view"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权查看项目内容")
        row = db.scalar(crm_project_scope_filter(select(CrmProject).where(CrmProject.id == payload.project_id), db, current_user))
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
        context["project"] = {
            "id": row.id,
            "project_code": row.project_code,
            "project_name": row.project_name,
            "project_type": row.project_type,
            "purpose": row.purpose,
            "business_line": row.business_line,
            "status": row.status,
            "approval_status": row.approval_status,
            "next_step_status": row.next_step_status,
            "next_step_action": row.next_step_action,
        }
        refs.append(f"project:{row.id}")
    if not payload.text and len(refs) == 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="请提供文字或业务对象")
    return context, refs


def _create_ai_draft(
    draft_type: str,
    payload: MobileAssistantDraftRequest,
    request: Request,
    db: Session,
    current_user: User,
) -> MobileAssistantDraftResponse:
    _require_ai_drafts(current_user)
    context, refs = _draft_context(draft_type, payload, db, current_user)
    system_prompt = (
        "你是企业 CRM 草稿助手。只生成供人工编辑的草稿，不执行审批、保存或任何写入动作。"
        "只输出 JSON：fields 必须为对象，warnings 和 source_refs 必须为字符串数组。"
        f"当前草稿类型：{draft_type}。"
    )
    try:
        raw = call_hermes_chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(context, ensure_ascii=False, default=str)},
            ],
            temperature=0.1,
        )
    except RuntimeError as exc:
        code = status.HTTP_504_GATEWAY_TIMEOUT if "timed out" in str(exc).lower() else status.HTTP_503_SERVICE_UNAVAILABLE
        raise HTTPException(status_code=code, detail="AI 服务暂时不可用，原始内容已保留，请稍后重试或手工填写") from exc
    try:
        parsed = parse_mobile_ai_draft(raw, draft_type)
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="AI 草稿格式异常，请重试或手工填写") from exc
    parsed["source_refs"] = list(dict.fromkeys(refs))
    generated_at = datetime.now(timezone.utc)
    draft_id = f"AID{generated_at:%Y%m%d%H%M%S}-{uuid4().hex[:8]}"
    conversation = AssistantConversation(
        conversation_no=draft_id,
        user_id=current_user.id,
        username_snapshot=current_user.username,
        channel="android",
        context_type=draft_type,
        context_id=str(payload.task_id or payload.approval_id or payload.project_id or "text"),
        operation=f"mobile.{draft_type}.draft",
        user_message=f"[内容未留存，长度 {len(payload.text or '')}]",
        assistant_message=json.dumps(
            {
                "content_redacted": True,
                "field_names": sorted(parsed["fields"].keys()),
                "warning_count": len(parsed["warnings"]),
            },
            ensure_ascii=False,
        ),
        source="hermes",
        model_name=settings.hermes_model,
        status="completed",
        payload_json={
            "draft_only": True,
            "source_refs": parsed["source_refs"],
            "context_revision": payload.context_revision,
            "content_retention": "none",
        },
    )
    db.add(conversation)
    write_audit_log(
        db,
        action_type="mobile_ai_draft_generate",
        resource_type="assistant_conversation",
        resource_id=draft_id,
        user=current_user,
        request=request,
        after_data={"draft_type": draft_type, "source_refs": parsed["source_refs"], "draft_only": True},
    )
    db.commit()
    return MobileAssistantDraftResponse(
        draft_id=draft_id,
        draft_type=draft_type,
        fields=parsed["fields"],
        warnings=parsed["warnings"],
        source_refs=parsed["source_refs"],
        model=settings.hermes_model,
        generated_at=generated_at,
    )


@router.post("/assistant/drafts/followup", response_model=MobileAssistantDraftResponse)
def mobile_followup_draft(payload: MobileAssistantDraftRequest, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> MobileAssistantDraftResponse:
    return _create_ai_draft("followup", payload, request, db, current_user)


@router.post("/assistant/drafts/approval-opinion", response_model=MobileAssistantDraftResponse)
def mobile_approval_opinion_draft(payload: MobileAssistantDraftRequest, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> MobileAssistantDraftResponse:
    return _create_ai_draft("approval_opinion", payload, request, db, current_user)


@router.post("/assistant/drafts/project-summary", response_model=MobileAssistantDraftResponse)
def mobile_project_summary_draft(payload: MobileAssistantDraftRequest, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> MobileAssistantDraftResponse:
    return _create_ai_draft("project_summary", payload, request, db, current_user)


def mobile_adoption_summary(
    *,
    eligible_users: int,
    active_user_ids: set[int],
    feedback_rows: list[Any],
    telemetry_events: list[dict[str, Any]],
) -> dict[str, Any]:
    feature_usage: dict[str, int] = {}
    followup_durations: list[int] = []
    for event in telemetry_events:
        if event.get("event_type") == "feature_usage" and event.get("code"):
            code = str(event["code"])
            feature_usage[code] = feature_usage.get(code, 0) + 1
        if event.get("event_type") == "form_timing" and event.get("code") == "followup" and isinstance(event.get("duration_ms"), int):
            followup_durations.append(int(event["duration_ms"]))
    resolved_hours = [
        (row.resolved_at - row.created_at).total_seconds() / 3600
        for row in feedback_rows
        if row.resolved_at is not None and row.created_at is not None
    ]
    feedback_statuses: dict[str, int] = {}
    for row in feedback_rows:
        feedback_statuses[row.status] = feedback_statuses.get(row.status, 0) + 1
    ai_requested = feature_usage.get("ai_draft_requested", 0)
    ai_success = feature_usage.get("ai_draft_structured_success", 0)
    ai_adopted = feature_usage.get("ai_draft_adopted", 0)
    return {
        "eligible_users": eligible_users,
        "weekly_active_users": len(active_user_ids),
        "weekly_active_rate": round(len(active_user_ids) * 100 / eligible_users, 2) if eligible_users else 0.0,
        "feature_usage": feature_usage,
        "followup_form_avg_ms": int(sum(followup_durations) / len(followup_durations)) if followup_durations else None,
        "followup_form_p50_ms": int(statistics.median(followup_durations)) if followup_durations else None,
        "feedback": feedback_statuses,
        "feedback_resolution_avg_hours": round(sum(resolved_hours) / len(resolved_hours), 2) if resolved_hours else None,
        "ai_draft_success_rate": round(ai_success * 100 / ai_requested, 2) if ai_requested else None,
        "ai_draft_adoption_rate": round(ai_adopted * 100 / ai_success, 2) if ai_success else None,
    }


@router.get("/admin/adoption/overview")
def mobile_admin_adoption_overview(
    days: int = Query(default=7, ge=1, le=30),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require_feedback_admin(db, current_user)
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    eligible_users = int(
        db.scalar(
            select(func.count(func.distinct(MobileSession.user_id)))
            .join(User, User.id == MobileSession.user_id)
            .where(
                MobileSession.revoked_at.is_(None),
                User.is_active.is_(True),
                User.status == "active",
            )
        )
        or 0
    )
    active_user_ids = set(
        db.scalars(
            select(MobileSession.user_id)
            .join(User, User.id == MobileSession.user_id)
            .where(
                MobileSession.revoked_at.is_(None),
                MobileSession.last_used_at >= since,
                User.is_active.is_(True),
                User.status == "active",
            )
            .distinct()
        ).all()
    )
    feedback_rows = list(db.scalars(select(MobileFeedback).where(MobileFeedback.created_at >= since)).all())
    telemetry_rows = list(db.scalars(select(MobileTelemetryRecord).where(MobileTelemetryRecord.occurred_at >= since)).all())
    events = [
        {
            "event_type": row.event_type,
            "code": row.code,
            "duration_ms": row.duration_ms,
        }
        for row in telemetry_rows
    ]
    summary = mobile_adoption_summary(
        eligible_users=eligible_users,
        active_user_ids=active_user_ids,
        feedback_rows=feedback_rows,
        telemetry_events=events,
    )
    return {"days": days, "generated_at": now.isoformat(), **summary}


__all__ = ["mobile_adoption_summary", "parse_mobile_ai_draft", "router"]

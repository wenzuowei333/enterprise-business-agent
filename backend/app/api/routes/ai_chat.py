from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.config import settings
from app.core.database import SessionLocal, get_db
from app.models import AiChatRun, AiConversation, AiMessage, AiUsageEvent, User
from app.schemas.ai_chat import (
    AiChatCancelResponse,
    AiChatConversationPublic,
    AiChatMessagePublic,
    AiChatRunPublic,
    AiChatStreamRequest,
)
from app.services.ai_chat_service import prepare_chat_run, require_ai_chat_enabled
from app.services.audit_service import write_audit_log
from app.services.hermes_ai_service import HermesCancelledError, stream_hermes_chat
from app.services.permission_service import has_permission


router = APIRouter(prefix="/ai/chat", tags=["ai-chat"])


def _require_chat_access(db: Session, user: User) -> None:
    require_ai_chat_enabled()
    if not has_permission(db, user, "exception_center.view") or not has_permission(db, user, "crm_insight.view"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="当前账号没有异常处理助手权限")


def _sse(event: str, data: dict[str, Any], event_id: int | None = None) -> str:
    prefix = f"id: {event_id}\n" if event_id is not None else ""
    return f"{prefix}event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def _message_public(row: AiMessage) -> AiChatMessagePublic:
    payload = row.payload_json if isinstance(row.payload_json, dict) else {}
    context_meta = payload.get("context_meta") if isinstance(payload.get("context_meta"), dict) else {}
    artifacts = payload.get("artifacts") if isinstance(payload.get("artifacts"), list) else []
    return AiChatMessagePublic(
        message_no=row.message_no,
        sequence_no=row.sequence_no,
        role=row.role,
        content=row.content,
        status=row.status,
        request_id=row.request_id,
        model_name=row.model_name,
        source_refs=list(row.source_refs_json or []),
        context_meta=context_meta,
        artifacts=[item for item in artifacts if isinstance(item, dict)],
        created_at=row.created_at,
    )


def _run_public(db: Session, run: AiChatRun) -> AiChatRunPublic:
    conversation = db.get(AiConversation, run.conversation_id)
    return AiChatRunPublic(
        run_no=run.run_no,
        conversation_no=conversation.conversation_no if conversation else "",
        status=run.status,
        request_id=run.request_id,
        model_name=run.model_name,
        provider_request_id=run.provider_request_id,
        usage=run.usage_json or {},
        error_code=run.error_code,
        started_at=run.started_at,
        completed_at=run.completed_at,
        cancelled_at=run.cancelled_at,
    )


@router.get("/conversations", response_model=list[AiChatConversationPublic])
def list_conversations(
    limit: int = 30,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[AiChatConversationPublic]:
    _require_chat_access(db, current_user)
    rows = list(
        db.scalars(
            select(AiConversation)
            .where(
                AiConversation.actor_user_id == current_user.id,
                AiConversation.channel == "exception_center_web",
                AiConversation.source_system == "global_ai_chat",
            )
            .order_by(AiConversation.updated_at.desc())
            .limit(max(1, min(limit, 50)))
        ).all()
    )
    result = []
    for row in rows:
        messages = list(
            db.scalars(select(AiMessage).where(AiMessage.conversation_id == row.id).order_by(AiMessage.sequence_no)).all()
        )
        metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
        result.append(
            AiChatConversationPublic(
                conversation_no=row.conversation_no,
                channel=row.channel,
                status=row.status,
                title=str(metadata.get("title") or "新会话"),
                model_name=row.model_name,
                message_count=len(messages),
                last_message=next((item.content[:120] for item in reversed(messages) if item.content), ""),
                context_type=row.context_type,
                context_id=row.context_id,
                operation=row.operation,
                evidence_version=str(metadata.get("evidence_version") or "") or None,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
        )
    return result


@router.get("/conversations/{conversation_no}/messages", response_model=list[AiChatMessagePublic])
def list_messages(
    conversation_no: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[AiChatMessagePublic]:
    _require_chat_access(db, current_user)
    conversation = db.scalar(
        select(AiConversation).where(
            AiConversation.conversation_no == conversation_no,
            AiConversation.actor_user_id == current_user.id,
            AiConversation.source_system == "global_ai_chat",
        )
    )
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI 会话不存在")
    rows = list(db.scalars(select(AiMessage).where(AiMessage.conversation_id == conversation.id).order_by(AiMessage.sequence_no)).all())
    return [_message_public(row) for row in rows]


@router.post("/streams")
def create_stream(
    payload: AiChatStreamRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    _require_chat_access(db, current_user)
    run, conversation, provider_messages, context_label, context_ready, artifacts = prepare_chat_run(
        db,
        current_user,
        payload,
    )
    if not provider_messages:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"message": "该请求已提交", "run_no": run.run_no})
    db.commit()

    def cancelled() -> bool:
        with SessionLocal() as check_db:
            current_status = check_db.scalar(select(AiChatRun.status).where(AiChatRun.id == run.id))
            return current_status in {"cancel_requested", "cancelled"}

    def events():  # noqa: ANN202
        event_id = 1
        answer_parts: list[str] = []
        usage: dict[str, Any] = {}
        started = datetime.now(timezone.utc)
        with SessionLocal() as stream_db:
            stream_run = stream_db.get(AiChatRun, run.id)
            stream_conversation = stream_db.get(AiConversation, conversation.id)
            assistant_message = stream_db.get(AiMessage, run.assistant_message_id)
            if stream_run is None or stream_conversation is None or assistant_message is None:
                yield _sse("error", {"code": "chat_run_missing", "message": "AI 会话初始化失败", "retryable": True})
                return
            stream_run.status = "streaming"
            stream_run.started_at = started
            stream_db.commit()
            yield _sse("run_started", {"run_no": run.run_no, "conversation_no": conversation.conversation_no, "request_id": run.request_id}, event_id)
            event_id += 1
            yield _sse("context_ready", context_ready or {"label": context_label}, event_id)
            event_id += 1
            yield _sse("message_started", {"message_no": assistant_message.message_no}, event_id)
            event_id += 1
            try:
                for item in stream_hermes_chat(provider_messages, cancel_requested=cancelled):
                    if item["type"] == "metadata":
                        stream_run.provider_request_id = item.get("provider_request_id")
                    elif item["type"] == "delta":
                        text = str(item.get("text") or "")
                        answer_parts.append(text)
                        yield _sse("delta", {"text": text}, event_id)
                        event_id += 1
                    elif item["type"] == "usage":
                        usage = dict(item.get("usage") or {})
                        yield _sse("usage", usage, event_id)
                        event_id += 1
                    elif item["type"] == "heartbeat":
                        yield ": ping\n\n"
                completed_at = datetime.now(timezone.utc)
                assistant_message.content = "".join(answer_parts).strip()
                assistant_message.status = "completed"
                stream_run.status = "completed"
                stream_run.usage_json = usage
                stream_run.completed_at = completed_at
                stream_conversation.status = "active"
                stream_conversation.model_name = settings.hermes_model
                stream_conversation.updated_at = completed_at
                usage_event = AiUsageEvent(
                    event_no=f"AI-USAGE-{uuid4().hex.upper()}",
                    conversation_id=stream_conversation.id,
                    message_id=assistant_message.id,
                    request_id=stream_run.request_id,
                    provider_request_id=stream_run.provider_request_id,
                    service_identity="exception_ai_service",
                    domain="global",
                    operation=payload.operation,
                    status="completed",
                    model_name=settings.hermes_model,
                    prompt_version="exception-chat.v1",
                    contract_version="global-ai-stream.v1",
                    latency_ms=max(0, int((completed_at - started).total_seconds() * 1000)),
                    prompt_tokens=usage.get("prompt_tokens"),
                    completion_tokens=usage.get("completion_tokens"),
                    total_tokens=usage.get("total_tokens"),
                    attempts=1,
                    source_system="global_ai_chat",
                    metadata_json={"channel": payload.channel},
                    occurred_at=completed_at,
                )
                stream_db.add(usage_event)
                write_audit_log(
                    stream_db,
                    action_type="ai_chat_message",
                    resource_type="ai_conversation",
                    resource_id=stream_conversation.conversation_no,
                    user=current_user,
                    request=request,
                    after_data={
                        "run_no": stream_run.run_no,
                        "request_id": stream_run.request_id,
                        "status": "completed",
                        "model": settings.hermes_model,
                        "usage": usage,
                    },
                )
                stream_db.commit()
                for artifact in artifacts:
                    yield _sse("artifact", {"artifact": artifact}, event_id)
                    event_id += 1
                yield _sse("message_completed", {"message": _message_public(assistant_message).model_dump(mode="json")}, event_id)
                event_id += 1
                yield _sse("done", {"run_no": run.run_no}, event_id)
            except GeneratorExit:
                stream_run.status = "cancelled"
                stream_run.cancelled_at = datetime.now(timezone.utc)
                assistant_message.content = "".join(answer_parts).strip()
                assistant_message.status = "cancelled"
                stream_db.commit()
                return
            except HermesCancelledError:
                stream_run.status = "cancelled"
                stream_run.cancelled_at = datetime.now(timezone.utc)
                assistant_message.content = "".join(answer_parts).strip()
                assistant_message.status = "cancelled"
                stream_db.commit()
                yield _sse("cancelled", {"run_no": run.run_no, "partial": bool(answer_parts)}, event_id)
                event_id += 1
                yield _sse("done", {"run_no": run.run_no, "status": "cancelled"}, event_id)
            except Exception as exc:
                stream_run.status = "failed"
                stream_run.error_code = type(exc).__name__[:120]
                assistant_message.content = "".join(answer_parts).strip()
                assistant_message.status = "failed"
                stream_db.commit()
                yield _sse("error", {"code": "ai_stream_failed", "message": "AI 回复生成失败，请稍后重试", "retryable": True, "request_id": run.request_id}, event_id)
                event_id += 1
                yield _sse("done", {"run_no": run.run_no, "status": "failed"}, event_id)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/runs/{run_no}", response_model=AiChatRunPublic)
def get_run(
    run_no: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AiChatRunPublic:
    _require_chat_access(db, current_user)
    run = db.scalar(select(AiChatRun).where(AiChatRun.run_no == run_no, AiChatRun.actor_user_id == current_user.id))
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI 运行记录不存在")
    return _run_public(db, run)


@router.post("/runs/{run_no}/cancel", response_model=AiChatCancelResponse)
def cancel_run(
    run_no: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AiChatCancelResponse:
    _require_chat_access(db, current_user)
    run = db.scalar(
        select(AiChatRun)
        .where(AiChatRun.run_no == run_no, AiChatRun.actor_user_id == current_user.id)
        .with_for_update()
    )
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI 运行记录不存在")
    if run.status in {"created", "streaming"}:
        run.status = "cancel_requested"
        db.commit()
    return AiChatCancelResponse(run_no=run.run_no, status=run.status)


@router.delete("/conversations/{conversation_no}")
def delete_conversation(
    conversation_no: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, bool]:
    _require_chat_access(db, current_user)
    conversation = db.scalar(
        select(AiConversation).where(
            AiConversation.conversation_no == conversation_no,
            AiConversation.actor_user_id == current_user.id,
            AiConversation.source_system == "global_ai_chat",
        )
    )
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI 会话不存在")
    active = db.scalar(
        select(func.count()).select_from(AiChatRun).where(
            AiChatRun.conversation_id == conversation.id,
            AiChatRun.status.in_(["created", "streaming", "cancel_requested"]),
        )
    )
    if active:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="当前会话仍在生成回复")
    db.delete(conversation)
    db.commit()
    return {"deleted": True}

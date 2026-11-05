from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.routes.crm_assistant import _build_migrated_context, _operation_instruction, _system_prompt
from app.core.config import settings
from app.models import (
    AiChatRun,
    AiContextSnapshotRecord,
    AiConversation,
    AiMessage,
    ExceptionAction,
    ExceptionCase,
    ExceptionDiagnosis,
    ExceptionEvent,
    ExceptionEvidence,
    User,
)
from app.schemas.ai_chat import AiChatContextRequest, AiChatStreamRequest
from app.services.exception_center_service import available_exception_action_types, scoped_exception_stmt
from app.services.hermes_ai_service import prepare_exception_evidence, redact_exception_evidence


CASE_ANALYSIS_OPERATION = "exception.case_analysis"


def _code(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex.upper()}"


def require_ai_chat_enabled() -> None:
    if not (
        settings.exception_center_enabled
        and settings.exception_ai_enabled
        and settings.exception_ai_global_enabled
        and settings.exception_ai_chat_enabled
    ):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="异常处理助手暂未开放")


def _visible_context_cases(db: Session, user: User, context: AiChatContextRequest) -> list[ExceptionCase]:
    stmt = scoped_exception_stmt(db, user)
    if context.scope in {"case", "selected_cases"}:
        if not context.case_nos:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="请选择可见的异常案件")
        rows = list(db.scalars(stmt.where(ExceptionCase.case_no.in_(context.case_nos)).order_by(ExceptionCase.id)).all())
        by_no = {row.case_no: row for row in rows}
        if len(by_no) != len(context.case_nos):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="异常案件不存在或当前账号无权查看")
        return [by_no[case_no] for case_no in context.case_nos]

    filters = context.filters
    if value := str(filters.get("domain") or "").strip():
        stmt = stmt.where(ExceptionCase.domain == value)
    if value := str(filters.get("status") or "").strip():
        stmt = stmt.where(ExceptionCase.status == value)
    if value := str(filters.get("severity") or "").strip():
        stmt = stmt.where(ExceptionCase.severity == value)
    if value := str(filters.get("occurrence_type") or "").strip():
        stmt = stmt.where(ExceptionCase.occurrence_type == value)
    if value := str(filters.get("rule_code") or "").strip():
        stmt = stmt.where(ExceptionCase.rule_code == value)
    if value := str(filters.get("q") or "").strip()[:120]:
        pattern = f"%{value}%"
        stmt = stmt.where(
            or_(
                ExceptionCase.case_no.ilike(pattern),
                ExceptionCase.title.ilike(pattern),
                ExceptionCase.resource_name.ilike(pattern),
            )
        )
    return list(db.scalars(stmt.order_by(ExceptionCase.last_seen_at.desc()).limit(30)).all())


def build_chat_context(db: Session, user: User, context: AiChatContextRequest) -> tuple[dict[str, Any], list[str], str]:
    global_context, global_snapshot = _build_migrated_context(db, user, required_permission="crm_insight.view")
    cases = _visible_context_cases(db, user, context)
    exception_rows = [
        {
            "case_no": row.case_no,
            "domain": row.domain,
            "rule_code": row.rule_code,
            "title": row.title,
            "severity": row.severity,
            "status": row.status,
            "occurrence_type": row.occurrence_type,
            "resource_type": row.resource_type,
            "resource_code": row.resource_code,
            "resource_name": row.resource_name,
            "reason": row.reason,
            "initial_guidance": row.initial_guidance,
            "affected_rows": row.affected_rows,
            "affected_amount": row.affected_amount,
            "affected_quantity": row.affected_quantity,
            "assignee_user_id": row.assignee_user_id,
            "due_at": row.due_at,
            "data_date": row.data_date,
            "evidence_version": row.evidence_version,
        }
        for row in cases
    ]
    scoped_context = redact_exception_evidence(
        {
            "global_business": global_context,
            "exception_center": {
                "scope": context.scope,
                "filters": context.filters if context.scope == "current_filters" else {},
                "case_count": len(exception_rows),
                "cases": exception_rows,
            },
        }
    )
    refs = list(dict.fromkeys([*global_snapshot.source_refs, *(f"exception_case:{row.case_no}" for row in cases)]))
    if context.scope == "case":
        label = f"当前案件 · {cases[0].case_no}"
    elif context.scope == "selected_cases":
        label = f"已选案件 · {len(cases)} 条"
    else:
        label = f"当前筛选 · {len(cases)} 条样本"
    return scoped_context, refs, label


def _case_context_meta(case: ExceptionCase, *, evidence_truncated: bool) -> dict[str, Any]:
    return {
        "case_no": case.case_no,
        "title": case.title,
        "severity": case.severity,
        "status": case.status,
        "evidence_version": case.evidence_version,
        "evidence_truncated": evidence_truncated,
    }


def _limit_case_context(value: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    byte_limit = min(
        max(1024, settings.exception_evidence_max_bytes),
        max(256, settings.exception_evidence_max_tokens) * 4,
    )
    if len(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")) <= byte_limit:
        return value, False
    bounded = dict(value)
    bounded["authorized_business_context"] = {"truncated": True}
    bounded["recent_events"] = list(bounded.get("recent_events") or [])[:5]
    bounded["recent_controlled_actions"] = list(bounded.get("recent_controlled_actions") or [])[:3]
    if len(json.dumps(bounded, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")) > byte_limit:
        bounded["recent_events"] = []
        bounded["recent_controlled_actions"] = []
        bounded["latest_structured_diagnosis"] = None
    if len(json.dumps(bounded, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")) > byte_limit:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="案件上下文超过安全分析上限")
    return bounded, True


def _case_analysis_context(
    db: Session,
    user: User,
    context: AiChatContextRequest,
) -> tuple[dict[str, Any], list[str], str, dict[str, Any], list[dict[str, Any]], ExceptionCase]:
    if not settings.exception_ai_case_analysis_enabled:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="单案 AI 分析暂未开放")
    if context.scope != "case" or len(context.case_nos) != 1 or context.filters:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="单案分析必须且只能指定一个案件")
    case = _visible_context_cases(db, user, context)[0]
    evidence = db.scalar(
        select(ExceptionEvidence).where(
            ExceptionEvidence.case_id == case.id,
            ExceptionEvidence.evidence_version == case.evidence_version,
        )
    )
    projected_evidence, evidence_stats = prepare_exception_evidence(
        dict(evidence.data_json or {}) if evidence else {},
        domain=case.domain,
    )
    diagnosis = db.scalar(
        select(ExceptionDiagnosis)
        .where(ExceptionDiagnosis.case_id == case.id, ExceptionDiagnosis.evidence_version == case.evidence_version)
        .order_by(ExceptionDiagnosis.id.desc())
        .limit(1)
    )
    events = list(
        db.scalars(select(ExceptionEvent).where(ExceptionEvent.case_id == case.id).order_by(ExceptionEvent.id.desc()).limit(10)).all()
    )
    actions = list(
        db.scalars(select(ExceptionAction).where(ExceptionAction.case_id == case.id).order_by(ExceptionAction.id.desc()).limit(5)).all()
    )
    global_context, global_snapshot = _build_migrated_context(db, user, required_permission="crm_insight.view")
    context_meta = _case_context_meta(case, evidence_truncated=bool(evidence_stats.get("evidence_truncated")))
    allowed_actions = available_exception_action_types(db, case, user)
    safe_action_path = (
        case.action_path
        if case.action_path and case.action_path.startswith("/") and not case.action_path.startswith("//")
        else None
    )
    artifact = {
        "type": "exception_case_analysis",
        "case": context_meta,
        "action_path": safe_action_path,
        "available_actions": allowed_actions,
        "remediation_enabled": bool(settings.exception_ai_remediation_enabled),
        "source_refs": [f"exception_case:{case.case_no}"],
        "evidence_truncated": context_meta["evidence_truncated"],
    }
    diagnosis_context = None
    if diagnosis is not None:
        diagnosis_context = {
            "root_cause_code": diagnosis.root_cause_code,
            "summary": diagnosis.summary,
            "confidence": diagnosis.confidence,
            "disposition": diagnosis.disposition,
            "evidence_refs": diagnosis.evidence_refs_json,
            "impact": diagnosis.impact_json,
            "recommended_steps": diagnosis.recommended_steps_json,
            "missing_evidence": diagnosis.missing_evidence_json,
            "diagnosed_at": diagnosis.diagnosed_at,
        }
    raw_context = {
        "case": {
            **context_meta,
            "domain": case.domain,
            "rule_code": case.rule_code,
            "occurrence_type": case.occurrence_type,
            "resource_type": case.resource_type,
            "resource_id": case.resource_id,
            "resource_code": case.resource_code,
            "resource_name": case.resource_name,
            "source_type": case.source_type,
            "source_id": case.source_id,
            "source_batch_kind": case.source_batch_kind,
            "source_batch_id": case.source_batch_id,
            "reason": case.reason,
            "initial_guidance": case.initial_guidance,
            "affected_rows": case.affected_rows,
            "affected_amount": case.affected_amount,
            "affected_quantity": case.affected_quantity,
            "data_date": case.data_date,
            "detected_at": case.detected_at,
            "last_seen_at": case.last_seen_at,
        },
        "evidence": projected_evidence,
        "evidence_limits": evidence_stats,
        "latest_structured_diagnosis": diagnosis_context,
        "recent_events": [
            {
                "event_type": row.event_type,
                "from_status": row.from_status,
                "to_status": row.to_status,
                "detail": row.detail_json,
                "created_at": row.created_at,
            }
            for row in events
        ],
        "recent_controlled_actions": [
            {
                "action_no": row.action_no,
                "action_type": row.action_type,
                "status": row.status,
                "allowed": row.allowed,
                "blockers": row.blockers_json,
                "evidence_version": row.evidence_version,
                "verification": row.verification_json,
                "created_at": row.created_at,
            }
            for row in actions
        ],
        "deterministic_action_catalog": allowed_actions,
        "original_record_path": safe_action_path,
        "authorized_business_context": global_context,
    }
    safe_context, context_truncated = _limit_case_context(redact_exception_evidence(raw_context))
    if context_truncated:
        context_meta["evidence_truncated"] = True
        if isinstance(safe_context.get("case"), dict):
            safe_context["case"]["evidence_truncated"] = True
        artifact["evidence_truncated"] = True
    evidence_refs = list(projected_evidence.get("canonical_evidence_refs") or [])
    refs = list(dict.fromkeys([*global_snapshot.source_refs, f"exception_case:{case.case_no}", *evidence_refs]))
    return safe_context, refs, f"当前案件 · {case.case_no}", context_meta, [artifact], case


def _case_analysis_instruction() -> str:
    return """你正在分析一个确定的异常案件。必须使用中文 Markdown，并严格按以下标题输出：
## 结论摘要
## 异常背景
## 原因分析
### 证据确认
### 合理推断
## 证据依据
## 具体解决方案
## 验证方法
## 风险与注意事项
## 仍需补充的信息

只能把上下文中明确出现的信息写入“证据确认”；推断必须放入“合理推断”并说明验证方式。若 evidence_truncated 为 true，必须明确说明上下文已裁剪。不得声称已经执行修复、审批、重建或任何业务写入；受控动作是否可用只以 deterministic_action_catalog 为准。"""


def _acquire_case_conversation_lock(db: Session, user_id: int, case_no: str) -> None:
    bind = db.get_bind()
    if bind is None or bind.dialect.name != "postgresql":
        return
    digest = hashlib.sha256(f"ai-case-conversation:{user_id}:{case_no}".encode()).digest()
    lock_key = int.from_bytes(digest[:8], byteorder="big", signed=True)
    db.execute(select(func.pg_advisory_xact_lock(lock_key)))


def prepare_chat_run(
    db: Session,
    user: User,
    payload: AiChatStreamRequest,
) -> tuple[AiChatRun, AiConversation, list[dict[str, str]], str, dict[str, Any], list[dict[str, Any]]]:
    existing = db.scalar(
        select(AiChatRun).where(
            AiChatRun.actor_user_id == user.id,
            AiChatRun.client_request_id == payload.client_request_id,
        )
    )
    if existing is not None:
        conversation = db.get(AiConversation, existing.conversation_id)
        if conversation is None:
            raise RuntimeError("AI conversation is missing")
        return existing, conversation, [], "重复请求", {}, []

    is_case_analysis = payload.operation == CASE_ANALYSIS_OPERATION
    context_meta: dict[str, Any] = {}
    artifacts: list[dict[str, Any]] = []
    case: ExceptionCase | None = None
    if is_case_analysis:
        context, source_refs, context_label, context_meta, artifacts, case = _case_analysis_context(db, user, payload.context)
        _acquire_case_conversation_lock(db, user.id, case.case_no)
        concurrent_existing = db.scalar(
            select(AiChatRun).where(
                AiChatRun.actor_user_id == user.id,
                AiChatRun.client_request_id == payload.client_request_id,
            )
        )
        if concurrent_existing is not None:
            concurrent_conversation = db.get(AiConversation, concurrent_existing.conversation_id)
            if concurrent_conversation is None:
                raise RuntimeError("AI conversation is missing")
            return concurrent_existing, concurrent_conversation, [], "重复请求", {}, []
    else:
        context, source_refs, context_label = build_chat_context(db, user, payload.context)

    conversation = None
    if is_case_analysis and case is not None:
        conversation = db.scalar(
            select(AiConversation).where(
                AiConversation.actor_user_id == user.id,
                AiConversation.channel == payload.channel,
                AiConversation.source_system == "global_ai_chat",
                AiConversation.context_type == "exception_case",
                AiConversation.context_id == case.case_no,
            )
        )
        if payload.conversation_no and (conversation is None or conversation.conversation_no != payload.conversation_no):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="当前会话不属于该异常案件")
    elif payload.conversation_no:
        conversation = db.scalar(
            select(AiConversation)
            .where(
                AiConversation.conversation_no == payload.conversation_no,
                AiConversation.actor_user_id == user.id,
                AiConversation.channel == payload.channel,
                AiConversation.source_system == "global_ai_chat",
            )
            .with_for_update()
        )
        if conversation is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI 会话不存在")

    reused = conversation is not None
    if conversation is None:
        conversation = AiConversation(
            conversation_no=_code("AI-CHAT"),
            domain=case.domain if case is not None else "global",
            channel=payload.channel,
            context_type="exception_case" if case is not None else None,
            context_id=case.case_no if case is not None else None,
            operation=payload.operation,
            status="active",
            actor_user_id=user.id,
            created_by_user_id=user.id,
            model_name=settings.hermes_model,
            source_system="global_ai_chat",
            metadata_json={
                "title": f"{case.case_no} · {case.title}" if case is not None else payload.message.strip()[:40],
                "evidence_version": case.evidence_version if case is not None else None,
            },
        )
        db.add(conversation)
        db.flush()
    elif case is not None:
        metadata = dict(conversation.metadata_json or {})
        metadata.update({"title": f"{case.case_no} · {case.title}", "evidence_version": case.evidence_version})
        conversation.metadata_json = metadata
        conversation.operation = payload.operation

    next_sequence = int(
        db.scalar(select(func.coalesce(func.max(AiMessage.sequence_no), 0)).where(AiMessage.conversation_id == conversation.id)) or 0
    ) + 1
    request_id = _code("AI-CHAT-REQ")
    message_payload = {
        "context_scope": payload.context.scope,
        "context_label": context_label,
        "context_meta": context_meta,
        "artifacts": artifacts,
    }
    user_message = AiMessage(
        message_no=_code("AI-MSG"),
        conversation_id=conversation.id,
        sequence_no=next_sequence,
        role="user",
        content=payload.message.strip(),
        status="completed",
        created_by_user_id=user.id,
        request_id=request_id,
        source_refs_json=source_refs,
        source_system="global_ai_chat",
        payload_json=message_payload,
    )
    assistant_message = AiMessage(
        message_no=_code("AI-MSG"),
        conversation_id=conversation.id,
        sequence_no=next_sequence + 1,
        role="assistant",
        content="",
        status="streaming",
        created_by_user_id=user.id,
        request_id=request_id,
        model_name=settings.hermes_model,
        contract_version="global-ai-stream.v1",
        source_refs_json=source_refs,
        source_system="global_ai_chat",
        payload_json=message_payload,
    )
    db.add_all([user_message, assistant_message])
    db.flush()
    run = AiChatRun(
        run_no=_code("AI-RUN"),
        conversation_id=conversation.id,
        user_message_id=user_message.id,
        assistant_message_id=assistant_message.id,
        actor_user_id=user.id,
        client_request_id=payload.client_request_id,
        request_id=request_id,
        status="created",
        model_name=settings.hermes_model,
    )
    snapshot = AiContextSnapshotRecord(
        snapshot_no=_code("AI-CTX"),
        conversation_id=conversation.id,
        domain=case.domain if case is not None else "global",
        context_version=(f"exception-case:{case.evidence_version}" if case is not None else f"exception-chat:{datetime.now(timezone.utc).isoformat()}"),
        resource_type="exception_case" if case is not None else "exception_context",
        resource_id=case.case_no if case is not None else (payload.context.case_nos[0] if payload.context.scope == "case" and payload.context.case_nos else None),
        structured_fields_json=context,
        source_refs_json=source_refs,
        redacted_fields_json=[],
        created_by_user_id=user.id,
        source_system="global_ai_chat",
    )
    db.add_all([run, snapshot])
    db.flush()

    history_rows = list(
        db.scalars(
            select(AiMessage)
            .where(
                AiMessage.conversation_id == conversation.id,
                AiMessage.role.in_(["user", "assistant"]),
                AiMessage.status.in_(["completed", "streaming"]),
            )
            .order_by(AiMessage.sequence_no.desc())
            .limit(20)
        ).all()
    )
    history = [
        {"role": row.role, "content": row.content}
        for row in reversed(history_rows)
        if row.content and row.id not in {user_message.id, assistant_message.id}
    ]
    instruction = _case_analysis_instruction() if is_case_analysis else _operation_instruction(payload.operation)
    provider_messages = [
        {"role": "system", "content": f"{_system_prompt()}\n\n{instruction}"},
        *history,
        {
            "role": "user",
            "content": (
                f"操作: {payload.operation}\n"
                f"用户问题: {payload.message.strip()}\n"
                f"异常中心上下文 JSON: {json.dumps(context, ensure_ascii=False, default=str)}"
            ),
        },
    ]
    event_context = {"label": context_label, "conversation_reused": reused, **context_meta}
    return run, conversation, provider_messages, context_label, event_context, artifacts

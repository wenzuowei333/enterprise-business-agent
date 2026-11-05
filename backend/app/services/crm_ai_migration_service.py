from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    AiActionExecution,
    AiActionProposal,
    AiContextSnapshotRecord,
    AiConversation,
    AiInsight,
    AiMessage,
    AiSecurityEvent,
    AiUsageEvent,
    AssistantConversation,
    AuditLog,
    CrmProjectInsight,
)
from app.schemas.crm import CrmAssistantConversationPublic, CrmProjectInsightPublic
from app.schemas.global_ai import AiContextPayload, AiContextRequest, AiContextSnapshot, GlobalAiResult
from app.services.ai_context_service import AiContextProvider


CRM_CONTEXT_FIELDS = {
    "user",
    "permission_flags",
    "summary",
    "projects",
    "risky_tasks",
    "open_work_items",
}

_SAFE_AUDIT_FIELDS = {
    "operation",
    "source",
    "status",
    "channel",
    "context_type",
    "context_id",
    "permission",
    "ai_request_id",
    "ai_contract_version",
    "ai_status",
    "ai_latency_ms",
    "ai_attempts",
    "created",
    "skipped",
    "deleted",
    "work_item_created",
}


def crm_ai_unified_enabled() -> bool:
    return settings.exception_ai_global_enabled and settings.exception_ai_crm_enabled


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _source_refs(context: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for project in context.get("projects", []):
        if isinstance(project, dict) and project.get("id") is not None:
            refs.append(f"crm_project:{project['id']}")
    for task in context.get("risky_tasks", []):
        if isinstance(task, dict) and task.get("id") is not None:
            refs.append(f"crm_task:{task['id']}")
    for item in context.get("open_work_items", []):
        if isinstance(item, dict) and item.get("id") is not None:
            refs.append(f"work_item:{item['id']}")
    return list(dict.fromkeys(refs))


def build_crm_context_snapshot(
    raw_context: dict[str, Any],
    *,
    actor_user_id: int,
    permission_codes: list[str],
    required_permission: str,
) -> AiContextSnapshot:
    provider = AiContextProvider()
    provider.register(
        "crm",
        lambda _request: AiContextPayload(
            context_version="crm-context.v1",
            fields=raw_context,
            source_refs=_source_refs(raw_context),
        ),
        allowed_fields=CRM_CONTEXT_FIELDS,
        required_permissions={required_permission},
    )
    return provider.build(
        AiContextRequest(
            domain="crm",
            actor_user_id=actor_user_id,
            permission_codes=permission_codes,
        )
    )


def _legacy_payload(metadata: Any) -> dict[str, Any] | list | None:
    value = _dict(metadata)
    if value.get("projection_version") == "crm-ai-stage3.v1":
        payload = value.get("legacy_payload")
        return payload if isinstance(payload, (dict, list)) else None
    return metadata if isinstance(metadata, (dict, list)) else None


def _compatibility(metadata: Any) -> dict[str, Any]:
    return _dict(_dict(metadata).get("compatibility"))


def _confidence_fraction(score: int | None) -> Decimal | None:
    if score is None:
        return None
    return Decimal(max(0, min(100, int(score)))) / Decimal("100")


def _confidence_percent(score: Decimal | None, compatibility: dict[str, Any]) -> int:
    raw = compatibility.get("confidence_score")
    if raw is not None:
        return max(0, min(100, int(raw)))
    return max(0, min(100, int((score or Decimal("0")) * 100)))


def _review_status(status: str) -> str:
    return {
        "draft": "pending",
        "accepted": "accepted",
        "rejected": "rejected",
        "ignored": "rejected",
    }.get(status, status)


def _legacy_review_status(status: str) -> str:
    return {"pending": "draft"}.get(status, status)


def _legacy_insight_status(row: AiInsight) -> str:
    compatibility = _compatibility(row.payload_json)
    return str(compatibility.get("legacy_status") or _legacy_review_status(row.review_status))


def mirror_conversation(
    db: Session,
    legacy: AssistantConversation,
    snapshot: AiContextSnapshot,
    result: GlobalAiResult | None,
) -> AiConversation:
    db.flush()
    legacy_id = str(legacy.id)
    existing = db.scalar(
        select(AiConversation).where(
            AiConversation.source_system == "crm",
            AiConversation.legacy_type == "assistant_conversation",
            AiConversation.legacy_id == legacy_id,
        )
    )
    if existing is not None:
        return existing
    created_at = legacy.created_at or datetime.now(timezone.utc)
    conversation = AiConversation(
        conversation_no=legacy.conversation_no,
        domain="crm",
        channel=legacy.channel,
        session_id=legacy.session_id,
        context_type=legacy.context_type,
        context_id=legacy.context_id,
        operation=legacy.operation,
        status=legacy.status,
        actor_user_id=legacy.user_id,
        created_by_user_id=legacy.user_id,
        model_name=legacy.model_name,
        source_system="crm",
        legacy_type="assistant_conversation",
        legacy_id=legacy_id,
        metadata_json={
            "projection_version": "crm-ai-stage3.v1",
            "legacy_payload": legacy.payload_json,
            "compatibility": {
                "username_snapshot": legacy.username_snapshot,
                "source": legacy.source,
            },
        },
        created_at=created_at,
        updated_at=created_at,
    )
    db.add(conversation)
    db.flush()
    source_refs = result.source_refs if result and result.source_refs else snapshot.source_refs
    common = {
        "conversation_id": conversation.id,
        "status": legacy.status,
        "created_by_user_id": legacy.user_id,
        "request_id": result.request_id if result else None,
        "model_name": result.model if result else legacy.model_name,
        "contract_version": result.contract_version if result else None,
        "source_refs_json": source_refs,
        "source_system": "crm",
        "legacy_id": legacy_id,
        "created_at": created_at,
        "updated_at": created_at,
    }
    db.add_all(
        [
            AiMessage(
                message_no=f"AI-CRM-MSG-{legacy_id}-USER",
                sequence_no=1,
                role="user",
                content=legacy.user_message,
                legacy_type="assistant_conversation.user_message",
                payload_json=None,
                **common,
            ),
            AiMessage(
                message_no=f"AI-CRM-MSG-{legacy_id}-ASSISTANT",
                sequence_no=2,
                role="assistant",
                content=legacy.assistant_message,
                legacy_type="assistant_conversation.assistant_message",
                payload_json=result.model_dump(mode="json") if result else None,
                **common,
            ),
            AiContextSnapshotRecord(
                snapshot_no=f"AI-CRM-CTX-{legacy_id}",
                conversation_id=conversation.id,
                domain=snapshot.domain,
                context_version=snapshot.context_version,
                resource_type=legacy.context_type,
                resource_id=legacy.context_id,
                structured_fields_json=snapshot.structured_fields,
                source_refs_json=snapshot.source_refs,
                redacted_fields_json=snapshot.redacted_fields,
                created_by_user_id=legacy.user_id,
                source_system="crm",
                legacy_type="assistant_conversation.context",
                legacy_id=legacy_id,
                created_at=created_at,
                updated_at=created_at,
            ),
        ]
    )
    return conversation


def mirror_insight(db: Session, legacy: CrmProjectInsight) -> AiInsight:
    db.flush()
    legacy_id = str(legacy.id)
    existing = db.scalar(
        select(AiInsight).where(
            AiInsight.source_system == "crm",
            AiInsight.legacy_type == "crm_project_insight",
            AiInsight.legacy_id == legacy_id,
        )
    )
    source_refs = []
    for prefix, value in (
        ("crm_project", legacy.project_id),
        ("crm_task", legacy.task_id),
        ("customer", legacy.customer_code),
    ):
        if value is not None:
            source_refs.append(f"{prefix}:{value}")
    resource_type = "crm_project" if legacy.project_id is not None else "crm_task"
    resource_id = str(legacy.project_id or legacy.task_id or legacy.customer_code or "") or None
    if existing is None:
        unified = AiInsight(
            insight_no=legacy.insight_no,
            domain="crm",
            insight_type=legacy.insight_type,
            resource_type=resource_type,
            resource_id=resource_id,
            summary=legacy.summary,
            suggested_action=legacy.suggested_action,
            risk_level=legacy.risk_level,
            opportunity_level=legacy.opportunity_level,
            confidence_score=_confidence_fraction(legacy.confidence_score),
            status="active",
            review_status=_review_status(legacy.status),
            reviewed_by_user_id=legacy.reviewed_by_user_id,
            reviewed_at=legacy.reviewed_at,
            review_note=legacy.review_note,
            created_by_user_id=legacy.generated_by_user_id,
            source_refs_json=source_refs,
            evidence_json=legacy.evidence_json,
            source_system="crm",
            legacy_type="crm_project_insight",
            legacy_id=legacy_id,
            payload_json={
                "projection_version": "crm-ai-stage3.v1",
                "legacy_payload": legacy.payload_json,
                "compatibility": {
                    "project_id": legacy.project_id,
                    "task_id": legacy.task_id,
                    "customer_code": legacy.customer_code,
                    "source": legacy.source,
                    "confidence_score": legacy.confidence_score,
                    "legacy_status": legacy.status,
                },
            },
            created_at=legacy.created_at,
            updated_at=legacy.updated_at,
        )
        db.add(unified)
        db.flush()
    else:
        unified = existing
    proposal = db.scalar(
        select(AiActionProposal).where(
            AiActionProposal.source_system == "crm",
            AiActionProposal.legacy_type == "crm_project_insight.action_proposal",
            AiActionProposal.legacy_id == legacy_id,
        )
    )
    if proposal is None:
        db.add(
            AiActionProposal(
                proposal_no=f"AI-CRM-PROP-{legacy_id}",
                insight_id=unified.id,
                domain="crm",
                action_type="crm_insight.review",
                resource_type=resource_type,
                resource_id=resource_id,
                status="proposed" if legacy.status == "draft" else "completed",
                review_status=_review_status(legacy.status),
                risk_level=legacy.risk_level,
                requires_confirmation=True,
                parameters_json={"suggested_action": legacy.suggested_action},
                source_refs_json=source_refs,
                created_by_user_id=legacy.generated_by_user_id,
                reviewed_by_user_id=legacy.reviewed_by_user_id,
                reviewed_at=legacy.reviewed_at,
                review_note=legacy.review_note,
                source_system="crm",
                legacy_type="crm_project_insight.action_proposal",
                legacy_id=legacy_id,
                created_at=legacy.created_at,
                updated_at=legacy.updated_at,
            )
        )
    return unified


def mirror_insight_review(
    db: Session,
    legacy: CrmProjectInsight,
    *,
    action: str,
    reviewer_user_id: int,
    work_item_created: bool,
    idempotency_key: str | None = None,
) -> AiActionExecution | None:
    unified = mirror_insight(db, legacy)
    unified.review_status = _review_status(legacy.status)
    unified.reviewed_by_user_id = legacy.reviewed_by_user_id
    unified.reviewed_at = legacy.reviewed_at
    unified.review_note = legacy.review_note
    unified.updated_at = legacy.updated_at
    payload = _dict(unified.payload_json)
    compatibility = _compatibility(payload)
    compatibility["legacy_status"] = legacy.status
    payload["compatibility"] = compatibility
    unified.payload_json = payload
    proposal = db.scalar(
        select(AiActionProposal).where(
            AiActionProposal.source_system == "crm",
            AiActionProposal.legacy_type == "crm_project_insight.action_proposal",
            AiActionProposal.legacy_id == str(legacy.id),
        )
    )
    if proposal is None:
        raise RuntimeError("Unified CRM AI action proposal is missing")
    proposal.review_status = "rejected" if action == "reject" else "accepted"
    proposal.status = "rejected" if action == "reject" else "completed"
    proposal.reviewed_by_user_id = reviewer_user_id
    proposal.reviewed_at = legacy.reviewed_at
    proposal.review_note = legacy.review_note
    effective_idempotency_key = idempotency_key or f"crm-insight:{legacy.id}:{action}"
    execution = db.scalar(
        select(AiActionExecution).where(
            AiActionExecution.idempotency_key == effective_idempotency_key
        )
    )
    if execution is not None and execution.proposal_id != proposal.id:
        raise RuntimeError("Unified CRM AI idempotency key belongs to another proposal")
    if execution is None:
        execution = AiActionExecution(
            execution_no=f"AI-CRM-EXEC-{legacy.id}-{action.upper()}",
            proposal_id=proposal.id,
            idempotency_key=effective_idempotency_key,
            status="completed",
            attempts=1,
            requested_by_user_id=reviewer_user_id,
            approved_by_user_id=reviewer_user_id,
            executor_identity="human_confirmed_crm_workflow",
            request_json={"action": action},
            result_json={"work_item_created": work_item_created},
            verification_json={"human_confirmed": True},
            started_at=legacy.reviewed_at,
            completed_at=legacy.reviewed_at,
            source_system="crm",
            legacy_type="crm_project_insight.action_execution",
            legacy_id=f"{legacy.id}:{action}",
        )
        db.add(execution)
        db.flush()
    return execution


def mirror_audit_event(
    db: Session,
    audit: AuditLog,
    *,
    result: GlobalAiResult | None = None,
    conversation: AiConversation | None = None,
) -> None:
    db.flush()
    legacy_id = str(audit.id)
    after_data = _dict(audit.after_data)
    safe_fields = {key: after_data[key] for key in _SAFE_AUDIT_FIELDS if key in after_data}
    outcome = str(after_data.get("ai_status") or after_data.get("status") or "completed")[:40]
    security = db.scalar(
        select(AiSecurityEvent).where(
            AiSecurityEvent.source_system == "crm",
            AiSecurityEvent.legacy_type == "audit_log",
            AiSecurityEvent.legacy_id == legacy_id,
        )
    )
    if security is None:
        db.add(
            AiSecurityEvent(
                event_no=f"AI-CRM-SEC-{legacy_id}",
                event_type=audit.action_type,
                severity="warning" if outcome in {"failed", "degraded", "completed_with_warning"} else "info",
                outcome=outcome,
                actor_user_id=audit.user_id,
                service_identity="exception_ai_service" if after_data.get("ai_request_id") else None,
                domain="crm",
                resource_type=audit.resource_type,
                resource_id=audit.resource_id,
                request_id=after_data.get("ai_request_id"),
                detail_json={
                    "legacy_action_type": audit.action_type,
                    "role_code": audit.role_code,
                    "fields": safe_fields,
                    "migration_version": "crm-ai-stage3.v1",
                },
                source_system="crm",
                legacy_type="audit_log",
                legacy_id=legacy_id,
                occurred_at=audit.created_at,
                created_at=audit.created_at,
            )
        )
    if result is None:
        return
    usage = db.scalar(
        select(AiUsageEvent).where(
            AiUsageEvent.source_system == "crm",
            AiUsageEvent.legacy_type == "audit_log.ai_usage",
            AiUsageEvent.legacy_id == legacy_id,
        )
    )
    if usage is not None:
        return
    assistant_message_id = None
    if conversation is not None:
        assistant_message_id = db.scalar(
            select(AiMessage.id).where(
                AiMessage.conversation_id == conversation.id,
                AiMessage.role == "assistant",
            )
        )
    db.add(
        AiUsageEvent(
            event_no=f"AI-CRM-USAGE-{legacy_id}",
            conversation_id=conversation.id if conversation else None,
            message_id=assistant_message_id,
            request_id=result.request_id,
            provider_request_id=result.provider_request_id,
            service_identity="exception_ai_service",
            domain="crm",
            operation=str(after_data.get("operation") or audit.action_type),
            status=result.status,
            model_name=result.model,
            prompt_version=result.prompt_version,
            contract_version=result.contract_version,
            latency_ms=result.latency_ms,
            prompt_tokens=result.usage.prompt_tokens,
            completion_tokens=result.usage.completion_tokens,
            total_tokens=result.usage.total_tokens,
            attempts=result.attempts,
            source_system="crm",
            legacy_type="audit_log.ai_usage",
            legacy_id=legacy_id,
            metadata_json={"migration_version": "crm-ai-stage3.v1"},
            occurred_at=audit.created_at,
            created_at=audit.created_at,
        )
    )


def _conversation_public(db: Session, row: AiConversation) -> CrmAssistantConversationPublic:
    messages = list(
        db.scalars(
            select(AiMessage)
            .where(AiMessage.conversation_id == row.id, AiMessage.role.in_(["user", "assistant"]))
            .order_by(AiMessage.sequence_no)
        ).all()
    )
    user_message = next((item.content for item in messages if item.role == "user"), "")
    assistant_message = next((item.content for item in messages if item.role == "assistant"), "")
    compatibility = _compatibility(row.metadata_json)
    legacy_id = int(row.legacy_id) if str(row.legacy_id or "").isdigit() else row.id
    return CrmAssistantConversationPublic(
        id=legacy_id,
        conversation_no=row.conversation_no,
        user_id=row.actor_user_id,
        username_snapshot=compatibility.get("username_snapshot"),
        channel=row.channel,
        session_id=row.session_id,
        context_type=row.context_type,
        context_id=row.context_id,
        operation=row.operation,
        user_message=user_message,
        assistant_message=assistant_message,
        source=str(compatibility.get("source") or ("hermes" if row.model_name else "rule")),
        model_name=row.model_name,
        status=row.status,
        payload_json=_legacy_payload(row.metadata_json),
        created_at=row.created_at,
    )


def list_unified_conversations(
    db: Session,
    *,
    user_id: int,
    channel: str | None = None,
    limit: int | None = 50,
) -> list[CrmAssistantConversationPublic]:
    stmt = select(AiConversation).where(
        AiConversation.domain == "crm",
        AiConversation.source_system == "crm",
        AiConversation.legacy_type == "assistant_conversation",
        AiConversation.actor_user_id == user_id,
    )
    if channel:
        stmt = stmt.where(AiConversation.channel == channel)
    stmt = stmt.order_by(AiConversation.created_at.desc(), AiConversation.id.desc())
    if limit is not None:
        stmt = stmt.limit(limit)
    rows = list(db.scalars(stmt).all())
    return [_conversation_public(db, row) for row in rows]


def delete_unified_conversations(db: Session, legacy_ids: list[int]) -> None:
    if not legacy_ids:
        return
    conversation_ids = list(
        db.scalars(
            select(AiConversation.id).where(
                AiConversation.source_system == "crm",
                AiConversation.legacy_type == "assistant_conversation",
                AiConversation.legacy_id.in_([str(item) for item in legacy_ids]),
            )
        ).all()
    )
    if not conversation_ids:
        return
    message_ids = list(
        db.scalars(select(AiMessage.id).where(AiMessage.conversation_id.in_(conversation_ids))).all()
    )
    if message_ids:
        db.execute(
            update(AiUsageEvent)
            .where(AiUsageEvent.message_id.in_(message_ids))
            .values(message_id=None)
        )
    db.execute(
        update(AiUsageEvent)
        .where(AiUsageEvent.conversation_id.in_(conversation_ids))
        .values(conversation_id=None)
    )
    for model in (AiInsight, AiActionProposal):
        db.execute(
            update(model)
            .where(model.conversation_id.in_(conversation_ids))
            .values(conversation_id=None)
        )
    db.execute(
        delete(AiContextSnapshotRecord).where(
            AiContextSnapshotRecord.conversation_id.in_(conversation_ids)
        )
    )
    db.execute(delete(AiMessage).where(AiMessage.conversation_id.in_(conversation_ids)))
    db.execute(
        delete(AiConversation).where(
            AiConversation.id.in_(conversation_ids),
        )
    )


def cancel_unified_conversation(db: Session, legacy: AssistantConversation) -> None:
    unified = db.scalar(
        select(AiConversation).where(
            AiConversation.source_system == "crm",
            AiConversation.legacy_type == "assistant_conversation",
            AiConversation.legacy_id == str(legacy.id),
        )
    )
    if unified is None:
        raise RuntimeError("Unified CRM AI conversation is missing")
    unified.status = legacy.status
    metadata = _dict(unified.metadata_json)
    metadata["legacy_payload"] = legacy.payload_json
    unified.metadata_json = metadata
    for message in db.scalars(select(AiMessage).where(AiMessage.conversation_id == unified.id)).all():
        message.status = legacy.status


def _insight_public(row: AiInsight) -> CrmProjectInsightPublic:
    compatibility = _compatibility(row.payload_json)
    legacy_id = int(row.legacy_id) if str(row.legacy_id or "").isdigit() else row.id
    return CrmProjectInsightPublic(
        id=legacy_id,
        insight_no=row.insight_no,
        project_id=compatibility.get("project_id"),
        task_id=compatibility.get("task_id"),
        customer_code=compatibility.get("customer_code"),
        insight_type=row.insight_type,
        summary=row.summary,
        suggested_action=row.suggested_action,
        risk_level=row.risk_level or "medium",
        opportunity_level=row.opportunity_level,
        confidence_score=_confidence_percent(row.confidence_score, compatibility),
        status=_legacy_insight_status(row),
        evidence_json=row.evidence_json,
        source=str(compatibility.get("source") or "rule"),
        generated_by_user_id=row.created_by_user_id,
        reviewed_by_user_id=row.reviewed_by_user_id,
        reviewed_at=row.reviewed_at,
        review_note=row.review_note,
        payload_json=_legacy_payload(row.payload_json),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def list_unified_insights(
    db: Session,
    *,
    legacy_ids: list[int],
    status_value: str | None,
    insight_type: str | None,
    limit: int,
    offset: int,
) -> tuple[list[CrmProjectInsightPublic], int]:
    if not legacy_ids:
        return [], 0
    stmt = select(AiInsight).where(
        AiInsight.domain == "crm",
        AiInsight.source_system == "crm",
        AiInsight.legacy_type == "crm_project_insight",
        AiInsight.legacy_id.in_([str(item) for item in legacy_ids]),
    )
    if insight_type:
        stmt = stmt.where(AiInsight.insight_type == insight_type)
    rows = list(db.scalars(stmt.order_by(AiInsight.created_at.desc(), AiInsight.id.desc())).all())
    public_rows = [_insight_public(row) for row in rows]
    if status_value:
        public_rows = [row for row in public_rows if row.status == status_value]
    total = len(public_rows)
    return public_rows[offset : offset + limit], total


def consistency_report(db: Session, *, user_id: int | None = None) -> dict[str, Any]:
    legacy_conversation_stmt = select(AssistantConversation)
    unified_conversation_stmt = select(AiConversation).where(
        AiConversation.source_system == "crm",
        AiConversation.legacy_type == "assistant_conversation",
    )
    if user_id is not None:
        legacy_conversation_stmt = legacy_conversation_stmt.where(AssistantConversation.user_id == user_id)
        unified_conversation_stmt = unified_conversation_stmt.where(AiConversation.actor_user_id == user_id)
    legacy_conversations = list(db.scalars(legacy_conversation_stmt).all())
    unified_conversations = list(db.scalars(unified_conversation_stmt).all())
    legacy_conversation_status = {str(row.id): row.status for row in legacy_conversations}
    unified_conversation_status = {str(row.legacy_id): row.status for row in unified_conversations}

    legacy_insights = list(db.scalars(select(CrmProjectInsight)).all())
    unified_insights = list(
        db.scalars(
            select(AiInsight).where(
                AiInsight.source_system == "crm",
                AiInsight.legacy_type == "crm_project_insight",
            )
        ).all()
    )
    legacy_insight_status = {str(row.id): _review_status(row.status) for row in legacy_insights}
    unified_insight_status = {
        str(row.legacy_id): _review_status(_legacy_insight_status(row)) for row in unified_insights
    }
    missing_conversations = sorted(set(legacy_conversation_status) - set(unified_conversation_status))
    missing_insights = sorted(set(legacy_insight_status) - set(unified_insight_status))
    extra_conversations = sorted(set(unified_conversation_status) - set(legacy_conversation_status))
    extra_insights = sorted(set(unified_insight_status) - set(legacy_insight_status))
    conversation_status_mismatches = sum(
        legacy_conversation_status[key] != unified_conversation_status.get(key)
        for key in legacy_conversation_status
        if key in unified_conversation_status
    )
    insight_status_mismatches = sum(
        legacy_insight_status[key] != unified_insight_status.get(key)
        for key in legacy_insight_status
        if key in unified_insight_status
    )
    consistent = not any(
        (
            missing_conversations,
            missing_insights,
            extra_conversations,
            extra_insights,
            conversation_status_mismatches,
            insight_status_mismatches,
        )
    )
    return {
        "enabled": crm_ai_unified_enabled(),
        "read_source": "unified" if consistent and crm_ai_unified_enabled() else "legacy",
        "consistent": consistent,
        "legacy_conversations": len(legacy_conversations),
        "unified_conversations": len(unified_conversations),
        "legacy_insights": len(legacy_insights),
        "unified_insights": len(unified_insights),
        "missing_conversations": len(missing_conversations),
        "missing_insights": len(missing_insights),
        "extra_conversations": len(extra_conversations),
        "extra_insights": len(extra_insights),
        "conversation_status_mismatches": conversation_status_mismatches,
        "insight_status_mismatches": insight_status_mismatches,
    }


def aggregate_conversation_counts(rows: list[CrmAssistantConversationPublic]) -> dict[str, dict[str, int]]:
    return {
        "status_counts": dict(Counter(row.status for row in rows)),
        "source_counts": dict(Counter(row.source for row in rows)),
        "operation_counts": dict(Counter(row.operation or "未设置" for row in rows)),
    }
